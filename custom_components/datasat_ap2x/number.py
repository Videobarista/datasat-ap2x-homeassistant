"""Number entities for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfSoundPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Ap2xConfigEntry, Ap2xRuntimeData
from .api import VOLUME_MAX
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fader, monitor level and, where supported, the dB volume."""
    runtime_data = entry.runtime_data
    entities: list[NumberEntity] = [
        Ap2xFaderNumber(runtime_data, entry),
        Ap2xMonitorLevelNumber(runtime_data, entry),
    ]
    if runtime_data.capabilities.volume_db:
        entities.append(Ap2xVolumeNumber(runtime_data, entry))
    async_add_entities(entities)


class Ap2xFaderNumber(Ap2xEntity, NumberEntity):
    """Master fader in the 0.0-10.0 scale shown on the front panel."""

    _attr_name = "Master fader"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
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
        await self._async_send(lambda: self.coordinator.client.set_fader(tenths), "set the fader")


class Ap2xVolumeNumber(Ap2xEntity, NumberEntity):
    """Master volume in dB, the same control as the fader in different units."""

    _attr_name = "Master volume"
    _attr_native_unit_of_measurement = UnitOfSoundPressure.DECIBEL
    _attr_native_min_value = -(VOLUME_MAX / 10)
    _attr_native_max_value = 0.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:volume-high"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the dB volume entity."""
        super().__init__(runtime_data, entry, "volume_db")

    @property
    def native_value(self) -> float | None:
        """Return the volume in dB, negative below reference."""
        volume = self.coordinator.data.volume_db
        return None if volume is None else round(-volume / 10, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume in dB."""
        tenths = round(abs(value) * 10)
        await self._async_send(
            lambda: self.coordinator.client.set_volume_db(tenths), "set the volume"
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

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
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
            lambda: self.coordinator.client.set_monitor_level(level), "set the monitor level"
        )
