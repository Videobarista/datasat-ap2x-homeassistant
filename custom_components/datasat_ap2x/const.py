"""Constants for the Datasat AP20/AP25 integration."""

DOMAIN = "datasat_ap2x"

CONF_FORMATS = "formats"
CONF_MACROS = "macros"
CONF_POWER_ON_MACRO = "power_on_macro"
CONF_POWER_OFF_MACRO = "power_off_macro"
CONF_POWER_SWITCH = "power_switch"
POWER_SWITCH_DOMAINS = ("switch", "input_boolean", "light")
CONF_ENABLE_PULSE = "enable_pulse"
CONF_MAC = "mac"
CONF_SERIAL = "serial"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 10  # seconds
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 300
HEALTH_INTERVAL = 60  # seconds between temperature and voltage reads

MANUFACTURER = "Datasat Digital Entertainment"
MODEL = "AP20/AP25"

FADER_MAX = 100  # tenths; 100 == 10.0 on the front panel
POWER_ON_DELAY = 20  # seconds the unit needs after leaving standby

SERVICE_PULSE = "pulse"
ATTR_GPIO = "gpio"

# Repair issue id, not a credential.
ISSUE_SETUP_PASSWORD = "setup_password"  # noqa: S105
