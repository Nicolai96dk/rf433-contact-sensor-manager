"""Diagnostic RF entities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import RF433Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [cls(entry.runtime_data, r) for r in entry.runtime_data.sensors.values() for cls in (LastMessage, LastSeen)]
    )


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
