"""Diagnostics support."""

from homeassistant.components.diagnostics import async_redact_data

TO_REDACT = {"rf_id", "raw", "device_id"}


async def async_get_config_entry_diagnostics(hass, entry):
    manager = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
            "runtime": {
                "statistics": manager.stats,
                "sensor_state": {
                    sid: {"last_seen": r.last_seen, "battery_low": r.battery_low, "contact": r.contact}
                    for sid, r in manager.sensors.items()
                },
                "unknown_signals": list(manager.unknown.values()),
            },
        },
        TO_REDACT,
    )
