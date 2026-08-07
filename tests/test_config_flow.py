"""Config-flow regression tests."""

from copy import deepcopy

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


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_loads_with_tasmota_defaults(hass, monkeypatch) -> None:
    """The guided setup loads with bridge and protocol defaults."""

    async def mqtt_ready(_hass) -> bool:
        return True

    monkeypatch.setattr(mqtt, "async_wait_for_mqtt_client", mqtt_ready)
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
    profile_defaults = result["data_schema"]({})
    assert profile_defaults["payload_length"] == 6
    assert profile_defaults["device_length"] == 4
    assert profile_defaults["event_length"] == 2
    assert profile_defaults["open_code"] == "0A"
    assert profile_defaults["closed_code"] == "0E"
    assert profile_defaults["tamper_code"] == "07"
    assert profile_defaults["battery_code"] == "06"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], profile_defaults)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "onboarding"
    assert result["menu_options"] == ["scan", "manual", "finish"]


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
        version=2,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "bridge"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bridge"
    assert convert(result["data_schema"], custom_serializer=cv.custom_serializer)
