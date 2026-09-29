"""DataUpdateCoordinator for the Datasat AP20/AP25."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    VOLTS_BOARDS,
    Ap2xCapabilities,
    Ap2xClient,
    Ap2xConnectionError,
    Ap2xError,
    Ap2xVolts,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, HEALTH_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class Ap2xData:
    """Polled state of the processor."""

    reachable: bool = False
    last_seen: datetime | None = None
    power: bool | None = None
    fader: int | None = None
    volume_db: int | None = None
    muted: bool | None = None
    format: str | None = None
    monitor_level: int | None = None
    monitor_muted: bool | None = None
    temperatures: list[float] = field(default_factory=list)
    volts: dict[str, Ap2xVolts] = field(default_factory=dict)


class Ap2xCoordinator(DataUpdateCoordinator[Ap2xData]):
    """Poll the AP20/AP25 over a persistent TCP connection.

    Operational values are read every cycle; temperatures and supply voltages
    change slowly and are read about once a minute. An unreachable unit is
    normal operation and is logged at debug level only.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Ap2xClient,
        capabilities: Ap2xCapabilities,
    ) -> None:
        """Initialise the coordinator with the configured poll interval."""
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.capabilities = capabilities
        self._was_reachable: bool | None = None
        self._health_due = 0.0

    async def _async_update_data(self) -> Ap2xData:
        """Read the operational state; an offline unit is not an error."""
        previous = self.data
        data = Ap2xData(last_seen=previous.last_seen if previous else None)
        if previous is not None:
            data.temperatures = previous.temperatures
            data.volts = previous.volts

        try:
            if self.capabilities.power:
                data.power = await self.client.get_power()
            data.fader = await self.client.get_fader()
            data.muted = await self.client.get_muted()
            data.format = await self.client.get_format()
            data.monitor_level = await self.client.get_monitor_level()
            data.monitor_muted = await self.client.get_monitor_muted()
            if self.capabilities.volume_db:
                data.volume_db = await self.client.get_volume_db()
            await self._async_update_health(data)
        except Ap2xConnectionError as err:
            if self._was_reachable is not False:
                _LOGGER.debug(
                    "Processor at %s stopped responding, reporting it as off: %s",
                    self.client.host,
                    err,
                )
            self._was_reachable = False
            return data
        except Ap2xError as err:
            # The unit answered but the exchange went wrong: that is a real fault.
            _LOGGER.error("Protocol error while polling %s: %s", self.client.host, err)
            self._was_reachable = False
            return data

        if self._was_reachable is False:
            _LOGGER.debug("Processor at %s is responding again", self.client.host)
        self._was_reachable = True
        data.reachable = True
        data.last_seen = dt_util.utcnow()
        return data

    async def _async_update_health(self, data: Ap2xData) -> None:
        """Read temperatures and supply voltages at a slower cadence."""
        now = self.hass.loop.time()
        if now < self._health_due and data.temperatures:
            return

        data.temperatures = await self.client.get_temperatures()
        volts: dict[str, Ap2xVolts] = {}
        for board in VOLTS_BOARDS:
            volts[board] = await self.client.get_volts(board)
        data.volts = volts
        self._health_due = now + HEALTH_INTERVAL
