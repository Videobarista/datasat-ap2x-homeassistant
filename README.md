# Datasat AP20/AP25 — Home Assistant integration

Custom integration for the Datasat AP20 and AP25 cinema audio processors, using the
TN-H413 rev D Remote Command API over TCP (port 14500).

## Features

- **Media player** entity:
  - Master fader as volume (0.0–10.0, tenths via `@FADER`)
  - Mute toggle (`@MUTED`)
  - Format selection as *source* with live feedback (`@FORMAT`)
  - Power on via Wake-on-LAN (MAC is read from the unit during setup) and/or a
    power-on macro; standby via a macro (`@RUNMACRO`)
- **Sensors**: H331 / H332 / H335 board temperatures (`@HEALTH TEMPERATURE`)
- **Binary sensor**: power-supply fault, based on the H336 `vok` flag
  (`@HEALTH H336VOLTS`)
- Optional NetCmd/Setup password (`@AUTH` on connect)
- Status polling (configurable interval) so HA stays in sync with changes made
  on the front panel or by other controllers
- Persistent TCP connection with automatic reconnect

## Installation (HACS custom repository)

1. HACS → Integrations → ⋮ → *Custom repositories* → add this repo (category
   *Integration*), or copy `custom_components/datasat_ap2x` into your HA
   `custom_components` folder.
2. Restart Home Assistant.
3. Settings → Devices & services → *Add integration* → **Datasat AP20/AP25**.
4. Enter the IP address (port 14500) and, if configured on the unit, the
   NetCmd or Setup password.

## Configuration (options)

The API has **no command to list formats** — `@FORMAT` only reads the current
one or sets one by exact name. Open the integration's *Configure* dialog and
enter the format names exactly as programmed on the unit, comma-separated:

```
Digital Cinema, HDMI 1, HDMI 2, Non-Sync
```

There you can also set:

- **Power-on / standby macro names** — macros defined on the AP20/AP25 itself
  (System → Automation). Leave empty to disable `turn_on`/`turn_off`.
- **Wake-on-LAN** — used for `turn_on` when the unit is unreachable.
- **Poll interval** (default 10 s).

## Presets (mute toggle, volume up/down)

These map directly to standard media player services, so dashboard buttons and
automations can use:

- `media_player.volume_mute` (toggle via `is_volume_muted`)
- `media_player.volume_up` / `media_player.volume_down` (one tenth per step)
- `media_player.select_source` for formats
- `media_player.turn_on` / `media_player.turn_off`

## Notes

- When the processor is in standby (unreachable), the media player shows
  **off** and `turn_on` still works via WoL.
- Serial control is not supported; this integration is Ethernet only.

## License

MIT
