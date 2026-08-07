"""Regression tests for import-blocking syntax errors."""

from pathlib import Path


def test_integration_modules_compile() -> None:
    """Every integration module must compile before Home Assistant imports it."""
    integration_dir = Path("custom_components/rf433_sensor_manager")

    for module in integration_dir.glob("*.py"):
        compile(module.read_text(encoding="utf-8"), str(module), "exec")
