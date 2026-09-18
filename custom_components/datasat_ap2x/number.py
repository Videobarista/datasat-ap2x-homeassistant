"""Number entities for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Ap2xConfigEntry
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the fader and monitor level entities."""
    runtime_data = entry.runtime_data
    async_add_entities(
        [
            Ap2xFaderNumber(runtime_data, entry),
            Ap2xMonitorLevelNumber(runtime_data, entry),
        ]
    )


class Ap2xFaderNumber(Ap2xEntity, NumberEntity):
    """Master fader in the 0.0-10.0 scale shown on the front panel."""

    _attr_name = "Master fader"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the fader entity."""
        super().__init__(runtime_data, entry, "fader")

    @property
    def native_value(self) -> float | None:
        """Return the fader position in front-panel units."""
        fader = self.coordinator.data.fader
        return None if fader is None else round(fader / 10, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Set the fader position in front-panel units."""
        tenths = round(value * 10)
        await self._async_send(
            lambda: self.coordinator.client.set_fader(tenths), "set the fader"
        )


class Ap2xMonitorLevelNumber(Ap2xEntity, NumberEntity):
    """Booth monitor level (@MONITORLEVEL), 0-100."""

    _attr_name = "Monitor level"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:speaker-message"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the monitor level entity."""
        super().__init__(runtime_data, entry, "monitor_level")

    @property
    def native_value(self) -> int | None:
        """Return the monitor level."""
        return self.coordinator.data.monitor_level

    async def async_set_native_value(self, value: float) -> None:
        """Set the monitor level."""
        level = int(value)
        await self._async_send(
            lambda: self.coordinator.client.set_monitor_level(level),
            "set the monitor level",
        )
