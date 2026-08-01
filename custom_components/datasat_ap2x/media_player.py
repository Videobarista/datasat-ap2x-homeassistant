"""Media player entity for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Ap2xConfigEntry
from .api import Ap2xConnectionError, send_wol
from .const import (
    CONF_FORMATS,
    CONF_MAC,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_USE_WOL,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .coordinator import Ap2xCoordinator

FADER_MAX = 100  # tenths -> 10.0 on the front panel


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([Ap2xMediaPlayer(entry.runtime_data, entry)])


class Ap2xMediaPlayer(CoordinatorEntity[Ap2xCoordinator], MediaPlayerEntity):
    """The processor as a media player: volume = master fader, source = format."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, coordinator: Ap2xCoordinator, entry: Ap2xConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_media_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
        )

    # ---- Helpers ---------------------------------------------------------

    @property
    def _formats(self) -> list[str]:
        raw = self._entry.options.get(CONF_FORMATS, "")
        return [f.strip() for f in raw.split(",") if f.strip()]

    @property
    def _mac(self) -> str | None:
        return self._entry.data.get(CONF_MAC)

    # ---- Entity properties ----------------------------------------------

    @property
    def available(self) -> bool:
        # Stay available in standby so turn_on (WoL) keeps working.
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState:
        if not self.coordinator.data.reachable:
            return MediaPlayerState.OFF
        return MediaPlayerState.ON

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = (
            MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )
        if self._formats:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if self._entry.options.get(CONF_POWER_ON_MACRO) or (
            self._entry.options.get(CONF_USE_WOL, True) and self._mac
        ):
            features |= MediaPlayerEntityFeature.TURN_ON
        if self._entry.options.get(CONF_POWER_OFF_MACRO):
            features |= MediaPlayerEntityFeature.TURN_OFF
        return features

    @property
    def volume_level(self) -> float | None:
        fader = self.coordinator.data.fader
        return None if fader is None else fader / FADER_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        return self.coordinator.data.muted

    @property
    def source(self) -> str | None:
        return self.coordinator.data.format

    @property
    def source_list(self) -> list[str] | None:
        return self._formats or None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"fader": (self.coordinator.data.fader or 0) / 10}

    # ---- Commands --------------------------------------------------------

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.client.set_fader(round(volume * FADER_MAX))
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        fader = self.coordinator.data.fader or 0
        await self.coordinator.client.set_fader(fader + 1)
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        fader = self.coordinator.data.fader or 0
        await self.coordinator.client.set_fader(fader - 1)
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.client.set_muted(mute)
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        await self.coordinator.client.set_format(source)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        if self._entry.options.get(CONF_USE_WOL, True) and self._mac:
            await self.hass.async_add_executor_job(send_wol, format_mac(self._mac))
        macro = self._entry.options.get(CONF_POWER_ON_MACRO)
        if macro:
            try:
                await self.coordinator.client.run_macro(macro)
            except Ap2xConnectionError:
                pass  # Device still booting; WoL should bring it up.
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        macro = self._entry.options.get(CONF_POWER_OFF_MACRO)
        if macro:
            try:
                await self.coordinator.client.run_macro(macro)
            except Ap2xConnectionError:
                pass
        await self.coordinator.async_request_refresh()
