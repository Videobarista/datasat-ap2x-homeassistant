"""Tests for the Datasat AP20/AP25 config and options flows."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.datasat_ap2x.api import Ap2xAuthError, Ap2xConnectionError, Ap2xProtocolError
from custom_components.datasat_ap2x.const import (
    CONF_ENABLE_PULSE,
    CONF_FORMATS,
    CONF_MAC,
    CONF_MACROS,
    CONF_POWER_ON_MACRO,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import HOST, MAC, PORT, SERIAL, TITLE, make_system_info

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

USER_INPUT = {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: ""}


async def test_user_flow(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """A manual setup tests the connection and creates an entry keyed by MAC address."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: f" {HOST} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: PORT,
        CONF_PASSWORD: "",
        CONF_MAC: MAC,
        CONF_SERIAL: SERIAL,
    }
    assert result["result"].unique_id == MAC
    mock_client.connect.assert_awaited_once()
    mock_client.disconnect.assert_awaited()


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (Ap2xAuthError("SECERR"), "invalid_auth"),
        (Ap2xConnectionError("refused"), "cannot_connect"),
        (Ap2xProtocolError("not a Datasat"), "not_a_processor"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Errors are shown on the form, the socket is closed, and the flow recovers."""
    mock_client.connect.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    mock_client.disconnect.assert_awaited()

    mock_client.connect.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("mac", "serial", "unique_id"),
    [
        (None, SERIAL, SERIAL),
        (None, None, f"{HOST}:{PORT}"),
    ],
)
async def test_user_flow_unique_id_fallback(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mac: str | None,
    serial: str | None,
    unique_id: str,
) -> None:
    """Without a MAC address the serial number, then host and port, identify the unit."""
    mock_client.get_system_info.return_value = make_system_info(mac=mac, serial=serial)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == unique_id


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Adding the same processor twice is refused."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_unsafe_password(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """A password with control characters is refused before anything is sent."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PASSWORD: "pw\r@POWER 0"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PASSWORD: "invalid_password"}
    mock_client.connect.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PASSWORD: "p@ssword"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == "p@ssword"


async def test_options_flow(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Options are stored, fields left empty are not, and pulses stay off by default."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_FORMATS: "DCP 5.1 discrete, Nonsync",
            CONF_MACROS: "",
            CONF_POWER_ON_MACRO: "FORMAT_1",
            CONF_SCAN_INTERVAL: 20,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_FORMATS: "DCP 5.1 discrete, Nonsync",
        CONF_POWER_ON_MACRO: "FORMAT_1",
        CONF_ENABLE_PULSE: False,
        CONF_SCAN_INTERVAL: 20,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_FORMATS, "Nonsync, HDMI 1\r@POWER 0"),
        (CONF_MACROS, "FORMAT_1, bad@macro"),
        (CONF_POWER_ON_MACRO, "Kanaal \u00e9"),
    ],
)
async def test_options_flow_unsafe_names(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, field: str, value: str
) -> None:
    """Names the processor cannot take are refused per field, and nothing is stored."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {field: value})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: "invalid_names"}
    assert mock_config_entry.options == {}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_PULSE: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_ENABLE_PULSE] is True
