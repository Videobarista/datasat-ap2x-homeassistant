"""Binary sensors for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up the connectivity and power-supply sensors."""
    runtime_data = entry.runtime_data
    async_add_entities(
        [
            Ap2xConnectivitySensor(runtime_data, entry),
            Ap2xPowerSupplySensor(runtime_data, entry),
        ]
    )


class Ap2xConnectivitySensor(Ap2xEntity, BinarySensorEntity):
    """On while the processor answers on TCP 14500."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connection"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the connectivity sensor."""
        super().__init__(runtime_data, entry, "connectivity")

    @property
    def available(self) -> bool:
        """Remain available while the processor is unreachable."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        """Return True while the processor responds."""
        return self._online


class Ap2xPowerSupplySensor(Ap2xEntity, BinarySensorEntity):
    """Problem sensor based on the H336 vok flag: on means a rail is out of limits."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Power supply fault"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry) -> None:
        """Initialise the power-supply sensor."""
        super().__init__(runtime_data, entry, "psu_fault")

    @property
    def available(self) -> bool:
        """Only available when the unit reported a voltage status."""
        return super().available and self.coordinator.data.power_ok is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the supply rails are out of limits."""
        power_ok = self.coordinator.data.power_ok
        return None if power_ok is None else not power_ok
