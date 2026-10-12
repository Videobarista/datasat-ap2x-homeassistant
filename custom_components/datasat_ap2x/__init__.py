"""The Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv, entity_registry as er, service
from homeassistant.helpers.typing import ConfigType

from .api import (
    MAX_GPIO,
    MIN_GPIO,
    Ap2xAuthError,
    Ap2xCapabilities,
    Ap2xClient,
    Ap2xConnectionError,
    Ap2xError,
    Ap2xSystemInfo,
    probe_capabilities,
)
from .const import ATTR_GPIO, DOMAIN, SERVICE_PULSE
from .coordinator import Ap2xCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions, independent of any config entry."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PULSE,
        entity_domain=Platform.MEDIA_PLAYER,
        schema={
            vol.Required(ATTR_GPIO): vol.All(vol.Coerce(int), vol.Range(min=MIN_GPIO, max=MAX_GPIO))
        },
        func="async_pulse",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Set up one Datasat processor from a config entry.

    A processor that does not answer is not a setup failure: these units are
    switched off at the rack every day, so the entities simply report it as off.
    A processor that answers but rejects the password is a configuration error.
    """
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
    except Ap2xAuthError as err:
        await client.disconnect()
        raise ConfigEntryError(
            f"The processor at {entry.data[CONF_HOST]} rejected the password"
        ) from err
    except Ap2xConnectionError as err:
        _LOGGER.debug("No identification read from %s during setup: %s", entry.data[CONF_HOST], err)
    except Ap2xError as err:
        _LOGGER.warning("Could not read identification from %s: %s", entry.data[CONF_HOST], err)

    _async_remove_legacy_entities(hass, entry)

    coordinator = Ap2xCoordinator(hass, entry, client, capabilities)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = Ap2xRuntimeData(coordinator, system, capabilities)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


@callback
def _async_remove_legacy_entities(hass: HomeAssistant, entry: Ap2xConfigEntry) -> None:
    """Remove entities that older versions created and that no longer exist.

    Up to version 1.3 there was a single combined power-supply sensor. It was
    replaced by one sensor per board, so the old entity would linger in the
    registry as permanently unavailable.
    """
    registry = er.async_get(hass)
    legacy_unique_id = f"{entry.unique_id or entry.entry_id}_psu_fault"
    entity_id = registry.async_get_entity_id(Platform.BINARY_SENSOR, DOMAIN, legacy_unique_id)
    if entity_id:
        _LOGGER.debug("Removing entity %s, replaced by the per-board supply sensors", entity_id)
        registry.async_remove(entity_id)


async def async_reload_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Unload a config entry and close the connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.client.disconnect()
    return unload_ok
