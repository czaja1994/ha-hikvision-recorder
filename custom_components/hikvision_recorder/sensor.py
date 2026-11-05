"""Last-restart sensor for the Hikvision Recorder integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import HikRecorderConfigEntry, HikRecorderCoordinator
from .entity import HikRecorderEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikRecorderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the last-restart sensor."""
    async_add_entities([HikRecorderLastRestartSensor(entry.runtime_data)])


class HikRecorderLastRestartSensor(HikRecorderEntity, RestoreSensor):
    """When this integration last restarted the NVR.

    The value is kept by the coordinator and restored across HA restarts.
    """

    _attr_translation_key = "last_restart"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HikRecorderCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.serial}_last_restart"

    @property
    def available(self) -> bool:
        # The timestamp is local knowledge; it stays visible while the NVR
        # reboots and is unreachable.
        return True

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_restart

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.last_restart is not None:
            return
        restored: datetime | None = None
        if (data := await self.async_get_last_sensor_data()) is not None and isinstance(
            data.native_value, datetime
        ):
            restored = data.native_value
        elif (state := await self.async_get_last_state()) is not None:
            restored = dt_util.parse_datetime(state.state)
        if restored is not None:
            self.coordinator.last_restart = restored
