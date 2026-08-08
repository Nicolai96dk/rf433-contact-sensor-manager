"""Diagnostic RF entities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import RF433Entity


async def async_setup_entry(hass, entry, async_add_entities):
    entities: list[SensorEntity] = [
        cls(entry.runtime_data, runtime)
        for runtime in entry.runtime_data.sensors.values()
        for cls in (LastMessage, LastSeen)
    ]
    entities.extend(
        LastTamper(entry.runtime_data, runtime)
        for runtime in entry.runtime_data.sensors.values()
        if entry.runtime_data.profiles[runtime.config["profile_id"]].get("tamper_code")
        and runtime.config.get("tamper_enabled", True)
    )
    async_add_entities(entities)


class LastMessage(RF433Entity, SensorEntity):
    _attr_name = "Last RF message"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "last_message")

    @property
    def native_value(self):
        return self.runtime.last_payload

    @property
    def extra_state_attributes(self):
        return {"rf_id": self.runtime.config["rf_id"]}


class LastSeen(RF433Entity, SensorEntity):
    _attr_name = "Last seen"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "last_seen")

    @property
    def native_value(self):
        return dt_util.parse_datetime(self.runtime.last_seen) if self.runtime.last_seen else None


class LastTamper(RF433Entity, SensorEntity):
    """Expose an explicit Never state until the first tamper event."""

    _attr_name = "Last tamper"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "last_tamper")

    @property
    def native_value(self):
        return self.runtime.tamper_last_seen or "Never"
