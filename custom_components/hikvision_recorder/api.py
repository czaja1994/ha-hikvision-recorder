"""Async ISAPI client for a Hikvision NVR.

Error messages name only the request path, never the full URL, the password or
the Authorization header.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import json
import logging
from typing import TypeVar
import xml.etree.ElementTree as ET

import httpx

from .const import REQUEST_TIMEOUT
from .parsing import (
    Camera,
    ChannelStatus,
    NvrDeviceInfo,
    parse_cameras,
    parse_device_info,
    parse_response_status,
    parse_schedule_enabled,
    parse_working_status,
    set_schedule_enabled,
)

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

PATH_DEVICE_INFO = "/ISAPI/System/deviceInfo"
PATH_CHANNELS = "/ISAPI/ContentMgmt/InputProxy/channels"
PATH_WORKING_STATUS = "/ISAPI/System/workingstatus?format=json"
PATH_TRACKS = "/ISAPI/ContentMgmt/record/tracks"
PATH_REBOOT = "/ISAPI/System/reboot"

PERM_WRITE_TRACKS = "Remote: Parameters Settings"
PERM_REBOOT = "Remote: Shutdown / Reboot"
PERM_WORKING_STATUS = "Remote: Log Search / Interrogate Working Status"

_PARSE_ERRORS = (
    ValueError,
    KeyError,
    AttributeError,
    TypeError,
    ET.ParseError,
    json.JSONDecodeError,
)


def _single_schedule_flag(track_xml: str) -> bool:
    """enableSchedule of a single-track document."""
    (value,) = parse_schedule_enabled(track_xml).values()
    return value


class NvrError(Exception):
    """Base class for all errors raised by the client."""


class NvrConnectionError(NvrError):
    """Timeout or network failure."""


class NvrBusyError(NvrError):
    """The NVR kept answering 503 Device Busy after all attempts."""


class NvrAuthError(NvrError):
    """HTTP 401/403, usually missing credentials or a missing permission."""

    def __init__(self, message: str, required_permission: str | None = None) -> None:
        super().__init__(message)
        self.required_permission = required_permission


class NvrWriteError(NvrError):
    """Writing failed for some tracks; the others were handled."""

    def __init__(self, message: str, failed_track_ids: list[int]) -> None:
        super().__init__(message)
        self.failed_track_ids = failed_track_ids


def _bare_path(path: str) -> str:
    """Path without the query string, for messages."""
    return path.split("?", 1)[0]


class HikvisionNvrClient:
    """Talks ISAPI to the NVR using HTTP digest authentication."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
        retry_delays: tuple[float, ...] = (1.0, 2.0),
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._client = client
        self._retry_delays = retry_delays

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        permission: str | None = None,
    ) -> httpx.Response:
        """Send one request, retrying on 503 Device Busy."""
        name = _bare_path(path)
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    f"http://{self._host}{path}",
                    content=content,
                    headers=headers,
                    auth=httpx.DigestAuth(self._username, self._password),
                    timeout=REQUEST_TIMEOUT,
                )
            except httpx.HTTPError as err:
                raise NvrConnectionError(
                    f"{method} {name} failed: {type(err).__name__}"
                ) from None

            status = response.status_code
            if status == 503:
                if attempt < attempts - 1:
                    _LOGGER.debug(
                        "%s %s: device busy, retry %d/%d",
                        method, name, attempt + 1, attempts - 1,
                    )
                    await asyncio.sleep(self._retry_delays[attempt])
                    continue
                raise NvrBusyError(
                    f"{method} {name}: device busy after {attempts} attempts"
                )
            if status in (401, 403):
                raise NvrAuthError(
                    f"{method} {name}: HTTP {status}"
                    + (f", requires permission '{permission}'" if permission else ""),
                    permission,
                )
            if not 200 <= status < 300:
                raise NvrError(f"{method} {name}: HTTP {status}")
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _parse(path: str, parser: Callable[[str], _T], text: str) -> _T:
        """Run a parser, turning any parsing failure into NvrError."""
        try:
            return parser(text)
        except _PARSE_ERRORS as err:
            raise NvrError(
                f"Unexpected response from {_bare_path(path)}: {type(err).__name__}"
            ) from None

    async def get_device_info(self) -> NvrDeviceInfo:
        response = await self._request("GET", PATH_DEVICE_INFO)
        return self._parse(PATH_DEVICE_INFO, parse_device_info, response.text)

    async def get_cameras(self) -> list[Camera]:
        response = await self._request("GET", PATH_CHANNELS)
        return self._parse(PATH_CHANNELS, parse_cameras, response.text)

    async def get_working_status(self) -> dict[int, ChannelStatus]:
        response = await self._request(
            "GET", PATH_WORKING_STATUS, permission=PERM_WORKING_STATUS
        )
        return self._parse(PATH_WORKING_STATUS, parse_working_status, response.text)

    async def get_schedule_enabled(self) -> dict[int, bool]:
        response = await self._request("GET", PATH_TRACKS)
        return self._parse(PATH_TRACKS, parse_schedule_enabled, response.text)

    async def set_recording(self, enabled: bool, track_ids: Iterable[int]) -> None:
        """Set enableSchedule on each track; try all, then report failures.

        Connection and authorisation errors abort at once (the NVR is
        unreachable or every write would be refused); per-track failures are
        collected and raised together as NvrWriteError.
        """
        failed: list[int] = []
        for track_id in track_ids:
            try:
                await self._set_track(track_id, enabled)
            except (NvrConnectionError, NvrAuthError):
                raise
            except NvrError as err:
                _LOGGER.warning("Could not set recording on track %s: %s", track_id, err)
                failed.append(track_id)
        if failed:
            raise NvrWriteError(
                f"Failed to update tracks {failed}", failed_track_ids=failed
            )

    async def _set_track(self, track_id: int, enabled: bool) -> None:
        path = f"{PATH_TRACKS}/{track_id}"
        response = await self._request("GET", path, permission=PERM_WRITE_TRACKS)
        current = self._parse(path, _single_schedule_flag, response.text)
        if current == enabled:
            return
        body = self._parse(
            path, lambda text: set_schedule_enabled(text, enabled), response.text
        )
        put = await self._request(
            "PUT",
            path,
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            permission=PERM_WRITE_TRACKS,
        )
        code, text = self._parse(path, parse_response_status, put.text)
        if code != 1:
            raise NvrError(f"PUT {path}: statusCode {code} ({text})")

    async def reboot(self) -> None:
        response = await self._request("PUT", PATH_REBOOT, permission=PERM_REBOOT)
        if response.text.strip():
            code, text = self._parse(PATH_REBOOT, parse_response_status, response.text)
            if code != 1:
                raise NvrError(f"PUT {PATH_REBOOT}: statusCode {code} ({text})")
