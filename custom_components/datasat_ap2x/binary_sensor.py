"""Power-supply health binary sensor for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Ap2xConfigEntry
from .const import DOMAIN
from .coordinator import Ap2xCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([Ap2xPowerSupplySensor(entry.runtime_data, entry)])


class Ap2xPowerSupplySensor(CoordinatorEntity[Ap2xCoordinator], BinarySensorEntity):
    """Problem sensor based on HEALTH H336VOLTS <vok>: on = fault."""

    _attr_has_entity_name = True
    _attr_name = "Power supply fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Ap2xCoordinator, entry: Ap2xConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_psu_fault"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data.reachable
            and self.coordinator.data.power_ok is not None
        )

    @property
    def is_on(self) -> bool | None:
        ok = self.coordinator.data.power_ok
        return None if ok is None else not ok
