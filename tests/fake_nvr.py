"""In-memory fake of a Hikvision NVR, usable as an httpx.MockTransport handler."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

import httpx

FIXTURES = Path(__file__).parent / "fixtures"

_TRACK_RE = re.compile(r"<Track\b.*?</Track>", re.DOTALL)
_ENABLE_RE = re.compile(r"<enableSchedule>(?:true|false)</enableSchedule>")
_ID_RE = re.compile(r"<id>(\d+)</id>")
_TRACK_PATH_RE = re.compile(r"^/ISAPI/ContentMgmt/record/tracks/(\d+)$")

_CHALLENGE = 'Digest realm="test", qop="auth", nonce="abc", algorithm="MD5"'


def _response_status(code: int, text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>\n'
        '<ResponseStatus version="1.0" '
        'xmlns="http://www.hikvision.com/ver20/XMLSchema">\n'
        f"<statusCode>{code}</statusCode>\n"
        f"<statusString>{text}</statusString>\n"
        "</ResponseStatus>\n"
    )


class FakeNvr:
    """Handler for httpx.MockTransport that behaves like a small NVR."""

    def __init__(self, username: str = "admin") -> None:
        self.username = username
        self._tracks_xml = (FIXTURES / "tracks.xml").read_text(encoding="utf-8")
        self._channels_xml = (FIXTURES / "channels.xml").read_text(encoding="utf-8")
        self._device_xml = (FIXTURES / "device_info.xml").read_text(encoding="utf-8")
        self._busy_xml = (FIXTURES / "busy.xml").read_text(encoding="utf-8")
        self._declaration = self._tracks_xml.split("\n", 1)[0]
        self._track_templates: dict[int, str] = {}
        for match in _TRACK_RE.finditer(self._tracks_xml):
            track_id = int(_ID_RE.search(match.group(0)).group(1))
            self._track_templates[track_id] = match.group(0)

        self.schedule_enabled: dict[int, bool] = {
            track_id: True for track_id in self._track_templates
        }
        self.online: dict[int, bool] = {1: True, 2: True, 3: True}
        self.put_bodies: list[str] = []
        self.busy_responses = 0
        self.deny_writes = False
        self.fail_tracks: set[int] = set()
        self.reboots = 0
        self.reboot_status_code = 1
        self.reboot_empty_body = False
        # The NVR drops the connection while rebooting: PUT reboot times out.
        self.reboot_timeout = False
        # Every request fails at the transport (cable pulled, NVR rebooting).
        self.unreachable = False
        # Tracks whose requests raise a connect timeout in the transport.
        self.timeout_tracks: set[int] = set()
        # Yield to the event loop before answering, so concurrent callers can
        # interleave the way they would over a real network.
        self.yield_on_request = False
        # (method, path, status) of every response served, in order.
        self.log: list[tuple[str, str, int]] = []

    # -- generated payloads -------------------------------------------------

    def track_xml(self, track_id: int) -> str:
        """Single-track XML exactly as served for the current state."""
        flag = "true" if self.schedule_enabled[track_id] else "false"
        body = _ENABLE_RE.sub(
            f"<enableSchedule>{flag}</enableSchedule>",
            self._track_templates[track_id],
            count=1,
        )
        return f"{self._declaration}\n{body}\n"

    def tracks_xml(self) -> str:
        """Track list XML with enableSchedule reflecting the current state."""

        def swap(match: re.Match[str]) -> str:
            track_id = int(_ID_RE.search(match.group(0)).group(1))
            flag = "true" if self.schedule_enabled[track_id] else "false"
            return _ENABLE_RE.sub(
                f"<enableSchedule>{flag}</enableSchedule>", match.group(0), count=1
            )

        return _TRACK_RE.sub(swap, self._tracks_xml)

    def working_status_json(self) -> str:
        chan_status = []
        for channel, online in sorted(self.online.items()):
            enabled = self.schedule_enabled.get(channel * 100 + 1, False)
            chan_status.append(
                {
                    "chanNo": channel,
                    "online": 1 if online else 0,
                    "record": 1 if online and enabled else 0,
                    "signal": 0,
                    "linkNum": 0,
                    "bitRate": 6291456,
                }
            )
        return json.dumps({"devStatus": 0, "ChanStatus": chan_status, "HDStatus": []})

    # -- transport handler --------------------------------------------------

    def __call__(self, request: httpx.Request):
        if self.yield_on_request:
            return self._yielding(request)
        return self._serve(request)

    async def _yielding(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return self._serve(request)

    def _serve(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("unreachable", request=request)
        if self.reboot_timeout and (
            request.method == "PUT" and request.url.path == "/ISAPI/System/reboot"
        ):
            self.reboots += 1
            raise httpx.ReadTimeout("timed out", request=request)
        match = _TRACK_PATH_RE.match(request.url.path)
        if match and int(match.group(1)) in self.timeout_tracks:
            raise httpx.ConnectTimeout("timed out", request=request)
        response = self._handle(request)
        self.log.append((request.method, request.url.path, response.status_code))
        return response

    def _handle(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        if auth is None:
            return httpx.Response(401, headers={"WWW-Authenticate": _CHALLENGE})
        if f'username="{self.username}"' not in auth:
            return httpx.Response(401, headers={"WWW-Authenticate": _CHALLENGE})

        if self.busy_responses > 0:
            self.busy_responses -= 1
            return httpx.Response(503, text=self._busy_xml)

        path = request.url.path
        if request.method == "GET":
            return self._get(path)
        if request.method == "PUT":
            if self.deny_writes:
                return httpx.Response(403, text="Forbidden")
            return self._put(path, request.content.decode("utf-8"))
        return httpx.Response(405)

    def _get(self, path: str) -> httpx.Response:
        if path == "/ISAPI/System/deviceInfo":
            return httpx.Response(200, text=self._device_xml)
        if path == "/ISAPI/ContentMgmt/InputProxy/channels":
            return httpx.Response(200, text=self._channels_xml)
        if path == "/ISAPI/System/workingstatus":
            return httpx.Response(200, text=self.working_status_json())
        if path == "/ISAPI/ContentMgmt/record/tracks":
            return httpx.Response(200, text=self.tracks_xml())
        match = _TRACK_PATH_RE.match(path)
        if match and int(match.group(1)) in self._track_templates:
            return httpx.Response(200, text=self.track_xml(int(match.group(1))))
        return httpx.Response(404)

    def _put(self, path: str, body: str) -> httpx.Response:
        if path == "/ISAPI/System/reboot":
            self.reboots += 1
            if self.reboot_empty_body:
                return httpx.Response(200, text="")
            return httpx.Response(
                200, text=_response_status(self.reboot_status_code, "reboot")
            )
        match = _TRACK_PATH_RE.match(path)
        if match and int(match.group(1)) in self._track_templates:
            track_id = int(match.group(1))
            self.put_bodies.append(body)
            if track_id in self.fail_tracks:
                return httpx.Response(200, text=_response_status(4, "Invalid Content"))
            flag = re.search(r"<enableSchedule>(true|false)</enableSchedule>", body)
            if flag is None:
                return httpx.Response(400, text=_response_status(6, "Invalid XML"))
            self.schedule_enabled[track_id] = flag.group(1) == "true"
            return httpx.Response(200, text=_response_status(1, "OK"))
        return httpx.Response(404)
