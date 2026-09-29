# Datasat AP20/AP25 — Home Assistant integration

[![Ruff](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/ruff.yml)
[![hassfest](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hassfest.yml)
[![HACS](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Videobarista/datasat-ap2x-homeassistant?display_name=tag)](https://github.com/Videobarista/datasat-ap2x-homeassistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=datasat-ap2x-homeassistant&category=integration)

Custom integration for the Datasat AP20 and AP25 cinema audio processors, using
the TN-H413 rev D remote command API over TCP (port 14500).

## Entities

| Entity | What it does |
| --- | --- |
| `media_player` | Master fader as volume, mute, format as source, power |
| `number` — Master fader | Fader in front-panel units (0.0–10.0) |
| `number` — Master volume | Volume in dB, if the unit accepts `@VOLUME` |
| `number` — Monitor level | Booth monitor level, 0–100 (`@MONITORLEVEL`) |
| `switch` — Mute | Master mute (`@MUTED`) |
| `switch` — Monitor mute | Booth monitor mute (`@MONITORMUTE`) |
| `switch` — Screensaver | Front panel screensaver, if the unit accepts `@SCR` |
| `button` — Macro … | One button per macro (`@RUNMACRO`) |
| `sensor` — H331/H332/H335 temperature | Board temperatures (`@HEALTH TEMPERATURE`) |
| `sensor` — Last seen | When the processor last answered |
| `binary_sensor` — Connection | On while the processor responds |
| `binary_sensor` — H331…H338 supply fault | Per-board supply rails (`@HEALTH …VOLTS`) |
| `binary_sensor` — CPU supply fault | The H336 `vcpu` flag |
| `binary_sensor` — Phantom power | The H336 48 V rail |

Other properties: optional NetCmd/Setup password (`@AUTH` on connect), a single
persistent TCP connection with automatic reconnect, and polling so Home
Assistant follows changes made on the front panel or by other controllers.
Temperatures and supply voltages are read about once a minute; everything else
every poll cycle.

Audio metering is not available: the remote command API exposes settings and
health data only, with no level or metering command.

## Undocumented commands

The AP20/AP25 technote (TN-H413 rev D) documents fewer commands than the one for
its sibling RS20i (TN-H413-01), even though both share a firmware family — the
RS20i's `@IDENTIFY` even answers with `AP20`. This integration probes the extra
commands once at setup and enables the matching features only when the unit
actually answers:

| Command | Feature it enables |
| --- | --- |
| `@POWER 0/1` | Real standby control and power state on the media player |
| `@FORMATNAMES` or `@INPUTNAMES` | Format dropdown filled from the unit itself |
| `@MACRONAMES` | A button per macro, without typing names |
| `@VOLUME` | Master volume in dB alongside the fader |
| `@SCR ON/OFF` | Screensaver switch |
| `@PULSE 1-21` | `datasat_ap2x.pulse` service for the GPIO outputs |

A probe costs one command and a few seconds at setup, and a unit that does not
know a command simply does not answer — the feature then stays hidden and the
manual fallbacks in the options are used instead. What was detected is visible
in the integration's diagnostics download.

## Services

`datasat_ap2x.pulse` fires a 250 ms pulse on a GPIO output:

```yaml
action: datasat_ap2x.pulse
target:
  entity_id: media_player.datasat_ap20_ap25
data:
  gpio: 3
```

## Requirements

Home Assistant 2025.2 or newer.

## Installation

Use the badge above, or add
`https://github.com/Videobarista/datasat-ap2x-homeassistant` as a custom
repository in HACS with category *Integration*. Alternatively, copy
`custom_components/datasat_ap2x` into your Home Assistant `custom_components`
folder.

Restart Home Assistant, then add it via *Settings → Devices & services → Add
integration → Datasat AP20/AP25*. Enter the IP address and, if the unit has one
configured, the NetCmd or Setup password.

## Configuration

Formats and macros are read from the processor when its firmware supports
listing them. If those lists stay empty, fill in the fallbacks in the
integration's *Configure* dialog, exactly as programmed on the unit:

```
Formats:  Digital Cinema, HDMI 1, HDMI 2, Non-Sync
Macros:   Showtime, Interval, Clean-up
```

Also configurable there: an external power switch entity, macros to run around
power on/off, and the poll interval (default 10 s).

## About power control

`media_player.turn_on` and `turn_off` use whatever the unit and your setup make
available, in this order:

1. **`@POWER`**, if the probe found it. This is the processor's own standby
   mode; leaving standby takes about 15 seconds before it is operational again.
2. **An external power switch**, if you point the option at a smart plug or
   relay that feeds the processor. Note the usual rack order: mute or power down
   the amplifiers first, then the processor.
3. **Power macros**, if a technician programmed them on the unit.

All three can be combined. Without any of them the power buttons stay hidden and
the media player reports *off* whenever the processor does not answer on port
14500, with *Last seen* keeping the timestamp of the last successful poll.

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
