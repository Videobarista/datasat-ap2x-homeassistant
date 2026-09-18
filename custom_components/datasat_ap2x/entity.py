"""Shared entity base for the Datasat AP20/AP25 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import Ap2xCoordinator


class Ap2xEntity(CoordinatorEntity[Ap2xCoordinator]):
    """Base entity that ties every platform to the same device."""

    _attr_has_entity_name = True

    def __init__(self, runtime_data, entry, key: str) -> None:
        """Set up device info and the unique id for this entity."""
        super().__init__(runtime_data.coordinator)
        self._entry = entry
        self._runtime_data = runtime_data
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
            sw_version=runtime_data.system.version,
            serial_number=runtime_data.system.serial,
            configuration_url=None,
        )

    @property
    def _online(self) -> bool:
        """Return True when the last poll reached the processor."""
        return bool(self.coordinator.data and self.coordinator.data.reachable)

    @property
    def available(self) -> bool:
        """Entities other than the media player follow the connection state."""
        return super().available and self._online
