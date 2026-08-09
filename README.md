# RF433 Contact Sensor Manager

<p align="center">
  <img src="https://raw.githubusercontent.com/Nicolai96dk/rf433-contact-sensor-manager/main/custom_components/rf433_contact_sensor_manager/brand/logo@2x.png" alt="RF433 Contact Sensor Manager" width="560">
</p>

RF433 Contact Sensor Manager turns raw 433 MHz door and window contact-sensor messages received through Home Assistant's MQTT integration into native Home Assistant devices and entities. MQTT is used only as transport from the RF bridge; decoded states are never republished.

## Prerequisites

Before installing this integration, you need:

- Home Assistant 2026.7.0 or newer
- Home Assistant's official MQTT integration already configured, connected, and receiving messages
- An external 433 MHz RF bridge already configured to publish received RF codes to MQTT
- Door or window contact sensors whose payload layout and event codes are known or can be identified

The supplied defaults are designed for Tasmota on a **SONOFF RF BridgeR2 433 MHz**. They use MQTT topic `tele/rf_bridge/RESULT`, JSON path `RfReceived.Data`, and Tasmota messages such as:

```json
{
  "RfReceived": {
    "Data": "6F620A"
  }
}
```

The RF bridge, Tasmota, MQTT broker, and Home Assistant MQTT integration must already be working. This integration does not flash, configure, or control the RF bridge.

## Features

- One MQTT RF bridge per config entry, with multiple bridges supported
- Guided setup entirely in Home Assistant's native dialog; no YAML or custom frontend
- Built-in **DS-4 / Generic Contact Sensor** protocol plus reusable custom profiles
- Live protocol preview that immediately interprets the newest matching RF code
- Continuous learning mode that shows the latest device immediately and identifies already configured devices
- Manual creation and creation from recent unknown signals
- Native door/window contact, latched low-battery, tamper event, last-message, and last-seen entities
- Per-sensor **Mark as closed** and bridge-wide **Mark all sensors as closed** corrections for missed one-way RF messages
- Battery-replacement reset button for profiles with a low-battery code
- Bridge-level latest signal, last signal time, traffic statistics, configured-sensor count, and unknown-signal count
- Persistent contact, battery, tamper, and per-device code history across Home Assistant restarts
- Exact RF device-ID matching, configurable duplicate suppression, JSON/raw payload support, and MQTT wildcards
- Diagnostics containing up to 100 distinct full codes for each configured device and 100 recent unknown codes

## Installation

### HACS custom repository

1. Add this GitHub repository to HACS as an **Integration**.
2. Install **RF433 Contact Sensor Manager** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Select **RF433 Contact Sensor Manager**.

For manual installation, copy `custom_components/rf433_contact_sensor_manager` into `custom_components` in your Home Assistant configuration directory, then restart Home Assistant.

### Upgrading from the old domain

Version 0.5.0 changes the integration domain from `rf433_sensor_manager` to `rf433_contact_sensor_manager`. Because the old name was not in public use, no automatic migration is included. Remove the old test integration and its `custom_components/rf433_sensor_manager` directory before installing 0.5.0, then configure the integration again.

## Configuration

Each config entry represents one RF bridge and one MQTT subscription. Initial setup starts with bridge name **Tasmota Sonoff RF-bridge**, topic `tele/rf_bridge/RESULT`, JSON payload format, path `RfReceived.Data`, and one second of duplicate suppression. Every value is editable.

Setup next opens the default protocol profile. Its **Payload** and **Codes** sections are collapsed initially, and live scanning remains active while you edit. Trigger a physical contact sensor to compare the newest code with the current profile without leaving the dialog.

The built-in profile expects six hexadecimal characters in the form `AAAAEE`:

- `AAAA`: four-character RF device ID
- `0A`: open
- `0E`: closed
- `07`: tamper
- `06`: low battery

These codes are common for the targeted generic contact sensors but are not a universal RF433 standard. Adjust the payload positions and event codes when your hardware uses another format.

After the profile is confirmed, add the first sensors through live learning or manual entry. Learning mode shows only the latest received RF code because the entered name and contact type apply to that code. Window is the default type. Choose **Add another sensor** to save and continue scanning, or **Done** to save and finish. If the current device ID is already configured, the preview says so immediately. Home Assistant areas can be assigned from the created device afterward.

The same bridge, learning, manual sensor, sensor editing, protocol profile, unknown signal, and information tools remain available later under the integration's **Configure** menu.

## State behavior

Contact sensors usually transmit in one direction only. A missed close packet can therefore leave Home Assistant showing a stale open state. **Mark as closed** corrects one sensor, while **Mark all sensors as closed** corrects every sensor attached to the bridge. These buttons change only Home Assistant's stored state; they do not transmit an RF command or alter the latest received RF message and code history. The next recognized RF open or close event takes precedence normally.

Low battery is latched when its configured event code is received. It remains on until **Battery replaced** is pressed; ordinary open and close messages do not clear it. A learned contact starts with the open or closed state of the newest signal seen during setup. Tamper initially reports **Never** until a tamper signal arrives.

The hub's latest RF signal includes every valid RF code received on the configured topic, whether or not it matches a configured device. For a known device ID, diagnostics retain every distinct suffix as well, including unrecognized messages such as `6F6201`.

## Troubleshooting

- Confirm the MQTT integration can see messages on the configured topic before opening learning mode.
- Check the exact topic, payload format, and JSON path when the live preview remains empty.
- Trigger the sensor physically; most battery-powered contact sensors do not transmit continuously.
- If a code appears but is not interpreted correctly, compare its length, device-ID position, event position, and event suffix with the protocol profile.
- If HACS still contains the pre-0.5.0 test version, remove the old domain directory and restart Home Assistant before reinstalling.

## Security and limitations

- Common 433 MHz contact-sensor messages are unencrypted, unauthenticated, replayable, and susceptible to interference or jamming. Do not use their state as the sole security boundary for an alarm or access-control system.
- Learning mode trusts the newest compatible RF signal. Trigger only the intended device and confirm its ID before saving.
- The integration is receive-only. It cannot request a fresh state from a sensor or guarantee that every transmission was received.
- Diagnostics redact configured RF IDs in configuration data, while retaining full runtime codes intentionally so unexpected event suffixes can be investigated. Review diagnostics before sharing them.
- The default profile is a starting point, not a promise of compatibility with every RF433 sensor or bridge.

## Development

Use Python 3.14.2 or newer, install the `test` dependency group, then run `pytest`, `ruff format --check .`, `ruff check .`, and `mypy custom_components/rf433_contact_sensor_manager`. GitHub Actions also runs HACS and hassfest validation.

## Removal

Delete every RF433 Contact Sensor Manager entry from **Settings → Devices & services**, remove the integration in HACS (or delete `custom_components/rf433_contact_sensor_manager` for a manual install), and restart Home Assistant.

## License

MIT
