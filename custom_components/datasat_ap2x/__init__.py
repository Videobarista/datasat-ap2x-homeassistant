"""The Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .api import Ap2xClient, Ap2xError, Ap2xSystemInfo
from .coordinator import Ap2xCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type Ap2xConfigEntry = ConfigEntry[Ap2xRuntimeData]


class Ap2xRuntimeData:
    """Objects shared by the platforms of one config entry."""

    def __init__(self, coordinator: Ap2xCoordinator, system: Ap2xSystemInfo) -> None:
        """Store the coordinator and the identification read at setup."""
        self.coordinator = coordinator
        self.system = system


async def async_setup_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Set up one Datasat processor from a config entry."""
    client = Ap2xClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_PASSWORD) or None,
    )

    system = Ap2xSystemInfo()
    try:
        system = await client.get_system_info()
    except Ap2xError as err:
        # The unit may be switched off right now; identification is optional.
        _LOGGER.info(
            "Could not read identification from %s during setup: %s",
            entry.data[CONF_HOST],
            err,
        )

    coordinator = Ap2xCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = Ap2xRuntimeData(coordinator, system)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Unload a config entry and close the connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.client.disconnect()
    return unload_ok
