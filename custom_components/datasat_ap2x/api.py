"""Async TCP client for the Datasat AP20/AP25 (TN-H413 protocol family)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 14500
_TIMEOUT = 5.0
PROBE_TIMEOUT = 3.0

VOLTS_BOARDS = ("H331", "H332", "H335", "H336", "H338")
MIN_GPIO = 1
MAX_GPIO = 21
VOLUME_MAX = 700  # negative tenths of a dB, 700 == -70.0 dB


class Ap2xError(Exception):
    """Base error for this client."""


class Ap2xAuthError(Ap2xError):
    """Raised when AUTH is rejected (SECERR)."""


class Ap2xConnectionError(Ap2xError):
    """Raised when the device cannot be reached or the link drops."""


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
    """One HEALTH voltage record."""

    present: bool = True
    ok: bool | None = None
    values: list[float] = field(default_factory=list)


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

    async def command(self, cmd: str, timeout: float = _TIMEOUT) -> str:
        """Send one command and return the response line without its terminator."""
        async with self._lock:
            try:
                await self._connect_locked()
                return await self._request_locked(cmd, timeout)
            except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
                await self._close_locked()
                raise Ap2xConnectionError(
                    f"I/O error while sending '{cmd}' to {self.host}: {err}"
                ) from err

    async def try_command(self, cmd: str, timeout: float = PROBE_TIMEOUT) -> str | None:
        """Send a command that the unit may not know, returning None if it does not answer.

        An unknown command usually produces no reply at all, so the connection
        is dropped afterwards and reopened by the next call.
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

        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), _TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            self._reader = None
            self._writer = None
            raise Ap2xConnectionError(f"Cannot connect to {self.host}:{self.port}: {err}") from err

        if self.password:
            reply = await self._request_locked(f"AUTH {self.password}", _TIMEOUT)
            if "SECERR" in reply.upper():
                await self._close_locked()
                raise Ap2xAuthError("Password rejected by the processor (SECERR)")
            _LOGGER.debug("Authenticated: %s", reply)

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

    async def _request_locked(self, cmd: str, timeout: float) -> str:
        """Write one command and read its reply. Caller holds the lock."""
        reader = self._reader
        writer = self._writer
        if reader is None or writer is None:
            raise Ap2xConnectionError(f"Not connected to {self.host}")

        writer.write(f"@{cmd}\r".encode("ascii", errors="replace"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.readuntil(b"\r"), timeout)
        text = raw.decode("ascii", errors="replace").strip("\r\n\x00 ")
        _LOGGER.debug("%s -> %s", cmd, text)
        return text

    # ---- Documented commands ---------------------------------------------

    async def get_system_info(self) -> Ap2xSystemInfo:
        """Read the static identification of the unit."""
        info = Ap2xSystemInfo()

        # @SYSTEM returns VER / VERDATE / MAC separated by LF within one record.
        system = await self.command("SYSTEM")
        for line in system.replace("\n", "|").split("|"):
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            key, value = parts[0].upper(), parts[1].strip()
            if key == "VER":
                info.version = value
            elif key == "VERDATE":
                info.version_date = value
            elif key == "MAC":
                info.mac = value

        if info.mac is None:
            info.mac = _text_arg(await self.command("MAC"))
        info.serial = _text_arg(await self.command("SERIALNO"))

        identify = await self.command("IDENTIFY")
        fields = identify.replace(",", " ").split()
        if len(fields) >= 5 and fields[0].upper().startswith("AP"):
            info.circuit, info.theater, info.screen = fields[2], fields[3], fields[4]

        info.boards = _board_names(await self.command("BOARDINFO"))
        return info

    async def get_fader(self) -> int | None:
        """Return the master fader level in tenths (0-100)."""
        return _int_arg(await self.command("FADER"))

    async def set_fader(self, tenths: int) -> None:
        """Set the master fader level in tenths (0-100)."""
        await self.command(f"FADER {max(0, min(100, int(tenths)))}")

    async def get_muted(self) -> bool | None:
        """Return the master mute state."""
        value = _int_arg(await self.command("MUTED"))
        return None if value is None else bool(value)

    async def set_muted(self, muted: bool) -> None:
        """Mute or unmute the main outputs."""
        await self.command(f"MUTED {1 if muted else 0}")

    async def get_format(self) -> str | None:
        """Return the name of the active format."""
        return _name_arg(await self.command("FORMAT"), "FORMAT")

    async def set_format(self, name: str) -> None:
        """Select a format by its exact name."""
        await self.command(f"FORMAT {name}")

    async def get_monitor_level(self) -> int | None:
        """Return the monitor (booth) level, 0-100."""
        return _int_arg(await self.command("MONITORLEVEL"))

    async def set_monitor_level(self, level: int) -> None:
        """Set the monitor (booth) level, 0-100."""
        await self.command(f"MONITORLEVEL {max(0, min(100, int(level)))}")

    async def get_monitor_muted(self) -> bool | None:
        """Return the monitor mute state."""
        value = _int_arg(await self.command("MONITORMUTE"))
        return None if value is None else bool(value)

    async def set_monitor_muted(self, muted: bool) -> None:
        """Mute or unmute the monitor output."""
        await self.command(f"MONITORMUTE {1 if muted else 0}")

    async def run_macro(self, name: str) -> bool:
        """Run a macro defined on the unit. Returns False when it does not exist."""
        reply = await self.command(f"RUNMACRO {name}")
        if reply.strip().upper().startswith("OK"):
            return True
        # The unit answered, so this is a naming problem rather than a link problem.
        _LOGGER.warning("Macro '%s' was not executed by the processor: %s", name, reply)
        return False

    async def get_temperatures(self) -> list[float]:
        """Return the [H331, H332, H335] board temperatures in degrees Celsius."""
        return _float_list(_text_arg(await self.command("HEALTH TEMPERATURE")))

    async def get_volts(self, board: str) -> Ap2xVolts:
        """Read one HEALTH voltage record, e.g. H336."""
        field_value = _text_arg(await self.command(f"HEALTH {board}VOLTS"))
        if not field_value or field_value.upper() == "NA":
            return Ap2xVolts(present=False)
        values = _float_list(field_value)
        if not values:
            return Ap2xVolts(present=True, ok=None)
        return Ap2xVolts(present=True, ok=bool(int(values[0])), values=values[1:])

    # ---- Commands shared with the RS20i, probed before use ---------------

    async def get_power(self) -> bool | None:
        """Return True when the unit is in operating mode, False in standby."""
        value = _int_arg(await self.command("POWER"))
        return None if value is None else bool(value)

    async def set_power(self, on: bool) -> None:
        """Switch between operating mode and standby. Waking takes about 15 seconds."""
        await self.command(f"POWER {1 if on else 0}")

    async def get_volume_db(self) -> int | None:
        """Return the master volume in negative tenths of a dB (0 to 700)."""
        return _int_arg(await self.command("VOLUME"))

    async def set_volume_db(self, tenths: int) -> None:
        """Set the master volume in negative tenths of a dB (0 to 700)."""
        await self.command(f"VOLUME {max(0, min(VOLUME_MAX, int(tenths)))}")

    async def set_screensaver(self, showing: bool) -> None:
        """Show the screensaver (True) or wake the display (False)."""
        await self.command(f"SCR {'OFF' if showing else 'ON'}")

    async def pulse_gpio(self, gpio: int) -> bool:
        """Fire a 250 ms pulse on one of the GPIO outputs (1-21)."""
        if not MIN_GPIO <= gpio <= MAX_GPIO:
            raise ValueError(f"GPIO must be between {MIN_GPIO} and {MAX_GPIO}, got {gpio}")
        reply = await self.command(f"PULSE {gpio}")
        if reply.strip().upper().startswith("OK"):
            return True
        _LOGGER.warning("Pulse on GPIO %s was not accepted: %s", gpio, reply)
        return False

    async def get_format_names(self, command: str) -> list[str]:
        """Read the list of format (input) names using the command that this unit accepts."""
        reply = await self.try_command(command)
        return _name_list(reply, command)

    async def get_macro_names(self) -> list[str]:
        """Read the list of macro names defined on the unit."""
        reply = await self.try_command("MACRONAMES")
        return _name_list(reply, "MACRONAMES")


async def probe_capabilities(client: Ap2xClient) -> Ap2xCapabilities:
    """Find out which undocumented commands this unit accepts.

    Every probe runs on its own connection attempt: a command the firmware does
    not know produces no reply, which drops the link, so probing this way cannot
    desynchronise the connection used for normal polling.
    """
    caps = Ap2xCapabilities()

    power = await client.try_command("POWER")
    if power is not None and _int_arg(power) in (0, 1):
        caps.power = True
        caps.pulse = True  # Same RS20i command set; PULSE itself cannot be probed safely.

    volume = await client.try_command("VOLUME")
    value = _int_arg(volume or "")
    if volume is not None and value is not None and 0 <= value <= VOLUME_MAX:
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


def _is_error_reply(reply: str) -> bool:
    """Return True when a reply means the command was refused or unknown."""
    text = reply.strip().upper()
    return not text or text.startswith(("ERR", "SECERR", "?"))


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
        _LOGGER.debug("Expected a number, got: %s", reply)
        return None


def _name_arg(reply: str, command: str) -> str | None:
    """Return a response value that may itself contain spaces."""
    text = reply.strip()
    if text.upper().startswith(command):
        text = text[len(command) :].strip()
    return text or None


def _name_list(reply: str | None, command: str) -> list[str]:
    """Parse a comma-separated list of names, with or without an echoed command word."""
    if reply is None:
        return []
    text = reply.strip()
    if text.upper().startswith(command):
        text = text[len(command) :].strip()
    return [name.strip() for name in text.split(",") if name.strip()]


def _board_names(reply: str) -> list[str]:
    """Return the board identifiers listed by @BOARDINFO."""
    names: list[str] = []
    for record in reply.replace("\n", ",").split(","):
        token = record.strip()
        if token.upper().startswith(("H3", "HDMI")) and token not in names:
            names.append(token)
    return names


def _float_list(csv: str | None) -> list[float]:
    """Parse a comma-separated list of floats, skipping unparsable fields."""
    if not csv:
        return []
    values: list[float] = []
    for item in csv.split(","):
        try:
            values.append(float(item))
        except ValueError:
            _LOGGER.debug("Skipping unparsable value: %s", item)
    return values
