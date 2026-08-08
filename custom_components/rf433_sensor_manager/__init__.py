"""RF433 Sensor Manager integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .manager import RF433Manager
from .panel import async_register_live_panel

type RF433ConfigEntry = ConfigEntry[RF433Manager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the hidden live setup panel."""
    await async_register_live_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RF433ConfigEntry) -> bool:
    manager = RF433Manager(hass, entry)
    try:
        await manager.async_start()
    except (HomeAssistantError, RuntimeError) as err:
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _remove_stale_registry_items(hass, entry, set(manager.sensors))
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="RF433 Sensor Manager",
        model="MQTT RF Bridge",
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _assign_sensor_areas(hass, entry, manager)
    return True


def _assign_sensor_areas(hass: HomeAssistant, entry: ConfigEntry, manager: RF433Manager) -> None:
    """Apply areas selected while learning sensors to their device entries."""
    registry = dr.async_get(hass)
    for sensor_id, runtime in manager.sensors.items():
        if not (area_id := runtime.config.get("area_id")):
            continue
        device = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}:{sensor_id}")})
        if device is not None and device.area_id != area_id:
            registry.async_update_device(device.id, area_id=area_id)


def _remove_stale_registry_items(hass: HomeAssistant, entry: ConfigEntry, sensor_ids: set[str]) -> None:
    """Remove entities and devices belonging to sensors deleted in the UI."""
    entity_registry = er.async_get(hass)
    valid_prefixes = tuple(f"{entry.entry_id}_{sensor_id}_" for sensor_id in sensor_ids)
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity_entry.unique_id.startswith(f"{entry.entry_id}_") and not entity_entry.unique_id.startswith(
            valid_prefixes
        ):
            entity_registry.async_remove(entity_entry.entity_id)

    device_registry = dr.async_get(hass)
    valid_identifiers = {(DOMAIN, f"{entry.entry_id}:{sensor_id}") for sensor_id in sensor_ids}
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        sensor_identifiers = {item for item in device_entry.identifiers if item[0] == DOMAIN and ":" in item[1]}
        if sensor_identifiers and sensor_identifiers.isdisjoint(valid_identifiers):
            device_registry.async_remove_device(device_entry.id)


async def async_unload_entry(hass: HomeAssistant, entry: RF433ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        return True
    return False


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entries."""
    if entry.version == 1:
        from copy import deepcopy

        from .const import CONF_PROFILES, DEFAULT_PROFILE, DEFAULT_PROFILE_ID

        options = dict(entry.options)
        profiles = list(options.get(CONF_PROFILES, []))
        if not any(profile["id"] == DEFAULT_PROFILE_ID for profile in profiles):
            profiles.insert(0, deepcopy(DEFAULT_PROFILE))
        options[CONF_PROFILES] = profiles
        hass.config_entries.async_update_entry(entry, options=options, version=2)
    if entry.version == 2:
        hass.config_entries.async_update_entry(entry, version=3)
    return entry.version == 3
