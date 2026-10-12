"""Tests for setting up, using and unloading the Datasat AP20/AP25 integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.datasat_ap2x.api import Ap2xAuthError, Ap2xConnectionError, Ap2xError
from custom_components.datasat_ap2x.const import DOMAIN, SERVICE_PULSE
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_INPUT_SOURCE_LIST,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_SELECT_SOURCE,
    SERVICE_VOLUME_SET,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import FORMATS, MAC, MACROS


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look up an entity id by the unique id the integration gives it."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}")
    assert entity_id is not None, f"no {platform} entity with key {key}"
    return entity_id


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The entry loads, creates the device and its entities, and unloads cleanly."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, MAC), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.sw_version == "3.1.2"

    player = hass.states.get(_entity_id(hass, Platform.MEDIA_PLAYER, "media_player"))
    assert player.state == STATE_ON
    assert player.attributes[ATTR_INPUT_SOURCE] == "DCP 5.1 discrete"
    assert player.attributes[ATTR_INPUT_SOURCE_LIST] == FORMATS
    assert player.attributes[ATTR_MEDIA_VOLUME_LEVEL] == pytest.approx(0.7)

    for macro in MACROS:
        key = "macro_" + macro.lower().replace(" ", "_")
        assert hass.states.get(_entity_id(hass, Platform.BUTTON, key)) is not None

    temperature = hass.states.get(_entity_id(hass, Platform.SENSOR, "temp_h331"))
    assert float(temperature.state) == pytest.approx(37.0)
    connection = hass.states.get(_entity_id(hass, Platform.BINARY_SENSOR, "connectivity"))
    assert connection.state == STATE_ON
    phantom = hass.states.get(_entity_id(hass, Platform.BINARY_SENSOR, "phantom_power"))
    assert phantom.state == STATE_OFF
    missing_board = hass.states.get(_entity_id(hass, Platform.BINARY_SENSOR, "volts_h338"))
    assert missing_board.state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.disconnect.assert_awaited()


async def test_setup_processor_off(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A processor that does not answer still loads and is reported as off."""
    offline = Ap2xConnectionError("no route to host")
    mock_client.get_system_info.side_effect = offline
    mock_client.get_fader.side_effect = offline

    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    player = hass.states.get(_entity_id(hass, Platform.MEDIA_PLAYER, "media_player"))
    assert player.state == STATE_OFF
    connection = hass.states.get(_entity_id(hass, Platform.BINARY_SENSOR, "connectivity"))
    assert connection.state == STATE_OFF

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_rejected_password(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A processor that rejects the password is a configuration error."""
    mock_client.get_system_info.side_effect = Ap2xAuthError("SECERR")

    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_client.disconnect.assert_awaited()


async def test_setup_unexpected_identification_reply(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An odd reply while identifying the unit is logged, and setup carries on."""
    mock_client.get_system_info.side_effect = Ap2xError("garbled reply")

    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_legacy_power_supply_sensor_removed(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The combined power-supply sensor from version 1.3 is removed on setup."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        Platform.BINARY_SENSOR,
        DOMAIN,
        f"{MAC}_psu_fault",
        config_entry=mock_config_entry,
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(legacy.entity_id) is None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_pulse_action_registered_without_entries(hass: HomeAssistant) -> None:
    """The pulse action exists as soon as the integration loads, before any entry."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, SERVICE_PULSE)


async def test_pulse_action(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The pulse action fires the requested GPIO output."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    await hass.services.async_call(
        DOMAIN, SERVICE_PULSE, {ATTR_ENTITY_ID: player, "gpio": 3}, blocking=True
    )
    mock_client.pulse_gpio.assert_awaited_once_with(3)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_media_player_controls(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Source, volume and power reach the processor as format, fader and POWER."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: player, ATTR_INPUT_SOURCE: "Nonsync"},
        blocking=True,
    )
    mock_client.set_format.assert_awaited_once_with("Nonsync")

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: player, ATTR_MEDIA_VOLUME_LEVEL: 0.5},
        blocking=True,
    )
    mock_client.set_fader.assert_awaited_once_with(50)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: player}, blocking=True
    )
    mock_client.set_power.assert_awaited_with(False)

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: player}, blocking=True
    )
    mock_client.set_power.assert_awaited_with(True)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_command_while_processor_off(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A command sent while the unit is unreachable is dropped without an error."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")
    mock_client.set_format.side_effect = Ap2xConnectionError("switched off")

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: player, ATTR_INPUT_SOURCE: "Nonsync"},
        blocking=True,
    )
    mock_client.set_format.assert_awaited_once_with("Nonsync")

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
