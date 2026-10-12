"""Tests for the Datasat AP20/AP25 config and options flows."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.datasat_ap2x.api import Ap2xAuthError, Ap2xConnectionError
from custom_components.datasat_ap2x.const import (
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


async def test_options_flow(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Options are stored, and fields left empty are not."""
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
        CONF_SCAN_INTERVAL: 20,
    }
