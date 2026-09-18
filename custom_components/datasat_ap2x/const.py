"""Constants for the Datasat AP20/AP25 integration."""

DOMAIN = "datasat_ap2x"

CONF_FORMATS = "formats"
CONF_MACROS = "macros"
CONF_POWER_ON_MACRO = "power_on_macro"
CONF_POWER_OFF_MACRO = "power_off_macro"
CONF_POWER_SWITCH = "power_switch"
CONF_MAC = "mac"
CONF_SERIAL = "serial"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 10  # seconds
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 300

MANUFACTURER = "Datasat Digital Entertainment"
MODEL = "AP20/AP25"

FADER_MAX = 100  # tenths; 100 == 10.0 on the front panel
