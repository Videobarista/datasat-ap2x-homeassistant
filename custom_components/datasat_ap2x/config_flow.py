"""Config flow for the Datasat AP20/AP25 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import (
    DEFAULT_PORT,
    Ap2xAuthError,
    Ap2xClient,
    Ap2xConnectionError,
    Ap2xProtocolError,
    is_safe_argument,
    is_safe_password,
)
from .const import (
    CONF_ENABLE_PULSE,
    CONF_FORMATS,
    CONF_MAC,
    CONF_MACROS,
    CONF_POWER_OFF_MACRO,
    CONF_POWER_ON_MACRO,
    CONF_POWER_SWITCH,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    POWER_SWITCH_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=65535, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_PASSWORD, default=""): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

# Option fields that hold names sent to the processor, and whether they hold a list.
_NAME_FIELDS = {
    CONF_FORMATS: True,
    CONF_MACROS: True,
    CONF_POWER_ON_MACRO: False,
    CONF_POWER_OFF_MACRO: False,
}


class Ap2xConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: host, port and optional NetCmd/Setup password."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for connection details and verify them against the processor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            password = str(user_input.get(CONF_PASSWORD) or "")

            if password and not is_safe_password(password):
                errors[CONF_PASSWORD] = "invalid_password"
                return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

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
            except Ap2xProtocolError as err:
                _LOGGER.debug("Unexpected answer from %s:%s: %s", host, port, err)
                errors["base"] = "not_a_processor"
            except Exception:
                _LOGGER.exception("Unexpected error while testing %s:%s", host, port)
                errors["base"] = "unknown"
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

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Ap2xOptionsFlow:
        """Return the options flow."""
        return Ap2xOptionsFlow()


def _invalid_name_fields(values: dict[str, Any]) -> dict[str, str]:
    """Return an error per option field that holds a name the processor cannot take."""
    errors: dict[str, str] = {}
    for key, is_list in _NAME_FIELDS.items():
        text = str(values.get(key) or "").strip()
        if not text:
            continue
        names = [name.strip() for name in text.split(",")] if is_list else [text]
        if any(name and not is_safe_argument(name) for name in names):
            errors[key] = "invalid_names"
    return errors


def _options_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the options form, prefilled with values."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_FORMATS, description={"suggested_value": values.get(CONF_FORMATS)}
            ): selector.TextSelector(),
            vol.Optional(
                CONF_MACROS, description={"suggested_value": values.get(CONF_MACROS)}
            ): selector.TextSelector(),
            vol.Optional(
                CONF_POWER_SWITCH, description={"suggested_value": values.get(CONF_POWER_SWITCH)}
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(POWER_SWITCH_DOMAINS))
            ),
            vol.Optional(
                CONF_POWER_ON_MACRO,
                description={"suggested_value": values.get(CONF_POWER_ON_MACRO)},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_POWER_OFF_MACRO,
                description={"suggested_value": values.get(CONF_POWER_OFF_MACRO)},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_ENABLE_PULSE, default=bool(values.get(CONF_ENABLE_PULSE, False))
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
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


class Ap2xOptionsFlow(OptionsFlow):
    """Options: formats, macros, power control, GPIO pulses and poll interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show, check and store the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _invalid_name_fields(user_input)
            if not errors:
                cleaned = {
                    key: value for key, value in user_input.items() if value not in ("", None)
                }
                return self.async_create_entry(title="", data=cleaned)

        values = user_input if user_input is not None else dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(values), errors=errors
        )
