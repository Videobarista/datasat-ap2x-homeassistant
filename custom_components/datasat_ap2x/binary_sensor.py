"""Binary sensors for the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Ap2xConfigEntry, Ap2xRuntimeData
from .api import VOLTS_BOARDS
from .entity import Ap2xEntity

PHANTOM_INDEX = 4  # H336 values after vok: ref, +5V, +15V, -15V, 48V, vcpu
VCPU_INDEX = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connectivity, supply and phantom power sensors."""
    runtime_data = entry.runtime_data
    entities: list[BinarySensorEntity] = [Ap2xConnectivitySensor(runtime_data, entry)]
    entities.extend(Ap2xVoltsSensor(runtime_data, entry, board) for board in VOLTS_BOARDS)
    entities.append(Ap2xCpuPowerSensor(runtime_data, entry))
    entities.append(Ap2xPhantomPowerSensor(runtime_data, entry))
    async_add_entities(entities)


class Ap2xConnectivitySensor(Ap2xEntity, BinarySensorEntity):
    """On while the processor answers on TCP 14500."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connection"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
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


class Ap2xVoltsSensor(Ap2xEntity, BinarySensorEntity):
    """Problem sensor for one board: on means a supply rail is out of limits."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry, board: str) -> None:
        """Initialise the supply sensor for one board."""
        super().__init__(runtime_data, entry, f"volts_{board.lower()}")
        self._board = board
        self._attr_name = f"{board} supply fault"

    @property
    def _record(self):
        """Return the stored voltage record for this board."""
        return self.coordinator.data.volts.get(self._board)

    @property
    def available(self) -> bool:
        """Only available when the board is fitted and reported a status."""
        record = self._record
        return super().available and record is not None and record.present and record.ok is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when a rail is out of limits."""
        record = self._record
        if record is None or record.ok is None:
            return None
        return not record.ok

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the measured voltages."""
        record = self._record
        return {"voltages": record.values if record else []}


class Ap2xCpuPowerSensor(Ap2xEntity, BinarySensorEntity):
    """Problem sensor for the CPU supply reported by the H336 board."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "CPU supply fault"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the CPU supply sensor."""
        super().__init__(runtime_data, entry, "cpu_power")

    @property
    def _value(self) -> float | None:
        """Return the vcpu flag from the H336 record."""
        record = self.coordinator.data.volts.get("H336")
        if record is None or len(record.values) <= VCPU_INDEX:
            return None
        return record.values[VCPU_INDEX]

    @property
    def available(self) -> bool:
        """Only available when the H336 board reported the flag."""
        return super().available and self._value is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when the CPU supply is out of limits."""
        value = self._value
        return None if value is None else value < 1


class Ap2xPhantomPowerSensor(Ap2xEntity, BinarySensorEntity):
    """On while the microphone phantom power rail is live."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Phantom power"

    def __init__(self, runtime_data: Ap2xRuntimeData, entry: Ap2xConfigEntry) -> None:
        """Initialise the phantom power sensor."""
        super().__init__(runtime_data, entry, "phantom_power")

    @property
    def _value(self) -> float | None:
        """Return the 48 V reading from the H336 record."""
        record = self.coordinator.data.volts.get("H336")
        if record is None or len(record.values) <= PHANTOM_INDEX:
            return None
        return record.values[PHANTOM_INDEX]

    @property
    def available(self) -> bool:
        """Only available when the H336 board reported the rail."""
        return super().available and self._value is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when phantom power is switched on."""
        value = self._value
        return None if value is None else value > 1
