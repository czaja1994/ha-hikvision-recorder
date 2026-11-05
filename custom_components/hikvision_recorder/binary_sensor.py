"""Per-camera binary sensors for the Hikvision Recorder integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HikRecorderConfigEntry, HikRecorderCoordinator
from .entity import HikRecorderEntity
from .parsing import Camera

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikRecorderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an online and a recording sensor per camera.

    The camera list comes from the channel configuration, so offline cameras
    still get their entities.
    """
    coordinator = entry.runtime_data
    entities: list[HikRecorderCameraSensor] = []
    for camera in coordinator.cameras:
        entities.append(HikRecorderCameraOnline(coordinator, camera))
        entities.append(HikRecorderCameraRecording(coordinator, camera))
    async_add_entities(entities)


class HikRecorderCameraSensor(HikRecorderEntity, BinarySensorEntity):
    """Base for sensors that read one channel of the working status.

    Unavailable (never off) when the last update failed or the channel is
    missing from the status, so an unreachable NVR is not mistaken for dead
    cameras.
    """

    def __init__(self, coordinator: HikRecorderCoordinator, camera: Camera) -> None:
        super().__init__(coordinator)
        self._camera = camera
        self._attr_translation_placeholders = {"camera": camera.name}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self._camera.channel in self.coordinator.data.status
        )


class HikRecorderCameraOnline(HikRecorderCameraSensor):
    """Whether the NVR reports the camera as online."""

    _attr_translation_key = "camera_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: HikRecorderCoordinator, camera: Camera) -> None:
        super().__init__(coordinator, camera)
        self._attr_unique_id = f"{coordinator.device.serial}_{camera.channel}_online"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.status[self._camera.channel].online


class HikRecorderCameraRecording(HikRecorderCameraSensor):
    """Whether the NVR is recording the camera right now."""

    _attr_translation_key = "camera_recording"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: HikRecorderCoordinator, camera: Camera) -> None:
        super().__init__(coordinator, camera)
        self._attr_unique_id = (
            f"{coordinator.device.serial}_{camera.channel}_recording"
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.status[self._camera.channel].recording
