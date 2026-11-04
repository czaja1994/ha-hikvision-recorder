"""Record redacted NVR responses into tests/fixtures. Issues GET requests only."""
from __future__ import annotations

import re
import sys

from _env import ROOT, client, load_env

FIXTURES = ROOT / "tests" / "fixtures"

# fixture name -> ISAPI path (all GET)
ENDPOINTS = {
    "device_info.xml": "/ISAPI/System/deviceInfo",
    "channels.xml": "/ISAPI/ContentMgmt/InputProxy/channels",
    "channels_status.xml": "/ISAPI/ContentMgmt/InputProxy/channels/status",
    "working_status.json": "/ISAPI/System/workingstatus?format=json",
    "tracks.xml": "/ISAPI/ContentMgmt/record/tracks",
    "track_101.xml": "/ISAPI/ContentMgmt/record/tracks/101",
}

REDACTIONS = {
    "serialNumber": "TESTSERIAL0001",
    "macAddress": "00:00:00:00:00:01",
    "deviceID": "00000000-0000-0000-0000-000000000001",
    "userName": "admin",
}


def redact(text: str) -> str:
    for tag, value in REDACTIONS.items():
        text = re.sub(
            rf"(<{tag}(?:\s[^>]*)?>)[^<]*(</{tag}>)", rf"\g<1>{value}\g<2>", text
        )
        text = re.sub(rf'("{tag}"\s*:\s*")[^"]*(")', rf"\g<1>{value}\g<2>", text)
    return text


def main() -> int:
    env = load_env()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with client(env) as http:
        for name, path in ENDPOINTS.items():
            response = http.get(path)  # GET only, never write to the NVR
            if response.status_code != 200:
                print(f"FAIL {path}: HTTP {response.status_code}")
                if name == "track_101.xml":
                    print("Track 101 is required by Task 3, stopping.")
                return 1
            (FIXTURES / name).write_text(redact(response.text), encoding="utf-8")
            print(f"ok   {path} -> {name}")
    print("busy.xml is not captured (a 503 cannot be provoked on demand).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
