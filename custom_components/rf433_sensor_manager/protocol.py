"""RF payload parsing."""

from __future__ import annotations

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
