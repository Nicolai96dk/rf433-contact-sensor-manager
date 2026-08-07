"""RF payload parsing."""

from __future__ import annotations

import json
import re
from typing import Any

HEX = re.compile(r"^[0-9A-F]+$")


def normalize_payload(value: Any) -> str | None:
    """Normalize an RF code without guessing or altering its meaning."""
    if not isinstance(value, (str, int)):
        return None
    result = str(value).strip().upper()
    return result if result and HEX.fullmatch(result) else None


def dotted_get(value: Any, path: str) -> Any:
    """Read a simple dotted object path."""
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def extract_payload(value: Any, payload_format: str, json_path: str) -> str | None:
    """Extract and normalize an RF payload from an MQTT message body."""
    if payload_format == "json":
        value = dotted_get(json.loads(value), json_path)
    return normalize_payload(value)


def parse(payload: str, profile: dict[str, Any]) -> tuple[str, str] | None:
    """Extract exact transmitter ID and event code."""
    expected = profile.get("payload_length")
    if expected not in (None, 0, "") and len(payload) != int(expected):
        return None
    ds, dl = int(profile["device_start"]), int(profile["device_length"])
    es, el = int(profile["event_start"]), int(profile["event_length"])
    if ds < 0 or es < 0 or dl < 1 or el < 1 or ds + dl > len(payload) or es + el > len(payload):
        return None
    return payload[ds : ds + dl], payload[es : es + el]


def event_kind(code: str, profile: dict[str, Any]) -> str:
    for kind, key in (
        ("open", "open_code"),
        ("closed", "closed_code"),
        ("tamper", "tamper_code"),
        ("battery", "battery_code"),
    ):
        if profile.get(key) and code == str(profile[key]).upper():
            return kind
    return "unknown"


class ProfileValidationError(ValueError):
    """Report the profile field that failed validation."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def normalize_profile(profile: dict[str, Any], profile_id: str, *, builtin: bool = False) -> dict[str, Any]:
    """Normalize and validate a user-editable protocol profile."""
    result = dict(profile)
    name = str(result.get("name", "")).strip()
    if not name:
        raise ProfileValidationError("name")
    result["name"] = name

    try:
        payload_length = result.get("payload_length")
        result["payload_length"] = None if payload_length in (None, "", 0, "0") else int(payload_length)
        for key in ("device_start", "device_length", "event_start", "event_length"):
            result[key] = int(result[key])
    except (KeyError, TypeError, ValueError) as err:
        raise ProfileValidationError("base") from err

    for key in ("device_start", "event_start"):
        if result[key] < 0:
            raise ProfileValidationError(key)
    for key in ("device_length", "event_length"):
        if result[key] < 1:
            raise ProfileValidationError(key)
    if result["payload_length"] is not None:
        if result["payload_length"] < 1:
            raise ProfileValidationError("payload_length")
        if result["device_start"] + result["device_length"] > result["payload_length"]:
            raise ProfileValidationError("device_length")
        if result["event_start"] + result["event_length"] > result["payload_length"]:
            raise ProfileValidationError("event_length")

    for key in ("open_code", "closed_code", "tamper_code", "battery_code"):
        code = normalize_payload(result.get(key)) if result.get(key) else None
        if key in ("open_code", "closed_code") and code is None:
            raise ProfileValidationError(key)
        if code is not None and len(code) != result["event_length"]:
            raise ProfileValidationError(key)
        result[key] = code
    codes = [result[key] for key in ("open_code", "closed_code", "tamper_code", "battery_code") if result[key]]
    if len(codes) != len(set(codes)):
        raise ProfileValidationError("base")

    result["id"] = profile_id
    result["builtin"] = builtin
    return result


def record_detection(detections: dict[str, dict[str, Any]], payload: str, profile: dict[str, Any]) -> bool:
    """Add one valid signal to an accumulating scan result."""
    parsed = parse(payload, profile)
    if parsed is None:
        return False
    device_id, event_code = parsed
    item = detections.setdefault(
        device_id,
        {
            "device_id": device_id,
            "count": 0,
            "events": [],
            "event_codes": [],
            "last_raw": payload,
        },
    )
    kind = event_kind(event_code, profile)
    item["count"] += 1
    item["last_raw"] = payload
    if kind not in item["events"]:
        item["events"].append(kind)
    if event_code not in item["event_codes"]:
        item["event_codes"].append(event_code)
    return True
