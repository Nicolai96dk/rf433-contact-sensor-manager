"""Diagnostic RF entities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .const import CONF_PAYLOAD_FORMAT, CONF_TOPIC
from .entity import RF433Entity, RF433HubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    entities: list[SensorEntity] = [
        LatestRFSignal(entry.runtime_data),
        LastRFSignal(entry.runtime_data),
        RFMessagesReceived(entry.runtime_data),
        ConfiguredSensors(entry.runtime_data),
        UnknownRFSignals(entry.runtime_data),
    ]
    entities.extend(
        cls(entry.runtime_data, runtime)
        for runtime in entry.runtime_data.sensors.values()
        for cls in (LastMessage, LastSeen)
    )
    entities.extend(
        LastTamper(entry.runtime_data, runtime)
        for runtime in entry.runtime_data.sensors.values()
        if entry.runtime_data.profiles[runtime.config["profile_id"]].get("tamper_code")
        and runtime.config.get("tamper_enabled", True)
    )
    async_add_entities(entities)


class LatestRFSignal(RF433HubEntity, SensorEntity):
    """Expose the newest valid RF code, recognized or not."""

    _attr_translation_key = "latest_rf_signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager):
        super().__init__(manager, "latest_rf_signal")

    @property
    def native_value(self):
        return self.manager.last_received_payload

    @property
    def extra_state_attributes(self):
        return {
            "mqtt_topic": self.manager.entry.data[CONF_TOPIC],
            "payload_format": self.manager.entry.data[CONF_PAYLOAD_FORMAT],
        }


class LastRFSignal(RF433HubEntity, SensorEntity):
    """Expose when the newest valid RF code was received."""

    _attr_translation_key = "last_rf_signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager):
        super().__init__(manager, "last_rf_signal")

    @property
    def native_value(self):
        return dt_util.parse_datetime(self.manager.last_received_at) if self.manager.last_received_at else None


class RFMessagesReceived(RF433HubEntity, SensorEntity):
    """Expose aggregate bridge traffic statistics."""

    _attr_translation_key = "rf_messages_received"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager):
        super().__init__(manager, "rf_messages_received")

    @property
    def native_value(self):
        return self.manager.stats["received"]

    @property
    def extra_state_attributes(self):
        return {
            "accepted": self.manager.stats["accepted"],
            "unknown": self.manager.stats["unknown"],
            "duplicates": self.manager.stats["duplicates"],
            "malformed": self.manager.stats["malformed"],
        }


class ConfiguredSensors(RF433HubEntity, SensorEntity):
    """Expose the number of sensors assigned to this bridge."""

    _attr_translation_key = "configured_sensors"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager):
        super().__init__(manager, "configured_sensors")

    @property
    def native_value(self):
        return len(self.manager.sensors)


class UnknownRFSignals(RF433HubEntity, SensorEntity):
    """Expose the current bounded list of distinct unknown codes."""

    _attr_translation_key = "unknown_rf_signals"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager):
        super().__init__(manager, "unknown_rf_signals")

    @property
    def native_value(self):
        return len(self.manager.unknown)

    @property
    def extra_state_attributes(self):
        return {"total_unknown_messages": self.manager.stats["unknown"]}


class LastMessage(RF433Entity, SensorEntity):
    _attr_translation_key = "last_message"
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
    _attr_translation_key = "last_seen"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "last_seen")

    @property
    def native_value(self):
        return dt_util.parse_datetime(self.runtime.last_seen) if self.runtime.last_seen else None


class LastTamper(RF433Entity, SensorEntity):
    """Expose an explicit Never state until the first tamper event."""

    _attr_translation_key = "last_tamper"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "last_tamper")

    @property
    def native_value(self):
        return self.runtime.tamper_last_seen or "Never"
