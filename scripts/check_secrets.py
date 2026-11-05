"""Fail (exit 1) if any git-tracked or staged file contains a secret value."""
from __future__ import annotations

import re
from pathlib import Path
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


def _git_output(root: Path, args: list[str], data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=root, input=data, capture_output=True, check=True
    ).stdout


def _short(sha: str) -> str:
    return sha[:10]


def scan_history(root: Path, secrets: set[str]) -> list[str]:
    """Locations of secret values in any blob or commit message reachable from a ref.

    Every blob reachable from `git rev-list --all` is read once, whatever
    revision or path it appears under. Returns "path:line [blob sha]" and
    "commit sha message" entries; the values themselves are never included,
    and a path that contains a value is shown as <path hidden>.
    """
    needles = [s.lower() for s in secrets]

    def leaks(text: str) -> bool:
        lowered = text.lower()
        return any(n in lowered for n in needles)

    found: list[str] = []

    # Commit messages.
    log = _git_output(root, ["log", "--all", "--format=%x1e%H%x1f%B"]).decode(
        "utf-8", errors="ignore"
    )
    for record in log.split("\x1e"):
        sha, _, message = record.partition("\x1f")
        if sha.strip() and leaks(message):
            found.append(f"commit {_short(sha.strip())} message")

    # Blobs: one (sha, first path) per unique blob.
    listing = _git_output(root, ["rev-list", "--objects", "--all"])
    checked = _git_output(
        root,
        ["cat-file", "--batch-check=%(objecttype) %(objectname) %(rest)"],
        listing,
    ).decode("utf-8", errors="ignore")
    blobs: dict[str, str] = {}
    for line in checked.splitlines():
        kind, _, rest = line.partition(" ")
        sha, _, path = rest.partition(" ")
        if kind == "blob" and sha not in blobs:
            blobs[sha] = path
    if not blobs:
        return found

    stream = _git_output(root, ["cat-file", "--batch"], "".join(f"{s}\n" for s in blobs).encode())
    pos = 0
    while pos < len(stream):
        header_end = stream.index(b"\n", pos)
        sha, _, size_text = stream[pos:header_end].decode().split(" ")
        size = int(size_text)
        body = stream[header_end + 1 : header_end + 1 + size]
        pos = header_end + 1 + size + 1
        path = blobs[sha]
        text = body.decode("utf-8", errors="ignore")
        if not leaks(text):
            continue
        where = "<path hidden>" if leaks(path) else path
        for number, line in enumerate(text.splitlines(), 1):
            if leaks(line):
                found.append(f"{where}:{number} [blob {_short(sha)}]")
    return found


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
    try:
        history = scan_history(ROOT, secrets)
    except subprocess.CalledProcessError as err:
        print(f"ERROR: cannot scan git history, failing closed: git {err.cmd[1]} failed")
        return 2
    if found:
        print("Secret values found in tracked files (file:line):")
        print("\n".join(found))
    if history:
        print("Secret values found in git history (location [blob], find the commit with")
        print("`git log --all --find-object=<blob>`):")
        print("\n".join(history))
    if found or history:
        return 1
    print(
        f"OK: {len(secrets)} secret values, none found in tracked files, "
        "any reachable revision or commit message."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
