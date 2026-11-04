"""Data update coordinator for the Hikvision Recorder integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    HikvisionNvrClient,
    NvrAuthError,
    NvrError,
    NvrWriteError,
)
from .const import DOMAIN, SCAN_INTERVAL
from .parsing import Camera, ChannelStatus, NvrDeviceInfo

_LOGGER = logging.getLogger(__name__)

type HikRecorderConfigEntry = ConfigEntry[HikRecorderCoordinator]


@dataclass
class NvrState:
    """One polling snapshot."""

    status: dict[int, ChannelStatus]
    schedule_enabled: dict[int, bool]


class HikRecorderCoordinator(DataUpdateCoordinator[NvrState]):
    """Polls the NVR for channel status and the recording schedule flags."""

    config_entry: HikRecorderConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HikRecorderConfigEntry,
        client: HikvisionNvrClient,
        device: NvrDeviceInfo,
        cameras: list[Camera],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.device = device
        self.cameras = cameras
        self.last_restart: datetime | None = None

    async def _async_update_data(self) -> NvrState:
        try:
            status = await self.client.get_working_status()
            schedule_enabled = await self.client.get_schedule_enabled()
        except NvrAuthError as err:
            if err.status_code == 401:
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err
        except NvrError as err:
            raise UpdateFailed(str(err)) from err
        return NvrState(status=status, schedule_enabled=schedule_enabled)

    async def async_set_recording(self, enabled: bool) -> None:
        """Switch recording on or off for every camera, then refresh.

        Every track is tried; the refresh runs even when some writes failed so
        entity state reflects the device.
        """
        track_ids = [camera.track_id for camera in self.cameras]
        try:
            await self.client.set_recording(enabled, track_ids)
        except NvrWriteError as err:
            names = [
                camera.name
                for camera in self.cameras
                if camera.track_id in err.failed_track_ids
            ]
            raise HomeAssistantError(
                "Could not switch recording for: " + ", ".join(names)
            ) from err
        except NvrAuthError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.async_request_refresh()

    async def async_reboot(self) -> None:
        """Reboot the NVR and remember when."""
        try:
            await self.client.reboot()
        except NvrError as err:
            raise HomeAssistantError(str(err)) from err
        self.last_restart = dt_util.utcnow()
        self.async_update_listeners()
