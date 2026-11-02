"""The Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
    service,
)
from homeassistant.helpers.typing import ConfigType

from .api import (
    AUTH_LEVEL_SETUP,
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
from .const import ATTR_GPIO, DOMAIN, ISSUE_SETUP_PASSWORD, SERVICE_PULSE
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
    """Register the integration's actions, independent of any config entry.

    The pulse action drives GPIO outputs that can switch real hardware, so only
    administrators (and automations) may call it. It also has to be switched on
    per processor in the options.
    """
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PULSE,
        entity_domain=Platform.MEDIA_PLAYER,
        schema={
            vol.Required(ATTR_GPIO): vol.All(vol.Coerce(int), vol.Range(min=MIN_GPIO, max=MAX_GPIO))
        },
        func="async_pulse",
        admin_only=True,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> bool:
    """Set up one Datasat processor from a config entry.

    A processor that does not answer is not a setup failure: these units are
    switched off at the rack every day, so the entities simply report it as off.
    A processor that answers but rejects the password is a configuration error.
    """
    host = entry.data[CONF_HOST]
    client = Ap2xClient(host, entry.data[CONF_PORT], entry.data.get(CONF_PASSWORD) or None)

    system = Ap2xSystemInfo()
    capabilities = Ap2xCapabilities()
    reachable = True
    try:
        system = await client.get_system_info()
    except Ap2xAuthError as err:
        await client.disconnect()
        raise ConfigEntryError(f"The processor at {host} rejected the password") from err
    except Ap2xConnectionError as err:
        reachable = False
        _LOGGER.debug("No identification read from %s during setup: %s", host, err)
    except Ap2xError as err:
        _LOGGER.warning("Could not read identification from %s: %s", host, err)

    if reachable:
        capabilities = await probe_capabilities(client)

    _async_check_auth_level(hass, entry, client)
    _async_remove_legacy_entities(hass, entry)

    coordinator = Ap2xCoordinator(hass, entry, client, capabilities)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = Ap2xRuntimeData(coordinator, system, capabilities)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


@callback
def _async_check_auth_level(
    hass: HomeAssistant, entry: Ap2xConfigEntry, client: Ap2xClient
) -> None:
    """Raise a repair issue when Home Assistant logs in with the Setup password.

    The integration only needs operator commands, for which the NetCmd password
    is enough. With the Setup password, anything that can reach Home Assistant's
    connection also has setup-level access to the processor.
    """
    issue_id = f"{ISSUE_SETUP_PASSWORD}_{entry.entry_id}"
    if client.auth_level == AUTH_LEVEL_SETUP:
        _LOGGER.debug("Logged in to %s with the Setup password", client.host)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_SETUP_PASSWORD,
            translation_placeholders={"title": entry.title},
        )
    elif client.auth_level is not None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


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


async def async_remove_entry(hass: HomeAssistant, entry: Ap2xConfigEntry) -> None:
    """Clean up the repair issue of a processor that is removed."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_SETUP_PASSWORD}_{entry.entry_id}")
