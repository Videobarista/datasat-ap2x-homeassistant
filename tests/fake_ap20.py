"""A scripted Datasat processor for the tests, reached through in-memory streams.

connected_to() replaces asyncio.open_connection inside the client, so the real
client code runs without a socket. Every connection records the address and
port it was opened to, and every command line records the connection that
carried it, so tests can check where the integration sends its traffic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

HOST = "192.0.2.20"  # documentation address (RFC 5737)
MAC = "080077124578"  # the example from TN-H413
SERIAL = "AP20-0001"

Reply = str | bytes | Callable[[str], "str | bytes | None"] | None

DEFAULT_REPLIES: dict[str, Reply] = {
    "SYSTEM": f"VER 3.1.2\nVERDATE 2024-05-01\nMAC {MAC}".encode() + b"\r\x00",
    "SERIALNO": f"SERIALNO {SERIAL}",
    "IDENTIFY": f"AP20 {HOST} Circuit-1 Theater-3 Screen-3",
    "BOARDINFO": "H331,1,2,3,4,5,6,7,\nH332,1,2,3,4,5,6,7,\nHDMI,1,2,3,4,5,6,7,",
    "AUTH": "AUTH OP",
    "POWER": "POWER 1",
    "FADER": "FADER 70",
    "MUTED": "MUTED 0",
    "FORMAT": "FORMAT Nonsync",
    "MONITORLEVEL": "MONITORLEVEL 100",
    "MONITORMUTE": "MONITORMUTE 0",
    "VOLUME": "BadCommand",
    "FORMATNAMES": "DCP 5.1 discrete,HDMI 1 Stereo,Nonsync",
    "INPUTNAMES": "BadCommand",
    "MACRONAMES": "FORMAT_1,HDMI 1",
    "SCR": "OK",
    "RUNMACRO": "OK",
    "PULSE": "OK",
    "HEALTH": lambda cmd: f"{cmd} 1,3.18,4.99,15.0,-15.0,-5.0",
}


@dataclass(frozen=True)
class SentLine:
    """One command line, with the address and port of the connection that carried it."""

    host: str
    port: int
    line: str


class _FakeWriter:
    """Stream writer that hands every complete command line to the fake device."""

    def __init__(
        self, device: FakeAP20, reader: asyncio.StreamReader, host: str, port: int
    ) -> None:
        self._device = device
        self._reader = reader
        self._host = host
        self._port = port
        self._buffer = b""
        self._closing = False

    def write(self, data: bytes) -> None:
        self._buffer += data
        while b"\r" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\r", 1)
            line = raw.decode("ascii")
            self._device.sent_lines.append(SentLine(self._host, self._port, line))
            self._reader.feed_data(self._device.answer(line))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._closing = True

    def is_closing(self) -> bool:
        return self._closing

    async def wait_closed(self) -> None:
        return None


class FakeAP20:
    """A scripted processor reached through an in-memory stream instead of a socket."""

    def __init__(self, **replies: Reply) -> None:
        self.replies: dict[str, Reply] = {**DEFAULT_REPLIES, **replies}
        self.sent: list[str] = []
        self.sent_lines: list[SentLine] = []
        self.targets: list[tuple[str, int]] = []

    @property
    def connections(self) -> int:
        """Return how many connections were opened."""
        return len(self.targets)

    async def open_connection(
        self, host: str, port: int, limit: int = 2**16
    ) -> tuple[asyncio.StreamReader, _FakeWriter]:
        self.targets.append((host, port))
        reader = asyncio.StreamReader(limit=limit)
        return reader, _FakeWriter(self, reader, host, port)

    def answer(self, line: str) -> bytes:
        self.sent.append(line)
        command = line.removeprefix("@")
        reply = self.replies.get(command, self.replies.get(command.split(" ", 1)[0]))
        if callable(reply):
            reply = reply(command)
        if reply is None:
            return b""
        if isinstance(reply, bytes):
            return reply
        return reply.encode("ascii") + b"\r"


@contextmanager
def connected_to(device: FakeAP20) -> Iterator[None]:
    """Route the client's connections to the fake device."""
    with patch(
        "custom_components.datasat_ap2x.api.asyncio.open_connection", device.open_connection
    ):
        yield
