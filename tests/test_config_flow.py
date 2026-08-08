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
    DOMAIN,
    FORMAT_JSON,
)
from custom_components.rf433_sensor_manager.preview import render_learning_preview, render_profile_preview


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_loads_with_tasmota_defaults(hass, hass_ws_client, monkeypatch) -> None:
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
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "protocol"
    assert result["preview"] == DOMAIN
    serialized = convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert [field["name"] for field in serialized] == ["name", "payload", "codes"]
    assert serialized[1]["type"] == "expandable"
    assert serialized[2]["type"] == "expandable"
    session = hass.data[DOMAIN]["preview_sessions"][result["flow_id"]]
    assert session.data["profile"]["open_code"] == "0A"
    callbacks[-1](
        SimpleNamespace(
            payload=json.dumps({"RfReceived": {"Data": "6F620A"}}),
            topic=DEFAULT_MQTT_TOPIC,
        )
    )
    assert session.data["latest"] == "6F620A"

    profile_input = result["data_schema"]({})
    assert profile_input["payload"] == {
        "payload_length": 6,
        "device_start": 0,
        "device_length": 4,
        "event_start": 4,
        "event_length": 2,
    }
    assert profile_input["codes"] == {
        "open_code": "0A",
        "closed_code": "0E",
        "tamper_code": "07",
        "battery_code": "06",
    }
    preview = render_profile_preview(session.data, profile_input)
    assert preview["state"] == "Identified 6F620A: Open"
    changed_profile = deepcopy(profile_input)
    changed_profile["codes"]["open_code"] = "FF"
    assert render_profile_preview(session.data, changed_profile)["state"] == "Identified 6F620A: Unknown event 0A"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/start_preview",
            "flow_id": result["flow_id"],
            "flow_type": "config_flow",
            "user_input": profile_input,
        }
    )
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["state"] == "Identified 6F620A: Open"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], profile_input)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "onboarding"
    assert result["menu_options"] == ["scan", "manual", "finish"]
    assert result.get("description_placeholders") is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_setup_scan_is_live_until_done_and_seeds_sensor(hass, hass_ws_client, monkeypatch) -> None:
    """Learning shows only the latest signal and seeds its state into the sensor."""
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
    profile_input = result["data_schema"]({})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], profile_input)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "scan"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    assert result["preview"] == DOMAIN
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/start_preview",
            "flow_id": result["flow_id"],
            "flow_type": "config_flow",
            "user_input": result["data_schema"]({}),
        }
    )
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["state"] == "Waiting for an RF signal…"
    scan_callback = callbacks[-1]
    scan_callback(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "ABCD07"}}), topic=DEFAULT_MQTT_TOPIC))
    assert (await client.receive_json())["event"]["state"] == "Identified ABCD07"
    scan_callback(SimpleNamespace(payload=json.dumps({"RfReceived": {"Data": "6F620A"}}), topic=DEFAULT_MQTT_TOPIC))
    pushed = (await client.receive_json())["event"]["state"]
    assert pushed == "Identified 6F620A"
    assert "ABCD" not in pushed
    session = hass.data[DOMAIN]["preview_sessions"][result["flow_id"]]
    assert session.data["latest"] == "6F620A"
    assert session.data["current_device_id"] == "6F62"
    preview = render_learning_preview(session.data, {})
    assert preview["state"] == "Identified 6F620A"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Office window", "contact_type": "window", "next_action": "add_another"},
    )
    assert result["type"] is FlowResultType.FORM
    serialized = convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert [field["name"] for field in serialized] == ["name", "contact_type", "next_action"]
    assert serialized[-1]["selector"]["select"]["mode"] == "list"
    assert session.data["latest"] is None
    assert session.data["current_device_id"] is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "", "contact_type": "door", "next_action": "done"},
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "onboarding_configured"
    assert result["description_placeholders"] == {"sensors": "1"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sensor = result["options"]["sensors"][0]
    assert sensor["rf_id"] == "6F62"
    assert "area_id" not in sensor
    assert sensor["contact_type"] == "window"
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
    """The options flow stays in one native dialog until Done is selected."""
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

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "learn_wait"
    assert result["preview"] == DOMAIN
    callback = next(iter(manager.scan_callbacks))
    callback("6F620E")
    session = hass.data[DOMAIN]["preview_sessions"][result["flow_id"]]
    assert session.data == {"latest": "6F620E", "current_device_id": "6F62"}
    assert render_learning_preview(session.data, {})["state"] == "Identified 6F620E"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Kitchen window", "contact_type": "window", "next_action": "done"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sensor = result["data"]["sensors"][0]
    assert sensor["initial_contact"] is False
    assert "area_id" not in sensor
    assert sensor["contact_type"] == "window"
    assert not manager.scan_callbacks
