"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import httpx
import pytest

from custom_components.hikvision_recorder.api import HikvisionNvrClient

from .fake_nvr import FakeNvr


@pytest.fixture
def fake_nvr() -> FakeNvr:
    """A fresh fake NVR."""
    return FakeNvr(username="admin")


@pytest.fixture
async def nvr_client(fake_nvr: FakeNvr) -> AsyncIterator[HikvisionNvrClient]:
    """A client wired to the fake NVR through httpx.MockTransport."""
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_nvr)) as http:
        yield HikvisionNvrClient(
            "nvr.test", "admin", "secret", http, retry_delays=(0, 0)
        )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ in every test."""


@pytest.fixture
def patch_nvr(fake_nvr: FakeNvr) -> Iterator[FakeNvr]:
    """Route the integration's HTTP client to the fake NVR, without retry sleeps."""

    def make_client(*args, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(fake_nvr))

    base = "custom_components.hikvision_recorder"
    with (
        patch(f"{base}.get_async_client", make_client),
        patch(f"{base}.config_flow.get_async_client", make_client),
        patch(f"{base}.RETRY_DELAYS", (0, 0)),
        patch(f"{base}.config_flow.RETRY_DELAYS", (0, 0)),
    ):
        yield fake_nvr
