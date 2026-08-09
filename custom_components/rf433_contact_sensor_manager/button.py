"""Configuration buttons for contact sensors and their RF bridge."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import RF433Entity, RF433HubEntity


async def async_setup_entry(hass, entry, async_add_entities):
    manager = entry.runtime_data
    entities: list[ButtonEntity] = [MarkAllSensorsAsClosed(manager)]
    for runtime in manager.sensors.values():
        if manager.profiles[runtime.config["profile_id"]].get("battery_code") and runtime.config.get(
            "battery_enabled", True
        ):
            entities.append(BatteryReplaced(manager, runtime))
        entities.append(MarkAsClosed(manager, runtime))
    async_add_entities(entities)


class BatteryReplaced(RF433Entity, ButtonEntity):
    _attr_translation_key = "battery_replaced"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "battery_replaced")

    async def async_press(self):
        await self.manager.async_reset_battery(self.runtime.config["id"])


class MarkAsClosed(RF433Entity, ButtonEntity):
    """Allow a user to correct a stale one-way contact state."""

    _attr_translation_key = "mark_as_closed"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "mark_as_closed")

    async def async_press(self):
        await self.manager.async_mark_closed(self.runtime.config["id"])


class MarkAllSensorsAsClosed(RF433HubEntity, ButtonEntity):
    """Allow a user to correct every stale contact state at once."""

    _attr_translation_key = "mark_all_sensors_as_closed"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager):
        super().__init__(manager, "mark_all_sensors_as_closed")

    async def async_press(self):
        await self.manager.async_mark_all_closed()
