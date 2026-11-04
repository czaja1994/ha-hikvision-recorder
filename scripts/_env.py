"""Shared helpers for the maintenance scripts (read .env, talk to the NVR with GET only)."""
from __future__ import annotations

from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("\"'")
    return env


def base_url(env: dict[str, str]) -> str:
    host = env["HIK_HOST"]
    return host.rstrip("/") if "://" in host else f"http://{host}"


def client(env: dict[str, str]) -> httpx.Client:
    return httpx.Client(
        base_url=base_url(env),
        auth=httpx.DigestAuth(env["HIK_USER"], env["HIK_PASS"]),
        timeout=10.0,
    )
