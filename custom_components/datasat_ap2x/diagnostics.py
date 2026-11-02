"""Diagnostics support for the Datasat AP20/AP25."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import Ap2xConfigEntry
from .const import CONF_MAC, CONF_SERIAL

# Diagnostics are meant to be shared in issue reports: leave out credentials and
# anything that identifies the unit, the network or the cinema it is installed in.
TO_REDACT = {CONF_PASSWORD, CONF_HOST, CONF_MAC, CONF_SERIAL, "circuit", "theater", "screen"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Ap2xConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one processor."""
    runtime_data = entry.runtime_data
    system = runtime_data.system
    client = runtime_data.coordinator.client
    data = runtime_data.coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "system": async_redact_data(
            {
                "version": system.version,
                "version_date": system.version_date,
                "circuit": system.circuit,
                "theater": system.theater,
                "screen": system.screen,
                "boards": system.boards,
            },
            TO_REDACT,
        ),
        "auth_level": client.auth_level,
        "capabilities": runtime_data.capabilities.as_dict(),
        "state": {
            "reachable": data.reachable,
            "power": data.power,
            "fader": data.fader,
            "volume_db": data.volume_db,
            "muted": data.muted,
            "format": data.format,
            "monitor_level": data.monitor_level,
            "monitor_muted": data.monitor_muted,
            "temperatures": data.temperatures,
            "volts": {
                board: {"present": record.present, "ok": record.ok, "values": record.values}
                for board, record in data.volts.items()
            },
        },
    }
