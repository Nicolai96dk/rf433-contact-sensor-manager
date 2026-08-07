"""Per-entry MQTT manager and persistent runtime state."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from time import monotonic
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DUPLICATE_INTERVAL,
    CONF_JSON_PATH,
    CONF_PAYLOAD_FORMAT,
    CONF_PROFILES,
    CONF_SENSORS,
    CONF_TOPIC,
    DEFAULT_OPTIONS,
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_ID,
    DOMAIN,
    SensorRuntime,
)
from .protocol import event_kind, extract_payload, parse

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


class RF433Manager:
    """Own the sole MQTT subscription and route accepted packets."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        options = {**DEFAULT_OPTIONS, **entry.options}
        self.profiles: dict[str, dict[str, Any]] = {
            DEFAULT_PROFILE_ID: DEFAULT_PROFILE,
            **{p["id"]: p for p in options[CONF_PROFILES]},
        }
        self.sensors: dict[str, SensorRuntime] = {s["id"]: SensorRuntime(s) for s in options[CONF_SENSORS]}
        self.unknown: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.stats: dict[str, int] = {
            "received": 0,
            "accepted": 0,
            "duplicates": 0,
            "malformed": 0,
            "unknown": 0,
        }
        self._recent: dict[str, float] = {}
        self._unsub: Callable[[], None] | None = None
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.scan_callbacks: set[Callable[[str], None]] = set()

    async def async_start(self) -> None:
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise RuntimeError("Home Assistant's MQTT integration is not configured or available")
        saved = await self._store.async_load() or {}
        self.unknown.update(saved.get("unknown", {}))
        for sid, state in saved.get("states", {}).items():
            if runtime := self.sensors.get(sid):
                runtime.battery_low = bool(state.get("battery_low"))
                runtime.contact = state.get("contact")
                runtime.last_payload, runtime.last_seen = state.get("last_payload"), state.get("last_seen")
        self._unsub = await mqtt.async_subscribe(self.hass, self.entry.data[CONF_TOPIC], self._message)

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        await self._async_save()

    @callback
    def _message(self, message) -> None:
        self.stats["received"] += 1
        try:
            payload = extract_payload(
                message.payload,
                self.entry.data[CONF_PAYLOAD_FORMAT],
                self.entry.data.get(CONF_JSON_PATH, "RfReceived.Data"),
            )
        except (ValueError, TypeError, KeyError):
            payload = None
        if payload is None:
            self.stats["malformed"] += 1
            _LOGGER.debug("Ignoring malformed RF message on %s", message.topic)
            return
        for scan_callback in tuple(self.scan_callbacks):
            scan_callback(payload)
        interval = float(self.entry.options.get(CONF_DUPLICATE_INTERVAL, 1.0))
        now_mono = monotonic()
        if interval and now_mono - self._recent.get(payload, -interval) < interval:
            self.stats["duplicates"] += 1
            return
        self._recent[payload] = now_mono
        self._recent = {k: v for k, v in self._recent.items() if now_mono - v <= max(interval, 1)}
        self._process(payload)

    @callback
    def _process(self, payload: str) -> None:
        now = dt_util.utcnow().isoformat()
        for runtime in self.sensors.values():
            profile = self.profiles.get(runtime.config["profile_id"])
            if profile is None:
                continue
            parsed = parse(payload, profile)
            if parsed and parsed[0] == runtime.config["rf_id"]:
                kind = event_kind(parsed[1], profile)
                runtime.last_payload, runtime.last_seen = payload, now
                if kind == "open":
                    runtime.contact = True
                elif kind == "closed":
                    runtime.contact = False
                elif kind == "battery" and runtime.config.get("battery_enabled", True):
                    runtime.battery_low = True
                runtime.config["last_event"] = kind
                runtime.notify()
                self.stats["accepted"] += 1
                self.hass.async_create_task(self._async_save())
                return
        self.stats["unknown"] += 1
        candidate = next((parsed for profile in self.profiles.values() if (parsed := parse(payload, profile))), None)
        item = self.unknown.pop(payload, {"raw": payload, "first_seen": now, "count": 0})
        item.update(
            {
                "last_seen": now,
                "count": item["count"] + 1,
                "device_id": candidate[0] if candidate else None,
                "event_code": candidate[1] if candidate else None,
            }
        )
        self.unknown[payload] = item
        while len(self.unknown) > 100:
            self.unknown.popitem(last=False)
        self.hass.async_create_task(self._async_save())

    async def async_reset_battery(self, sensor_id: str) -> None:
        runtime = self.sensors[sensor_id]
        runtime.battery_low = False
        runtime.config["battery_reset_at"] = dt_util.utcnow().isoformat()
        runtime.notify()
        await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "unknown": dict(self.unknown),
                "states": {
                    sid: {
                        "battery_low": r.battery_low,
                        "contact": r.contact,
                        "last_payload": r.last_payload,
                        "last_seen": r.last_seen,
                    }
                    for sid, r in self.sensors.items()
                },
            }
        )
