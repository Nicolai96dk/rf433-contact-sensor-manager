import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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
normalize_payload = protocol.normalize_payload
parse = protocol.parse


def test_normalize_and_parse():
    assert normalize_payload(" 6f620a ") == "6F620A"
    assert normalize_payload("not hex") is None
    assert parse("6F620A", DEFAULT_PROFILE) == ("6F62", "0A")
    assert event_kind("0A", DEFAULT_PROFILE) == "open"
    assert event_kind("0E", DEFAULT_PROFILE) == "closed"
    assert parse("6F62", DEFAULT_PROFILE) is None


def test_dotted_get():
    assert dotted_get({"RfReceived": {"Data": "6F620A"}}, "RfReceived.Data") == "6F620A"
