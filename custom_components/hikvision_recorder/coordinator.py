"""Data update coordinator for the Hikvision Recorder integration."""

from __future__ import annotations

import asyncio
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
    NvrConnectionError,
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
    online: dict[int, bool]
    schedule_enabled: dict[int, bool]


class HikRecorderCoordinator(DataUpdateCoordinator[NvrState]):
    """Polls the NVR for channel status, camera online flags and schedule flags."""

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
        # Serialises every write to the NVR (recording flags, reboot).
        self._write_lock = asyncio.Lock()
        # Channels already warned about as missing from channels/status.
        self._warned_no_online: set[int] = set()

    async def _async_update_data(self) -> NvrState:
        try:
            status = await self.client.get_working_status()
            online = await self.client.get_channel_online()
            schedule_enabled = await self.client.get_schedule_enabled()
        except NvrAuthError as err:
            if err.status_code == 401:
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err
        except NvrError as err:
            raise UpdateFailed(str(err)) from err
        self._warn_missing_online(online)
        return NvrState(status=status, online=online, schedule_enabled=schedule_enabled)

    def _warn_missing_online(self, online: dict[int, bool]) -> None:
        """Log one warning per configured channel the NVR left out of channels/status."""
        for camera in self.cameras:
            if camera.channel in online:
                self._warned_no_online.discard(camera.channel)
            elif camera.channel not in self._warned_no_online:
                self._warned_no_online.add(camera.channel)
                _LOGGER.warning(
                    "Channel %s (%s) is missing from the NVR channel status; "
                    "its online sensor is unavailable until it reappears",
                    camera.channel,
                    camera.name,
                )

    async def async_set_recording(self, enabled: bool) -> None:
        """Switch recording on or off for every camera, then refresh.

        Every track is tried; the refresh runs even when some writes failed so
        entity state reflects the device. The whole call holds the write lock,
        so overlapping calls run one after another and the last one wins.
        """
        track_ids = [camera.track_id for camera in self.cameras]
        async with self._write_lock:
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
                await self.async_refresh()

    async def async_reboot(self) -> None:
        """Reboot the NVR and remember when.

        The NVR typically drops the connection while rebooting, so a
        connection error after the request counts as a started reboot. Any
        other error (403, bad statusCode) means it did not reboot.
        """
        async with self._write_lock:
            try:
                await self.client.reboot()
            except NvrConnectionError as err:
                _LOGGER.warning(
                    "NVR dropped the connection during reboot, assuming it is restarting: %s",
                    err,
                )
            except NvrError as err:
                raise HomeAssistantError(str(err)) from err
            self.last_restart = dt_util.utcnow()
            self.async_update_listeners()
