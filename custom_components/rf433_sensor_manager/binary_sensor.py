"""Contact and latched battery entities."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import RF433Entity


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for runtime in entry.runtime_data.sensors.values():
        entities.append(Contact(entry.runtime_data, runtime))
        profile = entry.runtime_data.profiles[runtime.config["profile_id"]]
        if profile.get("battery_code") and runtime.config.get("battery_enabled", True):
            entities.append(Battery(entry.runtime_data, runtime))
    async_add_entities(entities)


class Contact(RF433Entity, BinarySensorEntity):
    _attr_name = "Contact"

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "contact")
        self._attr_device_class = (
            BinarySensorDeviceClass.DOOR
            if runtime.config.get("contact_type") == "door"
            else BinarySensorDeviceClass.WINDOW
        )

    @property
    def is_on(self):
        return self.runtime.contact


class Battery(RF433Entity, BinarySensorEntity):
    _attr_name = "Low battery"
    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "battery")

    @property
    def is_on(self):
        return self.runtime.battery_low
