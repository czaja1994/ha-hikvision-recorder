"""Constants for the Hikvision Recorder integration."""
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "hikvision_recorder"
SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 10.0
PLATFORMS = [Platform.SWITCH, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
