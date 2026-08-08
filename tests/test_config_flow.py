"""Config-flow regression tests."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry
from voluptuous_serialize import convert

from custom_components.rf433_sensor_manager.const import (
    CONF_JSON_PATH,
    CONF_NAME,
    CONF_PAYLOAD_FORMAT,
    CONF_TOPIC,
    DEFAULT_BRIDGE_NAME,
    DEFAULT_JSON_PATH,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_OPTIONS,
    DEFAULT_PROFILE,
    DOMAIN,
    FORMAT_JSON,
)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_loads_with_tasmota_defaults(hass, monkeypatch) -> None:
    """The guided setup opens a live profile preview with Tasmota defaults."""

    callbacks = []

    async def mqtt_ready(_hass) -> bool:
        return True

    async def mqtt_subscribe(_hass, _topic, callback):
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(mqtt, "async_wait_for_mqtt_client", mqtt_ready)
    monkeypatch.setattr(mqtt, "async_subscribe", mqtt_subscribe)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    defaults = result["data_schema"]({})
    assert defaults[CONF_NAME] == DEFAULT_BRIDGE_NAME
    assert defaults[CONF_TOPIC] == DEFAULT_MQTT_TOPIC

    result = await hass.config_entries.flow.async_configure(result["flow_id"], defaults)
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "protocol"
    session = hass.data[DOMAIN]["live_sessions"][result["flow_id"]]
    assert session.data["profile"]["open_code"] == "0A"
    callbacks[-1](
        SimpleNamespace(
            payload=json.dumps({"RfReceived": {"Data": "6F620A"}}),
            topic=DEFAULT_MQTT_TOPIC,
        )
    )
    assert session.data["latest"] == "6F620A"

    profile_input = {key: value for key, value in DEFAULT_PROFILE.items() if key not in {"id", "builtin"}}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"profile": profile_input})
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "onboarding"
    assert result["menu_options"] == ["scan", "manual", "finish"]
    assert result.get("description_placeholders") is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_setup_scan_is_live_until_done_and_seeds_sensor(hass, monkeypatch) -> None:
    """Discovery pushes new IDs and carries learned state into the sensor."""
    callbacks = []

    async def mqtt_ready(_hass) -> bool:
        return True

    async def mqtt_subscribe(_hass, _topic, callback):
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(mqtt, "async_wait_for_mqtt_client", mqtt_ready)
    monkeypatch.setattr(mqtt, "async_subscribe", mqtt_subscribe)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], result["data_schema"]({}))
    profile_input = {key: value for key, value in DEFAULT_PROFILE.items() if key not in {"id", "builtin"}}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"profile": profile_input})
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "scan"})

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "scan"
    scan_callback = callbacks[-1]
    scan_callback(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "6F620A"}}), topic=DEFAULT_MQTT_TOPIC))
    scan_callback(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "ABCD07"}}), topic=DEFAULT_MQTT_TOPIC))
    session = hass.data[DOMAIN]["live_sessions"][result["flow_id"]]
    assert [item["device_id"] for item in session.data["detections"]] == ["6F62", "ABCD"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"devices": [{"device_id": "6F62", "name": "Office window", "area_id": "office"}]},
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "onboarding_configured"
    assert result["description_placeholders"] == {"sensors": "1"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sensor = result["options"]["sensors"][0]
    assert sensor["rf_id"] == "6F62"
    assert sensor["area_id"] == "office"
    assert sensor["initial_contact"] is True
    assert sensor["initial_payload"] == "6F620A"
    assert sensor["initial_code_history"]["6F620A"]["event"] == "open"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_rejects_invalid_mqtt_topic(hass, monkeypatch) -> None:
    """An invalid topic is reported without invoking the MQTT client."""

    async def mqtt_should_not_be_checked(_hass) -> bool:
        pytest.fail("MQTT readiness must not be checked for an invalid topic")

    monkeypatch.setattr(mqtt, "async_wait_for_mqtt_client", mqtt_should_not_be_checked)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    user_input = result["data_schema"]({})
    user_input[CONF_TOPIC] = "tele/#/RESULT"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_TOPIC: "invalid_topic"}
    assert convert(result["data_schema"], custom_serializer=cv.custom_serializer)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_bridge_options_schema_is_serializable(hass) -> None:
    """The editable bridge topic form can be sent to the frontend."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_BRIDGE_NAME,
        data={
            CONF_NAME: DEFAULT_BRIDGE_NAME,
            CONF_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_PAYLOAD_FORMAT: FORMAT_JSON,
            CONF_JSON_PATH: DEFAULT_JSON_PATH,
        },
        options=deepcopy(DEFAULT_OPTIONS),
        version=3,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "bridge"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bridge"
    assert convert(result["data_schema"], custom_serializer=cv.custom_serializer)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_learning_pushes_devices_until_done(hass) -> None:
    """The options flow uses the manager callback until its live panel finishes."""
    manager = SimpleNamespace(scan_callbacks=set())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_BRIDGE_NAME,
        data={
            CONF_NAME: DEFAULT_BRIDGE_NAME,
            CONF_TOPIC: DEFAULT_MQTT_TOPIC,
            CONF_PAYLOAD_FORMAT: FORMAT_JSON,
            CONF_JSON_PATH: DEFAULT_JSON_PATH,
        },
        options=deepcopy(DEFAULT_OPTIONS),
        version=3,
    )
    entry.runtime_data = manager
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "learn"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], result["data_schema"]({}))

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    callback = next(iter(manager.scan_callbacks))
    callback("6F620E")
    session = hass.data[DOMAIN]["live_sessions"][result["flow_id"]]
    assert session.data["detections"][0]["device_id"] == "6F62"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"devices": [{"device_id": "6F62", "name": "Kitchen window", "area_id": "kitchen"}]},
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sensor = result["data"]["sensors"][0]
    assert sensor["initial_contact"] is False
    assert sensor["area_id"] == "kitchen"
    assert not manager.scan_callbacks
