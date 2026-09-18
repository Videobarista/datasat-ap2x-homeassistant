"""Config flow for the Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging
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
from homeassistant.helpers import selector

from .api import DEFAULT_PORT, Ap2xAuthError, Ap2xClient, Ap2xConnectionError
from .const import (
    CONF_FORMATS,
    CONF_MAC,
    CONF_MACROS,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_POWER_SWITCH,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_USE_WOL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=65535, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_PASSWORD, default=""): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class Ap2xConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: host, port and optional NetCmd/Setup password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for connection details and verify them against the processor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            password = str(user_input.get(CONF_PASSWORD) or "")

            client = Ap2xClient(host, port, password or None)
            system = None
            try:
                await client.connect()
                system = await client.get_system_info()
            except Ap2xAuthError:
                errors["base"] = "invalid_auth"
            except Ap2xConnectionError as err:
                _LOGGER.debug("Connection test to %s:%s failed: %s", host, port, err)
                errors["base"] = "cannot_connect"
            finally:
                await client.disconnect()

            if system is not None:
                unique_id = system.mac or system.serial or f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Datasat AP20/AP25 ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PASSWORD: password,
                        CONF_MAC: system.mac,
                        CONF_SERIAL: system.serial,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Ap2xOptionsFlow:
        """Return the options flow."""
        return Ap2xOptionsFlow()


class Ap2xOptionsFlow(OptionsFlow):
    """Options: formats, macros, power control and poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            cleaned = {
                key: value for key, value in user_input.items() if value not in ("", None)
            }
            cleaned[CONF_USE_WOL] = bool(user_input.get(CONF_USE_WOL, False))
            return self.async_create_entry(title="", data=cleaned)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FORMATS, description={"suggested_value": options.get(CONF_FORMATS)}
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_MACROS, description={"suggested_value": options.get(CONF_MACROS)}
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_POWER_SWITCH,
                    description={"suggested_value": options.get(CONF_POWER_SWITCH)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "light"]
                    )
                ),
                vol.Optional(
                    CONF_POWER_ON_MACRO,
                    description={"suggested_value": options.get(CONF_POWER_ON_MACRO)},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_POWER_OFF_MACRO,
                    description={"suggested_value": options.get(CONF_POWER_OFF_MACRO)},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_USE_WOL, default=options.get(CONF_USE_WOL, False)
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
