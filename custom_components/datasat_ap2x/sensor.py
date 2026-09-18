"""Sensors for the Datasat AP20/AP25."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Ap2xConfigEntry
from .entity import Ap2xEntity

BOARDS = ("H331", "H332", "H335")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    runtime_data = entry.runtime_data
    entities: list[SensorEntity] = [
        Ap2xTemperatureSensor(runtime_data, entry, index, board)
        for index, board in enumerate(BOARDS)
    ]
    entities.append(Ap2xLastSeenSensor(runtime_data, entry))
    async_add_entities(entities)


class Ap2xTemperatureSensor(Ap2xEntity, SensorEntity):
    """One board temperature from @HEALTH TEMPERATURE."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, runtime_data, entry: Ap2xConfigEntry, index: int, board: str
    ) -> None:
        """Initialise the temperature sensor for one board."""
        super().__init__(runtime_data, entry, f"temp_{board.lower()}")
        self._index = index
        self._attr_name = f"{board} temperature"

    @property
    def available(self) -> bool:
        """Only available when this board reported a value."""
        return (
            super().available
            and len(self.coordinator.data.temperatures) > self._index
        )

    @property
    def native_value(self) -> float | None:
        """Return the board temperature."""
        temperatures = self.coordinator.data.temperatures
        if len(temperatures) > self._index:
            return temperatures[self._index]
        return None


class Ap2xLastSeenSensor(Ap2xEntity, SensorEntity):
    """Timestamp of the last successful poll, useful while the unit is off."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last seen"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the last-seen sensor."""
        super().__init__(runtime_data, entry, "last_seen")

    @property
    def available(self) -> bool:
        """Remain available while the processor is off."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> datetime | None:
        """Return when the processor last answered."""
        return self.coordinator.data.last_seen
