"""Switch entities for the Datasat AP20/AP25."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Ap2xConfigEntry
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the mute switches."""
    runtime_data = entry.runtime_data
    async_add_entities(
        [
            Ap2xMuteSwitch(runtime_data, entry),
            Ap2xMonitorMuteSwitch(runtime_data, entry),
        ]
    )


class Ap2xMuteSwitch(Ap2xEntity, SwitchEntity):
    """Master mute (@MUTED) as a switch, for one-button dashboard control."""

    _attr_name = "Mute"
    _attr_icon = "mdi:volume-off"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the master mute switch."""
        super().__init__(runtime_data, entry, "mute")

    @property
    def is_on(self) -> bool | None:
        """Return True while the main outputs are muted."""
        return self.coordinator.data.muted

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute the main outputs."""
        await self.coordinator.client.set_muted(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute the main outputs."""
        await self.coordinator.client.set_muted(False)
        await self.coordinator.async_request_refresh()


class Ap2xMonitorMuteSwitch(Ap2xEntity, SwitchEntity):
    """Monitor mute (@MONITORMUTE) as a switch."""

    _attr_name = "Monitor mute"
    _attr_icon = "mdi:speaker-off"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the monitor mute switch."""
        super().__init__(runtime_data, entry, "monitor_mute")

    @property
    def is_on(self) -> bool | None:
        """Return True while the monitor output is muted."""
        return self.coordinator.data.monitor_muted

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute the monitor output."""
        await self.coordinator.client.set_monitor_muted(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute the monitor output."""
        await self.coordinator.client.set_monitor_muted(False)
        await self.coordinator.async_request_refresh()
