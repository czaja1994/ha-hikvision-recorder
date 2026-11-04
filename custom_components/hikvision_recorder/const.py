"""Constants for the Hikvision Recorder integration."""
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "hikvision_recorder"
SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 10.0
PLATFORMS = [Platform.SWITCH, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
# Pauses between attempts when the NVR answers 503 Device Busy (3 attempts).
RETRY_DELAYS = (1.0, 2.0)
