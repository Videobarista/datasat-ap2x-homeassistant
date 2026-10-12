"""Fixtures for the Datasat AP20/AP25 tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.datasat_ap2x.api import Ap2xCapabilities, Ap2xSystemInfo, Ap2xVolts
from custom_components.datasat_ap2x.const import CONF_MAC, CONF_SERIAL, DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT

# Documentation address (RFC 5737); the MAC is the example from TN-H413.
HOST = "192.0.2.20"
PORT = 14500
MAC = "080077124578"
SERIAL = "AP20-0001"
TITLE = f"Datasat AP20/AP25 ({HOST})"

FORMATS = ["DCP 5.1 discrete", "HDMI 1 Stereo", "Nonsync"]
MACROS = ["FORMAT_1", "HDMI 1"]

ENTRY_DATA: dict[str, Any] = {
    CONF_HOST: HOST,
    CONF_PORT: PORT,
    CONF_PASSWORD: "",
    CONF_MAC: MAC,
    CONF_SERIAL: SERIAL,
}


def make_system_info(mac: str | None = MAC, serial: str | None = SERIAL) -> Ap2xSystemInfo:
    """Return the identification an AP20 reports."""
    return Ap2xSystemInfo(
        version="3.1.2",
        version_date="2024-05-01",
        mac=mac,
        serial=serial,
        boards=["H331", "H332", "H335", "H336"],
    )


def make_capabilities() -> Ap2xCapabilities:
    """Return the capabilities found on a real AP20: everything but @VOLUME."""
    return Ap2xCapabilities(
        power=True,
        screensaver=True,
        volume_db=False,
        pulse=True,
        names_command="FORMATNAMES",
        format_names=list(FORMATS),
        macro_names=list(MACROS),
    )


def _volts(board: str) -> Ap2xVolts:
    """Return a healthy voltage record; the H338 board is not fitted."""
    if board == "H338":
        return Ap2xVolts(present=False)
    if board == "H336":
        # ref, +5V, +15V, -15V, 48V phantom (off), vcpu ok
        return Ap2xVolts(present=True, ok=True, values=[3.39, 5.10, 15.0, -14.4, 0.0, 1.0])
    return Ap2xVolts(present=True, ok=True, values=[3.18, 4.99, 15.0, -15.0, -5.0])


def make_client() -> MagicMock:
    """Return a mocked Ap2xClient that behaves like a healthy AP20 in operation."""
    client = MagicMock()
    client.host = HOST
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_system_info = AsyncMock(return_value=make_system_info())
    client.get_power = AsyncMock(return_value=True)
    client.get_fader = AsyncMock(return_value=70)
    client.get_muted = AsyncMock(return_value=False)
    client.get_format = AsyncMock(return_value="DCP 5.1 discrete")
    client.get_monitor_level = AsyncMock(return_value=70)
    client.get_monitor_muted = AsyncMock(return_value=False)
    client.get_volume_db = AsyncMock(return_value=None)
    client.get_temperatures = AsyncMock(return_value=[37.0, 34.0, 36.0])
    client.get_volts = AsyncMock(side_effect=_volts)
    for name in (
        "set_fader",
        "set_muted",
        "set_format",
        "set_monitor_level",
        "set_monitor_muted",
        "set_power",
        "set_volume_db",
        "set_screensaver",
    ):
        setattr(client, name, AsyncMock())
    client.run_macro = AsyncMock(return_value=True)
    client.pulse_gpio = AsyncMock(return_value=True)
    return client


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the TCP client everywhere it is created; return the shared instance."""
    client = make_client()
    with (
        patch("custom_components.datasat_ap2x.config_flow.Ap2xClient", return_value=client),
        patch("custom_components.datasat_ap2x.Ap2xClient", return_value=client),
        patch(
            "custom_components.datasat_ap2x.probe_capabilities",
            new=AsyncMock(return_value=make_capabilities()),
        ),
    ):
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip setting up the entry, for config flow tests."""
    with patch(
        "custom_components.datasat_ap2x.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for one processor."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id=MAC,
        data=dict(ENTRY_DATA),
    )
