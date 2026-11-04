"""Offline tests for scripts/recording_probe.py, against FakeNvr only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "recording_probe.py"
_spec = importlib.util.spec_from_file_location("recording_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

FAST = {"poll_interval": 0, "timeout": 0.05}


async def test_success_path(nvr_client, fake_nvr, tmp_path, capsys):
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is True
    assert fake_nvr.schedule_enabled[301] is True
    for track_id in (101, 201, 301):
        assert (tmp_path / f"track_{track_id}.xml").read_text(
            encoding="utf-8"
        ) == fake_nvr.track_xml(track_id)
    assert "track 301 identical to backup" in capsys.readouterr().out


async def test_failure_after_off_restores_schedule(
    nvr_client, fake_nvr, tmp_path, monkeypatch
):
    original = fake_nvr.working_status_json

    def stuck_recording() -> str:
        data = json.loads(original())
        for item in data["ChanStatus"]:
            item["record"] = 1
        return json.dumps(data)

    monkeypatch.setattr(fake_nvr, "working_status_json", stuck_recording)
    assert await probe.run_probe(nvr_client, tmp_path, **FAST) is False
    assert fake_nvr.schedule_enabled[301] is True
    assert any(body for body in fake_nvr.put_bodies)  # off step was written
