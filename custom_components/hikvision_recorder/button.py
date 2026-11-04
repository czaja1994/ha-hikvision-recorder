"""Restart button for the Hikvision Recorder integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HikRecorderConfigEntry, HikRecorderCoordinator
from .entity import HikRecorderEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikRecorderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the restart button."""
    async_add_entities([HikRecorderRestartButton(entry.runtime_data)])


class HikRecorderRestartButton(HikRecorderEntity, ButtonEntity):
    """Reboots the NVR."""

    _attr_translation_key = "restart"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: HikRecorderCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.serial}_restart"

    async def async_press(self) -> None:
        await self.coordinator.async_reboot()
