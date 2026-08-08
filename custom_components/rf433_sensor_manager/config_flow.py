"""UI configuration and management flows."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA_ID,
    CONF_DUPLICATE_INTERVAL,
    CONF_JSON_PATH,
    CONF_NAME,
    CONF_PAYLOAD_FORMAT,
    CONF_PROFILES,
    CONF_SENSORS,
    CONF_TOPIC,
    DEFAULT_BRIDGE_NAME,
    DEFAULT_JSON_PATH,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_OPTIONS,
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_ID,
    DOMAIN,
    FORMAT_JSON,
    FORMAT_RAW,
)
from .preview import (
    PreviewSession,
    async_register_preview,
    register_preview_session,
    remove_preview_session,
    render_learning_preview,
    render_profile_preview,
)
from .protocol import (
    ProfileValidationError,
    extract_payload,
    normalize_payload,
    normalize_profile,
    parse,
    record_detection,
)

FORMAT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=[FORMAT_JSON, FORMAT_RAW], translation_key="payload_format")
)
TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=["door", "window"], translation_key="contact_type")
)
AREA_SELECTOR = selector.AreaSelector()
LEARNING_ACTION_ADD = "add_another"
LEARNING_ACTION_DONE = "done"
LEARNING_ACTION_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[LEARNING_ACTION_ADD, LEARNING_ACTION_DONE],
        mode=selector.SelectSelectorMode.LIST,
        translation_key="learning_action",
    )
)


def _flatten_protocol_profile(values: dict[str, Any]) -> dict[str, Any]:
    """Flatten the sectioned initial protocol form for profile parsing."""
    result = {key: value for key, value in values.items() if key not in {"payload", "codes"}}
    for section_name in ("payload", "codes"):
        section_values = values.get(section_name)
        if isinstance(section_values, dict):
            result.update(section_values)
    return result


def _protocol_profile_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the sectioned initial protocol profile schema."""
    values = _flatten_protocol_profile(values)
    return vol.Schema(
        {
            vol.Required("name", default=values.get("name", DEFAULT_PROFILE["name"])): str,
            vol.Required("payload", default={}): data_entry_flow.section(
                vol.Schema(
                    {
                        vol.Optional("payload_length", default=values.get("payload_length") or 0): vol.All(
                            vol.Coerce(int), vol.Range(min=0)
                        ),
                        vol.Required("device_start", default=values.get("device_start", 0)): vol.Coerce(int),
                        vol.Required("device_length", default=values.get("device_length", 4)): vol.Coerce(int),
                        vol.Required("event_start", default=values.get("event_start", 4)): vol.Coerce(int),
                        vol.Required("event_length", default=values.get("event_length", 2)): vol.Coerce(int),
                    }
                ),
                {"collapsed": False},
            ),
            vol.Required("codes", default={}): data_entry_flow.section(
                vol.Schema(
                    {
                        vol.Required("open_code", default=values.get("open_code", "0A")): str,
                        vol.Required("closed_code", default=values.get("closed_code", "0E")): str,
                        vol.Optional("tamper_code", default=values.get("tamper_code") or ""): str,
                        vol.Optional("battery_code", default=values.get("battery_code") or ""): str,
                    }
                ),
                {"collapsed": False},
            ),
        }
    )


def _profile_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the editable protocol profile schema with suggested defaults."""
    return vol.Schema(
        {
            vol.Required("name", default=values.get("name", DEFAULT_PROFILE["name"])): str,
            vol.Optional("payload_length", default=values.get("payload_length") or 0): vol.All(
                vol.Coerce(int), vol.Range(min=0)
            ),
            vol.Required("device_start", default=values.get("device_start", 0)): vol.Coerce(int),
            vol.Required("device_length", default=values.get("device_length", 4)): vol.Coerce(int),
            vol.Required("event_start", default=values.get("event_start", 4)): vol.Coerce(int),
            vol.Required("event_length", default=values.get("event_length", 2)): vol.Coerce(int),
            vol.Required("open_code", default=values.get("open_code", "0A")): str,
            vol.Required("closed_code", default=values.get("closed_code", "0E")): str,
            vol.Optional("tamper_code", default=values.get("tamper_code") or ""): str,
            vol.Optional("battery_code", default=values.get("battery_code") or ""): str,
        }
    )


def _learned_sensor(detection: dict[str, Any], profile_id: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Build a sensor configuration seeded from its learned RF state."""
    name = str(user_input.get("name") or "").strip() or f"RF sensor {detection['device_id']}"
    item: dict[str, Any] = {
        "name": name,
        "rf_id": detection["device_id"],
        "profile_id": profile_id,
        "contact_type": user_input.get("contact_type", "door"),
        "tamper_enabled": True,
        "battery_enabled": True,
        "initial_payload": detection["last_raw"],
        "initial_seen": detection.get("last_seen"),
        "initial_event": detection.get("last_event"),
        "initial_code_history": deepcopy(detection.get("codes", {})),
    }
    if detection.get("last_event") == "open":
        item["initial_contact"] = True
    elif detection.get("last_event") == "closed":
        item["initial_contact"] = False
    return item


def _select_option(value: str, label: str) -> selector.SelectOptionDict:
    """Build a typed selector option."""
    return {"value": value, "label": label}


def _learning_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the native form for the device in the latest RF signal."""
    return vol.Schema(
        {
            vol.Optional("name", default=values.get("name", "")): str,
            vol.Required("contact_type", default=values.get("contact_type", "door")): TYPE_SELECTOR,
            vol.Required(
                "next_action", default=values.get("next_action", LEARNING_ACTION_ADD)
            ): LEARNING_ACTION_SELECTOR,
        }
    )


class RF433ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one MQTT RF bridge and its first protocol profile."""

    VERSION = 3

    def __init__(self) -> None:
        self._entry_data: dict[str, Any] = {}
        self._pending_options: dict[str, Any] = deepcopy(DEFAULT_OPTIONS)
        self._scan_profile: dict[str, Any] = deepcopy(DEFAULT_PROFILE)
        self._scan_detections: dict[str, dict[str, Any]] = {}
        self._scan_current_id: str | None = None
        self._scan_session: PreviewSession | None = None
        self._profile_unsub: Callable[[], None] | None = None
        self._scan_unsub: Callable[[], None] | None = None

    @staticmethod
    async def async_setup_preview(hass) -> None:
        """Set up Home Assistant's native config-flow preview API."""
        await async_register_preview(hass)

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Collect the bridge source settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                topic = mqtt.valid_subscribe_topic(user_input[CONF_TOPIC])
            except vol.Invalid:
                errors[CONF_TOPIC] = "invalid_topic"
            else:
                if not await mqtt.async_wait_for_mqtt_client(self.hass):
                    errors["base"] = "mqtt_unavailable"
                else:
                    self._entry_data = dict(user_input)
                    self._entry_data[CONF_TOPIC] = topic
                    self._entry_data.setdefault(CONF_JSON_PATH, DEFAULT_JSON_PATH)
                    return await self.async_step_protocol()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_BRIDGE_NAME): str,
                vol.Required(CONF_TOPIC, default=DEFAULT_MQTT_TOPIC): str,
                vol.Required(CONF_PAYLOAD_FORMAT, default=FORMAT_JSON): FORMAT_SELECTOR,
                vol.Optional(CONF_JSON_PATH, default=DEFAULT_JSON_PATH): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_protocol(self, user_input=None) -> ConfigFlowResult:
        """Configure the initial profile with an in-dialog live RF preview."""
        errors: dict[str, str] = {}
        if user_input is not None:
            profile_values = _flatten_protocol_profile(user_input)
            try:
                self._scan_profile = normalize_profile(profile_values, DEFAULT_PROFILE_ID, builtin=True)
            except ProfileValidationError as err:
                errors[err.field if err.field == "name" else "base"] = "invalid_profile"
            else:
                self._stop_profile_reader()
                self._pending_options[CONF_PROFILES] = [deepcopy(self._scan_profile)]
                return await self.async_step_onboarding()
        if self._profile_unsub is None:
            try:
                await self._async_start_profile_reader()
            except HomeAssistantError:
                return self.async_abort(reason="mqtt_unavailable")
        return self.async_show_form(
            step_id="protocol",
            data_schema=_protocol_profile_schema(user_input or self._scan_profile),
            errors=errors,
            last_step=False,
            preview=DOMAIN,
        )

    async def _async_start_profile_reader(self) -> None:
        """Push raw RF samples into the native profile preview."""
        session = PreviewSession(
            data={"profile": deepcopy(DEFAULT_PROFILE), "latest": None},
            renderer=render_profile_preview,
        )
        register_preview_session(self.hass, self.flow_id, session)

        @callback
        def received(message) -> None:
            try:
                payload = extract_payload(
                    message.payload,
                    self._entry_data[CONF_PAYLOAD_FORMAT],
                    self._entry_data.get(CONF_JSON_PATH, DEFAULT_JSON_PATH),
                )
            except (ValueError, TypeError, KeyError):
                return
            if payload is not None:
                session.data["latest"] = payload
                session.publish()

        self._profile_unsub = await mqtt.async_subscribe(self.hass, self._entry_data[CONF_TOPIC], received)

    @callback
    def _stop_profile_reader(self) -> None:
        if self._profile_unsub is not None:
            self._profile_unsub()
            self._profile_unsub = None
        remove_preview_session(self.hass, self.flow_id)

    async def async_step_onboarding(self, user_input=None) -> ConfigFlowResult:
        """Offer discovery, manual creation, or finishing setup."""
        sensor_count = len(self._pending_options[CONF_SENSORS])
        return self.async_show_menu(
            step_id="onboarding_configured" if sensor_count else "onboarding",
            menu_options=["scan", "manual", "finish"],
            description_placeholders={"sensors": str(sensor_count)} if sensor_count else None,
        )

    async def async_step_onboarding_configured(self, user_input=None) -> ConfigFlowResult:
        """Return to onboarding after at least one sensor was configured."""
        return await self.async_step_onboarding(user_input)

    async def _async_start_setup_scan(self) -> None:
        """Start an open-ended scan rendered inside the setup dialog."""
        self._scan_detections = {}
        self._scan_current_id = None

        session = PreviewSession(
            data={"latest": None, "current_device_id": None},
            renderer=render_learning_preview,
        )
        self._scan_session = session
        register_preview_session(self.hass, self.flow_id, session)

        @callback
        def received(message) -> None:
            try:
                payload = extract_payload(
                    message.payload,
                    self._entry_data[CONF_PAYLOAD_FORMAT],
                    self._entry_data.get(CONF_JSON_PATH, DEFAULT_JSON_PATH),
                )
            except (ValueError, TypeError, KeyError):
                return
            if payload is not None:
                parsed = parse(payload, self._scan_profile)
                if parsed is None:
                    return
                device_id = parsed[0]
                if device_id != self._scan_current_id:
                    self._scan_detections = {}
                if record_detection(
                    self._scan_detections,
                    payload,
                    self._scan_profile,
                    dt_util.utcnow().isoformat(),
                ):
                    self._scan_current_id = device_id
                    session.data["latest"] = payload
                    session.data["current_device_id"] = self._scan_current_id
                    session.publish()

        self._scan_unsub = await mqtt.async_subscribe(self.hass, self._entry_data[CONF_TOPIC], received)

    @callback
    def _stop_setup_scan(self) -> None:
        if self._scan_unsub is not None:
            self._scan_unsub()
            self._scan_unsub = None
        self._scan_session = None
        self._scan_current_id = None
        remove_preview_session(self.hass, self.flow_id)

    def _clear_setup_detection(self) -> None:
        """Wait for a fresh RF signal before another sensor is saved."""
        self._scan_detections = {}
        self._scan_current_id = None
        if self._scan_session is not None:
            self._scan_session.data["latest"] = None
            self._scan_session.data["current_device_id"] = None
            self._scan_session.publish()

    async def async_step_scan(self, user_input=None) -> ConfigFlowResult:
        """Adopt sensors continuously inside the native setup dialog."""
        errors: dict[str, str] = {}
        if user_input is not None:
            next_action = user_input.get("next_action", LEARNING_ACTION_ADD)
            detection = self._scan_detections.get(self._scan_current_id or "")
            if detection is None and next_action == LEARNING_ACTION_DONE:
                self._stop_setup_scan()
                return await self.async_step_onboarding()
            if detection is None:
                errors["base"] = "no_signal"
            elif any(sensor["rf_id"] == detection["device_id"] for sensor in self._pending_options[CONF_SENSORS]):
                if next_action == LEARNING_ACTION_DONE:
                    self._stop_setup_scan()
                    return await self.async_step_onboarding()
                errors["base"] = "already_configured"
            else:
                self._add_pending_sensor(_learned_sensor(detection, self._scan_profile["id"], user_input))
                if next_action == LEARNING_ACTION_DONE:
                    self._stop_setup_scan()
                    return await self.async_step_onboarding()
                self._clear_setup_detection()
                user_input = None
        if self._scan_unsub is None:
            try:
                await self._async_start_setup_scan()
            except HomeAssistantError:
                self._stop_setup_scan()
                return await self.async_step_scan_error()
        return self.async_show_form(
            step_id="scan",
            data_schema=_learning_schema(user_input or {}),
            errors=errors,
            last_step=False,
            preview=DOMAIN,
        )

    async def async_step_scan_error(self, user_input=None) -> ConfigFlowResult:
        """Offer recovery when MQTT was unavailable during scanning."""
        return self.async_show_menu(step_id="scan_error", menu_options=["scan_retry", "manual", "finish"])

    async def async_step_scan_retry(self, user_input=None) -> ConfigFlowResult:
        """Retry an unavailable setup scan."""
        return await self.async_step_scan()

    async def async_step_manual(self, user_input=None) -> ConfigFlowResult:
        """Add a sensor manually during initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            rf_id = normalize_payload(user_input["rf_id"])
            if rf_id is None:
                errors["rf_id"] = "invalid_hex"
            elif len(rf_id) != self._scan_profile["device_length"]:
                errors["rf_id"] = "invalid_rf_id_length"
            elif any(sensor["rf_id"] == rf_id for sensor in self._pending_options[CONF_SENSORS]):
                errors["rf_id"] = "already_configured"
            else:
                self._add_pending_sensor(
                    {
                        **user_input,
                        "rf_id": rf_id,
                        "profile_id": self._scan_profile["id"],
                    }
                )
                return await self.async_step_onboarding()
        values = user_input or {}
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=values.get("name", "")): str,
                    vol.Required("rf_id", default=values.get("rf_id", "")): str,
                    vol.Required("contact_type", default=values.get("contact_type", "door")): TYPE_SELECTOR,
                    vol.Optional(
                        CONF_AREA_ID,
                        description={"suggested_value": values.get(CONF_AREA_ID)},
                    ): AREA_SELECTOR,
                    vol.Required("tamper_enabled", default=values.get("tamper_enabled", True)): bool,
                    vol.Required("battery_enabled", default=values.get("battery_enabled", True)): bool,
                }
            ),
            errors=errors,
        )

    def _add_pending_sensor(self, sensor: dict[str, Any]) -> None:
        """Append one stable sensor configuration to the pending entry."""
        self._pending_options[CONF_SENSORS].append({**sensor, "id": str(uuid4())})

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        """Create the fully configured bridge entry."""
        self._stop_profile_reader()
        self._stop_setup_scan()
        await self.async_set_unique_id(str(uuid4()))
        return self.async_create_entry(
            title=self._entry_data[CONF_NAME],
            data=self._entry_data,
            options=self._pending_options,
        )

    @callback
    def async_remove(self) -> None:
        """Release live MQTT resources if the user closes the flow."""
        self._stop_profile_reader()
        self._stop_setup_scan()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RF433OptionsFlow()


class RF433OptionsFlow(config_entries.OptionsFlow):
    """Native menu-based configuration."""

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self._selected: str | None = None
        self._learned: str | None = None
        self._learn_raw: str | None = None
        self._learn_event: str | None = None
        self._learn_profile: str | None = None
        self._scan_detections: dict[str, dict[str, Any]] = {}
        self._scan_current_id: str | None = None
        self._learn_session: PreviewSession | None = None
        self._learn_callback: Callable[[str], None] | None = None

    @staticmethod
    async def async_setup_preview(hass) -> None:
        """Set up Home Assistant's native options-flow preview API."""
        await async_register_preview(hass)

    async def async_step_init(self, user_input=None):
        self.options = deepcopy({**DEFAULT_OPTIONS, **self.config_entry.options})
        return self.async_show_menu(
            step_id="init",
            menu_options=["bridge", "add_sensor", "learn", "sensors", "profiles", "unknown", "information"],
        )

    async def async_step_bridge(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                topic = mqtt.valid_subscribe_topic(user_input[CONF_TOPIC])
            except vol.Invalid:
                errors[CONF_TOPIC] = "invalid_topic"
            else:
                data = dict(self.config_entry.data)
                data.update(
                    {
                        CONF_TOPIC: topic,
                        CONF_PAYLOAD_FORMAT: user_input[CONF_PAYLOAD_FORMAT],
                        CONF_JSON_PATH: user_input[CONF_JSON_PATH],
                    }
                )
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                self.options[CONF_DUPLICATE_INTERVAL] = user_input[CONF_DUPLICATE_INTERVAL]
                return self.async_create_entry(data=self.options)
        values = {
            **self.config_entry.data,
            CONF_DUPLICATE_INTERVAL: self.options[CONF_DUPLICATE_INTERVAL],
            **(user_input or {}),
        }
        return self.async_show_form(
            step_id="bridge",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC, default=values[CONF_TOPIC]): str,
                    vol.Required(CONF_PAYLOAD_FORMAT, default=values[CONF_PAYLOAD_FORMAT]): FORMAT_SELECTOR,
                    vol.Optional(CONF_JSON_PATH, default=values.get(CONF_JSON_PATH, DEFAULT_JSON_PATH)): str,
                    vol.Required(
                        CONF_DUPLICATE_INTERVAL,
                        default=values[CONF_DUPLICATE_INTERVAL],
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=60)),
                }
            ),
            errors=errors,
        )

    def _profiles(self) -> list[dict[str, Any]]:
        profiles = {DEFAULT_PROFILE_ID: deepcopy(DEFAULT_PROFILE)}
        profiles.update({profile["id"]: profile for profile in self.options[CONF_PROFILES]})
        return list(profiles.values())

    def _profile(self, profile_id: str) -> dict[str, Any]:
        return next(profile for profile in self._profiles() if profile["id"] == profile_id)

    def _profile_selector(self):
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[_select_option(profile["id"], profile["name"]) for profile in self._profiles()]
            )
        )

    async def async_step_add_sensor(self, user_input=None):
        return await self._sensor_form("add_sensor", user_input)

    async def _sensor_form(self, step, user_input, initial=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            rf_id = normalize_payload(user_input["rf_id"])
            profile = self._profile(user_input["profile_id"])
            if not rf_id:
                errors["rf_id"] = "invalid_hex"
            elif len(rf_id) != profile["device_length"]:
                errors["rf_id"] = "invalid_rf_id_length"
            elif any(
                sensor["rf_id"] == rf_id
                and sensor["profile_id"] == user_input["profile_id"]
                and sensor.get("id") != (initial or {}).get("id")
                for sensor in self.options[CONF_SENSORS]
            ):
                errors["rf_id"] = "already_configured"
            else:
                item = {
                    **(initial or {}),
                    **user_input,
                    "rf_id": rf_id,
                    "id": (initial or {}).get("id", str(uuid4())),
                }
                if initial:
                    self.options[CONF_SENSORS] = [
                        item if sensor["id"] == item["id"] else sensor for sensor in self.options[CONF_SENSORS]
                    ]
                else:
                    self.options[CONF_SENSORS].append(item)
                return self.async_create_entry(data=self.options)
        values = user_input or initial or {}
        schema = vol.Schema(
            {
                vol.Required("name", default=values.get("name", "")): str,
                vol.Required("rf_id", default=values.get("rf_id", self._learned or "")): str,
                vol.Required(
                    "profile_id",
                    default=values.get("profile_id", self._learn_profile or DEFAULT_PROFILE_ID),
                ): self._profile_selector(),
                vol.Required("contact_type", default=values.get("contact_type", "door")): TYPE_SELECTOR,
                vol.Optional(CONF_AREA_ID, description={"suggested_value": values.get(CONF_AREA_ID)}): AREA_SELECTOR,
                vol.Required("tamper_enabled", default=values.get("tamper_enabled", True)): bool,
                vol.Required("battery_enabled", default=values.get("battery_enabled", True)): bool,
            }
        )
        return self.async_show_form(
            step_id=step,
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "raw": self._learn_raw or "",
                "device": self._learned or "",
                "event": self._learn_event or "",
            },
        )

    async def async_step_learn(self, user_input=None):
        if user_input is not None:
            self._learn_profile = user_input["profile_id"]
            self._scan_detections = {}
            return await self.async_step_learn_wait()
        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema({vol.Required("profile_id", default=DEFAULT_PROFILE_ID): self._profile_selector()}),
        )

    async def _async_start_learn_scan(self) -> None:
        """Start an open-ended manager scan inside the options dialog."""
        manager = self.config_entry.runtime_data
        profile = self._profile(self._learn_profile or DEFAULT_PROFILE_ID)
        self._scan_current_id = None

        session = PreviewSession(
            data={"latest": None, "current_device_id": None},
            renderer=render_learning_preview,
        )
        self._learn_session = session
        register_preview_session(self.hass, self.flow_id, session)

        @callback
        def received(payload: str) -> None:
            parsed = parse(payload, profile)
            if parsed is None:
                return
            device_id = parsed[0]
            if device_id != self._scan_current_id:
                self._scan_detections = {}
            if not record_detection(self._scan_detections, payload, profile, dt_util.utcnow().isoformat()):
                return
            self._scan_current_id = device_id
            session.data["latest"] = payload
            session.data["current_device_id"] = self._scan_current_id
            session.publish()

        self._learn_callback = received
        manager.scan_callbacks.add(received)

    @callback
    def _stop_learn_scan(self) -> None:
        if self._learn_callback is not None:
            self.config_entry.runtime_data.scan_callbacks.discard(self._learn_callback)
            self._learn_callback = None
        self._learn_session = None
        self._scan_current_id = None
        remove_preview_session(self.hass, self.flow_id)

    def _clear_learn_detection(self) -> None:
        """Wait for a fresh RF signal before another sensor is saved."""
        self._scan_detections = {}
        self._scan_current_id = None
        if self._learn_session is not None:
            self._learn_session.data["latest"] = None
            self._learn_session.data["current_device_id"] = None
            self._learn_session.publish()

    async def async_step_learn_wait(self, user_input=None):
        """Adopt sensors continuously inside the native options dialog."""
        errors: dict[str, str] = {}
        if user_input is not None:
            next_action = user_input.get("next_action", LEARNING_ACTION_ADD)
            detection = self._scan_detections.get(self._scan_current_id or "")
            if detection is None and next_action == LEARNING_ACTION_DONE:
                self._stop_learn_scan()
                return self.async_create_entry(data=self.options)
            if detection is None:
                errors["base"] = "no_signal"
            elif any(
                sensor["rf_id"] == detection["device_id"]
                and sensor["profile_id"] == (self._learn_profile or DEFAULT_PROFILE_ID)
                for sensor in self.options[CONF_SENSORS]
            ):
                if next_action == LEARNING_ACTION_DONE:
                    self._stop_learn_scan()
                    return self.async_create_entry(data=self.options)
                errors["base"] = "already_configured"
            else:
                item = _learned_sensor(detection, self._learn_profile or DEFAULT_PROFILE_ID, user_input)
                self.options[CONF_SENSORS].append({**item, "id": str(uuid4())})
                if next_action == LEARNING_ACTION_DONE:
                    self._stop_learn_scan()
                    return self.async_create_entry(data=self.options)
                self._clear_learn_detection()
                user_input = None
        if self._learn_callback is None:
            await self._async_start_learn_scan()
        return self.async_show_form(
            step_id="learn_wait",
            data_schema=_learning_schema(user_input or {}),
            errors=errors,
            last_step=False,
            preview=DOMAIN,
        )

    async def async_step_learn_retry(self, user_input=None):
        self._stop_learn_scan()
        return await self.async_step_learn_wait()

    async def async_step_sensors(self, user_input=None):
        if not self.options[CONF_SENSORS]:
            return self.async_abort(reason="no_sensors")
        if user_input is not None:
            self._selected = user_input["sensor"]
            return self.async_show_menu(step_id="sensor_action", menu_options=["edit_sensor", "delete_sensor"])
        choices = [_select_option(sensor["id"], sensor["name"]) for sensor in self.options[CONF_SENSORS]]
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {vol.Required("sensor"): selector.SelectSelector(selector.SelectSelectorConfig(options=choices))}
            ),
        )

    async def async_step_edit_sensor(self, user_input=None):
        item = next(sensor for sensor in self.options[CONF_SENSORS] if sensor["id"] == self._selected)
        return await self._sensor_form("edit_sensor", user_input, item)

    async def async_step_delete_sensor(self, user_input=None):
        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="not_confirmed")
            self.options[CONF_SENSORS] = [
                sensor for sensor in self.options[CONF_SENSORS] if sensor["id"] != self._selected
            ]
            return self.async_create_entry(data=self.options)
        return self.async_show_form(
            step_id="delete_sensor",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    async def async_step_profiles(self, user_input=None):
        return self.async_show_menu(step_id="profiles", menu_options=["add_profile", "edit_profile", "delete_profile"])

    async def async_step_add_profile(self, user_input=None):
        return await self._profile_form("add_profile", user_input)

    async def _profile_form(self, step, user_input, initial=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            profile_id = (initial or {}).get("id", str(uuid4()))
            try:
                item = normalize_profile(
                    user_input,
                    profile_id,
                    builtin=profile_id == DEFAULT_PROFILE_ID,
                )
            except ProfileValidationError as err:
                errors[err.field if err.field in user_input else "base"] = "invalid_profile"
            else:
                replaced = False
                profiles = []
                for profile in self.options[CONF_PROFILES]:
                    if profile["id"] == item["id"]:
                        profiles.append(item)
                        replaced = True
                    else:
                        profiles.append(profile)
                if not replaced:
                    profiles.append(item)
                self.options[CONF_PROFILES] = profiles
                return self.async_create_entry(data=self.options)
        values = user_input or initial or {}
        return self.async_show_form(step_id=step, data_schema=_profile_schema(values), errors=errors)

    async def async_step_edit_profile(self, user_input=None):
        return await self._select_profile("edit_profile_form", user_input, True)

    async def async_step_edit_profile_form(self, user_input=None):
        return await self._profile_form(
            "edit_profile_form", user_input, self._profile(self._selected or DEFAULT_PROFILE_ID)
        )

    async def async_step_delete_profile(self, user_input=None):
        return await self._select_profile("delete_profile_confirm", user_input, False)

    async def _select_profile(self, next_step, user_input, allow_builtin):
        profiles = (
            self._profiles()
            if allow_builtin
            else [profile for profile in self.options[CONF_PROFILES] if profile["id"] != DEFAULT_PROFILE_ID]
        )
        if not profiles:
            return self.async_abort(reason="no_custom_profiles")
        if user_input is not None:
            self._selected = user_input["profile"]
            return await getattr(self, f"async_step_{next_step}")()
        return self.async_show_form(
            step_id=next_step.rsplit("_", 1)[0],
            data_schema=vol.Schema(
                {
                    vol.Required("profile"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[_select_option(profile["id"], profile["name"]) for profile in profiles]
                        )
                    )
                }
            ),
        )

    async def async_step_delete_profile_confirm(self, user_input=None):
        if any(sensor["profile_id"] == self._selected for sensor in self.options[CONF_SENSORS]):
            return self.async_abort(reason="profile_in_use")
        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="not_confirmed")
            self.options[CONF_PROFILES] = [
                profile for profile in self.options[CONF_PROFILES] if profile["id"] != self._selected
            ]
            return self.async_create_entry(data=self.options)
        return self.async_show_form(
            step_id="delete_profile_confirm",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    async def async_step_unknown(self, user_input=None):
        unknown = self.config_entry.runtime_data.unknown
        if not unknown:
            return self.async_abort(reason="no_unknown")
        if user_input is not None:
            selected = unknown[user_input["raw"]]
            self._learned = selected.get("device_id") or user_input["raw"]
            self._learn_raw = selected["raw"]
            self._learn_event = selected.get("event_code") or ""
            return await self._sensor_form("unknown_create", None)
        choices = [
            _select_option(key, f"{key} — {value['count']}x — {value['last_seen']}")
            for key, value in reversed(unknown.items())
        ]
        return self.async_show_form(
            step_id="unknown",
            data_schema=vol.Schema(
                {vol.Required("raw"): selector.SelectSelector(selector.SelectSelectorConfig(options=choices))}
            ),
        )

    async def async_step_unknown_create(self, user_input=None):
        return await self._sensor_form("unknown_create", user_input)

    async def async_step_information(self, user_input=None):
        manager = self.config_entry.runtime_data
        history: list[str] = []
        tamper: list[str] = []
        for runtime in manager.sensors.values():
            name = runtime.config["name"]
            rf_id = runtime.config["rf_id"]
            codes = "\n".join(
                f"  {item['raw']} — event {item['event_code']} ({item['event']}), "
                f"{item['count']}x, latest {item.get('last_seen') or 'during setup'}"
                for item in runtime.code_history.values()
            )
            history.append(f"{name} [{rf_id}]\n{codes or '  No codes received yet'}")
            tamper.append(f"{name}: {runtime.tamper_last_seen or 'Never'}")
        return self.async_show_form(
            step_id="information",
            data_schema=vol.Schema({}),
            description_placeholders={
                "sensors": str(len(manager.sensors)),
                "unknown": str(len(manager.unknown)),
                "received": str(manager.stats["received"]),
                "latest": manager.last_received_payload or "None yet",
                "latest_seen": manager.last_received_at or "Never",
                "history": "\n\n".join(history) or "No configured sensors.",
                "tamper": "\n".join(tamper) or "No configured sensors.",
            },
        )

    @callback
    def async_remove(self) -> None:
        """Release the manager scan callback when the flow closes."""
        self._stop_learn_scan()
