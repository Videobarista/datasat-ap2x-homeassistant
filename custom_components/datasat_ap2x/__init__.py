"""The Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .api import (
    Ap2xCapabilities,
    Ap2xClient,
    Ap2xConnectionError,
    Ap2xError,
    Ap2xSystemInfo,
    probe_capabilities,
)
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

    def __init__(
        self,
        coordinator: Ap2xCoordinator,
        system: Ap2xSystemInfo,
        capabilities: Ap2xCapabilities,
    ) -> None:
        """Store the coordinator, the identification and the probed capabilities."""
        self.coordinator = coordinator
        self.system = system
        self.capabilities = capabilities


async def async_setup_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Set up one Datasat processor from a config entry."""
    client = Ap2xClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_PASSWORD) or None,
    )

    system = Ap2xSystemInfo()
    capabilities = Ap2xCapabilities()
    try:
        system = await client.get_system_info()
        capabilities = await probe_capabilities(client)
    except Ap2xConnectionError as err:
        # The unit is simply switched off; both reads are optional at setup.
        _LOGGER.debug("No identification read from %s during setup: %s", entry.data[CONF_HOST], err)
    except Ap2xError as err:
        _LOGGER.warning("Could not read identification from %s: %s", entry.data[CONF_HOST], err)

    coordinator = Ap2xCoordinator(hass, entry, client, capabilities)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = Ap2xRuntimeData(coordinator, system, capabilities)
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
