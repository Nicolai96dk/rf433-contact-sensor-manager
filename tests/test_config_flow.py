"""Config-flow regression tests."""

import pytest
from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.data_entry_flow import FlowResultType

from custom_components.rf433_sensor_manager.const import (
    CONF_NAME,
    CONF_TOPIC,
    DEFAULT_BRIDGE_NAME,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
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
