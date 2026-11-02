"""Async TCP client for the Datasat AP20/AP25 (TN-H413 protocol family).

Everything the processor sends is treated as untrusted input: replies are length
limited, matched against the command that was sent, and parsed defensively.
Everything sent to the processor is checked first, so a name or password can
never carry a second command.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import math

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 14500
_TIMEOUT = 5.0
PROBE_TIMEOUT = 3.0

# Longest reply accepted. Real replies are well under 1 KiB; anything longer means
# the unit (or whatever answers on this address) is misbehaving.
LINE_LIMIT = 8192

MAX_ARGUMENT_LENGTH = 64  # format and macro names
MAX_PASSWORD_LENGTH = 64
MAX_NAMES = 64  # formats or macros accepted from one listing
MAX_TEXT_LENGTH = 64  # identification fields such as version or theater name
MAX_BOARDS = 16

VOLTS_BOARDS = ("H331", "H332", "H335", "H336", "H338")
MIN_GPIO = 1
MAX_GPIO = 21
FADER_MAX = 100  # tenths; 100 == 10.0 on the front panel
LEVEL_MAX = 100  # monitor level
VOLUME_MAX = 700  # negative tenths of a dB, 700 == -70.0 dB

AUTH_LEVEL_SETUP = "SETUP"
AUTH_LEVEL_OPERATOR = "OP"

# Replies that identify the unit or its site. They are left out of the debug log,
# because debug logs tend to end up in public issue reports.
_PRIVATE_REPLIES = frozenset({"SYSTEM", "MAC", "SERIALNO", "IDENTIFY"})


class Ap2xError(Exception):
    """Base error for this client."""


class Ap2xAuthError(Ap2xError):
    """Raised when the processor refuses the password or demands one."""


class Ap2xConnectionError(Ap2xError):
    """Raised when the device cannot be reached or the link drops."""


class Ap2xProtocolError(Ap2xError):
    """Raised when the processor answers, but not with a reply to what was asked."""


class Ap2xInvalidArgument(Ap2xError, ValueError):
    """Raised when a name cannot be sent safely as part of a command."""


@dataclass
class Ap2xSystemInfo:
    """Static information read once, at setup time."""

    version: str | None = None
    version_date: str | None = None
    mac: str | None = None
    serial: str | None = None
    circuit: str | None = None
    theater: str | None = None
    screen: str | None = None
    boards: list[str] = field(default_factory=list)


@dataclass
class Ap2xCapabilities:
    """Commands this unit accepts beyond the documented AP20 set.

    The AP20/AP25 technote (TN-H413 rev D) documents fewer commands than its
    sibling RS20i (TN-H413-01), although both share one firmware family. Each
    extra command is probed once at setup instead of being assumed.
    """

    power: bool = False
    screensaver: bool = False
    volume_db: bool = False
    pulse: bool = False
    names_command: str | None = None
    format_names: list[str] = field(default_factory=list)
    macro_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """Return a log- and diagnostics-friendly summary."""
        return {
            "power": self.power,
            "screensaver": self.screensaver,
            "volume_db": self.volume_db,
            "pulse": self.pulse,
            "names_command": self.names_command,
            "format_names": self.format_names,
            "macro_names": self.macro_names,
        }


@dataclass
class Ap2xVolts:
    """One HEALTH voltage record.

    values keeps the position of every field after the status flag; a field that
    could not be read is None, so later fields never shift into the wrong place.
    """

    present: bool = True
    ok: bool | None = None
    values: list[float | None] = field(default_factory=list)


# ---- Input checks --------------------------------------------------------


def is_safe_argument(value: str) -> bool:
    """Return True for a name that can be sent as a command argument.

    The protocol is line based: a carriage return ends a command and "@" starts
    the next one. Only printable ASCII without "@" is accepted, so a name can never
    carry a second command.
    """
    return (
        0 < len(value) <= MAX_ARGUMENT_LENGTH
        and value.isascii()
        and value.isprintable()
        and "@" not in value
    )


def is_safe_password(value: str) -> bool:
    """Return True for a password that can be sent with @AUTH.

    Passwords may contain "@"; control characters, which could end the line, are
    refused.
    """
    return 0 < len(value) <= MAX_PASSWORD_LENGTH and value.isascii() and value.isprintable()


def parse_name_list(text: str) -> list[str]:
    """Split a comma-separated list of names, keeping only names that are safe to send.

    Names are trimmed, duplicates are dropped and at most MAX_NAMES are kept, so a
    misbehaving unit cannot flood Home Assistant with entities.
    """
    names: list[str] = []
    for raw in text.split(","):
        name = raw.strip()
        if not name or name in names:
            continue
        if not is_safe_argument(name):
            _LOGGER.debug("Ignoring a name that cannot be sent to the unit: %r", name[:80])
            continue
        if len(names) == MAX_NAMES:
            _LOGGER.debug("Ignoring names beyond the first %s", MAX_NAMES)
            break
        names.append(name)
    return names


def _check_argument(value: str, what: str) -> str:
    """Return value if it is safe to send, otherwise raise Ap2xInvalidArgument."""
    if not is_safe_argument(value):
        raise Ap2xInvalidArgument(
            f"{what} {value[:80]!r} cannot be sent: use up to {MAX_ARGUMENT_LENGTH} "
            "printable ASCII characters, without '@'"
        )
    return value


class Ap2xClient:
    """Persistent connection to an AP20/AP25.

    Commands are sent as ``@COMMAND<CR>``. Responses are ASCII, terminated by
    ``<CR>``; ``@SYSTEM`` uses ``<LF>`` between its fields and ends with a NUL
    byte after the final ``<CR>``.
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT, password: str | None = None) -> None:
        """Store the connection details without opening a socket yet."""
        self.host = host
        self.port = port
        self.password = password
        self.auth_level: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return True while the socket is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the connection and authenticate when a password is configured."""
        async with self._lock:
            await self._connect_locked()

    async def disconnect(self) -> None:
        """Close the connection."""
        async with self._lock:
            await self._close_locked()

    async def command(
        self,
        cmd: str,
        timeout: float = _TIMEOUT,
        *,
        expect: tuple[str, ...] | None = None,
    ) -> str:
        """Send one command and return the reply without its terminator.

        With expect, the first word of the reply must be one of those words.
        Anything else means request and reply have drifted apart, so the socket is
        closed and the next command starts on a clean connection.
        """
        if not cmd.isascii() or not cmd.isprintable():
            raise Ap2xInvalidArgument(
                f"Refusing to send a command with control characters: {cmd[:40]!r}"
            )

        async with self._lock:
            try:
                await self._connect_locked()
                reply = await self._request_locked(cmd, timeout)
            except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
                await self._close_locked()
                raise Ap2xConnectionError(
                    f"I/O error while sending '{_keyword(cmd)}' to {self.host}: {err}"
                ) from err
            except asyncio.LimitOverrunError as err:
                await self._close_locked()
                raise Ap2xProtocolError(
                    f"Reply to '{_keyword(cmd)}' from {self.host} is longer than {LINE_LIMIT} bytes"
                ) from err

            if expect is not None and _keyword(reply) not in expect:
                await self._close_locked()
                if _keyword(reply) == "SECERR":
                    raise Ap2xAuthError(
                        f"The processor at {self.host} requires a valid password for "
                        f"'{_keyword(cmd)}' (SECERR)"
                    )
                raise Ap2xProtocolError(
                    f"Expected a reply to '{_keyword(cmd)}' from {self.host}, "
                    f"got one starting with '{_keyword(reply)[:20]}'"
                )
            return reply

    async def try_command(self, cmd: str, timeout: float = PROBE_TIMEOUT) -> str | None:
        """Send a command that the unit may not know, returning None if it does not answer.

        An unknown command produces "BadCommand" or no reply at all; in the second
        case the connection is dropped and reopened by the next call.
        """
        try:
            reply = await self.command(cmd, timeout=timeout)
        except Ap2xError as err:
            _LOGGER.debug("Command '%s' is not supported by %s: %s", cmd, self.host, err)
            return None
        if _is_error_reply(reply):
            _LOGGER.debug("Command '%s' rejected by %s: %s", cmd, self.host, reply)
            return None
        return reply

    # ---- Connection handling --------------------------------------------

    async def _connect_locked(self) -> None:
        """Open the socket and authenticate. Caller holds the lock."""
        if self.connected:
            return

        if self.password and not is_safe_password(self.password):
            raise Ap2xAuthError(
                "The configured password contains characters that cannot be sent to the processor"
            )

        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, limit=LINE_LIMIT), _TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            self._reader = None
            self._writer = None
            raise Ap2xConnectionError(f"Cannot connect to {self.host}:{self.port}: {err}") from err

        if self.password:
            try:
                reply = await self._request_locked(f"AUTH {self.password}", _TIMEOUT, "AUTH ***")
            except (
                OSError,
                TimeoutError,
                asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,
            ) as err:
                await self._close_locked()
                raise Ap2xConnectionError(f"Authentication to {self.host} failed: {err}") from err
            words = reply.upper().split()
            if "SECERR" in words:
                await self._close_locked()
                raise Ap2xAuthError("Password rejected by the processor (SECERR)")
            if AUTH_LEVEL_SETUP in words:
                self.auth_level = AUTH_LEVEL_SETUP
            elif AUTH_LEVEL_OPERATOR in words:
                self.auth_level = AUTH_LEVEL_OPERATOR
            else:
                _LOGGER.debug("Unrecognised reply to AUTH from %s: %s", self.host, reply[:40])

    async def _close_locked(self) -> None:
        """Close the socket. Caller holds the lock."""
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except OSError as err:
            _LOGGER.debug("Error while closing connection to %s: %s", self.host, err)

    async def _request_locked(self, cmd: str, timeout: float, log_cmd: str | None = None) -> str:
        """Write one command and read its reply. Caller holds the lock.

        Callers that send credentials pass log_cmd with the secret left out, so
        the password never reaches the log, not even at debug level.
        """
        reader = self._reader
        writer = self._writer
        if reader is None or writer is None:
            raise Ap2xConnectionError(f"Not connected to {self.host}")

        writer.write(f"@{cmd}\r".encode("ascii"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.readuntil(b"\r"), timeout)
        text = raw.decode("ascii", errors="replace").strip("\r\n\x00 ")
        shown = "<private, not logged>" if _keyword(cmd) in _PRIVATE_REPLIES else text
        _LOGGER.debug("%s -> %s", log_cmd if log_cmd is not None else cmd, shown)
        return text

    # ---- Documented commands ---------------------------------------------

    async def get_system_info(self) -> Ap2xSystemInfo:
        """Read the static identification of the unit."""
        info = Ap2xSystemInfo()

        # @SYSTEM returns VER / VERDATE / MAC separated by LF within one record.
        # The first command on a fresh connection, so no earlier reply can be pending.
        system = await self.command("SYSTEM")
        for line in system.replace("\n", "|").split("|"):
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].upper(), _clean_text(parts[1])
            if key == "VER":
                info.version = value
            elif key == "VERDATE":
                info.version_date = value
            elif key == "MAC":
                info.mac = value

        if info.mac is None:
            info.mac = _clean_text(_text_arg(await self.command("MAC", expect=("MAC",))))
        info.serial = _clean_text(_text_arg(await self.command("SERIALNO", expect=("SERIALNO",))))

        identify = await self.command("IDENTIFY")
        fields = identify.replace(",", " ").split()
        if len(fields) >= 5 and fields[0].upper().startswith("AP"):
            info.circuit = _clean_text(fields[2])
            info.theater = _clean_text(fields[3])
            info.screen = _clean_text(fields[4])

        info.boards = _board_names(await self.command("BOARDINFO"))
        return info

    async def get_fader(self) -> int | None:
        """Return the master fader level in tenths (0-100)."""
        return _bounded_int(await self.command("FADER", expect=("FADER",)), 0, FADER_MAX)

    async def set_fader(self, tenths: int) -> None:
        """Set the master fader level in tenths (0-100)."""
        await self._set("FADER", max(0, min(FADER_MAX, int(tenths))))

    async def get_muted(self) -> bool | None:
        """Return the master mute state."""
        return _flag(await self.command("MUTED", expect=("MUTED",)))

    async def set_muted(self, muted: bool) -> None:
        """Mute or unmute the main outputs."""
        await self._set("MUTED", 1 if muted else 0)

    async def get_format(self) -> str | None:
        """Return the name of the active format."""
        name = _name_arg(await self.command("FORMAT", expect=("FORMAT",)), "FORMAT")
        return _clean_text(name)

    async def set_format(self, name: str) -> None:
        """Select a format by its exact name."""
        await self._set("FORMAT", _check_argument(name, "Format name"))

    async def get_monitor_level(self) -> int | None:
        """Return the monitor (booth) level, 0-100."""
        reply = await self.command("MONITORLEVEL", expect=("MONITORLEVEL",))
        return _bounded_int(reply, 0, LEVEL_MAX)

    async def set_monitor_level(self, level: int) -> None:
        """Set the monitor (booth) level, 0-100."""
        await self._set("MONITORLEVEL", max(0, min(LEVEL_MAX, int(level))))

    async def get_monitor_muted(self) -> bool | None:
        """Return the monitor mute state."""
        return _flag(await self.command("MONITORMUTE", expect=("MONITORMUTE",)))

    async def set_monitor_muted(self, muted: bool) -> None:
        """Mute or unmute the monitor output."""
        await self._set("MONITORMUTE", 1 if muted else 0)

    async def run_macro(self, name: str) -> bool:
        """Run a macro defined on the unit. Returns False when the unit refuses it."""
        _check_argument(name, "Macro name")
        reply = await self.command(f"RUNMACRO {name}", expect=("OK", "ERR"))
        if _keyword(reply) == "OK":
            return True
        # The unit answered, so this is a naming problem rather than a link problem.
        _LOGGER.warning("Macro '%s' was not executed by the processor: %s", name, reply[:80])
        return False

    async def get_temperatures(self) -> list[float | None]:
        """Return the [H331, H332, H335] board temperatures in degrees Celsius."""
        reply = await self.command("HEALTH TEMPERATURE", expect=("HEALTH",))
        return _float_list(_text_arg(reply))

    async def get_volts(self, board: str) -> Ap2xVolts:
        """Read one HEALTH voltage record, e.g. H336."""
        reply = await self.command(f"HEALTH {board}VOLTS", expect=("HEALTH",))
        field_value = _text_arg(reply)
        if not field_value or field_value.upper() == "NA":
            return Ap2xVolts(present=False)
        values = _float_list(field_value)
        if not values:
            return Ap2xVolts(present=True, ok=None)
        flag = values[0]
        ok = True if flag == 1 else False if flag == 0 else None
        return Ap2xVolts(present=True, ok=ok, values=values[1:])

    async def _set(self, keyword: str, value: int | str) -> None:
        """Send a write command and check that the reply belongs to it."""
        reply = await self.command(f"{keyword} {value}", expect=(keyword, "OK", "ERR"))
        if _keyword(reply) == "ERR":
            _LOGGER.warning("The processor refused '%s %s': %s", keyword, value, reply[:80])

    # ---- Commands shared with the RS20i, probed before use ---------------

    async def get_power(self) -> bool | None:
        """Return True when the unit is in operating mode, False in standby."""
        return _flag(await self.command("POWER", expect=("POWER",)))

    async def set_power(self, on: bool) -> None:
        """Switch between operating mode and standby. Waking takes about 15 seconds."""
        await self._set("POWER", 1 if on else 0)

    async def get_volume_db(self) -> int | None:
        """Return the master volume in negative tenths of a dB (0 to 700)."""
        return _bounded_int(await self.command("VOLUME", expect=("VOLUME",)), 0, VOLUME_MAX)

    async def set_volume_db(self, tenths: int) -> None:
        """Set the master volume in negative tenths of a dB (0 to 700)."""
        await self._set("VOLUME", max(0, min(VOLUME_MAX, int(tenths))))

    async def set_screensaver(self, showing: bool) -> None:
        """Show the screensaver (True) or wake the display (False)."""
        await self._set("SCR", "OFF" if showing else "ON")

    async def pulse_gpio(self, gpio: int) -> bool:
        """Fire a 250 ms pulse on one of the GPIO outputs (1-21)."""
        if not MIN_GPIO <= gpio <= MAX_GPIO:
            raise Ap2xInvalidArgument(f"GPIO must be between {MIN_GPIO} and {MAX_GPIO}, got {gpio}")
        reply = await self.command(f"PULSE {gpio}", expect=("OK", "ERR", "PULSE"))
        if _keyword(reply) in ("OK", "PULSE"):
            return True
        _LOGGER.warning("Pulse on GPIO %s was not accepted: %s", gpio, reply[:80])
        return False


async def probe_capabilities(client: Ap2xClient) -> Ap2xCapabilities:
    """Find out which undocumented commands this unit accepts.

    Every probe runs on its own connection attempt: a command the firmware does
    not know produces no reply, which drops the link, so probing this way cannot
    desynchronise the connection used for normal polling.
    """
    caps = Ap2xCapabilities()

    power = await client.try_command("POWER")
    if power is not None and _keyword(power) == "POWER" and _flag(power) is not None:
        caps.power = True
        caps.pulse = True  # Same RS20i command set; PULSE itself cannot be probed safely.

    volume = await client.try_command("VOLUME")
    if (
        volume is not None
        and _keyword(volume) == "VOLUME"
        and _bounded_int(volume, 0, VOLUME_MAX) is not None
    ):
        caps.volume_db = True

    for command in ("FORMATNAMES", "INPUTNAMES"):
        names = _name_list(await client.try_command(command), command)
        if names:
            caps.names_command = command
            caps.format_names = names
            break

    caps.macro_names = _name_list(await client.try_command("MACRONAMES"), "MACRONAMES")

    # SCR ON only wakes the display, which is harmless to try.
    if (await client.try_command("SCR ON")) is not None:
        caps.screensaver = True

    _LOGGER.debug("Capabilities of %s: %s", client.host, caps.as_dict())
    return caps


# ---- Parsing helpers -----------------------------------------------------


def _keyword(text: str) -> str:
    """Return the first word of a command or reply, upper case."""
    parts = text.split(maxsplit=1)
    return parts[0].upper() if parts else ""


def _is_error_reply(reply: str) -> bool:
    """Return True when a reply means the command was refused or unknown.

    An AP20 answers an unknown command with "BadCommand", which must not be
    mistaken for data by the commands whose reply carries no keyword of its own.
    """
    text = reply.strip().upper().replace(" ", "")
    return not text or text.startswith(("ERR", "SECERR", "BADCOMMAND", "NAK", "?"))


def _text_arg(reply: str) -> str | None:
    """Return the last whitespace-separated field of a response."""
    parts = reply.split()
    return parts[-1] if len(parts) >= 2 else None


def _int_arg(reply: str) -> int | None:
    """Return the last field of a response as an integer, or None."""
    value = _text_arg(reply)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        _LOGGER.debug("Expected a number, got: %s", reply[:40])
        return None


def _bounded_int(reply: str, low: int, high: int) -> int | None:
    """Return the last field as an integer when it lies within [low, high]."""
    value = _int_arg(reply)
    if value is None or not low <= value <= high:
        if value is not None:
            _LOGGER.debug("Ignoring out-of-range value %s (expected %s-%s)", value, low, high)
        return None
    return value


def _flag(reply: str) -> bool | None:
    """Return a 0/1 reply as a boolean; anything else is unknown."""
    value = _bounded_int(reply, 0, 1)
    return None if value is None else bool(value)


def _clean_text(value: str | None) -> str | None:
    """Return printable ASCII text, cut to MAX_TEXT_LENGTH; None when nothing is left."""
    if value is None:
        return None
    text = "".join(char for char in value if char.isascii() and char.isprintable()).strip()
    return text[:MAX_TEXT_LENGTH] or None


def _name_arg(reply: str, command: str) -> str | None:
    """Return a response value that may itself contain spaces."""
    text = reply.strip()
    if text.upper().startswith(command):
        text = text[len(command) :].strip()
    return text or None


def _name_list(reply: str | None, command: str) -> list[str]:
    """Parse a listing of names, with or without an echoed command word."""
    if reply is None:
        return []
    text = reply.strip()
    if text.upper().startswith(command):
        text = text[len(command) :].strip()
    return parse_name_list(text)


def _board_names(reply: str) -> list[str]:
    """Return the board identifiers listed by @BOARDINFO."""
    names: list[str] = []
    for record in reply.replace("\n", ",").split(","):
        token = _clean_text(record)
        if (
            token
            and len(token) <= 16
            and token.upper().startswith(("H3", "HDMI"))
            and token not in names
        ):
            names.append(token)
            if len(names) == MAX_BOARDS:
                break
    return names


def _float_list(csv: str | None) -> list[float | None]:
    """Parse a comma-separated list of numbers, keeping each value in its position.

    Fields that are not finite numbers (text, "inf", "nan") become None, so the
    fields after them keep their meaning.
    """
    if not csv:
        return []
    values: list[float | None] = []
    for item in csv.split(","):
        try:
            number = float(item)
        except ValueError:
            number = math.nan
        if math.isfinite(number):
            values.append(number)
        else:
            _LOGGER.debug("Ignoring a value that is not a finite number: %r", item[:20])
            values.append(None)
    return values
