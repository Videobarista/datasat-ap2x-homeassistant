"""Async TCP client for the Datasat AP20/AP25 (TN-H413 rev D protocol)."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 14500
_TIMEOUT = 5.0


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


class Ap2xClient:
    """Persistent connection to an AP20/AP25.

    Commands are sent as ``@COMMAND<CR>``. Responses are ASCII, terminated by
    ``<CR>``; ``@SYSTEM`` uses ``<LF>`` between its fields and ends with a NUL
    byte after the final ``<CR>``.
    """

    def __init__(
        self, host: str, port: int = DEFAULT_PORT, password: str | None = None
    ) -> None:
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

    async def command(self, cmd: str) -> str:
        """Send one command and return the response line without its terminator."""
        async with self._lock:
            try:
                await self._connect_locked()
                return await self._request_locked(cmd)
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
                await self._close_locked()
                raise Ap2xConnectionError(
                    f"I/O error while sending '{cmd}' to {self.host}: {err}"
                ) from err

    # ---- Connection handling --------------------------------------------

    async def _connect_locked(self) -> None:
        if self.connected:
            return

        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), _TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            self._reader = None
            self._writer = None
            raise Ap2xConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err}"
            ) from err

        if self.password:
            reply = await self._request_locked(f"AUTH {self.password}")
            if "SECERR" in reply.upper():
                await self._close_locked()
                raise Ap2xAuthError("Password rejected by the processor (SECERR)")
            _LOGGER.debug("Authenticated: %s", reply)

    async def _close_locked(self) -> None:
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

    async def _request_locked(self, cmd: str) -> str:
        reader = self._reader
        writer = self._writer
        if reader is None or writer is None:
            raise Ap2xConnectionError(f"Not connected to {self.host}")

        writer.write(f"@{cmd}\r".encode("ascii", errors="replace"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.readuntil(b"\r"), _TIMEOUT)
        text = raw.decode("ascii", errors="replace").strip("\r\n\x00 ")
        _LOGGER.debug("%s -> %s", cmd, text)
        return text

    # ---- Read-only information ------------------------------------------

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
        reply = await self.command("FORMAT")
        if reply.upper().startswith("FORMAT"):
            return reply[len("FORMAT") :].strip() or None
        return reply.strip() or None

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
        _LOGGER.warning("Macro '%s' was not executed: %s", name, reply)
        return False

    async def get_temperatures(self) -> list[float]:
        """Return the [H331, H332, H335] board temperatures in degrees Celsius."""
        reply = await self.command("HEALTH TEMPERATURE")
        return _float_list(_text_arg(reply))

    async def get_h336_volts_ok(self) -> bool | None:
        """Return True when the H336 supply rails are within limits."""
        return await self._volts_ok("H336VOLTS")

    async def get_h331_volts_ok(self) -> bool | None:
        """Return True when the H331 supply rails are within limits."""
        return await self._volts_ok("H331VOLTS")

    async def _volts_ok(self, sub_cmd: str) -> bool | None:
        reply = await self.command(f"HEALTH {sub_cmd}")
        field = _text_arg(reply)
        if not field or field.upper() == "NA":
            return None
        first = field.split(",")[0].strip()
        if first in ("0", "1"):
            return first == "1"
        _LOGGER.debug("Unexpected %s response: %s", sub_cmd, reply)
        return None


# ---- Parsing helpers -----------------------------------------------------


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


def send_wol(mac: str, broadcast: str = "255.255.255.255") -> None:
    """Send a Wake-on-LAN magic packet. Blocking; run in an executor."""
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    packet = bytes.fromhex("FF" * 6 + clean * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, 9))
