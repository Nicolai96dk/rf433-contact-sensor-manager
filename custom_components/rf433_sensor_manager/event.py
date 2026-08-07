"""Native tamper event entities."""

from homeassistant.components.event import EventEntity

from .entity import RF433Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            Tamper(entry.runtime_data, r)
            for r in entry.runtime_data.sensors.values()
            if entry.runtime_data.profiles[r.config["profile_id"]].get("tamper_code")
            and r.config.get("tamper_enabled", True)
        ]
    )


class Tamper(RF433Entity, EventEntity):
    _attr_name = "Tamper"
    _attr_event_types = ("tamper",)

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "tamper")
        self._last_seen = None

    def _update(self):
        if self.runtime.config.get("last_event") == "tamper" and self.runtime.last_seen != self._last_seen:
            self._last_seen = self.runtime.last_seen
            self._trigger_event(
                "tamper",
                {
                    "raw_payload": self.runtime.last_payload,
                    "rf_id": self.runtime.config["rf_id"],
                    "bridge": self.manager.entry.title,
                },
            )
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        self.runtime.listeners.add(self._update)
        self.async_on_remove(lambda: self.runtime.listeners.discard(self._update))
