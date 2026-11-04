"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

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
