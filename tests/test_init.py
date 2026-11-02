"""Tests for setting up, using and unloading the Datasat AP20/AP25 integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

from custom_components.datasat_ap2x.api import (
    Ap2xAuthError,
    Ap2xConnectionError,
    Ap2xError,
    Ap2xProtocolError,
)
from custom_components.datasat_ap2x.const import (
    CONF_ENABLE_PULSE,
    DOMAIN,
    ISSUE_SETUP_PASSWORD,
    SERVICE_PULSE,
)
from custom_components.datasat_ap2x.diagnostics import async_get_config_entry_diagnostics
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
    CONF_HOST,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_UP,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import FORMATS, HOST, MAC, MACROS, SERIAL

REDACTED = "**REDACTED**"


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look up an entity id by the unique id the integration gives it."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}")
    assert entity_id is not None, f"no {platform} entity with key {key}"
    return entity_id


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, options: dict | None = None) -> None:
    """Add the entry, apply options, and set it up."""
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload the entry again."""
    assert await hass.config_entries.async_unload(entry.entry_id)
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
    """With pulses allowed in the options, the action fires the requested GPIO output."""
    await _setup(hass, mock_config_entry, {CONF_ENABLE_PULSE: True})
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    await hass.services.async_call(
        DOMAIN, SERVICE_PULSE, {ATTR_ENTITY_ID: player, "gpio": 3}, blocking=True
    )
    mock_client.pulse_gpio.assert_awaited_once_with(3)
    await _unload(hass, mock_config_entry)


async def test_pulse_action_off_by_default(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Pulses are refused until they are allowed in the options."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_PULSE, {ATTR_ENTITY_ID: player, "gpio": 3}, blocking=True
        )
    mock_client.pulse_gpio.assert_not_awaited()
    await _unload(hass, mock_config_entry)


async def test_pulse_action_admin_only(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    hass_read_only_user: MockUser,
) -> None:
    """A user without admin rights cannot fire pulses, even when they are allowed."""
    await _setup(hass, mock_config_entry, {CONF_ENABLE_PULSE: True})
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_PULSE,
            {ATTR_ENTITY_ID: player, "gpio": 3},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    mock_client.pulse_gpio.assert_not_awaited()
    await _unload(hass, mock_config_entry)


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


async def test_select_unknown_format_is_refused(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Only formats from the list are sent, so no second command can be smuggled in."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_SELECT_SOURCE,
            {ATTR_ENTITY_ID: player, ATTR_INPUT_SOURCE: "Nonsync\r@POWER 0"},
            blocking=True,
        )
    mock_client.set_format.assert_not_awaited()
    await _unload(hass, mock_config_entry)


async def test_volume_steps_read_the_fader_first(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Volume up and down step from the fader as it is now, not as it was last polled."""
    await _setup(hass, mock_config_entry)
    player = _entity_id(hass, Platform.MEDIA_PLAYER, "media_player")

    # Someone moved the fader on the front panel since the last poll.
    mock_client.get_fader.return_value = 30
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_VOLUME_UP, {ATTR_ENTITY_ID: player}, blocking=True
    )
    mock_client.set_fader.assert_awaited_once_with(31)

    mock_client.set_fader.reset_mock()
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_VOLUME_DOWN, {ATTR_ENTITY_ID: player}, blocking=True
    )
    mock_client.set_fader.assert_awaited_once_with(29)

    mock_client.set_fader.reset_mock()
    mock_client.get_fader.return_value = None
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_VOLUME_UP, {ATTR_ENTITY_ID: player}, blocking=True
    )
    mock_client.set_fader.assert_not_awaited()
    await _unload(hass, mock_config_entry)


async def test_setup_password_raises_repair_issue(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Logging in with the Setup password raises a repair issue, removed with the entry."""
    mock_client.auth_level = "SETUP"
    await _setup(hass, mock_config_entry)
    issue_id = f"{ISSUE_SETUP_PASSWORD}_{mock_config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_operator_password_clears_repair_issue(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """After switching to the NetCmd password, the repair issue disappears."""
    issue_id = f"{ISSUE_SETUP_PASSWORD}_{mock_config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_SETUP_PASSWORD,
    )
    mock_client.auth_level = "OP"
    await _setup(hass, mock_config_entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    await _unload(hass, mock_config_entry)


async def test_unexpected_answer_is_logged_once(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A processor that keeps answering nonsense gives one warning, not one per poll."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    mock_client.get_fader.side_effect = Ap2xProtocolError("garbled reply")
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and "garbled reply" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert coordinator.data.reachable is False

    mock_client.get_fader.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.data.reachable is True
    await _unload(hass, mock_config_entry)


async def test_diagnostics_leave_out_private_data(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics redact credentials, addresses, identifiers and site names."""
    await _setup(hass, mock_config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    data = diagnostics["entry"]["data"]
    assert data[CONF_HOST] == REDACTED
    assert data["mac"] == REDACTED
    assert data["serial"] == REDACTED
    assert diagnostics["system"]["theater"] == REDACTED
    assert diagnostics["system"]["version"] == "3.1.2"
    text = str(diagnostics)
    for private in (HOST, MAC, SERIAL, "Circuit-1", "Theater-3", "Screen-3"):
        assert private not in text
    await _unload(hass, mock_config_entry)
