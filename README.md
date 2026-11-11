# Datasat AP20/AP25 — Home Assistant integration

[![Ruff](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/ruff.yml)
[![hassfest](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hassfest.yml)
[![HACS](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/codeql.yml)
[![Tests](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/Videobarista/datasat-ap2x-homeassistant?display_name=tag)](https://github.com/Videobarista/datasat-ap2x-homeassistant/releases)
[![Local only](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/local-only.yml/badge.svg?branch=main)](https://github.com/Videobarista/datasat-ap2x-homeassistant/actions/workflows/local-only.yml)
[![IoT class](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FVideobarista%2Fdatasat-ap2x-homeassistant%2Fmain%2Fcustom_components%2Fdatasat_ap2x%2Fmanifest.json&query=%24.iot_class&label=IoT%20class&color=41BDF5)](#local-only)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Quality scale: Bronze (aligned)](https://img.shields.io/badge/quality%20scale-bronze%20(aligned)-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

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

## Actions

### `datasat_ap2x.pulse`

Fires a 250 ms pulse on one of the processor's GPIO outputs, for example to
trigger masking, lights or an amplifier relay that is wired to the unit.

| Field | Required | Description |
| --- | --- | --- |
| `target` | yes | The processor's media player entity. |
| `gpio` | yes | GPIO output number, 1 to 21. |

```yaml
action: datasat_ap2x.pulse
target:
  entity_id: media_player.datasat_ap20_ap25
data:
  gpio: 3
```

GPIO outputs can switch real hardware, so the action is guarded twice:

- It is **off by default**. Turn on *Allow the GPIO pulse action* in the
  integration's *Configure* dialog for each processor that should accept it.
- Only **administrators and automations** may call it. Users without admin
  rights get an "Unauthorized" error, also from a dashboard button.

The action only has an effect on units whose firmware accepts the `@PULSE`
command. A pulse sent while the processor is switched off is dropped.

All other control uses the standard media player, number, switch and button
actions of Home Assistant.

## Requirements

Home Assistant 2025.10 or newer.

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
power on/off, the GPIO pulse action (off by default) and the poll interval
(default 10 s). Names must be printable ASCII without `@`, up to 64 characters;
the dialog refuses anything else.

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
unit is unreachable are dropped and logged at debug level too. Problems with a
unit that *is* answering — a macro that does not exist, an unexpected response,
a refused password — are logged as a warning or error once, not on every poll.

The debug log shows every command and reply, except the password and the
replies that identify the unit (MAC address, serial number, site names).

To follow what goes over the wire:

```yaml
logger:
  logs:
    custom_components.datasat_ap2x: debug
```

## Security

The integration treats the processor's control port as untrusted in both
directions:

- **Nothing unsafe is sent.** Format names, macro names and the password are
  checked before they reach the unit, and a format can only be selected from the
  unit's own list, so no name can carry a second command.
- **Nothing unexpected is believed.** Replies are limited in length and must
  belong to the command that was sent. A reply that does not fit closes the
  connection, so the next poll starts clean instead of reading shifted values.
  Out-of-range and non-numeric values are treated as unknown.
- **Volume steps are taken from the fader as it is now**, read just before the
  step, so a level changed on the front panel never makes the volume jump.
- **Least privilege.** Use the NetCmd password: the integration only needs
  operator commands. If Home Assistant logs in with the Setup password, a repair
  issue says so.
- **Nothing is opened.** The integration listens on no port and only connects
  out to the processor.

### Local only

The integration only talks to your processor, never to the internet or any
other service. Two automated checks back the **Local only** badge:

- [`scripts/check_local_only.py`](scripts/check_local_only.py) reads the code
  without running it. It fails on cloud or discovery settings in the manifest,
  on any library outside a short allowlist, on listening sockets, HTTP sessions,
  subprocesses and hard-coded addresses, and on any connection other than the
  one TCP connection to the host and port you configured.
- [`tests/test_local_only.py`](tests/test_local_only.py) runs the real client
  against a simulated processor and records every connection during the config
  flow, setup, polling and commands. All of them must go to the configured host
  and port.

One deliberate exception: if you set the optional **power switch**, the
integration switches that entity through a Home Assistant action. That stays
inside Home Assistant. The static check makes sure it can only be a `switch`,
`input_boolean` or `light`, and the test checks that nothing else is called.

The **IoT class** badge is read live from the manifest: `local_polling` means
Home Assistant asks the processor for its state over your own network.

This covers the integration itself; what Home Assistant does (for example its
optional analytics) is up to your Home Assistant settings.

### Network hardening

The protocol itself is unencrypted and the integration cannot change that: the
password and every command travel in plain text. Protect the processor on the
network:

| From | To the processor | |
| --- | --- | --- |
| Home Assistant | TCP 14500 (control) | allow |
| Other controllers (e.g. Bitfocus Companion) | TCP 14500 | allow |
| One management computer | VNC (TCP 5900 by default) | allow |
| Everything else | anything | block |
| The processor | the internet and other networks | block |

- Put the AV equipment in its own VLAN and give the processor a fixed address
  (DHCP reservation).
- The processor runs a **VNC server** that gives full control of the touch
  screen; the setup menus are protected only by the Setup password.
- Network firmware updates fetch from Datasat's servers. Open internet access
  only for an update, or update from a USB stick instead.
- Set both a NetCmd and a Setup password on the unit.
- To see which ports the unit really opens, scan it once from a computer on the
  same network, for example `nmap -Pn -p- <processor-ip>`.

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Removal

1. Go to **Settings → Devices & services** and open **Datasat AP20/AP25**.
2. Open the menu (three dots) next to the processor and choose **Delete**.
3. To remove the files as well: in HACS, open **Datasat AP20/AP25** and choose
   **Remove**, or delete `custom_components/datasat_ap2x` for a manual
   installation. Restart Home Assistant afterwards.

Nothing is changed on the processor itself. If you set a NetCmd password only for
Home Assistant, you can clear it under **System > Access Control** on the unit.

## Quality scale

This integration is aligned with the **Bronze** tier of the
[Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
Home Assistant only grades integrations that ship with Home Assistant itself, so this is a
self-assessment, not an official rating. The status per rule is recorded in
[`quality_scale.yaml`](custom_components/datasat_ap2x/quality_scale.yaml).

One choice is deliberate: a processor that does not answer during setup is not treated as
a setup failure, because these units are switched off at the rack every day. The entry
loads and the entities report the processor as off. A rejected password does fail setup.

## License

[MIT](LICENSE). Datasat and AP20/AP25 are trademarks of their respective
owners; this project is not affiliated with or endorsed by Datasat Digital
Entertainment.
