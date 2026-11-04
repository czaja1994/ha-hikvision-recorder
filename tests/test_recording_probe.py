"""Offline tests for scripts/recording_probe.py, against FakeNvr only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from custom_components.hikvision_recorder.api import NvrError

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "recording_probe.py"
_spec = importlib.util.spec_from_file_location("recording_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

FAST = {"poll_interval": 0, "timeout": 0.05, "restore_delays": (0, 0, 0)}
TRACK_301 = "/ISAPI/ContentMgmt/record/tracks/301"


def _puts(fake):
    return [path for method, path, _ in fake.log if method == "PUT"]


def _stuck_recording(fake, monkeypatch):
    original = fake.working_status_json

    def stuck() -> str:
        data = json.loads(original())
        for item in data["ChanStatus"]:
            item["record"] = 1
        return json.dumps(data)

    monkeypatch.setattr(fake, "working_status_json", stuck)


def _flaky_set_recording(client, monkeypatch, fail_from, fail_until):
    """Make set_recording calls number fail_from..fail_until (1-based) raise."""
    real = client.set_recording
    calls = {"n": 0}

    async def wrapper(enabled, track_ids):
        calls["n"] += 1
        if fail_from <= calls["n"] <= fail_until:
            raise NvrError("injected")
        await real(enabled, track_ids)

    monkeypatch.setattr(client, "set_recording", wrapper)


async def test_success_path(nvr_client, fake_nvr, tmp_path, capsys):
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is True
    assert fake_nvr.schedule_enabled[301] is True
    for track_id in (101, 201, 301):
        assert (tmp_path / f"track_{track_id}.xml").read_text(
            encoding="utf-8"
        ) == fake_nvr.track_xml(track_id)
    assert "track 301 identical to backup" in capsys.readouterr().out
    assert set(_puts(fake_nvr)) == {TRACK_301}
    assert "<enableSchedule>false</enableSchedule>" in fake_nvr.put_bodies[0]
    assert "<enableSchedule>true</enableSchedule>" in fake_nvr.put_bodies[-1]


async def test_stuck_recording_restores(nvr_client, fake_nvr, tmp_path, monkeypatch):
    _stuck_recording(fake_nvr, monkeypatch)
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is True
    assert set(_puts(fake_nvr)) == {TRACK_301}
    assert "<enableSchedule>false</enableSchedule>" in fake_nvr.put_bodies[0]
    assert "<enableSchedule>true</enableSchedule>" in fake_nvr.put_bodies[-1]


async def test_off_put_fails(nvr_client, fake_nvr, tmp_path):
    fake_nvr.fail_tracks = {301}
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is True


async def test_preflight_channel_offline_no_writes(nvr_client, fake_nvr, tmp_path):
    fake_nvr.online[3] = False
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert _puts(fake_nvr) == []


async def test_preflight_backup_already_disabled_no_writes(
    nvr_client, fake_nvr, tmp_path
):
    fake_nvr.schedule_enabled[301] = False
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert _puts(fake_nvr) == []


async def test_resume_times_out(nvr_client, fake_nvr, tmp_path, monkeypatch):
    real = fake_nvr.working_status_json

    def never_resumes() -> str:
        data = json.loads(real())
        for item in data["ChanStatus"]:
            if item["chanNo"] == 3 and fake_nvr.put_bodies and len(
                fake_nvr.put_bodies
            ) >= 2:
                item["record"] = 0
        return json.dumps(data)

    monkeypatch.setattr(fake_nvr, "working_status_json", never_resumes)
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is True


async def test_restore_succeeds_on_later_attempt(
    nvr_client, fake_nvr, tmp_path, monkeypatch
):
    _stuck_recording(fake_nvr, monkeypatch)
    # call 1 = off, calls 2-3 = failing restores, call 4 succeeds
    _flaky_set_recording(nvr_client, monkeypatch, 2, 3)
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is True


async def test_restore_fails_every_attempt(
    nvr_client, fake_nvr, tmp_path, monkeypatch, capsys
):
    _stuck_recording(fake_nvr, monkeypatch)
    _flaky_set_recording(nvr_client, monkeypatch, 2, 99)
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is False
    out = capsys.readouterr().out
    assert "RESTORE FAILED" in out and "track_301.xml" in out
