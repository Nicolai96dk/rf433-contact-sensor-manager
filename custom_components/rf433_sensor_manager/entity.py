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


class RF433HubEntity(Entity):
    """Base entity attached to the RF bridge device."""

    _attr_has_entity_name = True

    def __init__(self, manager, suffix: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_hub_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=manager.entry.title,
            manufacturer="RF433 Sensor Manager",
            model="MQTT RF Bridge",
        )

    async def async_added_to_hass(self):
        self.manager.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.manager.listeners.discard(self.async_write_ha_state))
