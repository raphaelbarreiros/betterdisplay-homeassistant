"""Explicit, manually scanned BetterDisplay configuration."""

from collections.abc import Mapping
from dataclasses import replace
import secrets
from typing import Any

import probatio

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import SelectSelector, TextSelector

from .api import BetterDisplayClient, BetterDisplayError, CannotConnect, Capability, Display, InvalidAuth, InvalidResponse, Probe, UnsupportedControl
from .const import (
    CONF_CAPABILITIES, CONF_DISPLAYS, CONF_FAMILIES, CONF_LABEL,
    CONF_SELECTION_MODE, CONF_TOKEN, CONF_WEBHOOKS, DEFAULT_FAMILIES,
    DEFAULT_PORT, DOMAIN, MAC_KEY, MODE_ALL, MODE_SELECTED, OPTIONAL_FAMILIES,
)
from .features import CATALOG, family_for, pro_required

DISPLAY_IDS = "display_ids"
MODE_MAC_ONLY = "mac_only"
MUTE_TARGETS = "mute_toggle_targets"


def _client(hass, data: Mapping[str, Any]) -> BetterDisplayClient:
    return BetterDisplayClient(async_get_clientsession(hass), data[CONF_HOST], data[CONF_PORT], data[CONF_TOKEN])


def _error(exc: Exception) -> str:
    if isinstance(exc, InvalidAuth):
        return "invalid_auth"
    if isinstance(exc, CannotConnect):
        return "cannot_connect"
    if isinstance(exc, ValueError):
        return "invalid_input"
    if isinstance(exc, InvalidResponse):
        return "invalid_response"
    return "unsupported_control"


def _families(values: Mapping[str, Any]) -> list[str]:
    families = values.get(CONF_FAMILIES, list(DEFAULT_FAMILIES))
    if not isinstance(families, list) or any(not isinstance(item, str) or item not in (*DEFAULT_FAMILIES, *OPTIONAL_FAMILIES) for item in families):
        raise ValueError("Invalid families")
    return list(dict.fromkeys(families))


def _family_field(values: Mapping[str, Any]) -> dict:
    return {probatio.Required(CONF_FAMILIES, default=list(values.get(CONF_FAMILIES, DEFAULT_FAMILIES))): SelectSelector({
        "options": list(DEFAULT_FAMILIES) + list(OPTIONAL_FAMILIES),
        "multiple": True, "translation_key": "families",
    })}


def _connection_schema(values: Mapping[str, Any], *, editing: bool = False) -> probatio.Schema:
    fields = {
        probatio.Required(CONF_LABEL, default=values.get(CONF_LABEL, "Mac")): str,
        probatio.Required(CONF_HOST, description={"suggested_value": values.get(CONF_HOST, "")}): str,
        probatio.Required(CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT)): probatio.All(int, probatio.Range(min=1, max=65535)),
        probatio.Required(probatio.Secret(CONF_TOKEN)): TextSelector({"type": "password"}),
    }
    if not editing:
        fields.update(_family_field(values))
    return probatio.Schema(fields)


def _eligible(probe: Probe, families: list[str]) -> dict[str, Display]:
    return {
        key: display for key, display in probe.displays.items()
        if probe.capabilities.get(key)
        and (display.device_type == "Display"
             or display.device_type == "VirtualScreen" and "virtual" in families
             or display.device_type == "DisplayGroup" and "groups" in families)
    }


def _label(display: Display) -> str:
    return f"{display.name} ({display.device_type}, tag {display.tag_id})"


def _targets_schema(probe: Probe, suggested: Mapping[str, Any], families: list[str]) -> probatio.Schema:
    candidates = _eligible(probe, families)
    return probatio.Schema({
        probatio.Required(CONF_SELECTION_MODE, description={"suggested_value": suggested[CONF_SELECTION_MODE]} if CONF_SELECTION_MODE in suggested else {}): SelectSelector({
            "options": [MODE_ALL, MODE_SELECTED, MODE_MAC_ONLY], "translation_key": "selection_mode",
        }),
        probatio.Optional(DISPLAY_IDS, description={"suggested_value": suggested.get(DISPLAY_IDS, [])}): SelectSelector({
            "multiple": True, "options": [{"value": key, "label": _label(display)} for key, display in candidates.items()],
        }),
        probatio.Optional(MUTE_TARGETS, description={"suggested_value": suggested.get(MUTE_TARGETS, [])}): SelectSelector({
            "multiple": True, "options": [{"value": key, "label": _label(display)} for key, display in candidates.items() if display.device_type == "Display" and "audio" in families],
        }),
    })


def _selection(probe: Probe, data: Mapping[str, Any], families: list[str], previous: Mapping[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    candidates = _eligible(probe, families)
    mode = data.get(CONF_SELECTION_MODE)
    if mode == MODE_ALL:
        keys = [key for key, display in candidates.items() if display.device_type == "Display"]
    elif mode == MODE_SELECTED:
        keys = data.get(DISPLAY_IDS, [])
    elif mode == MODE_MAC_ONLY:
        if "mac" not in families:
            return None, "mac_family_required"
        keys = []
    else:
        return None, "selection_required"
    if not isinstance(keys, list) or any(not isinstance(key, str) or key not in candidates for key in keys) or len(keys) != len(set(keys)):
        return None, "invalid_selection"
    if not keys and mode != MODE_MAC_ONLY:
        return None, "no_selection"
    mute = data.get(MUTE_TARGETS, [])
    if not isinstance(mute, list) or any(not isinstance(key, str) or key not in keys or candidates[key].device_type != "Display" or "audio" not in families for key in mute) or len(mute) != len(set(mute)):
        return None, "invalid_mute_selection"
    return _snapshot(probe, keys, mode, families, mute, previous), None


async def _probe_saved(client: BetterDisplayClient, families: list[str], previous: Mapping[str, Any] | None = None) -> Probe:
    probe = await client.probe(families)
    if previous is None or "connections" not in families:
        return probe
    for item in previous.get(CONF_DISPLAYS, []):
        stored = Display.from_dict(item)
        saved = previous.get(CONF_CAPABILITIES, {}).get(stored.key, {})
        if stored.device_type != "Display" or stored.resolve(probe.displays) is not None or "connected" not in saved:
            continue
        try:
            connected = await client.read_feature(stored, "connected")
        except (UnsupportedControl, InvalidResponse):
            continue
        if connected.value is not False:
            continue
        # A UUID read verifies this configured-but-disconnected display. Keep
        # its confirmed capabilities rather than deleting entities due to absence.
        probe.displays[stored.key] = stored
        probe.capabilities[stored.key] = {
            feature: Capability.from_dict(capability)
            for feature, capability in saved.items()
            if feature in CATALOG and family_for(feature, stored) in families
        }
        probe.capabilities[stored.key]["connected"] = connected
    return probe


def _snapshot(probe: Probe, keys: list[str], mode: str, families: list[str], mute: list[str], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    previous_displays = [Display.from_dict(item) for item in (previous or {}).get(CONF_DISPLAYS, [])]
    old_by_uuid = {display.uuid: display for display in previous_displays if display.device_type == "Display"}
    selected: dict[str, Display] = {}
    key_map: dict[str, str] = {}
    for key in keys:
        display = probe.displays[key]
        old = old_by_uuid.get(display.uuid) if display.device_type == "Display" else None
        if old is not None:
            display = replace(display, entity_key=old.key)
        selected[display.key] = display
        key_map[key] = display.key
    if "mac" in families or "layout" in families:
        key_map[MAC_KEY] = MAC_KEY
    return {
        CONF_SELECTION_MODE: mode,
        CONF_DISPLAYS: [display.to_dict() for display in selected.values()],
        CONF_FAMILIES: families,
        CONF_CAPABILITIES: {key_map[key]: {feature: capability.to_dict() for feature, capability in capabilities.items()} for key, capabilities in probe.capabilities.items() if key in key_map},
        CONF_WEBHOOKS: {key: secret for key, secret in (previous or {}).get(CONF_WEBHOOKS, {}).items() if key in selected and selected[key].device_type == "Display"},
        MUTE_TARGETS: [key_map[key] for key in mute],
    }


def _control_label(feature: str, target: Display | None) -> str:
    name = CATALOG[feature].name
    if feature == "ambientLight":
        license_text = "API license unclear; read-only"
    elif feature == "xdrPreset":
        license_text = "Free ordinary presets; BetterDisplay XDR requires Pro"
    elif feature == "rotation":
        license_text = "Pro per API; UI documentation differs"
    elif feature == "synchronization" and target is not None and target.tag_id == "-1001":
        license_text = "Free basic sync; advanced syncing requires Pro"
    else:
        license_text = "Pro" if pro_required(feature, target) else "Free; capability-dependent"
    return f"{name} ({license_text})"


def _confirmation(data: Mapping[str, Any], options: Mapping[str, Any], probe: Probe, previous: Mapping[str, Any] | None = None) -> dict[str, str]:
    displays = [Display.from_dict(item) for item in options[CONF_DISPLAYS]]
    selected = {display.key: display for display in displays}
    before = {Display.from_dict(item).key for item in (previous or {}).get(CONF_DISPLAYS, [])}
    after = {display.key for display in displays}
    return {
        "mac": data[CONF_LABEL], "host": data[CONF_HOST],
        "displays": "\n".join(f"- {_label(display)}" for display in displays) or "Mac-only controls (no displays)",
        "families": ", ".join(options[CONF_FAMILIES]) or "None",
        "controls": "\n".join(f"- {_label(selected[key]) if key in selected else 'Mac'}: {', '.join(_control_label(feature, selected.get(key)) for feature in features)}" for key, features in options[CONF_CAPABILITIES].items()) or "No readable controls",
        "mute_targets": ", ".join(selected[key].name for key in options[MUTE_TARGETS]) or "None",
        "pro_status": {True: "available", False: "not available", None: "unknown"}[probe.pro_available],
        "skipped": str(len(probe.displays) - len(_eligible(probe, options[CONF_FAMILIES]))),
        "added": str(len(after - before)), "removed": str(len(before - after)),
    }


class BetterDisplayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one Mac without using its mutable endpoint as identity."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._probe: Probe | None = None
        self._options: dict[str, Any] = {}
        self._editing: ConfigEntry | None = None
        self._families: list[str] = list(DEFAULT_FAMILIES)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "BetterDisplayOptionsFlow":
        return BetterDisplayOptionsFlow()

    def _duplicate(self, client: BetterDisplayClient) -> bool:
        return any(entry.entry_id != (self._editing.entry_id if self._editing else None) and _client(self.hass, entry.data).endpoint_key == client.endpoint_key for entry in self._async_current_entries())

    async def _validate(self, values: Mapping[str, Any]) -> str | None:
        try:
            if not values[CONF_LABEL].strip():
                return "invalid_input"
            families = _families(self._editing.options if self._editing else values)
            client = _client(self.hass, values)
            if self._duplicate(client):
                return "already_configured"
            probe = await _probe_saved(client, families, self._editing.options if self._editing else None)
        except (BetterDisplayError, ValueError) as exc:
            return _error(exc)
        if self._editing:
            old = self._editing.options
            displays = [Display.from_dict(item) for item in old[CONF_DISPLAYS]]
            key_map = {}
            for display in displays:
                found = display.resolve(probe.displays)
                if found is None:
                    return "identity_mismatch"
                key_map[display.key] = found.key
            if not displays and (old.get(CONF_SELECTION_MODE) != MODE_MAC_ONLY or "mac" not in families):
                return "identity_mismatch"
            self._options = _snapshot(probe, list(key_map.values()), old[CONF_SELECTION_MODE], families, [key_map[key] for key in old.get(MUTE_TARGETS, [])], old)
        elif not _eligible(probe, families) and not ("mac" in families and probe.capabilities.get(MAC_KEY)):
            return "no_displays"
        self._data = {CONF_HOST: client.host, CONF_PORT: client.port, CONF_LABEL: values[CONF_LABEL].strip(), CONF_TOKEN: values[CONF_TOKEN]}
        self._probe = probe
        self._families = families
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            error = await self._validate(user_input)
            if error is None:
                return await self.async_step_targets()
            errors["base"] = error
        return self.async_show_form(step_id="user", data_schema=_connection_schema(user_input or {}), errors=errors)

    async def async_step_targets(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._probe is not None
        errors = {}
        if user_input is not None:
            options, error = _selection(self._probe, user_input, self._families)
            if error is None:
                assert options is not None
                self._options = options
                return await self.async_step_confirm()
            errors["base"] = error
        return self.async_show_form(step_id="targets", data_schema=_targets_schema(self._probe, user_input or {}, self._families), errors=errors, description_placeholders={"mac": self._data[CONF_LABEL]})

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._probe is not None
        if user_input is not None:
            if self._duplicate(_client(self.hass, self._data)):
                return self.async_abort(reason="already_configured")
            if self._editing:
                return self.async_update_reload_and_abort(self._editing, title=self._data[CONF_LABEL], data=self._data, options=self._options)
            return self.async_create_entry(title=self._data[CONF_LABEL], data=self._data, options=self._options)
        return self.async_show_form(step_id="confirm", data_schema=probatio.Schema({}), description_placeholders=_confirmation(self._data, self._options, self._probe, self._editing.options if self._editing else None), last_step=True)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._editing = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            error = await self._validate(user_input)
            if error is None:
                return await self.async_step_confirm()
            if error == "identity_mismatch":
                return self.async_abort(reason=error)
            errors["base"] = error
        return self.async_show_form(step_id="reconfigure", data_schema=_connection_schema(user_input or self._editing.data, editing=True), errors=errors, description_placeholders={"mac": self._editing.title})

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._editing = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            error = await self._validate({**self._editing.data, CONF_TOKEN: user_input[CONF_TOKEN]})
            if error is None:
                return self.async_update_reload_and_abort(self._editing, data=self._data, options=self._options)
            if error == "identity_mismatch":
                return self.async_abort(reason=error)
            errors["base"] = error
        return self.async_show_form(step_id="reauth_confirm", data_schema=probatio.Schema({probatio.Required(probatio.Secret(CONF_TOKEN)): TextSelector({"type": "password"})}), errors=errors, description_placeholders={"mac": self._editing.title})


class BetterDisplayOptionsFlow(OptionsFlowWithReload):
    """Rescan explicitly or manage events without contacting the Mac."""

    def __init__(self) -> None:
        self._probe: Probe | None = None
        self._options: dict[str, Any] = {}
        self._families: list[str] = list(DEFAULT_FAMILIES)
        self._event_urls = ""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["rescan", "events"])

    async def async_step_rescan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                families = _families(user_input)
                probe = await _probe_saved(_client(self.hass, self.config_entry.data), families, self.config_entry.options)
            except (BetterDisplayError, ValueError) as exc:
                errors["base"] = _error(exc)
            else:
                self._families = families
                self._probe = probe
                return await self.async_step_targets()
        return self.async_show_form(step_id="rescan", data_schema=probatio.Schema(_family_field(user_input or self.config_entry.options)), errors=errors, description_placeholders={"mac": self.config_entry.title})

    async def async_step_targets(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._probe is not None
        errors = {}
        if user_input is not None:
            options, error = _selection(self._probe, user_input, self._families, self.config_entry.options)
            if error is None:
                assert options is not None
                self._options = options
                return await self.async_step_confirm()
            errors["base"] = error
        eligible = _eligible(self._probe, self._families)
        current_keys = {
            display.key: found.key
            for item in self.config_entry.options[CONF_DISPLAYS]
            if (found := (display := Display.from_dict(item)).resolve(eligible)) is not None
        }
        suggested = user_input if user_input is not None else {
            CONF_SELECTION_MODE: self.config_entry.options[CONF_SELECTION_MODE],
            DISPLAY_IDS: list(current_keys.values()),
            MUTE_TARGETS: [current_keys[key] for key in self.config_entry.options.get(MUTE_TARGETS, []) if key in current_keys and "audio" in self._families],
        }
        return self.async_show_form(step_id="targets", data_schema=_targets_schema(self._probe, suggested, self._families), errors=errors, description_placeholders={"mac": self.config_entry.title})

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._probe is not None
        if user_input is not None:
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="confirm", data_schema=probatio.Schema({}), description_placeholders=_confirmation(self.config_entry.data, self._options, self._probe, self.config_entry.options), last_step=True)

    async def async_step_events(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        displays = {display.key: display for item in self.config_entry.options[CONF_DISPLAYS] if (display := Display.from_dict(item)).device_type == "Display"}
        saved = self.config_entry.options.get(CONF_WEBHOOKS, {})
        errors = {}
        if user_input is not None:
            keys = user_input.get(DISPLAY_IDS, [])
            if not isinstance(keys, list) or any(not isinstance(key, str) or key not in displays for key in keys) or len(keys) != len(set(keys)):
                errors["base"] = "invalid_selection"
            else:
                try:
                    base = get_url(self.hass, allow_external=False, allow_cloud=False).rstrip("/") if keys else ""
                except NoURLAvailableError:
                    errors["base"] = "internal_url_required"
                else:
                    hooks = {key: saved.get(key) or secrets.token_hex(32) for key in keys}
                    self._options = {**self.config_entry.options, CONF_WEBHOOKS: hooks}
                    self._event_urls = "\n\n".join(f"{displays[key].name}:\n{base}/api/webhook/{secret}?hook=[*:EVENT_HOOK:*]" for key, secret in hooks.items()) or "No event webhooks enabled."
                    return await self.async_step_events_confirm()
        return self.async_show_form(step_id="events", data_schema=probatio.Schema({
            probatio.Optional(DISPLAY_IDS, default=[key for key in saved if key in displays]): SelectSelector({"multiple": True, "options": [{"value": key, "label": _label(display)} for key, display in displays.items()]})
        }), errors=errors, description_placeholders={"mac": self.config_entry.title})

    async def async_step_events_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="events_confirm", data_schema=probatio.Schema({}), description_placeholders={"urls": self._event_urls}, last_step=True)
