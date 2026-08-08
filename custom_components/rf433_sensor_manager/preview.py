"""Native config-flow previews for live RF setup and learning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DEFAULT_PROFILE, DEFAULT_PROFILE_ID, DOMAIN
from .protocol import ProfileValidationError, event_kind, normalize_profile, parse

DATA_PREVIEW_SESSIONS = "preview_sessions"
DATA_PREVIEW_REGISTERED = "preview_registered"

PreviewRenderer = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
InputCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class PreviewSession:
    """Live data source rendered by Home Assistant's native flow preview."""

    data: dict[str, Any]
    renderer: PreviewRenderer
    input_callback: InputCallback | None = None
    listeners: set[Callable[[], None]] = field(default_factory=set)

    @callback
    def publish(self) -> None:
        """Push the latest RF data to every preview subscriber."""
        for listener in tuple(self.listeners):
            listener()


def _sessions(hass: HomeAssistant) -> dict[str, PreviewSession]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_PREVIEW_SESSIONS, {})


@callback
def register_preview_session(hass: HomeAssistant, flow_id: str, session: PreviewSession) -> None:
    """Register one flow-owned preview session."""
    _sessions(hass)[flow_id] = session


@callback
def remove_preview_session(hass: HomeAssistant, flow_id: str) -> None:
    """Remove one completed or cancelled preview session."""
    _sessions(hass).pop(flow_id, None)


def _preview_entity(state: str, friendly_name: str) -> dict[str, Any]:
    """Build the generic entity preview shape expected by Home Assistant."""
    return {
        "domain": "sensor",
        "state": state,
        "attributes": {
            "friendly_name": friendly_name,
            "icon": "mdi:access-point-network",
        },
    }


def render_profile_preview(data: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """Interpret the latest raw code using the currently entered profile fields."""
    raw = data.get("latest")
    if not raw:
        return _preview_entity("Waiting for an RF signal…", "Scanning for RF codes")

    values = {
        key: value
        for key, value in {**data.get("profile", DEFAULT_PROFILE), **user_input}.items()
        if key not in {"id", "builtin"}
    }
    try:
        profile = normalize_profile(values, DEFAULT_PROFILE_ID, builtin=True)
    except ProfileValidationError:
        return _preview_entity(f"Identified {raw}: profile values are invalid", "Scanning for RF codes")
    if (parsed := parse(raw, profile)) is None:
        return _preview_entity(f"Identified {raw}: profile does not match", "Scanning for RF codes")

    device_id, event_code = parsed
    kind = event_kind(event_code, profile)
    status = {
        "open": "Open",
        "closed": "Closed",
        "tamper": "Tamper",
        "battery": "Low battery",
        "unknown": f"Unknown event {event_code}",
    }[kind]
    return _preview_entity(f"Identified {raw}: {status}", f"Scanning · Device {device_id}")


def render_learning_preview(data: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """Show the current device and every ID accumulated by the open-ended scan."""
    detections: dict[str, dict[str, Any]] = data.get("detections", {})
    if not detections:
        return _preview_entity("Waiting for an RF signal…", "Scanning for RF sensors")

    device_ids = list(reversed(detections))
    ids = ", ".join(device_ids)
    current_id = data.get("current_device_id")
    if current_id is None:
        return _preview_entity(
            f"All identified devices are configured · Scanned: {ids}",
            f"Scanning · {len(device_ids)} device{'s' if len(device_ids) != 1 else ''}",
        )
    configured = set(data.get("configured_ids", []))
    waiting = sum(device_id != current_id and device_id not in configured for device_id in device_ids)
    suffix = f" · {waiting} waiting" if waiting else ""
    return _preview_entity(
        f"Identified Device {current_id}{suffix} · Scanned: {ids}",
        f"Scanning · {len(device_ids)} device{'s' if len(device_ids) != 1 else ''}",
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/start_preview",
        vol.Required("flow_id"): str,
        vol.Required("flow_type"): vol.Any("config_flow", "options_flow"),
        vol.Required("user_input"): dict,
    }
)
@websocket_api.require_admin
@callback
def websocket_start_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe Home Assistant's native flow preview to live RF data."""
    session = _sessions(hass).get(msg["flow_id"])
    if session is None:
        connection.send_error(msg["id"], "not_found", "The live RF scan is no longer active")
        return
    user_input = msg["user_input"]
    if session.input_callback is not None:
        session.input_callback(user_input)

    @callback
    def forward() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], session.renderer(session.data, user_input)))

    session.listeners.add(forward)

    @callback
    def unsubscribe() -> None:
        session.listeners.discard(forward)

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    forward()


async def async_register_preview(hass: HomeAssistant) -> None:
    """Register the native preview WebSocket API once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_PREVIEW_REGISTERED):
        return
    domain_data[DATA_PREVIEW_REGISTERED] = True
    websocket_api.async_register_command(hass, websocket_start_preview)
