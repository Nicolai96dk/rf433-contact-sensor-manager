"""Live Home Assistant panel used by setup and learn flows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

PANEL_PATH = "rf433-sensor-manager-live"
PANEL_ELEMENT = "rf433-sensor-manager-live-panel"
STATIC_URL = "/rf433_sensor_manager_static"
PANEL_VERSION = "0.3.0"
DATA_SESSIONS = "live_sessions"
DATA_PANEL_REGISTERED = "panel_registered"


@dataclass(slots=True)
class LiveSession:
    """One authenticated live UI session."""

    mode: str
    data: dict[str, Any]
    async_done: Callable[[dict[str, Any]], Awaitable[None]]
    listeners: set[Callable[[dict[str, Any]], None]] = field(default_factory=set)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe view for the frontend."""
        return {"mode": self.mode, **self.data}

    @callback
    def publish(self) -> None:
        """Push the current snapshot to every connected panel."""
        snapshot = self.snapshot()
        for listener in tuple(self.listeners):
            listener(snapshot)


def _sessions(hass: HomeAssistant) -> dict[str, LiveSession]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_SESSIONS, {})


@callback
def register_session(hass: HomeAssistant, flow_id: str, session: LiveSession) -> None:
    """Expose a flow-owned session to the live panel."""
    _sessions(hass)[flow_id] = session


@callback
def remove_session(hass: HomeAssistant, flow_id: str) -> None:
    """Remove a completed or cancelled live session."""
    _sessions(hass).pop(flow_id, None)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/live/subscribe",
        vol.Required("flow_id"): str,
    }
)
@websocket_api.require_admin
@callback
def websocket_subscribe_live(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe the live panel to one active setup/options flow."""
    session = _sessions(hass).get(msg["flow_id"])
    if session is None:
        connection.send_error(msg["id"], "not_found", "The live setup session is no longer active")
        return

    @callback
    def forward(snapshot: dict[str, Any]) -> None:
        connection.send_event(msg["id"], snapshot)

    session.listeners.add(forward)

    @callback
    def unsubscribe() -> None:
        session.listeners.discard(forward)

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    forward(session.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/live/done",
        vol.Required("flow_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_live_done(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Finish a live flow using the values entered in the panel."""
    session = _sessions(hass).get(msg["flow_id"])
    if session is None:
        connection.send_error(msg["id"], "not_found", "The live setup session is no longer active")
        return
    try:
        await session.async_done(msg["data"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_input", str(err))
        return
    connection.send_result(msg["id"])


async def async_register_live_panel(hass: HomeAssistant) -> None:
    """Register the hidden custom panel and its WebSocket API once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_PANEL_REGISTERED):
        return
    domain_data[DATA_PANEL_REGISTERED] = True

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL,
                str(Path(__file__).parent / "frontend"),
                cache_headers=False,
            )
        ]
    )
    websocket_api.async_register_command(hass, websocket_subscribe_live)
    websocket_api.async_register_command(hass, websocket_live_done)
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        frontend_url_path=PANEL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_ELEMENT,
                "module_url": f"{STATIC_URL}/live-panel.js?v={PANEL_VERSION}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=True,
        show_in_sidebar=False,
    )
