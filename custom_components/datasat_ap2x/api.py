"""Async TCP client for the Datasat AP20/AP25 (TN-H413 rev D protocol)."""

from __future__ import annotations

import asyncio
import logging
import socket

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 14500
_TIMEOUT = 5.0


class Ap2xAuthError(Exception):
    """Raised when AUTH is rejected (SECERR)."""


class Ap2xConnectionError(Exception):
    """Raised when the device cannot be reached."""


class Ap2xClient:
    """Persistent connection to an AP20/AP25.

    Commands are sent as ``@COMMAND<CR>``; responses are ASCII terminated
    by ``<CR>`` (SYSTEM additionally uses ``<LF>`` separators and a NUL).
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT, password: str | None = None) -> None:
        self.host = host
        self.port = port
        self.password = password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the connection and authenticate if a password is set."""
        async with self._lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), _TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            self._reader = self._writer = None
            raise Ap2xConnectionError(f"Cannot connect to {self.host}:{self.port}") from err

        if self.password:
            reply = await self._request_locked(f"AUTH {self.password}")
            if "SECERR" in reply:
                await self._close_locked()
                raise Ap2xAuthError("AUTH rejected (SECERR)")

    async def disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = None

    async def command(self, cmd: str) -> str:
        """Send one command and return the raw response line."""
        async with self._lock:
            try:
                await self._connect_locked()
                return await self._request_locked(cmd)
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
                await self._close_locked()
                raise Ap2xConnectionError(f"I/O error on '{cmd}'") from err

    async def _request_locked(self, cmd: str) -> str:
        assert self._reader is not None and self._writer is not None
        self._writer.write(f"@{cmd}\r".encode("ascii"))
        await self._writer.drain()
        raw = await asyncio.wait_for(self._reader.readuntil(b"\r"), _TIMEOUT)
        # SYSTEM ends with CR + NUL; flush a trailing NUL if present.
        text = raw.decode("ascii", errors="replace").strip("\r\n\x00 ")
        _LOGGER.debug("%s -> %s", cmd, text)
        return text

    # ---- Convenience wrappers -------------------------------------------

    async def get_mac(self) -> str | None:
        reply = await self.command("MAC")
        parts = reply.split()
        return parts[-1] if len(parts) >= 2 else None

    async def get_serial(self) -> str | None:
        reply = await self.command("SERIALNO")
        parts = reply.split()
        return parts[-1] if len(parts) >= 2 else None

    async def get_fader(self) -> int | None:
        return _int_arg(await self.command("FADER"))

    async def set_fader(self, tenths: int) -> None:
        await self.command(f"FADER {max(0, min(100, tenths))}")

    async def get_muted(self) -> bool | None:
        val = _int_arg(await self.command("MUTED"))
        return None if val is None else bool(val)

    async def set_muted(self, muted: bool) -> None:
        await self.command(f"MUTED {1 if muted else 0}")

    async def get_format(self) -> str | None:
        reply = await self.command("FORMAT")
        if reply.upper().startswith("FORMAT"):
            return reply[6:].strip() or None
        return reply.strip() or None

    async def set_format(self, name: str) -> None:
        await self.command(f"FORMAT {name}")

    async def run_macro(self, name: str) -> bool:
        return (await self.command(f"RUNMACRO {name}")).strip().upper().startswith("OK")

    async def get_temperatures(self) -> list[float]:
        """Return [H331, H332, H335] board temperatures in °C."""
        reply = await self.command("HEALTH TEMPERATURE")
        return _float_list(_last_field(reply))

    async def get_h336_volts_ok(self) -> bool | None:
        """Return True if the H336 power-supply voltages are within limits."""
        reply = await self.command("HEALTH H336VOLTS")
        field = _last_field(reply)
        if field.upper() == "NA" or not field:
            return None
        first = field.split(",")[0].strip()
        return first == "1" if first in ("0", "1") else None


def _last_field(reply: str) -> str:
    """Strip the echoed command words, keep the data part."""
    parts = reply.split()
    return parts[-1] if parts else ""


def _int_arg(reply: str) -> int | None:
    try:
        return int(_last_field(reply))
    except ValueError:
        return None


def _float_list(csv: str) -> list[float]:
    out: list[float] = []
    for item in csv.split(","):
        try:
            out.append(float(item))
        except ValueError:
            continue
    return out


def send_wol(mac: str, broadcast: str = "255.255.255.255") -> None:
    """Send a Wake-on-LAN magic packet (blocking, run in executor)."""
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    packet = bytes.fromhex("FF" * 6 + clean * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, 9))
