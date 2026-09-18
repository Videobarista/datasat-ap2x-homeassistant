# Datasat AP20/AP25 — Home Assistant integration

[![Release](https://img.shields.io/github/v/release/Videobarista/datasat-ap2x-homeassistant?display_name=tag)](https://github.com/Videobarista/datasat-ap2x-homeassistant/releases)
[![Validate](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/validate.yml)
[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

Custom integration for the Datasat AP20 and AP25 cinema audio processors, using
the TN-H413 rev D remote command API over TCP (port 14500).

## Entities

| Entity | What it does |
| --- | --- |
| `media_player` | Master fader as volume, mute, format as source, power |
| `number` — Master fader | Fader in front-panel units (0.0–10.0) |
| `number` — Monitor level | Booth monitor level, 0–100 (`@MONITORLEVEL`) |
| `switch` — Mute | Master mute (`@MUTED`) |
| `switch` — Monitor mute | Booth monitor mute (`@MONITORMUTE`) |
| `button` — Macro … | One button per configured macro (`@RUNMACRO`) |
| `sensor` — H331/H332/H335 temperature | Board temperatures (`@HEALTH TEMPERATURE`) |
| `sensor` — Last seen | When the processor last answered |
| `binary_sensor` — Connection | On while the processor responds |
| `binary_sensor` — Power supply fault | H336 rails out of limits (`@HEALTH H336VOLTS`) |

Other properties: optional NetCmd/Setup password (`@AUTH` on connect), a single
persistent TCP connection with automatic reconnect, and polling so Home
Assistant follows changes made on the front panel or by other controllers.

## Installation

HACS → ⋮ → *Custom repositories* → add
`https://github.com/Videobarista/datasat-ap2x-homeassistant` as category
*Integration*. Or copy `custom_components/datasat_ap2x` into your Home
Assistant `custom_components` folder.

Restart Home Assistant, then add it via *Settings → Devices & services → Add
integration → Datasat AP20/AP25*. Enter the IP address and, if the unit has one
configured, the NetCmd or Setup password.

## Configuration

The API has no command to list formats or macros, so enter their names yourself
in the integration's *Configure* dialog, exactly as programmed on the unit:

```
Formats:  Digital Cinema, HDMI 1, HDMI 2, Non-Sync
Macros:   Showtime, Interval, Clean-up
```

Also configurable there: an external power switch entity, macros to run around
power on/off, and the poll interval (default 10 s).

## About power control

**The AP20/AP25 has no power or standby command.** TN-H413 rev D exposes system
information, health, format, fader, mute, monitor level and macros — nothing
that switches the unit on or off, and there is no standby state to read back.
Wake-on-LAN is not supported by the processor either, so this integration does
not pretend otherwise.

What it does instead:

- **Detects power state by reachability.** If the processor does not answer on
  port 14500, the media player reports *off*, the *Connection* sensor goes off
  and *Last seen* keeps the timestamp of the last successful poll.
- **Delegates real power control.** Point the *External power switch* option at
  a smart plug or relay that feeds the processor, and `media_player.turn_on` /
  `turn_off` will switch that entity. Note the usual rack order: mute or power
  down the amplifiers first, then the processor.
- **Runs macros around it.** If a technician has programmed macros (for example
  to drive the GPIO relays that control the amplifier rack), name them in the
  power-on/power-off options.

For everyday use, muting is the intended "off" for this class of device.

## Logging

A processor that is switched off is normal operation, not a fault: it is logged
at debug level and the entities simply report *off*. Commands sent while the
unit is unreachable are dropped and logged at debug level too. Protocol errors
from a unit that *is* answering — a macro that does not exist, an unexpected
response — are logged as warnings or errors.

To follow what goes over the wire:

```yaml
logger:
  logs:
    custom_components.datasat_ap2x: debug
```

## License

[MIT](LICENSE). Datasat and AP20/AP25 are trademarks of their respective
owners; this project is not affiliated with or endorsed by Datasat Digital
Entertainment.
