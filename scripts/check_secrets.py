"""Fail (exit 1) if any git-tracked or staged file contains a secret value."""
from __future__ import annotations

import re
import subprocess
import sys

from _env import ROOT, client, load_env


def live_values(env: dict[str, str]) -> set[str]:
    values: set[str] = set()
    with client(env) as http:
        response = http.get("/ISAPI/System/deviceInfo")
        response.raise_for_status()
    for tag in ("serialNumber", "macAddress"):
        match = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", response.text)
        if match:
            values.add(match.group(1).strip())
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
    secrets = live_values(env)
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
