"""Buttons that run macros on the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import Ap2xConfigEntry
from .const import CONF_MACROS
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one button per configured macro name."""
    raw = entry.options.get(CONF_MACROS, "")
    macros = [item.strip() for item in raw.split(",") if item.strip()]
    async_add_entities(
        Ap2xMacroButton(entry.runtime_data, entry, macro) for macro in macros
    )


class Ap2xMacroButton(Ap2xEntity, ButtonEntity):
    """Run one macro defined on the processor (@RUNMACRO)."""

    _attr_icon = "mdi:play-box-outline"

    def __init__(self, runtime_data, entry: Ap2xConfigEntry, macro: str) -> None:
        """Initialise a button for one macro name."""
        super().__init__(runtime_data, entry, f"macro_{slugify(macro)}")
        self._macro = macro
        self._attr_name = f"Macro {macro}"

    async def async_press(self) -> None:
        """Execute the macro on the processor."""
        await self.coordinator.client.run_macro(self._macro)
        await self.coordinator.async_request_refresh()
