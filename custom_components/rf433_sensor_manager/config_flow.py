"""UI configuration and management flows."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DUPLICATE_INTERVAL,
    CONF_JSON_PATH,
    CONF_NAME,
    CONF_PAYLOAD_FORMAT,
    CONF_PROFILES,
    CONF_SENSORS,
    CONF_TOPIC,
    DEFAULT_OPTIONS,
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_ID,
    DOMAIN,
    FORMAT_JSON,
    FORMAT_RAW,
)
from .protocol import normalize_payload, parse

FORMAT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=[FORMAT_JSON, FORMAT_RAW], translation_key="payload_format")
)
TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=["door", "window"], translation_key="contact_type")
)


class RF433ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(str(uuid4()))
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=user_input, options=deepcopy(DEFAULT_OPTIONS)
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_TOPIC): str,
                vol.Required(CONF_PAYLOAD_FORMAT, default=FORMAT_JSON): FORMAT_SELECTOR,
                vol.Optional(CONF_JSON_PATH, default="RfReceived.Data"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RF433OptionsFlow()


class RF433OptionsFlow(config_entries.OptionsFlow):
    """Native menu-based configuration."""

    def __init__(self):
        self.options = {}
        self._selected = None
        self._learn_task = None
        self._learned = None
        self._learn_profile = None

    async def async_step_init(self, user_input=None):
        self.options = deepcopy({**DEFAULT_OPTIONS, **self.config_entry.options})
        return self.async_show_menu(
            step_id="init",
            menu_options=["bridge", "add_sensor", "learn", "sensors", "profiles", "unknown", "information"],
        )

    async def async_step_bridge(self, user_input=None):
        if user_input is not None:
            data = dict(self.config_entry.data)
            data.update({k: user_input[k] for k in (CONF_TOPIC, CONF_PAYLOAD_FORMAT, CONF_JSON_PATH)})
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            self.options[CONF_DUPLICATE_INTERVAL] = user_input[CONF_DUPLICATE_INTERVAL]
            return self.async_create_entry(data=self.options)
        d = self.config_entry.data
        return self.async_show_form(
            step_id="bridge",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC, default=d[CONF_TOPIC]): str,
                    vol.Required(CONF_PAYLOAD_FORMAT, default=d[CONF_PAYLOAD_FORMAT]): FORMAT_SELECTOR,
                    vol.Optional(CONF_JSON_PATH, default=d.get(CONF_JSON_PATH, "RfReceived.Data")): str,
                    vol.Required(CONF_DUPLICATE_INTERVAL, default=self.options[CONF_DUPLICATE_INTERVAL]): vol.All(
                        vol.Coerce(float), vol.Range(min=0, max=60)
                    ),
                }
            ),
        )

    def _profiles(self):
        return [DEFAULT_PROFILE, *self.options[CONF_PROFILES]]

    def _profile_selector(self):
        return selector.SelectSelector(
            selector.SelectSelectorConfig(options=[{"value": p["id"], "label": p["name"]} for p in self._profiles()])
        )

    async def async_step_add_sensor(self, user_input=None):
        return await self._sensor_form("add_sensor", user_input)

    async def _sensor_form(self, step, user_input, initial=None):
        errors = {}
        if user_input is not None:
            rf_id = normalize_payload(user_input["rf_id"])
            if not rf_id:
                errors["rf_id"] = "invalid_hex"
            elif any(
                s["rf_id"] == rf_id
                and s["profile_id"] == user_input["profile_id"]
                and s.get("id") != (initial or {}).get("id")
                for s in self.options[CONF_SENSORS]
            ):
                errors["rf_id"] = "already_configured"
            else:
                item = {**(initial or {}), **user_input, "rf_id": rf_id, "id": (initial or {}).get("id", str(uuid4()))}
                if initial:
                    self.options[CONF_SENSORS] = [
                        item if s["id"] == item["id"] else s for s in self.options[CONF_SENSORS]
                    ]
                else:
                    self.options[CONF_SENSORS].append(item)
                return self.async_create_entry(data=self.options)
        v = user_input or initial or {}
        schema = vol.Schema(
            {
                vol.Required("name", default=v.get("name", "")): str,
                vol.Required("rf_id", default=v.get("rf_id", self._learned or "")): str,
                vol.Required("profile_id", default=v.get("profile_id", DEFAULT_PROFILE_ID)): self._profile_selector(),
                vol.Required("contact_type", default=v.get("contact_type", "door")): TYPE_SELECTOR,
                vol.Required("tamper_enabled", default=v.get("tamper_enabled", True)): bool,
                vol.Required("battery_enabled", default=v.get("battery_enabled", True)): bool,
            }
        )
        return self.async_show_form(
            step_id=step, data_schema=schema, errors=errors, description_placeholders={"raw": self._learned or ""}
        )

    async def async_step_learn(self, user_input=None):
        if user_input is not None:
            self._learn_profile = user_input["profile_id"]
            return await self.async_step_learn_wait()
        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema({vol.Required("profile_id", default=DEFAULT_PROFILE_ID): self._profile_selector()}),
        )

    async def async_step_learn_wait(self, user_input=None):
        manager = self.config_entry.runtime_data

        async def wait_message():
            future = self.hass.loop.create_future()

            def received(payload):
                if not future.done():
                    future.set_result(payload)

            manager.learn_callbacks.add(received)
            try:
                return await asyncio.wait_for(future, 60)
            finally:
                manager.learn_callbacks.discard(received)

        self._learn_task = self.hass.async_create_task(wait_message())
        return self.async_show_progress(
            step_id="learn_wait",
            progress_action="wait_for_signal",
            progress_task=self._learn_task,
            description_placeholders={"bridge": self.config_entry.title},
        )

    async def async_step_learn_wait_done(self, user_input=None):
        try:
            raw = self._learn_task.result()
            profile = next(p for p in self._profiles() if p["id"] == self._learn_profile)
            candidate = parse(raw, profile)
            if candidate is None:
                return self.async_abort(reason="learn_invalid_profile")
            self._learned = candidate[0]
        except TimeoutError, asyncio.CancelledError:
            return self.async_abort(reason="learn_timeout")
        return await self._sensor_form("learn_done", user_input)

    async def async_step_sensors(self, user_input=None):
        if not self.options[CONF_SENSORS]:
            return self.async_abort(reason="no_sensors")
        if user_input is not None:
            self._selected = user_input["sensor"]
            return self.async_show_menu(step_id="sensor_action", menu_options=["edit_sensor", "delete_sensor"])
        choices = [{"value": s["id"], "label": s["name"]} for s in self.options[CONF_SENSORS]]
        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {vol.Required("sensor"): selector.SelectSelector(selector.SelectSelectorConfig(options=choices))}
            ),
        )

    async def async_step_edit_sensor(self, user_input=None):
        item = next(s for s in self.options[CONF_SENSORS] if s["id"] == self._selected)
        return await self._sensor_form("edit_sensor", user_input, item)

    async def async_step_delete_sensor(self, user_input=None):
        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="not_confirmed")
            self.options[CONF_SENSORS] = [s for s in self.options[CONF_SENSORS] if s["id"] != self._selected]
            return self.async_create_entry(data=self.options)
        return self.async_show_form(
            step_id="delete_sensor", data_schema=vol.Schema({vol.Required("confirm", default=False): bool})
        )

    async def async_step_profiles(self, user_input=None):
        return self.async_show_menu(step_id="profiles", menu_options=["add_profile", "edit_profile", "delete_profile"])

    async def async_step_add_profile(self, user_input=None):
        return await self._profile_form("add_profile", user_input)

    async def _profile_form(self, step, user_input, initial=None):
        if user_input is not None:
            for key in ("open_code", "closed_code", "tamper_code", "battery_code"):
                user_input[key] = normalize_payload(user_input.get(key)) if user_input.get(key) else None
            item = {**(initial or {}), **user_input, "id": (initial or {}).get("id", str(uuid4()))}
            self.options[CONF_PROFILES] = (
                [item if p["id"] == item["id"] else p for p in self.options[CONF_PROFILES]]
                if initial
                else [*self.options[CONF_PROFILES], item]
            )
            return self.async_create_entry(data=self.options)
        v = user_input or initial or {}
        schema = vol.Schema(
            {
                vol.Required("name", default=v.get("name", "")): str,
                vol.Optional("payload_length", default=v.get("payload_length", 6)): vol.Any(None, vol.Coerce(int)),
                vol.Required("device_start", default=v.get("device_start", 0)): vol.Coerce(int),
                vol.Required("device_length", default=v.get("device_length", 4)): vol.Coerce(int),
                vol.Required("event_start", default=v.get("event_start", 4)): vol.Coerce(int),
                vol.Required("event_length", default=v.get("event_length", 2)): vol.Coerce(int),
                vol.Required("open_code", default=v.get("open_code", "0A")): str,
                vol.Required("closed_code", default=v.get("closed_code", "0E")): str,
                vol.Optional("tamper_code", default=v.get("tamper_code", "")): str,
                vol.Optional("battery_code", default=v.get("battery_code", "")): str,
            }
        )
        return self.async_show_form(step_id=step, data_schema=schema)

    async def async_step_edit_profile(self, user_input=None):
        return await self._select_profile("edit_profile_form", user_input, False)

    async def async_step_edit_profile_form(self, user_input=None):
        return await self._profile_form(
            "edit_profile_form", user_input, next(p for p in self.options[CONF_PROFILES] if p["id"] == self._selected)
        )

    async def async_step_delete_profile(self, user_input=None):
        return await self._select_profile("delete_profile_confirm", user_input, False)

    async def _select_profile(self, next_step, user_input, allow_builtin):
        profiles = self._profiles() if allow_builtin else self.options[CONF_PROFILES]
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
                            options=[{"value": p["id"], "label": p["name"]} for p in profiles]
                        )
                    )
                }
            ),
        )

    async def async_step_delete_profile_confirm(self, user_input=None):
        if any(s["profile_id"] == self._selected for s in self.options[CONF_SENSORS]):
            return self.async_abort(reason="profile_in_use")
        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="not_confirmed")
            self.options[CONF_PROFILES] = [p for p in self.options[CONF_PROFILES] if p["id"] != self._selected]
            return self.async_create_entry(data=self.options)
        return self.async_show_form(
            step_id="delete_profile_confirm", data_schema=vol.Schema({vol.Required("confirm", default=False): bool})
        )

    async def async_step_unknown(self, user_input=None):
        unknown = self.config_entry.runtime_data.unknown
        if not unknown:
            return self.async_abort(reason="no_unknown")
        if user_input is not None:
            selected = unknown[user_input["raw"]]
            self._learned = selected.get("device_id") or user_input["raw"]
            return await self._sensor_form("unknown_create", None)
        choices = [
            {"value": k, "label": f"{k} — {v['count']}x — {v['last_seen']}"} for k, v in reversed(unknown.items())
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
        m = self.config_entry.runtime_data
        return self.async_show_form(
            step_id="information",
            data_schema=vol.Schema({}),
            description_placeholders={
                "sensors": str(len(m.sensors)),
                "unknown": str(len(m.unknown)),
                "received": str(m.stats["received"]),
            },
        )
