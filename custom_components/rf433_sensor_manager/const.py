"""Constants and data models for RF433 Sensor Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOMAIN = "rf433_sensor_manager"
PLATFORMS = ["binary_sensor", "sensor", "event", "button"]
CONF_NAME = "name"
CONF_TOPIC = "topic"
CONF_PAYLOAD_FORMAT = "payload_format"
CONF_JSON_PATH = "json_path"
CONF_DUPLICATE_INTERVAL = "duplicate_interval"
CONF_PROFILES = "profiles"
CONF_SENSORS = "sensors"
FORMAT_JSON = "json"
FORMAT_RAW = "raw"
DEFAULT_PROFILE_ID = "ds4_contact"
DEFAULT_PROFILE = {
    "id": DEFAULT_PROFILE_ID,
    "name": "DS-4 / Generic Contact Sensor",
    "payload_length": 6,
    "device_start": 0,
    "device_length": 4,
    "event_start": 4,
    "event_length": 2,
    "open_code": "0A",
    "closed_code": "0E",
    "tamper_code": "07",
    "battery_code": "06",
    "builtin": True,
}
DEFAULT_OPTIONS = {CONF_DUPLICATE_INTERVAL: 1.0, CONF_PROFILES: [], CONF_SENSORS: []}


@dataclass(slots=True)
class SensorRuntime:
    """Mutable state for one configured transmitter."""

    config: dict[str, Any]
    contact: bool | None = None
    battery_low: bool = False
    last_payload: str | None = None
    last_seen: str | None = None
    listeners: set[Any] = field(default_factory=set)

    def notify(self) -> None:
        for listener in tuple(self.listeners):
            listener()
