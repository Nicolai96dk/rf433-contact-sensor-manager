"""Runtime state and diagnostics regression tests."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rf433_contact_sensor_manager.button import (
    BatteryReplaced,
    MarkAllSensorsAsClosed,
    MarkAsClosed,
)
from custom_components.rf433_contact_sensor_manager.button import (
    async_setup_entry as async_setup_buttons,
)
from custom_components.rf433_contact_sensor_manager.const import (
    CONF_DUPLICATE_INTERVAL,
    CONF_JSON_PATH,
    CONF_NAME,
    CONF_PAYLOAD_FORMAT,
    CONF_PROFILES,
    CONF_SENSORS,
    CONF_TOPIC,
    DEFAULT_BRIDGE_NAME,
    DEFAULT_JSON_PATH,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PROFILE,
    DOMAIN,
    FORMAT_JSON,
)
from custom_components.rf433_contact_sensor_manager.diagnostics import async_get_config_entry_diagnostics
from custom_components.rf433_contact_sensor_manager.manager import RF433Manager
from custom_components.rf433_contact_sensor_manager.sensor import (
    ConfiguredSensors,
    LastRFSignal,
    LatestRFSignal,
    RFMessagesReceived,
    UnknownRFSignals,
)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_learned_state_and_all_device_codes_are_retained(hass, monkeypatch) -> None:
    """Known IDs retain unknown suffixes without losing learned contact state."""
    initial_history = {
        "6F620A": {
            "raw": "6F620A",
            "event_code": "0A",
            "event": "open",
            "recognized": True,
            "first_seen": "2026-08-07T18:00:00+00:00",
            "last_seen": "2026-08-07T18:00:00+00:00",
            "count": 1,
        }
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_BRIDGE_NAME,
        data={
            CONF_NAME: DEFAULT_BRIDGE_NAME,
            CONF_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_PAYLOAD_FORMAT: FORMAT_JSON,
            CONF_JSON_PATH: DEFAULT_JSON_PATH,
        },
        options={
            CONF_DUPLICATE_INTERVAL: 0,
            CONF_PROFILES: [deepcopy(DEFAULT_PROFILE)],
            CONF_SENSORS: [
                {
                    "id": "sensor-1",
                    "name": "Office window",
                    "rf_id": "6F62",
                    "profile_id": DEFAULT_PROFILE["id"],
                    "contact_type": "window",
                    "tamper_enabled": True,
                    "battery_enabled": True,
                    "initial_contact": True,
                    "initial_payload": "6F620A",
                    "initial_seen": "2026-08-07T18:00:00+00:00",
                    "initial_event": "open",
                    "initial_code_history": initial_history,
                }
            ],
        },
        version=1,
    )
    manager = RF433Manager(hass, entry)
    monkeypatch.setattr(manager, "_async_save", AsyncMock())
    entry.runtime_data = manager

    runtime = manager.sensors["sensor-1"]
    assert runtime.contact is True
    assert runtime.last_payload == "6F620A"

    manager._message(
        SimpleNamespace(
            payload=json.dumps({"RfReceived": {"Data": "6F6201"}}),
            topic=DEFAULT_MQTT_TOPIC,
        )
    )
    await hass.async_block_till_done()

    assert runtime.contact is True
    assert runtime.last_payload == "6F6201"
    assert runtime.last_event == "unknown"
    assert runtime.code_history["6F6201"]["event_code"] == "01"
    assert runtime.code_history["6F6201"]["recognized"] is False
    assert manager.last_received_payload == "6F6201"
    assert not manager.unknown

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    sensor_state = diagnostics["runtime"]["sensor_state"]["sensor-1"]
    assert sensor_state["tamper_last_seen"] == "never"
    assert {item["raw"] for item in sensor_state["code_history"]} == {"6F620A", "6F6201"}
    assert diagnostics["runtime"]["last_received"]["raw"] == "6F6201"

    manager._message(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "6F6206"}}), topic=DEFAULT_MQTT_TOPIC))
    manager._message(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "6F6207"}}), topic=DEFAULT_MQTT_TOPIC))
    manager._message(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "6F620E"}}), topic=DEFAULT_MQTT_TOPIC))
    manager._message(SimpleNamespace(payload="not-json", topic=DEFAULT_MQTT_TOPIC))
    await hass.async_block_till_done()
    assert runtime.battery_low is True
    assert runtime.tamper_last_seen is not None
    assert runtime.contact is False
    assert manager.stats["malformed"] == 1


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_hub_diagnostics_show_every_valid_rf_signal(hass, monkeypatch) -> None:
    """Bridge entities update for recognized and unrecognized RF traffic."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_BRIDGE_NAME,
        data={
            CONF_NAME: DEFAULT_BRIDGE_NAME,
            CONF_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_PAYLOAD_FORMAT: FORMAT_JSON,
            CONF_JSON_PATH: DEFAULT_JSON_PATH,
        },
        options={
            CONF_DUPLICATE_INTERVAL: 0,
            CONF_PROFILES: [deepcopy(DEFAULT_PROFILE)],
            CONF_SENSORS: [],
        },
        version=1,
    )
    manager = RF433Manager(hass, entry)
    monkeypatch.setattr(manager, "_async_save", AsyncMock())
    notifications = []
    manager.listeners.add(lambda: notifications.append(manager.last_received_payload))

    manager._message(
        SimpleNamespace(
            payload=json.dumps({"RfReceived": {"Data": "6F6201"}}),
            topic=DEFAULT_MQTT_TOPIC,
        )
    )
    await hass.async_block_till_done()

    latest = LatestRFSignal(manager)
    received = RFMessagesReceived(manager)
    assert latest.native_value == "6F6201"
    assert latest.extra_state_attributes["mqtt_topic"] == DEFAULT_MQTT_TOPIC
    assert LastRFSignal(manager).native_value is not None
    assert received.native_value == 1
    assert received.extra_state_attributes["unknown"] == 1
    assert ConfiguredSensors(manager).native_value == 0
    assert UnknownRFSignals(manager).native_value == 1
    assert notifications == ["6F6201"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_manual_close_buttons_update_one_or_all_sensors(hass, monkeypatch) -> None:
    """Configuration buttons correct state without replacing RF history."""
    sensors = [
        {
            "id": sensor_id,
            "name": name,
            "rf_id": rf_id,
            "profile_id": DEFAULT_PROFILE["id"],
            "contact_type": "window",
            "tamper_enabled": True,
            "battery_enabled": True,
            "initial_contact": True,
            "initial_payload": f"{rf_id}0A",
            "initial_event": "open",
        }
        for sensor_id, name, rf_id in (
            ("sensor-1", "Office window", "6F62"),
            ("sensor-2", "Kitchen window", "ABCD"),
        )
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_BRIDGE_NAME,
        data={
            CONF_NAME: DEFAULT_BRIDGE_NAME,
            CONF_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_PAYLOAD_FORMAT: FORMAT_JSON,
            CONF_JSON_PATH: DEFAULT_JSON_PATH,
        },
        options={
            CONF_DUPLICATE_INTERVAL: 0,
            CONF_PROFILES: [deepcopy(DEFAULT_PROFILE)],
            CONF_SENSORS: sensors,
        },
        version=1,
    )
    manager = RF433Manager(hass, entry)
    save = AsyncMock()
    monkeypatch.setattr(manager, "_async_save", save)
    entry.runtime_data = manager

    entities = []
    await async_setup_buttons(hass, entry, entities.extend)
    one_sensor_button = next(
        entity for entity in entities if isinstance(entity, MarkAsClosed) and entity.runtime.config["id"] == "sensor-1"
    )
    all_sensors_button = next(entity for entity in entities if isinstance(entity, MarkAllSensorsAsClosed))
    battery_button = next(
        entity
        for entity in entities
        if isinstance(entity, BatteryReplaced) and entity.runtime.config["id"] == "sensor-1"
    )

    await one_sensor_button.async_press()
    assert manager.sensors["sensor-1"].contact is False
    assert manager.sensors["sensor-1"].manual_closed_at is not None
    assert manager.sensors["sensor-1"].last_payload == "6F620A"
    assert manager.sensors["sensor-1"].last_event == "open"
    assert manager.sensors["sensor-2"].contact is True

    manager.sensors["sensor-1"].contact = True
    await all_sensors_button.async_press()
    assert all(runtime.contact is False for runtime in manager.sensors.values())
    assert all(runtime.manual_closed_at is not None for runtime in manager.sensors.values())
    manager.sensors["sensor-1"].battery_low = True
    await battery_button.async_press()
    assert manager.sensors["sensor-1"].battery_low is False
    assert "battery_reset_at" in manager.sensors["sensor-1"].config
    assert save.await_count == 3

    assert sum(isinstance(entity, BatteryReplaced) for entity in entities) == 2
    assert sum(isinstance(entity, MarkAsClosed) for entity in entities) == 2
    assert sum(isinstance(entity, MarkAllSensorsAsClosed) for entity in entities) == 1
