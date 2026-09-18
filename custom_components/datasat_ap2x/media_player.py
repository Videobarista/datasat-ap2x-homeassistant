"""Media player entity for the Datasat AP20/AP25."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Ap2xConfigEntry
from .const import (
    CONF_FORMATS,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_POWER_SWITCH,
    FADER_MAX,
)
from .entity import Ap2xEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player for this processor."""
    async_add_entities([Ap2xMediaPlayer(entry.runtime_data, entry)])


class Ap2xMediaPlayer(Ap2xEntity, MediaPlayerEntity):
    """The processor as a media player: volume is the master fader, source the format."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the media player entity."""
        super().__init__(runtime_data, entry, "media_player")

    # ---- Configuration helpers ------------------------------------------

    @property
    def _formats(self) -> list[str]:
        raw = self._entry.options.get(CONF_FORMATS, "")
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def _power_switch(self) -> str | None:
        return self._entry.options.get(CONF_POWER_SWITCH) or None

    # ---- State -----------------------------------------------------------

    @property
    def available(self) -> bool:
        """Stay available while the unit is off so turn_on remains usable."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState:
        """Report on when the processor answers, off when it does not."""
        return MediaPlayerState.ON if self._online else MediaPlayerState.OFF

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Expose the features that are actually configured."""
        features = (
            MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )
        if self._formats:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if self._power_switch or self._entry.options.get(CONF_POWER_ON_MACRO):
            features |= MediaPlayerEntityFeature.TURN_ON
        if self._power_switch or self._entry.options.get(CONF_POWER_OFF_MACRO):
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
        """Return the configured format names."""
        return self._formats or None

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Expose the fader in the unit used on the front panel."""
        fader = self.coordinator.data.fader
        return {"fader": None if fader is None else fader / 10}

    # ---- Commands --------------------------------------------------------

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the master fader."""
        level = round(volume * FADER_MAX)
        await self._async_send(
            lambda: self.coordinator.client.set_fader(level), "set the fader"
        )

    async def async_volume_up(self) -> None:
        """Raise the master fader by one tenth."""
        level = (self.coordinator.data.fader or 0) + 1
        await self._async_send(
            lambda: self.coordinator.client.set_fader(level), "raise the fader"
        )

    async def async_volume_down(self) -> None:
        """Lower the master fader by one tenth."""
        level = (self.coordinator.data.fader or 0) - 1
        await self._async_send(
            lambda: self.coordinator.client.set_fader(level), "lower the fader"
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the main outputs."""
        await self._async_send(
            lambda: self.coordinator.client.set_muted(mute), "change the mute state"
        )

    async def async_select_source(self, source: str) -> None:
        """Select a format by name."""
        await self._async_send(
            lambda: self.coordinator.client.set_format(source),
            f"select format '{source}'",
        )

    async def async_turn_on(self) -> None:
        """Switch on the configured power switch, then run the power-on macro."""
        await self._call_power_switch(SERVICE_TURN_ON)

        macro = self._entry.options.get(CONF_POWER_ON_MACRO)
        if macro:
            await self._async_send(
                lambda: self.coordinator.client.run_macro(macro),
                f"run power-on macro '{macro}'",
            )
        else:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Run the standby macro, then switch off the configured power switch."""
        macro = self._entry.options.get(CONF_POWER_OFF_MACRO)
        if macro:
            await self._async_send(
                lambda: self.coordinator.client.run_macro(macro),
                f"run standby macro '{macro}'",
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
