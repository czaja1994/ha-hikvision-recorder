"""Tests for ISAPI parsing helpers."""

from pathlib import Path

import pytest

from custom_components.hikvision_recorder.parsing import (
    Camera,
    ChannelStatus,
    parse_cameras,
    parse_device_info,
    parse_response_status,
    parse_schedule_enabled,
    parse_working_status,
    set_schedule_enabled,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_device_info():
    info = parse_device_info(load("device_info.xml"))
    assert info.model == "NVR-4CH-POE"
    assert info.serial == "TESTSERIAL0001"
    assert info.firmware == "V4.30.216"


def test_parse_cameras():
    assert parse_cameras(load("channels.xml")) == [
        Camera(1, "Hall", 101),
        Camera(2, "Living room", 201),
        Camera(3, "Office", 301),
    ]


def test_parse_working_status():
    status = parse_working_status(load("working_status.json"))
    assert status == {
        n: ChannelStatus(n, True, True) for n in (1, 2, 3)
    }
    off = parse_working_status('{"ChanStatus":[{"chanNo":1,"online":0,"record":0}]}')
    assert off[1] == ChannelStatus(1, False, False)


def test_parse_schedule_enabled():
    assert parse_schedule_enabled(load("tracks.xml")) == {
        101: True,
        201: True,
        301: True,
    }


def test_set_schedule_enabled_changes_only_flag():
    track_101 = load("track_101.xml")
    out = set_schedule_enabled(track_101, False)
    assert "<enableSchedule>false</enableSchedule>" in out
    assert out.replace("<enableSchedule>false<", "<enableSchedule>true<") == track_101
    assert set_schedule_enabled(out, True) == track_101


def test_set_schedule_enabled_rejects_ambiguous():
    with pytest.raises(ValueError):
        set_schedule_enabled("<Track><id>1</id></Track>", True)
    with pytest.raises(ValueError):
        set_schedule_enabled(
            "<a><enableSchedule>true</enableSchedule>"
            "<enableSchedule>false</enableSchedule></a>",
            True,
        )


def test_parse_response_status():
    assert parse_response_status(load("busy.xml")) == (2, "Device Busy")
