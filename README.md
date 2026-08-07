# RF433 Sensor Manager

A UI-configured Home Assistant custom integration that converts raw RF433 messages arriving through Home Assistant's MQTT integration into native devices and entities. MQTT is transport only; decoded state is never republished.

## Features

- One bridge and MQTT subscription per config entry, with multiple bridges supported
- JSON (simple dotted path) and plain payloads, MQTT wildcards, configurable duplicate suppression
- Built-in **DS-4 / Generic Contact Sensor** protocol (`AAAAEE`: four-character ID and two-character event)
- Reusable custom protocol profiles and exact RF-ID matching
- Manual, learn-mode, and recent-unknown-signal sensor creation
- Door/window contact, latched low battery, native tamper event, last message, last seen, and battery-reset button
- Persistent contact/battery/history state, bounded unknown history, diagnostics, and stable device/entity identifiers
- Entirely native Home Assistant config and options flows; no YAML or custom frontend

## Installation

### HACS custom repository

1. Add this GitHub repository to HACS as an **Integration**.
2. Install **RF433 Sensor Manager** and restart Home Assistant.
3. Ensure Home Assistant's MQTT integration is configured.
4. Go to **Settings → Devices & services → Add integration** and choose RF433 Sensor Manager.

For manual installation, copy `custom_components/rf433_sensor_manager` into the same path in your Home Assistant configuration directory and restart.

## Configuration

Each entry represents one RF bridge. Enter a name, MQTT subscription topic, payload format, and (for JSON) a dotted path such as `RfReceived.Data`. Open **Configure** afterward to add or learn sensors, manage custom profiles, inspect unknown signals, and change bridge settings.

The built-in profile recognizes six hexadecimal characters: the first four are the exact sensor ID and the final two map `0A` open, `0E` closed, `07` tamper, and `06` low battery. Low battery remains set until **Battery replaced** is pressed. Open/close messages never clear it.

Learn mode listens for 60 seconds. Because RF transmissions are unauthenticated, confirm that the displayed code belongs to the intended sensor. Unknown history is limited to 100 distinct raw codes.

## Development

Use Python 3.14.2 or newer, install the `test` dependency group, then run `pytest`, `ruff check .`, and `mypy custom_components/rf433_sensor_manager`. GitHub Actions also runs HACS and hassfest validation.

## Privacy and limitations

Diagnostics redact configured RF identifiers. RF433 signals can be replayed and should not be treated as a security boundary. A Home Assistant restart is not needed for options changes; the entry reloads automatically.

## License

MIT
