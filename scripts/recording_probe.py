"""Live probe: does enableSchedule=false on one track really stop recording?

WRITES to the NVR (only enableSchedule of one track, then restores it).
Run it only after the user has agreed in chat. Exit code 0 only if recording
stopped, resumed, and the track XML is byte-identical to the backup.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402

from custom_components.hikvision_recorder.api import (  # noqa: E402
    HikvisionNvrClient,
    NvrError,
)


async def _wait_for(
    client: HikvisionNvrClient,
    channel: int,
    expected: bool,
    poll_interval: float,
    timeout: float,
) -> float | None:
    """Poll until the channel's recording equals expected; seconds or None."""
    start = time.monotonic()
    while True:
        try:
            status = await client.get_working_status()
            if channel in status and status[channel].recording == expected:
                return time.monotonic() - start
        except NvrError as err:
            print(f"  poll error: {err}")
        if time.monotonic() - start >= timeout:
            return None
        await asyncio.sleep(poll_interval)


async def run_probe(
    client: HikvisionNvrClient,
    backup_dir: pathlib.Path,
    track_ids: tuple[int, ...] = (101, 201, 301),
    probe_track: int = 301,
    probe_channel: int = 3,
    poll_interval: float = 5.0,
    timeout: float = 60.0,
    restore_delays: tuple[float, ...] = (2.0, 5.0, 10.0),
) -> bool:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups: dict[int, str] = {}
    for track_id in track_ids:
        backups[track_id] = await client.get_track_xml(track_id)
        (backup_dir / f"track_{track_id}.xml").write_text(
            backups[track_id], encoding="utf-8"
        )
    print(f"backups written to {backup_dir}")

    # Preflight: abort before any write unless the state is what we expect.
    if backups[probe_track].count("<enableSchedule>true</enableSchedule>") != 1:
        print(
            f"ABORT: backup of track {probe_track} does not contain exactly one "
            "enableSchedule=true; nothing written"
        )
        return False
    try:
        status = await client.get_working_status()
    except NvrError as err:
        print(f"ABORT: cannot read working status ({err}); nothing written")
        return False
    channel = status.get(probe_channel)
    if channel is None or not channel.online or not channel.recording:
        print(
            f"ABORT: channel {probe_channel} is missing, offline or not recording; "
            "nothing written"
        )
        return False

    ok = False
    off_attempted = False
    try:
        off_attempted = True
        await client.set_recording(False, [probe_track])
        stopped = await _wait_for(client, probe_channel, False, poll_interval, timeout)
        if stopped is None:
            print(f"FAIL: channel {probe_channel} still recording after {timeout}s")
            return False
        print(f"recording stopped after {stopped:.1f}s")

        await client.set_recording(True, [probe_track])
        resumed = await _wait_for(client, probe_channel, True, poll_interval, timeout)
        if resumed is None:
            print(f"FAIL: channel {probe_channel} not recording after {timeout}s")
            return False
        print(f"recording resumed after {resumed:.1f}s")

        final = await client.get_track_xml(probe_track)
        if final != backups[probe_track]:
            print(f"FAIL: track {probe_track} differs from backup")
            return False
        print(f"track {probe_track} identical to backup")
        ok = True
    except NvrError as err:
        print(f"FAIL: {err}")
    finally:
        if off_attempted:
            restored = False
            for attempt in range(len(restore_delays) + 1):
                try:
                    await client.set_recording(True, [probe_track])
                    restored = True
                    break
                except NvrError as err:
                    print(f"restore attempt {attempt + 1} failed: {err}")
                    if attempt < len(restore_delays):
                        await asyncio.sleep(restore_delays[attempt])
            if not restored:
                print(
                    f"RESTORE FAILED: set enableSchedule to true on track "
                    f"{probe_track} manually; original XML: "
                    f"{backup_dir / f'track_{probe_track}.xml'}"
                )
                ok = False
    return ok


async def _main() -> bool:
    from _env import base_url, load_env

    env = load_env()
    host = base_url(env).split("://", 1)[1]
    backup_dir = (
        pathlib.Path.home()
        / "hikvision-recorder-backups"
        / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    async with httpx.AsyncClient() as http:
        client = HikvisionNvrClient(host, env["HIK_USER"], env["HIK_PASS"], http)
        return await run_probe(client, backup_dir)


def main() -> int:
    return 0 if asyncio.run(_main()) else 1


if __name__ == "__main__":
    sys.exit(main())
