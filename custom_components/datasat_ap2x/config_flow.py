"""Config flow for the Datasat AP20/AP25 integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback

from .api import DEFAULT_PORT, Ap2xAuthError, Ap2xClient, Ap2xConnectionError
from .const import (
    CONF_FORMATS,
    CONF_MAC,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_SCAN_INTERVAL,
    CONF_USE_WOL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


class Ap2xConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: host, port, optional NetCmd/Setup password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = Ap2xClient(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input.get(CONF_PASSWORD) or None,
            )
            try:
                await client.connect()
                mac = await client.get_mac()
                serial = await client.get_serial()
            except Ap2xAuthError:
                errors["base"] = "invalid_auth"
            except Ap2xConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await client.disconnect()
                unique_id = mac or serial or user_input[CONF_HOST]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Datasat AP20/AP25 ({user_input[CONF_HOST]})",
                    data={**user_input, CONF_MAC: mac},
                )
            finally:
                await client.disconnect()

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Ap2xOptionsFlow:
        return Ap2xOptionsFlow()


class Ap2xOptionsFlow(OptionsFlow):
    """Options: format list, power macros, WoL, poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FORMATS, default=options.get(CONF_FORMATS, "")
                ): str,
                vol.Optional(
                    CONF_POWER_ON_MACRO,
                    default=options.get(CONF_POWER_ON_MACRO, ""),
                ): str,
                vol.Optional(
                    CONF_POWER_OFF_MACRO,
                    default=options.get(CONF_POWER_OFF_MACRO, ""),
                ): str,
                vol.Optional(
                    CONF_USE_WOL, default=options.get(CONF_USE_WOL, True)
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=2, max=300)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
