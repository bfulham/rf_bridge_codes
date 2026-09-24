"""Constants for the RF Bridge Codes integration."""

DOMAIN = "rf_bridge_codes"

CONF_SEND_SERVICE = "send_service"
CONF_RAW_PARAM = "raw_param"

DEFAULT_SEND_SERVICE = "esphome.rf_bridge_send_raw_code"
DEFAULT_RAW_PARAM = "raw"

# ESPHome api: actions are exposed as esphome.<device>_<action>; the sniff
# action is found by swapping this suffix on the configured send service
SEND_SERVICE_SUFFIX = "_send_raw_code"
SNIFF_SERVICE_SUFFIX = "_start_bucket_sniffing"

# fired by the uart debug: block in the ESPHome YAML (see README)
EVENT_BUCKET = "esphome.rf_bridge_bucket"
ATTR_RAW = "raw"

CAPTURE_TIMEOUT = 30
# keep listening this long after the first code: many remotes send a
# different "still held" code after the first burst
LISTEN_WINDOW = 1.0
# most different codes offered to pick from after learning
MAX_VARIANTS = 4

# how many times each B0 code is transmitted back to back; too many and some
# receivers treat the tail as a second press (e.g. a light toggling twice)
CONF_REPEATS = "repeats"
DEFAULT_REPEATS = 3

STORAGE_VERSION = 1

SERVICE_ADD_CODE = "add_code"
SERVICE_DELETE_CODE = "delete_code"
SERVICE_SEND_CODE = "send_code"
SERVICE_LEARN_CODE = "learn_code"

ATTR_NAME = "name"
ATTR_CODE = "code"

SIGNAL_CODE_ADDED = f"{DOMAIN}_code_added"
SIGNAL_CODE_REMOVED = f"{DOMAIN}_code_removed"
