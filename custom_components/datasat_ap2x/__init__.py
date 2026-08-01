"""The Datasat AP20/AP25 integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .api import Ap2xClient
from .coordinator import Ap2xCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
]

type Ap2xConfigEntry = ConfigEntry[Ap2xCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    client = Ap2xClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_PASSWORD) or None,
    )
    coordinator = Ap2xCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: Ap2xConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.disconnect()
    return unload_ok
