"""Battery reset buttons."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import RF433Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            BatteryReplaced(entry.runtime_data, r)
            for r in entry.runtime_data.sensors.values()
            if entry.runtime_data.profiles[r.config["profile_id"]].get("battery_code")
            and r.config.get("battery_enabled", True)
        ]
    )


class BatteryReplaced(RF433Entity, ButtonEntity):
    _attr_name = "Battery replaced"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager, runtime):
        super().__init__(manager, runtime, "battery_replaced")

    async def async_press(self):
        await self.manager.async_reset_battery(self.runtime.config["id"])
