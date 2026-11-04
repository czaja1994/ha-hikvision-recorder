"""Tests for the ISAPI client, run against FakeNvr."""

from __future__ import annotations

import httpx
import pytest

from custom_components.hikvision_recorder.api import (
    HikvisionNvrClient,
    NvrAuthError,
    NvrBusyError,
    NvrConnectionError,
    NvrError,
    NvrWriteError,
)
from custom_components.hikvision_recorder.parsing import (
    ChannelStatus,
    set_schedule_enabled,
)

from .fake_nvr import FakeNvr

ALL_TRACKS = [101, 201, 301]


async def test_get_working_status_with_digest(nvr_client, fake_nvr):
    status = await nvr_client.get_working_status()
    assert status == {
        1: ChannelStatus(1, True, True),
        2: ChannelStatus(2, True, True),
        3: ChannelStatus(3, True, True),
    }
    assert [code for _, _, code in fake_nvr.log] == [401, 200]


async def test_read_endpoints(nvr_client):
    info = await nvr_client.get_device_info()
    cameras = await nvr_client.get_cameras()
    schedule = await nvr_client.get_schedule_enabled()
    assert info.model == "NVR-4CH-POE"
    assert [camera.track_id for camera in cameras] == ALL_TRACKS
    assert schedule == {101: True, 201: True, 301: True}


async def test_set_recording_off_puts_only_flag(nvr_client, fake_nvr):
    expected = {tid: set_schedule_enabled(fake_nvr.track_xml(tid), False) for tid in ALL_TRACKS}
    await nvr_client.set_recording(False, ALL_TRACKS)
    assert fake_nvr.put_bodies == [expected[tid] for tid in ALL_TRACKS]
    assert fake_nvr.schedule_enabled == {101: False, 201: False, 301: False}
    status = await nvr_client.get_working_status()
    assert not any(channel.recording for channel in status.values())


async def test_set_recording_on_again(nvr_client, fake_nvr):
    fake_nvr.schedule_enabled.update({101: False, 201: False, 301: False})
    await nvr_client.set_recording(True, ALL_TRACKS)
    assert fake_nvr.schedule_enabled == {101: True, 201: True, 301: True}
    assert all(channel.recording for channel in (await nvr_client.get_working_status()).values())


async def test_set_recording_skips_tracks_already_in_state(nvr_client, fake_nvr):
    fake_nvr.schedule_enabled[101] = False
    await nvr_client.set_recording(False, [101])
    assert fake_nvr.put_bodies == []


async def test_set_recording_partial_failure(nvr_client, fake_nvr):
    fake_nvr.fail_tracks = {201}
    with pytest.raises(NvrWriteError) as excinfo:
        await nvr_client.set_recording(False, ALL_TRACKS)
    assert excinfo.value.failed_track_ids == [201]
    assert fake_nvr.schedule_enabled == {101: False, 201: True, 301: False}


async def test_put_200_with_bad_status_is_failure(nvr_client, fake_nvr):
    fake_nvr.fail_tracks = {101}
    with pytest.raises(NvrWriteError) as excinfo:
        await nvr_client.set_recording(False, [101])
    assert excinfo.value.failed_track_ids == [101]
    # HTTP was 200 for the PUT, yet it must not count as success.
    assert ("PUT", "/ISAPI/ContentMgmt/record/tracks/101", 200) in fake_nvr.log


async def test_busy_retried_then_succeeds(nvr_client, fake_nvr):
    fake_nvr.busy_responses = 2
    status = await nvr_client.get_working_status()
    assert len(status) == 3
    assert [code for _, _, code in fake_nvr.log].count(503) == 2


async def test_busy_exhausted(nvr_client, fake_nvr):
    fake_nvr.busy_responses = 5
    with pytest.raises(NvrBusyError):
        await nvr_client.get_working_status()
    assert [code for _, _, code in fake_nvr.log].count(503) == 3


async def test_write_forbidden_names_permission(nvr_client, fake_nvr):
    fake_nvr.deny_writes = True
    with pytest.raises(NvrAuthError) as excinfo:
        await nvr_client.set_recording(False, ALL_TRACKS)
    assert excinfo.value.required_permission == "Remote: Parameters Settings"


async def test_reboot_forbidden_names_permission(nvr_client, fake_nvr):
    fake_nvr.deny_writes = True
    with pytest.raises(NvrAuthError) as excinfo:
        await nvr_client.reboot()
    assert excinfo.value.required_permission == "Remote: Shutdown / Reboot"


async def test_wrong_credentials_is_auth_error(fake_nvr):
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_nvr)) as http:
        client = HikvisionNvrClient("nvr.test", "intruder", "x", http, retry_delays=(0, 0))
        with pytest.raises(NvrAuthError) as excinfo:
            await client.get_device_info()
    assert excinfo.value.required_permission is None


async def test_reboot(nvr_client, fake_nvr):
    await nvr_client.reboot()
    assert fake_nvr.reboots == 1


async def test_timeout_maps_to_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HikvisionNvrClient("nvr.test", "admin", "secret", http, retry_delays=(0, 0))
        with pytest.raises(NvrConnectionError):
            await client.get_working_status()


async def test_malformed_body_raises_nvr_error(nvr_client, monkeypatch):
    monkeypatch.setattr(FakeNvr, "working_status_json", lambda self: "this is not json")
    with pytest.raises(NvrError) as excinfo:
        await nvr_client.get_working_status()
    assert "/ISAPI/System/workingstatus" in str(excinfo.value)


async def test_errors_never_leak_password(fake_nvr):
    fake_nvr.busy_responses = 5
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_nvr)) as http:
        client = HikvisionNvrClient("nvr.test", "admin", "s3cr3t-pw", http, retry_delays=(0, 0))
        with pytest.raises(NvrBusyError) as excinfo:
            await client.get_device_info()
    assert "s3cr3t-pw" not in str(excinfo.value)
    assert "Authorization" not in str(excinfo.value)
