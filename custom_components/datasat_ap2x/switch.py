"""Switch entities for the Datasat AP20/AP25."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Ap2xConfigEntry, Ap2xRuntimeData
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the mute switches and, where supported, the screensaver."""
    runtime_data = entry.runtime_data
    entities: list[SwitchEntity] = [
        Ap2xMuteSwitch(runtime_data, entry),
        Ap2xMonitorMuteSwitch(runtime_data, entry),
    ]
    if runtime_data.capabilities.screensaver:
        entities.append(Ap2xScreensaverSwitch(runtime_data, entry))
    async_add_entities(entities)


class Ap2xMuteSwitch(Ap2xEntity, SwitchEntity):
    """Master mute (@MUTED) as a switch, for one-button dashboard control."""

    _attr_name = "Mute"
    _attr_icon = "mdi:volume-off"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the master mute switch."""
        super().__init__(runtime_data, entry, "mute")

    @property
    def is_on(self) -> bool | None:
        """Return True while the main outputs are muted."""
        return self.coordinator.data.muted

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute the main outputs."""
        await self._async_send(lambda: self.coordinator.client.set_muted(True), "mute the outputs")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute the main outputs."""
        await self._async_send(
            lambda: self.coordinator.client.set_muted(False), "unmute the outputs"
        )


class Ap2xMonitorMuteSwitch(Ap2xEntity, SwitchEntity):
    """Monitor mute (@MONITORMUTE) as a switch."""

    _attr_name = "Monitor mute"
    _attr_icon = "mdi:speaker-off"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the monitor mute switch."""
        super().__init__(runtime_data, entry, "monitor_mute")

    @property
    def is_on(self) -> bool | None:
        """Return True while the monitor output is muted."""
        return self.coordinator.data.monitor_muted

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute the monitor output."""
        await self._async_send(
            lambda: self.coordinator.client.set_monitor_muted(True), "mute the monitor output"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute the monitor output."""
        await self._async_send(
            lambda: self.coordinator.client.set_monitor_muted(False), "unmute the monitor output"
        )


class Ap2xScreensaverSwitch(Ap2xEntity, SwitchEntity):
    """Front panel screensaver (@SCR). The unit cannot report its current state."""

    _attr_name = "Screensaver"
    _attr_icon = "mdi:monitor-off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the screensaver switch."""
        super().__init__(runtime_data, entry, "screensaver")
        self._showing = False

    @property
    def is_on(self) -> bool:
        """Return the last state this integration set."""
        return self._showing

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Show the screensaver."""
        await self._async_send(
            lambda: self.coordinator.client.set_screensaver(True), "show the screensaver"
        )
        self._showing = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Wake the front panel display."""
        await self._async_send(
            lambda: self.coordinator.client.set_screensaver(False), "wake the display"
        )
        self._showing = False
        self.async_write_ha_state()
