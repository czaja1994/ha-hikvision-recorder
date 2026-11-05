"""Setup, coordinator and device-registry tests."""

from __future__ import annotations

import asyncio
import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_recorder.const import DOMAIN
from custom_components.hikvision_recorder.coordinator import HikRecorderCoordinator

from .fake_nvr import FakeNvr


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="TESTSERIAL0001",
        title="Network Video Recorder",
        data={CONF_HOST: "nvr.test", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"},
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_own_device_alongside_other_integration_by_mac(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    """Since HA 2026.8 a device belongs to exactly one config entry.

    Another integration's device with the same MAC can therefore no longer be
    merged into ours; setup must not collide with it and must register our own
    device carrying the same MAC connection (so the UI can relate them).
    """
    other = MockConfigEntry(domain="other_integration")
    other.add_to_hass(hass)
    registry = dr.async_get(hass)
    existing = registry.async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(CONNECTION_NETWORK_MAC, "00:00:00:00:00:01")},
    )

    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    device = registry.async_get_device_by_identifier(
        (DOMAIN, "TESTSERIAL0001"), entry.entry_id
    )
    assert device is not None
    assert device.id != existing.id
    assert device.config_entry_id == entry.entry_id
    assert (CONNECTION_NETWORK_MAC, "00:00:00:00:00:01") in device.connections
    assert device.manufacturer == "Hikvision"
    assert device.model == "NVR-4CH-POE"
    assert device.sw_version == "V4.30.216"
    assert device.name == "Network Video Recorder"
    # The other integration's device is untouched.
    assert registry.async_get(existing.id).config_entry_id == other.entry_id


async def test_setup_with_camera_offline_keeps_all_cameras(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.online[1] = False
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    coordinator = entry.runtime_data
    assert [c.name for c in coordinator.cameras] == ["Hall", "Living room", "Office"]
    assert coordinator.data.status[1].online is False


async def test_update_failed_on_busy(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    entry = await _setup(hass)
    coordinator: HikRecorderCoordinator = entry.runtime_data
    assert coordinator.last_update_success is True

    patch_nvr.busy_responses = 10
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False

    patch_nvr.busy_responses = 0
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert entry.state is ConfigEntryState.LOADED


async def test_setup_not_ready_when_nvr_busy(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.busy_responses = 10
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_bad_credentials_starts_reauth(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.username = "someone-else"
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_credentials_revoked_during_polling_starts_reauth(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    entry = await _setup(hass)
    patch_nvr.username = "someone-else"
    await entry.runtime_data.async_refresh()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_working_status_forbidden_is_update_failed_with_permission(
    hass: HomeAssistant, patch_nvr: FakeNvr, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    entry = await _setup(hass)
    coordinator: HikRecorderCoordinator = entry.runtime_data
    real = patch_nvr._handle

    def forbid_status(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ISAPI/System/workingstatus":
            return httpx.Response(403, text="Forbidden")
        return real(request)

    monkeypatch.setattr(patch_nvr, "_handle", forbid_status)
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert "Log Search / Interrogate Working Status" in str(coordinator.last_exception)
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_set_recording_and_reboot(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    entry = await _setup(hass)
    coordinator: HikRecorderCoordinator = entry.runtime_data

    await coordinator.async_set_recording(False)
    assert patch_nvr.schedule_enabled == {101: False, 201: False, 301: False}

    patch_nvr.fail_tracks = {201}
    with pytest.raises(HomeAssistantError, match="Living room"):
        await coordinator.async_set_recording(True)
    assert patch_nvr.schedule_enabled == {101: True, 201: False, 301: True}

    assert coordinator.last_restart is None
    await coordinator.async_reboot()
    assert patch_nvr.reboots == 1
    assert coordinator.last_restart is not None


async def test_overlapping_writes_do_not_interleave(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    """A turn_off and a turn_on racing must end with the last call's value."""
    entry = await _setup(hass)
    coordinator: HikRecorderCoordinator = entry.runtime_data
    patch_nvr.yield_on_request = True

    await asyncio.gather(
        coordinator.async_set_recording(False),
        coordinator.async_set_recording(True),
    )

    assert patch_nvr.schedule_enabled == {101: True, 201: True, 301: True}
    # Every PUT of the first call precedes every PUT of the second.
    flags = [
        re.search(r"<enableSchedule>(true|false)<", body).group(1)
        for body in patch_nvr.put_bodies
    ]
    assert flags == ["false"] * 3 + ["true"] * 3


async def test_unload_entry(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
