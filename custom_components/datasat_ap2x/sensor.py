"""Board temperature sensors for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Ap2xConfigEntry
from .const import DOMAIN
from .coordinator import Ap2xCoordinator

BOARDS = ("H331", "H332", "H335")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        Ap2xTemperatureSensor(entry.runtime_data, entry, idx, board)
        for idx, board in enumerate(BOARDS)
    )


class Ap2xTemperatureSensor(CoordinatorEntity[Ap2xCoordinator], SensorEntity):
    """One board temperature (HEALTH TEMPERATURE t1/t2/t3)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: Ap2xCoordinator,
        entry: Ap2xConfigEntry,
        index: int,
        board: str,
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_name = f"{board} temperature"
        self._attr_unique_id = f"{entry.unique_id}_temp_{board.lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data.reachable
            and len(self.coordinator.data.temperatures) > self._index
        )

    @property
    def native_value(self) -> float | None:
        temps = self.coordinator.data.temperatures
        return temps[self._index] if len(temps) > self._index else None
