"""Tests for the TCP client, against a scripted processor that can misbehave."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import logging
from unittest.mock import patch

import pytest

from custom_components.datasat_ap2x.api import (
    AUTH_LEVEL_SETUP,
    LINE_LIMIT,
    MAX_ARGUMENT_LENGTH,
    MAX_NAMES,
    Ap2xAuthError,
    Ap2xClient,
    Ap2xInvalidArgument,
    Ap2xProtocolError,
    is_safe_argument,
    is_safe_password,
    parse_name_list,
    probe_capabilities,
)

HOST = "192.0.2.20"
MAC = "080077124578"
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


class _FakeWriter:
    """Stream writer that hands every complete command line to the fake device."""

    def __init__(self, device: FakeAP20, reader: asyncio.StreamReader) -> None:
        self._device = device
        self._reader = reader
        self._buffer = b""
        self._closing = False

    def write(self, data: bytes) -> None:
        self._buffer += data
        while b"\r" in self._buffer:
            line, self._buffer = self._buffer.split(b"\r", 1)
            self._reader.feed_data(self._device.answer(line.decode("ascii")))

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
        self.connections = 0

    async def open_connection(
        self, host: str, port: int, limit: int = 2**16
    ) -> tuple[asyncio.StreamReader, _FakeWriter]:
        self.connections += 1
        reader = asyncio.StreamReader(limit=limit)
        return reader, _FakeWriter(self, reader)

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


@contextmanager
def captured_log() -> Iterator[list[logging.LogRecord]]:
    """Capture everything the client logs, including debug lines."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("custom_components.datasat_ap2x.api")
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _text(records: list[logging.LogRecord]) -> str:
    return "\n".join(record.getMessage() for record in records)


# ---- Input checks ---------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["DCP 5.1 discrete", "HDMI 1", "Mic via center", "8CH 7.1", "x" * MAX_ARGUMENT_LENGTH]
)
def test_safe_names(name: str) -> None:
    """Real format and macro names pass."""
    assert is_safe_argument(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Nonsync\r@POWER 0",
        "line\nbreak",
        "tab\there",
        "nul\x00",
        "Kanaal é",
        "mail@example",
        "x" * (MAX_ARGUMENT_LENGTH + 1),
    ],
)
def test_unsafe_names(name: str) -> None:
    """Names that could end a command line, or that the unit cannot hold, are refused."""
    assert not is_safe_argument(name)


def test_passwords() -> None:
    """Passwords may contain '@' but never characters that end the line."""
    assert is_safe_password("p@ss word!")
    assert not is_safe_password("pw\r@POWER 0")
    assert not is_safe_password("")


def test_parse_name_list_caps_and_cleans() -> None:
    """Listings are trimmed, deduplicated, cleaned and capped."""
    raw = ",".join(
        [" HDMI 1 ", "HDMI 1", "bad@name", "Kanaal é", ""] + [f"F{i}" for i in range(100)]
    )
    names = parse_name_list(raw)
    assert names[0] == "HDMI 1"
    assert len(names) == MAX_NAMES
    assert len(set(names)) == len(names)
    assert "bad@name" not in names
    assert "Kanaal é" not in names


async def test_format_name_with_carriage_return_is_never_sent() -> None:
    """A second command smuggled into a name is refused before anything is sent."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xInvalidArgument):
        await client.set_format("Nonsync\r@POWER 0")
    assert device.sent == []


async def test_macro_name_with_carriage_return_is_never_sent() -> None:
    """The same check guards macro names."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xInvalidArgument):
        await client.run_macro("FORMAT_1\r@POWER 0")
    assert device.sent == []


async def test_command_with_control_characters_is_refused() -> None:
    """The client itself refuses any command line with control characters."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xInvalidArgument):
        await client.command("FADER 70\r@POWER 0")
    assert device.sent == []


async def test_unsafe_password_is_never_sent() -> None:
    """A password with control characters is refused without connecting."""
    device = FakeAP20()
    client = Ap2xClient(HOST, password="pw\r@POWER 0")
    with connected_to(device), pytest.raises(Ap2xAuthError):
        await client.get_fader()
    assert device.sent == []
    assert device.connections == 0


async def test_pulse_out_of_range_is_refused() -> None:
    """GPIO numbers outside 1-21 never reach the unit."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xInvalidArgument):
        await client.pulse_gpio(22)
    assert device.sent == []


# ---- Authentication -------------------------------------------------------


async def test_auth_level_recorded_and_password_not_logged() -> None:
    """The login level is recorded and the password never appears in the log."""
    device = FakeAP20(AUTH="AUTH SETUP")
    client = Ap2xClient(HOST, password="s3cret-pw")
    with connected_to(device), captured_log() as records:
        assert await client.get_fader() == 70
    assert client.auth_level == AUTH_LEVEL_SETUP
    assert device.sent[0] == "@AUTH s3cret-pw"
    assert "s3cret-pw" not in _text(records)
    assert "AUTH ***" in _text(records)


async def test_rejected_password() -> None:
    """SECERR on login is an authentication error and closes the socket."""
    device = FakeAP20(AUTH="AUTH SECERR")
    client = Ap2xClient(HOST, password="wrong")
    with connected_to(device), pytest.raises(Ap2xAuthError):
        await client.get_fader()
    assert not client.connected


async def test_secerr_on_a_command_is_an_auth_error() -> None:
    """A command refused for lack of a password raises an authentication error."""
    device = FakeAP20(FADER="SECERR")
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xAuthError):
        await client.get_fader()


# ---- Untrusted replies ----------------------------------------------------


async def test_overlong_reply_resets_the_connection() -> None:
    """A reply without terminator beyond the limit is a protocol error, not a hang."""
    device = FakeAP20(FADER=b"A" * (LINE_LIMIT + 100))
    client = Ap2xClient(HOST)
    with connected_to(device):
        with pytest.raises(Ap2xProtocolError):
            await client.get_fader()
        assert not client.connected

        device.replies["FADER"] = "FADER 70"
        assert await client.get_fader() == 70
    assert device.connections == 2


async def test_unexpected_extra_line_resynchronises() -> None:
    """An extra reply is caught at the next command and the connection starts afresh."""
    device = FakeAP20(FADER="FADER 70\rPOWER 1")
    client = Ap2xClient(HOST)
    with connected_to(device):
        assert await client.get_fader() == 70
        with pytest.raises(Ap2xProtocolError):
            await client.get_monitor_level()
        assert not client.connected
        assert await client.get_monitor_level() == 100


async def test_write_reply_must_belong_to_the_command() -> None:
    """A write command whose reply belongs to something else is a protocol error."""
    device = FakeAP20(RUNMACRO="FADER 70")
    client = Ap2xClient(HOST)
    with connected_to(device), pytest.raises(Ap2xProtocolError):
        await client.run_macro("FORMAT_1")


async def test_refused_macro_returns_false() -> None:
    """ERR from the unit means the macro does not exist."""
    device = FakeAP20(RUNMACRO="ERR no macro")
    client = Ap2xClient(HOST)
    with connected_to(device):
        assert await client.run_macro("FORMAT_9") is False


@pytest.mark.parametrize(
    ("reply", "expected"),
    [("FADER 999", None), ("FADER -5", None), ("FADER abc", None), ("FADER 35", 35)],
)
async def test_fader_out_of_range_is_ignored(reply: str, expected: int | None) -> None:
    """Values outside the documented range are treated as unknown."""
    device = FakeAP20(FADER=reply)
    client = Ap2xClient(HOST)
    with connected_to(device):
        assert await client.get_fader() == expected


async def test_non_finite_numbers_keep_their_position() -> None:
    """'inf', 'nan' and text become None without shifting the fields after them."""
    device = FakeAP20(
        HEALTH=lambda cmd: (
            "HEALTH TEMPERATURE 34,inf,nan"
            if cmd == "HEALTH TEMPERATURE"
            else "HEALTH H336VOLTS inf,3.39,5.10,15.0,-15.0-,0.0,1"
        )
    )
    client = Ap2xClient(HOST)
    with connected_to(device):
        assert await client.get_temperatures() == [34.0, None, None]
        volts = await client.get_volts("H336")
    assert volts.ok is None
    assert volts.values == [3.39, 5.10, 15.0, None, 0.0, 1.0]


async def test_identification_is_cleaned_and_kept_out_of_the_log() -> None:
    """Identification is parsed, while MAC, serial and site names stay out of the log."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device), captured_log() as records:
        info = await client.get_system_info()
    assert info.version == "3.1.2"
    assert info.mac == MAC
    assert info.serial == SERIAL
    assert info.theater == "Theater-3"
    assert info.boards == ["H331", "H332", "HDMI"]
    log = _text(records)
    for private in (MAC, SERIAL, "Circuit-1", "Theater-3"):
        assert private not in log
    # The configured address is logged on connect; the one inside @IDENTIFY is not.
    assert f"AP20 {HOST}" not in log


async def test_probe_on_an_ap20() -> None:
    """The probe finds what a real AP20 supports, and nothing it does not."""
    device = FakeAP20()
    client = Ap2xClient(HOST)
    with connected_to(device):
        caps = await probe_capabilities(client)
    assert caps.power
    assert caps.pulse
    assert caps.screensaver
    assert not caps.volume_db
    assert caps.names_command == "FORMATNAMES"
    assert caps.format_names == ["DCP 5.1 discrete", "HDMI 1 Stereo", "Nonsync"]
    assert caps.macro_names == ["FORMAT_1", "HDMI 1"]


async def test_probe_ignores_a_reply_for_another_command() -> None:
    """A POWER probe answered with something else does not enable power control."""
    device = FakeAP20(POWER="FADER 70")
    client = Ap2xClient(HOST)
    with connected_to(device):
        caps = await probe_capabilities(client)
    assert not caps.power
    assert not caps.pulse
