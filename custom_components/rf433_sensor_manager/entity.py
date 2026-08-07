"""Shared RF433 entity base."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class RF433Entity(Entity):
    _attr_has_entity_name = True

    def __init__(self, manager, runtime, suffix: str) -> None:
        self.manager, self.runtime = manager, runtime
        sid = runtime.config["id"]
        self._attr_unique_id = f"{manager.entry.entry_id}_{sid}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{manager.entry.entry_id}:{sid}")},
            name=runtime.config["name"],
            manufacturer="Generic",
            model=manager.profiles[runtime.config["profile_id"]]["name"],
            via_device=(DOMAIN, manager.entry.entry_id),
        )

    async def async_added_to_hass(self):
        self.runtime.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.runtime.listeners.discard(self.async_write_ha_state))
