"""Pure parsing and editing helpers for Hikvision ISAPI payloads."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import xml.etree.ElementTree as ET

NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}

_ENABLE_SCHEDULE_RE = re.compile(r"<enableSchedule>(?:true|false)</enableSchedule>")


@dataclass(frozen=True)
class NvrDeviceInfo:
    """Identity of the NVR."""

    name: str
    model: str
    serial: str
    mac: str
    firmware: str


@dataclass(frozen=True)
class Camera:
    """A camera channel; track_id = channel * 100 + 1."""

    channel: int
    name: str
    track_id: int


@dataclass(frozen=True)
class ChannelStatus:
    """Live status of one channel."""

    channel: int
    online: bool
    recording: bool


def _text(root: ET.Element, tag: str) -> str:
    return (root.findtext(f"h:{tag}", default="", namespaces=NS) or "").strip()


def parse_device_info(xml: str) -> NvrDeviceInfo:
    """Parse /ISAPI/System/deviceInfo."""
    root = ET.fromstring(xml)
    return NvrDeviceInfo(
        name=_text(root, "deviceName"),
        model=_text(root, "model"),
        serial=_text(root, "serialNumber"),
        mac=_text(root, "macAddress"),
        firmware=_text(root, "firmwareVersion"),
    )


def parse_cameras(xml: str) -> list[Camera]:
    """Parse InputProxy channels into cameras."""
    root = ET.fromstring(xml)
    cameras: list[Camera] = []
    for channel in root.findall("h:InputProxyChannel", NS):
        number = int(_text(channel, "id"))
        cameras.append(Camera(number, _text(channel, "name"), number * 100 + 1))
    return cameras


def parse_working_status(text: str) -> dict[int, ChannelStatus]:
    """Parse the workingstatus JSON (ChanStatus list)."""
    data = json.loads(text)
    result: dict[int, ChannelStatus] = {}
    for item in data.get("ChanStatus", []):
        number = int(item["chanNo"])
        result[number] = ChannelStatus(
            number, item.get("online") == 1, item.get("record") == 1
        )
    return result


def parse_schedule_enabled(tracks_xml: str) -> dict[int, bool]:
    """Map track id to its CustomExtension/enableSchedule value."""
    root = ET.fromstring(tracks_xml)
    result: dict[int, bool] = {}
    for track in root.iter(f"{{{NS['h']}}}Track"):
        enable = track.find(".//h:CustomExtension/h:enableSchedule", NS)
        if enable is None:
            continue
        result[int(_text(track, "id"))] = (enable.text or "").strip().lower() == "true"
    return result


def set_schedule_enabled(track_xml: str, enabled: bool) -> str:
    """Replace exactly one enableSchedule value, leaving all else untouched."""
    matches = _ENABLE_SCHEDULE_RE.findall(track_xml)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one enableSchedule element, found {len(matches)}"
        )
    value = "true" if enabled else "false"
    return _ENABLE_SCHEDULE_RE.sub(
        f"<enableSchedule>{value}</enableSchedule>", track_xml, count=1
    )


def parse_response_status(xml: str) -> tuple[int, str]:
    """Parse a ResponseStatus into (statusCode, statusString)."""
    root = ET.fromstring(xml)
    return int(_text(root, "statusCode")), _text(root, "statusString")
