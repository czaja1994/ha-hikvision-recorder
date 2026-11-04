"""Recording switch for the Hikvision Recorder integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HikRecorderConfigEntry, HikRecorderCoordinator
from .entity import HikRecorderEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikRecorderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the recording switch."""
    async_add_entities([HikRecorderRecordingSwitch(entry.runtime_data)])


class HikRecorderRecordingSwitch(HikRecorderEntity, SwitchEntity):
    """On while at least one camera's recording schedule is enabled."""

    _attr_translation_key = "recording"

    def __init__(self, coordinator: HikRecorderCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.serial}_recording"

    @property
    def is_on(self) -> bool:
        schedule = self.coordinator.data.schedule_enabled
        return any(
            schedule.get(camera.track_id, False) for camera in self.coordinator.cameras
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self.coordinator.data.schedule_enabled
        return {
            "cameras": {
                camera.name: schedule.get(camera.track_id, False)
                for camera in self.coordinator.cameras
            }
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_recording(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_recording(False)
