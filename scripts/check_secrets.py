"""Fail (exit 1) if any git-tracked or staged file contains a secret value."""
from __future__ import annotations

import re
import subprocess
import sys
import time

import httpx

from _env import ROOT, client, load_env


class SecretCheckError(Exception):
    """The live identifiers could not be obtained; the gate must fail closed."""


def parse_identifiers(text: str) -> set[str]:
    """Extract serialNumber and macAddress; raise if either is missing or empty."""
    values: set[str] = set()
    for tag in ("serialNumber", "macAddress"):
        match = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", text)
        if not match or not match.group(1).strip():
            raise SecretCheckError(f"{tag} not found in deviceInfo response")
        values.add(match.group(1).strip())
    return values


def fetch_device_info(env: dict[str, str]) -> str:
    """GET deviceInfo, retrying 503 up to 3 times (1 s, 2 s pauses)."""
    try:
        with client(env) as http:
            for attempt in range(3):
                response = http.get("/ISAPI/System/deviceInfo")
                if response.status_code != 503:
                    break
                if attempt < 2:
                    time.sleep(attempt + 1)
    except httpx.HTTPError as err:
        raise SecretCheckError(f"NVR unreachable ({type(err).__name__})") from None
    if response.status_code != 200:
        raise SecretCheckError(f"deviceInfo returned HTTP {response.status_code}")
    return response.text


def live_values(env: dict[str, str]) -> set[str]:
    values = parse_identifiers(fetch_device_info(env))
    if env.get("HIK_PASS"):
        values.add(env["HIK_PASS"])
    if env.get("HIK_USER") and env["HIK_USER"].lower() != "admin":
        values.add(env["HIK_USER"])
    for item in env.get("SECRET_EXTRA", "").split(","):
        if item.strip():
            values.add(item.strip())
    for value in list(values):
        if re.fullmatch(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", value):
            values.add(re.sub(r"[:-]", "", value))
    return {v for v in values if v}


def git_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode()
    return [f for f in out.split("\0") if f]


def main() -> int:
    env = load_env()
    try:
        secrets = live_values(env)
    except SecretCheckError as err:
        print(f"ERROR: cannot verify secrets, failing closed: {err}")
        return 2
    found: list[str] = []
    for name in git_files():
        path = ROOT / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        # also check the staged blob, which may differ from the working copy
        staged = subprocess.run(
            ["git", "show", f":{name}"], cwd=ROOT, capture_output=True
        ).stdout.decode("utf-8", errors="ignore").splitlines()
        for source in (lines, staged):
            for number, line in enumerate(source, 1):
                lowered = line.lower()
                if any(s.lower() in lowered for s in secrets):
                    entry = f"{name}:{number}"
                    if entry not in found:
                        found.append(entry)
    if found:
        print("Secret values found (file:line):")
        print("\n".join(found))
        return 1
    print(f"OK: {len(secrets)} secret values, none found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
