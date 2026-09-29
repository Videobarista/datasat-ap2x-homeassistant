"""Media player entity for the Datasat AP20/AP25."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Ap2xConfigEntry, Ap2xRuntimeData
from .api import MAX_GPIO, MIN_GPIO
from .const import (
    ATTR_GPIO,
    CONF_FORMATS,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_POWER_SWITCH,
    FADER_MAX,
    SERVICE_PULSE,
)
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player and register the GPIO pulse service."""
    async_add_entities([Ap2xMediaPlayer(entry.runtime_data, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PULSE,
        {vol.Required(ATTR_GPIO): vol.All(vol.Coerce(int), vol.Range(min=MIN_GPIO, max=MAX_GPIO))},
        "async_pulse",
    )


class Ap2xMediaPlayer(Ap2xEntity, MediaPlayerEntity):
    """The processor as a media player: volume is the fader, source the format."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the media player entity."""
        super().__init__(runtime_data, entry, "media_player")

    @property
    def _formats(self) -> list[str]:
        """Return the format names, read from the unit when it supports listing them."""
        if self._capabilities.format_names:
            return self._capabilities.format_names
        raw = self._entry.options.get(CONF_FORMATS, "")
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def _power_switch(self) -> str | None:
        """Return the external switch entity that feeds the processor."""
        return self._entry.options.get(CONF_POWER_SWITCH) or None

    @property
    def available(self) -> bool:
        """Stay available while the unit is off so turn_on remains usable."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState:
        """Report standby and unreachable units as off."""
        return MediaPlayerState.ON if self._awake else MediaPlayerState.OFF

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Expose the features that this unit and this configuration support."""
        features = (
            MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )
        if self._formats:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if (
            self._capabilities.power
            or self._power_switch
            or self._entry.options.get(CONF_POWER_ON_MACRO)
        ):
            features |= MediaPlayerEntityFeature.TURN_ON
        if (
            self._capabilities.power
            or self._power_switch
            or self._entry.options.get(CONF_POWER_OFF_MACRO)
        ):
            features |= MediaPlayerEntityFeature.TURN_OFF
        return features

    @property
    def volume_level(self) -> float | None:
        """Return the master fader as a 0.0-1.0 value."""
        fader = self.coordinator.data.fader
        return None if fader is None else fader / FADER_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        """Return the master mute state."""
        return self.coordinator.data.muted

    @property
    def source(self) -> str | None:
        """Return the active format."""
        return self.coordinator.data.format

    @property
    def source_list(self) -> list[str] | None:
        """Return the known format names."""
        return self._formats or None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the fader and, where supported, the volume in dB."""
        fader = self.coordinator.data.fader
        attributes: dict[str, object] = {"fader": None if fader is None else fader / 10}
        volume_db = self.coordinator.data.volume_db
        if volume_db is not None:
            attributes["volume_db"] = -volume_db / 10
        attributes["format_list_source"] = (
            self._capabilities.names_command if self._capabilities.format_names else "options"
        )
        return attributes

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the master fader."""
        level = round(volume * FADER_MAX)
        await self._async_send(lambda: self.coordinator.client.set_fader(level), "set the fader")

    async def async_volume_up(self) -> None:
        """Raise the master fader by one tenth."""
        level = (self.coordinator.data.fader or 0) + 1
        await self._async_send(lambda: self.coordinator.client.set_fader(level), "raise the fader")

    async def async_volume_down(self) -> None:
        """Lower the master fader by one tenth."""
        level = (self.coordinator.data.fader or 0) - 1
        await self._async_send(lambda: self.coordinator.client.set_fader(level), "lower the fader")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the main outputs."""
        await self._async_send(
            lambda: self.coordinator.client.set_muted(mute), "change the mute state"
        )

    async def async_select_source(self, source: str) -> None:
        """Select a format by name."""
        await self._async_send(
            lambda: self.coordinator.client.set_format(source), f"select format '{source}'"
        )

    async def async_pulse(self, gpio: int) -> None:
        """Fire a 250 ms pulse on a GPIO output."""
        await self._async_send(
            lambda: self.coordinator.client.pulse_gpio(gpio), f"pulse GPIO {gpio}"
        )

    async def async_turn_on(self) -> None:
        """Leave standby, using the unit's own power command where available."""
        await self._call_power_switch(SERVICE_TURN_ON)

        if self._capabilities.power:
            await self._async_send(lambda: self.coordinator.client.set_power(True), "leave standby")

        macro = self._entry.options.get(CONF_POWER_ON_MACRO)
        if macro:
            await self._async_send(
                lambda: self.coordinator.client.run_macro(macro), f"run power-on macro '{macro}'"
            )

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Run the standby macro, then put the unit in standby."""
        macro = self._entry.options.get(CONF_POWER_OFF_MACRO)
        if macro:
            await self._async_send(
                lambda: self.coordinator.client.run_macro(macro), f"run standby macro '{macro}'"
            )

        if self._capabilities.power:
            await self._async_send(
                lambda: self.coordinator.client.set_power(False), "enter standby"
            )

        await self._call_power_switch(SERVICE_TURN_OFF)
        await self.coordinator.async_request_refresh()

    async def _call_power_switch(self, service: str) -> None:
        """Forward power control to an external switch entity, when configured."""
        entity_id = self._power_switch
        if not entity_id:
            return
        domain = entity_id.split(".", 1)[0]
        await self.hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
