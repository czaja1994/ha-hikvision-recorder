"""Entity tests: switch, camera binary sensors, restart button, last-restart sensor."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.hikvision_recorder.const import DOMAIN
from custom_components.hikvision_recorder.coordinator import HikRecorderCoordinator

from .fake_nvr import FakeNvr

SERIAL = "TESTSERIAL0001"
SWITCH = "switch.network_video_recorder_recording"
BUTTON = "button.network_video_recorder_restart_nvr"
LAST_RESTART = "sensor.network_video_recorder_last_restart"
ONLINE = {
    "hall": "binary_sensor.network_video_recorder_hall_online",
    "living_room": "binary_sensor.network_video_recorder_living_room_online",
    "office": "binary_sensor.network_video_recorder_office_online",
}
RECORDING = {
    "hall": "binary_sensor.network_video_recorder_hall_recording",
    "living_room": "binary_sensor.network_video_recorder_living_room_recording",
    "office": "binary_sensor.network_video_recorder_office_recording",
}


async def _setup(
    hass: HomeAssistant, password: str = "secret"
) -> tuple[MockConfigEntry, HikRecorderCoordinator]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="Network Video Recorder",
        data={CONF_HOST: "nvr.test", CONF_USERNAME: "admin", CONF_PASSWORD: password},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data


async def _switch(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )


async def test_entities_created(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    entry, _ = await _setup(hass)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)

    by_domain: dict[str, list[er.RegistryEntry]] = {}
    for reg_entry in entries:
        by_domain.setdefault(reg_entry.domain, []).append(reg_entry)
    assert {domain: len(items) for domain, items in by_domain.items()} == {
        SWITCH_DOMAIN: 1,
        BINARY_SENSOR_DOMAIN: 6,
        BUTTON_DOMAIN: 1,
        SENSOR_DOMAIN: 1,
    }

    assert {e.unique_id for e in entries} == {
        f"{SERIAL}_recording",
        f"{SERIAL}_restart",
        f"{SERIAL}_last_restart",
        *(f"{SERIAL}_{channel}_online" for channel in (1, 2, 3)),
        *(f"{SERIAL}_{channel}_recording" for channel in (1, 2, 3)),
    }
    assert registry.async_get(SWITCH).unique_id == f"{SERIAL}_recording"
    for name in ("hall", "living_room", "office"):
        assert registry.async_get(ONLINE[name]) is not None
        assert registry.async_get(RECORDING[name]) is not None
    assert registry.async_get(BUTTON).unique_id == f"{SERIAL}_restart"
    assert registry.async_get(LAST_RESTART).unique_id == f"{SERIAL}_last_restart"

    assert hass.states.get(ONLINE["hall"]).attributes["friendly_name"] == (
        "Network Video Recorder Hall online"
    )
    assert hass.states.get(RECORDING["living_room"]).attributes["friendly_name"] == (
        "Network Video Recorder Living room recording"
    )
    assert hass.states.get(SWITCH).attributes["friendly_name"] == (
        "Network Video Recorder Recording"
    )


async def test_switch_off_then_on(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    _, coordinator = await _setup(hass)
    assert hass.states.get(SWITCH).state == STATE_ON
    assert all(hass.states.get(e).state == STATE_ON for e in RECORDING.values())

    await _switch(hass, SERVICE_TURN_OFF)
    # The post-write refresh is debounced; refresh explicitly before asserting.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert patch_nvr.schedule_enabled == {101: False, 201: False, 301: False}
    assert coordinator.data.schedule_enabled == {101: False, 201: False, 301: False}
    assert all(not s.recording for s in coordinator.data.status.values())
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert all(hass.states.get(e).state == STATE_OFF for e in RECORDING.values())

    await _switch(hass, SERVICE_TURN_ON)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert patch_nvr.schedule_enabled == {101: True, 201: True, 301: True}
    assert coordinator.data.schedule_enabled == {101: True, 201: True, 301: True}
    assert all(s.recording for s in coordinator.data.status.values())
    assert hass.states.get(SWITCH).state == STATE_ON
    assert all(hass.states.get(e).state == STATE_ON for e in RECORDING.values())


async def test_switch_partial_state_is_on(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.schedule_enabled = {101: True, 201: False, 301: False}
    _, _ = await _setup(hass)
    state = hass.states.get(SWITCH)
    assert state.state == STATE_ON
    assert state.attributes["cameras"] == {
        "Hall": True,
        "Living room": False,
        "Office": False,
    }


async def test_switch_partial_write_failure_raises(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    patch_nvr.fail_tracks = {201}

    with pytest.raises(HomeAssistantError, match="Living room"):
        await _switch(hass, SERVICE_TURN_OFF)
    # Every other track was still switched; the state reflects the device.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert patch_nvr.schedule_enabled == {101: False, 201: True, 301: False}
    assert coordinator.data.schedule_enabled == {101: False, 201: True, 301: False}
    state = hass.states.get(SWITCH)
    assert state.state == STATE_ON
    assert state.attributes["cameras"] == {
        "Hall": False,
        "Living room": True,
        "Office": False,
    }


async def test_switch_permission_error_message(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    patch_nvr.deny_writes = True

    with pytest.raises(HomeAssistantError, match="Remote: Parameters Settings"):
        await _switch(hass, SERVICE_TURN_OFF)
    # Nothing changed and the entity is still usable afterwards.
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_camera_offline_sensor(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    _, coordinator = await _setup(hass)
    assert hass.states.get(ONLINE["hall"]).state == STATE_ON

    patch_nvr.online[1] = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data.status[1].online is False
    assert hass.states.get(ONLINE["hall"]).state == STATE_OFF
    assert hass.states.get(RECORDING["hall"]).state == STATE_OFF
    assert hass.states.get(ONLINE["office"]).state == STATE_ON


async def test_camera_offline_at_startup_still_has_entities(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    patch_nvr.online[1] = False
    await _setup(hass)
    assert hass.states.get(ONLINE["hall"]).state == STATE_OFF
    assert hass.states.get(RECORDING["hall"]).state == STATE_OFF


async def test_channel_missing_from_status_is_unavailable(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    del coordinator.data.status[2]
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(ONLINE["living_room"]).state == STATE_UNAVAILABLE
    assert hass.states.get(RECORDING["living_room"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ONLINE["hall"]).state == STATE_ON


async def test_nvr_unreachable_sensors_unavailable_not_off(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    assert hass.states.get(ONLINE["hall"]).state == STATE_ON

    patch_nvr.unreachable = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    for entity_id in (*ONLINE.values(), *RECORDING.values()):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    patch_nvr.unreachable = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ONLINE["hall"]).state == STATE_ON


async def test_errors_do_not_leak_password(
    hass: HomeAssistant, patch_nvr: FakeNvr, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _, _ = await _setup(hass, password="s3cret-pass")
    patch_nvr.deny_writes = True

    with pytest.raises(HomeAssistantError) as excinfo:
        await _switch(hass, SERVICE_TURN_OFF)
    assert "s3cret-pass" not in str(excinfo.value)
    assert "s3cret-pass" not in caplog.text


async def test_restart_button_sets_last_restart(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    assert hass.states.get(LAST_RESTART).state == STATE_UNKNOWN

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )
    await hass.async_block_till_done()
    assert patch_nvr.reboots == 1
    assert coordinator.last_restart is not None

    state = hass.states.get(LAST_RESTART)
    restarted = datetime.fromisoformat(state.state)
    assert abs(dt_util.utcnow() - restarted) < timedelta(seconds=30)
    assert state.attributes["device_class"] == "timestamp"


async def test_restart_when_nvr_drops_connection_still_counts(
    hass: HomeAssistant, patch_nvr: FakeNvr, caplog: pytest.LogCaptureFixture
) -> None:
    """The NVR typically drops the connection while rebooting (R17)."""
    _, coordinator = await _setup(hass)
    patch_nvr.reboot_timeout = True

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )
    await hass.async_block_till_done()
    assert patch_nvr.reboots == 1
    assert coordinator.last_restart is not None
    assert abs(dt_util.utcnow() - coordinator.last_restart) < timedelta(seconds=30)
    assert hass.states.get(LAST_RESTART).state != STATE_UNKNOWN
    assert any(
        record.levelno == logging.WARNING and "reboot" in record.getMessage().lower()
        for record in caplog.records
    )


async def test_restart_rejected_by_nvr_raises_and_keeps_last_restart(
    hass: HomeAssistant, patch_nvr: FakeNvr
) -> None:
    _, coordinator = await _setup(hass)
    patch_nvr.reboot_status_code = 4

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
        )
    assert patch_nvr.reboots == 1
    assert coordinator.last_restart is None
    assert hass.states.get(LAST_RESTART).state == STATE_UNKNOWN


async def test_last_restart_restored(hass: HomeAssistant, patch_nvr: FakeNvr) -> None:
    mock_restore_cache(
        hass, [State(LAST_RESTART, "2026-11-01T10:00:00+00:00")]
    )
    _, coordinator = await _setup(hass)

    expected = datetime.fromisoformat("2026-11-01T10:00:00+00:00")
    assert hass.states.get(LAST_RESTART).state == "2026-11-01T10:00:00+00:00"
    assert coordinator.last_restart == expected
