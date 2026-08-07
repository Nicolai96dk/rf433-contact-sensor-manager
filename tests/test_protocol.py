import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "rf433_sensor_manager"


def load_module(name: str):
    spec = spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


const = load_module("const")
protocol = load_module("protocol")
DEFAULT_PROFILE = const.DEFAULT_PROFILE
dotted_get = protocol.dotted_get
event_kind = protocol.event_kind
extract_payload = protocol.extract_payload
normalize_payload = protocol.normalize_payload
normalize_profile = protocol.normalize_profile
parse = protocol.parse
record_detection = protocol.record_detection


def test_normalize_and_parse():
    assert normalize_payload(" 6f620a ") == "6F620A"
    assert normalize_payload("not hex") is None
    assert parse("6F620A", DEFAULT_PROFILE) == ("6F62", "0A")
    assert event_kind("0A", DEFAULT_PROFILE) == "open"
    assert event_kind("0E", DEFAULT_PROFILE) == "closed"
    assert event_kind("07", DEFAULT_PROFILE) == "tamper"
    assert event_kind("06", DEFAULT_PROFILE) == "battery"
    assert parse("6F62", DEFAULT_PROFILE) is None


def test_dotted_get():
    assert dotted_get({"RfReceived": {"Data": "6F620A"}}, "RfReceived.Data") == "6F620A"


def test_tasmota_defaults_and_json_extraction():
    assert const.DEFAULT_BRIDGE_NAME == "Tasmota Sonoff RF-bridge"
    assert const.DEFAULT_MQTT_TOPIC == "tele/rf_bridge/RESULT"
    payload = '{"RfReceived":{"Data":"6f620e"}}'
    assert extract_payload(payload, "json", "RfReceived.Data") == "6F620E"
    assert extract_payload(" 6f620a ", "raw", "ignored") == "6F620A"


def test_profile_normalization_and_validation():
    profile = normalize_profile(
        {
            "name": " Contact ",
            "payload_length": "6",
            "device_start": "0",
            "device_length": "4",
            "event_start": "4",
            "event_length": "2",
            "open_code": "0a",
            "closed_code": "0e",
            "tamper_code": "07",
            "battery_code": "06",
        },
        "profile",
    )
    assert profile["name"] == "Contact"
    assert profile["open_code"] == "0A"
    assert parse("6F620A", profile) == ("6F62", "0A")

    with pytest.raises(protocol.ProfileValidationError):
        normalize_profile({**profile, "closed_code": "0A"}, "profile")


def test_scan_accumulates_devices_and_events():
    detections = {}
    assert record_detection(detections, "6F620A", DEFAULT_PROFILE)
    assert record_detection(detections, "6F620E", DEFAULT_PROFILE)
    assert record_detection(detections, "ABCD07", DEFAULT_PROFILE)
    assert not record_detection(detections, "FFFF", DEFAULT_PROFILE)
    assert set(detections) == {"6F62", "ABCD"}
    assert detections["6F62"]["count"] == 2
    assert detections["6F62"]["events"] == ["open", "closed"]
    assert detections["ABCD"]["events"] == ["tamper"]
