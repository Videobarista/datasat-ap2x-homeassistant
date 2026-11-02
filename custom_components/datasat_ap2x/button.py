"""Buttons that run macros on the Datasat AP20/AP25."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from . import Ap2xConfigEntry, Ap2xRuntimeData
from .api import parse_name_list
from .const import CONF_MACROS
from .entity import Ap2xEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Ap2xConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one button per macro, read from the unit when it can list them.

    Two names that would get the same entity id (such as "HDMI 1" and "HDMI-1")
    get one button only, so no entity silently goes missing.
    """
    runtime_data = entry.runtime_data
    macros = list(runtime_data.capabilities.macro_names)
    if not macros:
        macros = parse_name_list(entry.options.get(CONF_MACROS, ""))
    buttons: list[Ap2xMacroButton] = []
    keys: set[str] = set()
    for macro in macros:
        key = slugify(macro)
        if key in keys:
            continue
        keys.add(key)
        buttons.append(Ap2xMacroButton(runtime_data, entry, macro))
    async_add_entities(buttons)


class Ap2xMacroButton(Ap2xEntity, ButtonEntity):
    """Run one macro defined on the processor (@RUNMACRO)."""

    _attr_icon = "mdi:play-box-outline"

    def __init__(
        self,
        runtime_data: Ap2xRuntimeData,
        entry: Ap2xConfigEntry,
        macro: str,
    ) -> None:
        """Initialise a button for one macro name."""
        super().__init__(runtime_data, entry, f"macro_{slugify(macro)}")
        self._macro = macro
        self._attr_name = f"Macro {macro}"

    async def async_press(self) -> None:
        """Execute the macro on the processor."""
        await self._async_send(
            lambda: self.coordinator.client.run_macro(self._macro), f"run macro '{self._macro}'"
        )
