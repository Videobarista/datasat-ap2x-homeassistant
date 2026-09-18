"""DataUpdateCoordinator for the Datasat AP20/AP25."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import Ap2xClient, Ap2xConnectionError, Ap2xError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class Ap2xData:
    """Polled state of the processor."""

    reachable: bool = False
    last_seen: datetime | None = None
    fader: int | None = None
    muted: bool | None = None
    format: str | None = None
    monitor_level: int | None = None
    monitor_muted: bool | None = None
    temperatures: list[float] = field(default_factory=list)
    power_ok: bool | None = None


class Ap2xCoordinator(DataUpdateCoordinator[Ap2xData]):
    """Poll the AP20/AP25 over a persistent TCP connection.

    The processor has no standby command and is regularly switched off at the
    rack, so an unreachable unit is reported as "off" rather than as an error.
    """

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: Ap2xClient
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
        self._was_reachable: bool | None = None

    async def _async_update_data(self) -> Ap2xData:
        """Read the operational state; never fail hard on an offline unit."""
        previous = self.data
        data = Ap2xData(last_seen=previous.last_seen if previous else None)

        try:
            data.fader = await self.client.get_fader()
            data.muted = await self.client.get_muted()
            data.format = await self.client.get_format()
            data.monitor_level = await self.client.get_monitor_level()
            data.monitor_muted = await self.client.get_monitor_muted()
            data.temperatures = await self.client.get_temperatures()
            data.power_ok = await self.client.get_h336_volts_ok()
        except Ap2xConnectionError as err:
            if self._was_reachable is not False:
                _LOGGER.info(
                    "Datasat processor at %s is not responding, reporting it as off"
                    " (%s)",
                    self.client.host,
                    err,
                )
            self._was_reachable = False
            return data
        except Ap2xError as err:
            _LOGGER.error("Unexpected error while polling %s: %s", self.client.host, err)
            self._was_reachable = False
            return data

        if self._was_reachable is False:
            _LOGGER.info("Datasat processor at %s is back online", self.client.host)
        self._was_reachable = True
        data.reachable = True
        data.last_seen = dt_util.utcnow()
        return data
