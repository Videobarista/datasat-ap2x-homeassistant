"""DataUpdateCoordinator for the Datasat AP20/AP25."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Ap2xClient, Ap2xConnectionError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class Ap2xData:
    """Polled state of the processor."""

    fader: int | None = None  # tenths, 0-100
    muted: bool | None = None
    format: str | None = None
    temperatures: list[float] = field(default_factory=list)
    power_ok: bool | None = None
    reachable: bool = False


class Ap2xCoordinator(DataUpdateCoordinator[Ap2xData]):
    """Poll the AP20/AP25 over its persistent TCP connection."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Ap2xClient) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client

    async def _async_update_data(self) -> Ap2xData:
        data = Ap2xData()
        try:
            data.fader = await self.client.get_fader()
            data.muted = await self.client.get_muted()
            data.format = await self.client.get_format()
            data.temperatures = await self.client.get_temperatures()
            data.power_ok = await self.client.get_h336_volts_ok()
            data.reachable = True
        except Ap2xConnectionError as err:
            # Device in standby / unreachable: keep entities alive but mark off.
            if self.data is not None:
                data = Ap2xData(reachable=False)
                return data
            raise UpdateFailed(str(err)) from err
        return data
