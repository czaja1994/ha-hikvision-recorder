"""Base entity for the Hikvision Recorder integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikRecorderCoordinator
from .parsing import NvrDeviceInfo


def build_device_info(device: NvrDeviceInfo) -> DeviceInfo:
    """Device registry info; the MAC connection only relates this device to others."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.serial)},
        connections={(CONNECTION_NETWORK_MAC, device.mac)},
        manufacturer="Hikvision",
        model=device.model,
        sw_version=device.firmware,
        name=device.name,
    )


class HikRecorderEntity(CoordinatorEntity[HikRecorderCoordinator]):
    """Base class: every entity belongs to the NVR device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HikRecorderCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = build_device_info(coordinator.device)
