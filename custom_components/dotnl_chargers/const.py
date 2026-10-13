"""Constants for the DOT-NL Chargers integration."""

from datetime import timedelta

DOMAIN = "dotnl_chargers"

API_URL = (
    "https://dotnl.ndw.nu/api/rest/geojson/dynamic-road-status"
    "/charge-point-data/v1/features"
)

LOCATIONS_DUMP_URL = "https://opendata.ndw.nu/charging_point_locations_ocpi.json.gz"

CONF_CHARGE_POINT_ID = "charge_point_id"
CONF_CHARGE_POINT = "charge_point"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_EVSES = "evses"

STATE_AVAILABLE = "available"
STATE_OCCUPIED = "occupied"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 3600

DEFAULT_SEARCH_RADIUS = 300
MAX_SEARCH_RADIUS = 2000

# Half-width of the bounding box used to poll a single charge point. When the
# charge point is not found there (its coordinates were corrected upstream) we
# retry once with the wider box.
POLL_RADIUS = 25
POLL_FALLBACK_RADIUS = 500

REQUEST_TIMEOUT = timedelta(seconds=20)
# The ID lookup streams the national OCPI dump (~17 MB compressed).
LOOKUP_TIMEOUT = timedelta(minutes=5)
MAX_LOOKUP_MATCHES = 10
MIN_LOOKUP_LENGTH = 8

# How often a per-socket lookup is repeated when the national dataset has not
# caught up with the availability reported by the API yet.
MAX_EVSE_RETRIES = 5

# A failed poll keeps the last known data this long before entities become
# unavailable; DOT-NL occasionally fails a single request.
STALE_AFTER = timedelta(minutes=10)

# DOT-NL limits the number of requests per second across all its users and
# answers 429 with the few milliseconds to wait when it is busy.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_MAX_WAIT = 5.0
