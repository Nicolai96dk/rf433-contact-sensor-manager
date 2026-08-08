"""Diagnostics support."""

from homeassistant.components.diagnostics import async_redact_data

# RF IDs remain redacted in configuration. Raw codes are deliberately retained
# in runtime history so diagnostics can reveal unexpected event suffixes.
TO_REDACT = {"rf_id", "device_id", "initial_payload", "initial_code_history"}


async def async_get_config_entry_diagnostics(hass, entry):
    manager = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
            "runtime": {
                "statistics": manager.stats,
                "last_received": {
                    "raw": manager.last_received_payload,
                    "at": manager.last_received_at,
                },
                "sensor_state": {
                    sid: {
                        "last_seen": r.last_seen,
                        "last_payload": r.last_payload,
                        "last_event": r.last_event,
                        "battery_low": r.battery_low,
                        "contact": r.contact,
                        "tamper_last_seen": r.tamper_last_seen or "never",
                        "code_history": list(r.code_history.values()),
                    }
                    for sid, r in manager.sensors.items()
                },
                "unknown_signals": list(manager.unknown.values()),
            },
        },
        TO_REDACT,
    )
