"""Constants for the RF Bridge Codes integration."""

DOMAIN = "rf_bridge_codes"

CONF_SEND_SERVICE = "send_service"
CONF_RAW_PARAM = "raw_param"

DEFAULT_SEND_SERVICE = "esphome.rf_bridge_send_raw_code"
DEFAULT_RAW_PARAM = "raw"

STORAGE_VERSION = 1
STORAGE_KEY = "rf_bridge_codes"

SERVICE_ADD_CODE = "add_code"
SERVICE_DELETE_CODE = "delete_code"
SERVICE_SEND_CODE = "send_code"

ATTR_NAME = "name"
ATTR_CODE = "code"

SIGNAL_CODE_ADDED = f"{DOMAIN}_code_added"
SIGNAL_CODE_REMOVED = f"{DOMAIN}_code_removed"
