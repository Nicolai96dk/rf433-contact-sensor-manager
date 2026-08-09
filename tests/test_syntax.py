"""Regression tests for import-blocking syntax errors."""

import json
import struct
from pathlib import Path

INTEGRATION_DIR = Path("custom_components/rf433_contact_sensor_manager")


def test_integration_modules_compile() -> None:
    """Every integration module must compile before Home Assistant imports it."""
    for module in INTEGRATION_DIR.glob("*.py"):
        compile(module.read_text(encoding="utf-8"), str(module), "exec")


def test_manifest_domain_and_custom_translation_layout() -> None:
    """The renamed custom integration has one matching domain and flat English translations."""
    manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
    translations = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == INTEGRATION_DIR.name == "rf433_contact_sensor_manager"
    assert manifest["name"] == translations["title"] == "RF433 Contact Sensor Manager"
    assert manifest["version"] == "0.5.0"
    assert not (INTEGRATION_DIR / "strings.json").exists()


def test_brand_assets_cover_light_dark_and_high_density() -> None:
    """Every supported brand variant is transparent and has the required dimensions."""
    brand = INTEGRATION_DIR / "brand"
    expected = {
        "icon.png": (256, 256),
        "dark_icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "dark_icon@2x.png": (512, 512),
        "logo.png": (350, 130),
        "dark_logo.png": (350, 130),
        "logo@2x.png": (700, 260),
        "dark_logo@2x.png": (700, 260),
    }
    for filename, dimensions in expected.items():
        header = (brand / filename).read_bytes()[:26]
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", header[16:24]) == dimensions
        assert header[25] == 6  # PNG true-colour with alpha
