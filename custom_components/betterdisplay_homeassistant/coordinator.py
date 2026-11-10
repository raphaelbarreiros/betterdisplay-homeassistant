"""Manually refreshed state and explicitly scoped, consent-checked operations."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BetterDisplayClient, BetterDisplayError, Capability, Display, InvalidAuth,
    InvalidResponse, UnsupportedControl,
)
from .const import (
    CONF_CAPABILITIES, CONF_DISPLAYS, CONF_FAMILIES, DEFAULT_FAMILIES, MAC_KEY,
)
from .features import CATALOG, family_for, pro_required

_LOGGER = logging.getLogger(__name__)
_ACTION_FAMILIES = {
    "changeInputSource": "input", "muteToggle": "audio", "setMain": "layout",
    "favoriteMode": "layout", "moveTo": "layout", "associated": "virtual",
    "applyLayoutProtection": "layout", "sendCEC": "cec",
}


@dataclass
class DisplayState:
    """Unknown, unsupported and last-read app state are kept distinct."""

    brightness: dict[str, float] = field(default_factory=dict)
    values: dict[str, dict[str, object]] = field(default_factory=dict)
    unavailable: set[str] = field(default_factory=set)
    feature_unavailable: set[tuple[str, str]] = field(default_factory=set)
    pro_available: bool | None = None
    pro_checked: bool = False
    last_read: datetime | None = None


class BetterDisplayCoordinator(DataUpdateCoordinator[DisplayState]):
    """No interval, startup probe, discovery loop or automatic write retries."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 client: BetterDisplayClient, displays: dict[str, Display]) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title,
                         update_interval=None)
        self.entry = entry
        self.client = client
        self.displays = displays
        self.data = DisplayState()
        self.capabilities = {
            key: {feature: Capability.from_dict(value) for feature, value in items.items()}
            for key, items in entry.options.get(CONF_CAPABILITIES, {}).items()
            if key == MAC_KEY or key in displays
        }
        self.registered_unique_ids: set[str] = set()
        self.completed_platforms: set[str] = set()
        self._request_lock = asyncio.Lock()
        self.stopped = False

    def selected_keys(self) -> set[str]:
        return {Display.from_dict(item).key
                for item in self.entry.options.get(CONF_DISPLAYS, [])}

    def permits(self, keys: tuple[str, ...]) -> bool:
        return (not self.stopped and bool(keys)
                and set(keys).issubset(self.displays)
                and set(keys).issubset(self.selected_keys()))

    def capability(self, key: str, feature: str) -> Capability | None:
        return self.capabilities.get(key, {}).get(feature)

    def _family_enabled(self, family: str) -> bool:
        return family in self.entry.options.get(CONF_FAMILIES, DEFAULT_FAMILIES)

    def feature_allowed(self, key: str, feature: str) -> bool:
        """Saved eligibility plus current consent, independent of other controls."""
        spec = CATALOG.get(feature)
        target = self.displays.get(key)
        if self.stopped or spec is None or not self._family_enabled(family_for(feature, target)):
            return False
        if key != MAC_KEY and not self.permits((key,)):
            return False
        scope = target.device_type if target else "Mac"
        if scope not in spec.scopes:
            return False
        if feature == "muteToggle":
            eligible = key in self.entry.options.get("mute_toggle_targets", [])
        elif feature in ("favoriteMode", "applyLayoutProtection"):
            eligible = True
        elif feature == "setMain":
            eligible = self.capability(key, "main") is not None
        else:
            eligible = self.capability(key, feature) is not None
        if not eligible:
            return False
        return not (spec.platform not in ("sensor", "binary_sensor")
                    and self.data.pro_checked and pro_required(feature, target)
                    and self.data.pro_available is not True)

    def _copy_state(self) -> DisplayState:
        return DisplayState(
            brightness=dict(self.data.brightness),
            values={key: dict(values) for key, values in self.data.values.items()},
            unavailable=set(self.data.unavailable),
            feature_unavailable=set(self.data.feature_unavailable),
            pro_available=self.data.pro_available, pro_checked=self.data.pro_checked,
            last_read=self.data.last_read,
        )

    def _publish(self, state: DisplayState) -> None:
        self.async_set_updated_data(state)

    def _matches(self, key: str, discovered: dict[str, Display]) -> bool:
        stored = self.displays[key]
        current = discovered.get(key)
        if current is None or current.device_type != stored.device_type:
            return False
        # These definition types lack an OS UUID. A changed name is an ambiguity,
        # not permission to bind a new definition to an existing automation.
        return current.uuid == stored.uuid if stored.uuid else current.name == stored.name

    def _check_target(self, key: str) -> Display | None:
        if self.stopped:
            raise HomeAssistantError("This computer's integration has been unloaded")
        if key == MAC_KEY:
            return None
        if not self.permits((key,)):
            raise HomeAssistantError("This device is no longer selected")
        return self.displays[key]

    async def _preflight(self, keys: tuple[str, ...], state: DisplayState) -> None:
        for key in keys:
            self._check_target(key)
        device_keys = tuple(key for key in keys if key != MAC_KEY)
        if not device_keys:
            return
        try:
            discovered = await self.client.discover()
        except BetterDisplayError:
            state.unavailable.update((*self.displays, MAC_KEY))
            raise
        missing = {key for key in device_keys if not self._matches(key, discovered)}
        if missing:
            state.unavailable.update(missing)
            raise HomeAssistantError(
                "A selected device is missing or its identity changed. "
                "No writes were sent; rescan and confirm in Configure."
            )
        state.unavailable.difference_update(device_keys)

    async def _check_pro(self, feature: str, target: Display | None,
                         state: DisplayState) -> None:
        if not pro_required(feature, target):
            return
        state.pro_available = await self.client.get_pro_available()
        state.pro_checked = True
        if state.pro_available is not True:
            raise HomeAssistantError(
                "This operation requires currently available BetterDisplay Pro features. "
                "No writes were sent."
            )

    async def _read_one(self, key: str, feature: str, state: DisplayState) -> Capability:
        capability = await self.client.read_feature(self.displays.get(key), feature)
        state.last_read = dt_util.utcnow()
        state.values.setdefault(key, {})[feature] = capability.value
        state.feature_unavailable.discard((key, feature))
        if feature == "brightness" and capability.value is not None:
            state.brightness[key] = float(capability.value)
        return capability

    async def _refresh_known(self, state: DisplayState) -> None:
        discovered = await self.client.discover() if self.displays else {}
        state.pro_available = await self.client.get_pro_available()
        state.pro_checked = True
        state.unavailable.discard(MAC_KEY)
        for key, features in self.capabilities.items():
            if key != MAC_KEY:
                if not self.permits((key,)) or not self._matches(key, discovered):
                    state.unavailable.add(key)
                    continue
                state.unavailable.discard(key)
            target = self.displays.get(key)
            for feature in features:
                spec = CATALOG.get(feature)
                if spec is None or not self._family_enabled(family_for(feature, target)):
                    continue
                if spec.platform == "button":
                    continue
                if (spec.platform not in ("sensor", "binary_sensor")
                        and pro_required(feature, target) and state.pro_available is not True):
                    state.feature_unavailable.add((key, feature))
                    continue
                try:
                    await self._read_one(key, feature, state)
                except (InvalidResponse, UnsupportedControl):
                    state.feature_unavailable.add((key, feature))
                    state.values.get(key, {}).pop(feature, None)
                    if feature == "brightness":
                        state.brightness.pop(key, None)

    async def _async_update_data(self) -> DisplayState:
        async with self._request_lock:
            if self.stopped:
                raise UpdateFailed("The integration has been unloaded")
            state = self._copy_state()
            try:
                await self._refresh_known(state)
            except InvalidAuth:
                state.unavailable.update((*self.displays, MAC_KEY))
                state.pro_available = None
                state.pro_checked = True
                self._publish(state)
                raise ConfigEntryAuthFailed("BetterDisplay rejected the saved token") from None
            except BetterDisplayError:
                state.unavailable.update((*self.displays, MAC_KEY))
                self._publish(state)
                raise UpdateFailed("Cannot refresh BetterDisplay; check this Mac's HTTP server") from None
            state.last_read = dt_util.utcnow()
            return state

    async def async_manual_refresh(self) -> None:
        await self.async_refresh()
        if not self.last_update_success:
            raise HomeAssistantError(
                "Refresh failed. Check the Mac, HTTP server and token, then refresh again."
            ) from None

    @staticmethod
    def _number(value: object, feature: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HomeAssistantError("The control needs a finite numeric value")
        minimum = -100 if feature == "temperature" else 0
        if not minimum <= value <= 100:
            raise HomeAssistantError(f"Value must be between {minimum} and 100")
        return (value + 100) / 200 if feature == "temperature" else value / 100

    def _ensure_consent(self, key: str, feature: str) -> None:
        spec = CATALOG.get(feature)
        target = self._check_target(key)
        if spec is None or not self._family_enabled(family_for(feature, target)):
            raise HomeAssistantError("Enable this control family in Configure before using it")
        if (target.device_type if target else "Mac") not in spec.scopes:
            raise HomeAssistantError("This operation is not valid for that device type")
        if self.capability(key, feature) is None:
            raise HomeAssistantError("This control was not found in the confirmed capability scan")

    async def async_set_feature(self, key: str, feature: str, value: object) -> None:
        self._ensure_consent(key, feature)
        spec = CATALOG[feature]
        if spec.platform not in ("number", "switch", "select"):
            raise HomeAssistantError("This control is not a writable value")
        wire_value = self._number(value, feature) if spec.normalized else value
        async with self._request_lock:
            state = self._copy_state()
            wrote = False
            try:
                self._ensure_consent(key, feature)
                await self._preflight((key,), state)
                target = self.displays.get(key)
                await self._check_pro(feature, target, state)
                if spec.list_feature:
                    fresh = await self.client.choices(target, feature)
                    saved = self.capability(key, feature).choices
                    wire_value = str(wire_value)
                    if wire_value not in fresh or saved.get(wire_value) != fresh[wire_value]:
                        raise HomeAssistantError("The option changed; rescan and confirm before applying it")
                if feature == "xdrPreset" and str(wire_value).casefold() == "betterdisplay xdr":
                    await self._check_pro("directBrightnessUpscaling", target, state)
                await self._read_one(key, feature, state)
                self._ensure_consent(key, feature)
                await self.client.write_feature(target, feature, wire_value)
                wrote = True
                observed = (await self._read_one(key, feature, state)).value
                if spec.normalized:
                    matched = isinstance(observed, (float, int)) and math.isclose(float(observed), float(wire_value), abs_tol=0.01)
                else:
                    matched = observed == wire_value or str(observed) == str(wire_value)
                if not matched:
                    raise InvalidResponse("The app readback did not match the requested value")
            except (BetterDisplayError, ValueError, HomeAssistantError) as error:
                if isinstance(error, HomeAssistantError):
                    self._publish(state)
                    raise
                state.feature_unavailable.add((key, feature))
                state.values.get(key, {}).pop(feature, None)
                self._publish(state)
                message = (
                    "The request may have taken effect but readback failed; no retry or rollback was sent."
                    if wrote else "The control request failed. Check support, authentication and the connection; no retries were sent."
                )
                raise HomeAssistantError(message) from None
            try:
                # Do not discard a verified value if an unrelated refresh fails.
                await self._refresh_known(state)
            except BetterDisplayError:
                self._publish(state)
                raise HomeAssistantError(
                    "Applied with matching app readback, but refreshing related controls "
                    "failed. Refresh manually; no retry or rollback was sent."
                ) from None
            self._publish(state)

    async def async_set_brightness(self, keys: tuple[str, ...], percent: float) -> None:
        value = self._number(percent, "brightness")
        keys = tuple(dict.fromkeys(keys))
        if not keys:
            raise HomeAssistantError("No brightness targets were selected")
        async with self._request_lock:
            state = self._copy_state()
            completed = 0
            current_key: str | None = None
            try:
                for key in keys:
                    self._ensure_consent(key, "brightness")
                await self._preflight(keys, state)
                for key in keys:
                    current_key = key
                    await self._read_one(key, "brightness", state)
                for key in keys:
                    current_key = key
                    self._ensure_consent(key, "brightness")
                    await self.client.write_feature(self.displays[key], "brightness", value)
                    observed = (await self._read_one(key, "brightness", state)).value
                    if not isinstance(observed, (int, float)) or not math.isclose(float(observed), value, abs_tol=0.01):
                        raise InvalidResponse("Brightness readback did not match")
                    completed += 1
            except (BetterDisplayError, ValueError, HomeAssistantError) as error:
                if current_key is not None:
                    state.feature_unavailable.add((current_key, "brightness"))
                    state.brightness.pop(current_key, None)
                self._publish(state)
                if isinstance(error, HomeAssistantError):
                    raise
                raise HomeAssistantError(
                    f"Brightness update incomplete: {completed} of {len(keys)} displays "
                    "have matching app readback. A failed request may still have taken "
                    "effect; no retry or rollback was sent."
                ) from None
            self._publish(state)

    async def async_perform(self, key: str, action: str, *, value: object = None,
                            other_key: str | None = None) -> None:
        family = _ACTION_FAMILIES.get(action)
        if family is None or not self._family_enabled(family):
            raise HomeAssistantError("Enable this action's control family in Configure first")
        async with self._request_lock:
            state = self._copy_state()
            try:
                target = self._check_target(key)
                other = self._check_target(other_key) if other_key is not None else None
                await self._preflight((key,) if other_key is None else (key, other_key), state)
                await self._check_pro(action, target, state)
                if action == "applyLayoutProtection":
                    if key != MAC_KEY:
                        raise HomeAssistantError("Layout protection is a Mac-wide action")
                elif target is None:
                    raise HomeAssistantError("Select an explicit device for this action")
                if action in ("moveTo", "associated"):
                    if other is None or other.device_type != "Display" or other_key == key:
                        raise HomeAssistantError("Choose a different selected display on the same Mac")
                    if action == "moveTo" and target.device_type != "Display":
                        raise HomeAssistantError("Only system displays can be moved")
                    if action == "associated" and target.device_type != "VirtualScreen":
                        raise HomeAssistantError("The association source must be a virtual screen")
                elif action not in ("applyLayoutProtection",) and target.device_type != "Display":
                    raise HomeAssistantError("This action requires a selected system display")
                if action == "changeInputSource":
                    saved = self.capability(key, action)
                    fresh = await self.client.choices(target, action)
                    if saved is None or value not in fresh or saved.choices.get(value) != fresh[value]:
                        raise HomeAssistantError("Input mapping changed or was not confirmed; rescan first")
                if action == "muteToggle" and key not in self.entry.options.get("mute_toggle_targets", []):
                    raise HomeAssistantError("Explicitly enable toggle-only mute for this display first")
                if action == "sendCEC":
                    controllers = await self.client.controllers(target)
                    if "CECController" not in controllers:
                        raise HomeAssistantError("No configured CEC controller was reported for this display")
                if action == "setMain":
                    await self._read_one(key, "main", state)
                self._check_target(key)
                if other_key is not None:
                    self._check_target(other_key)
                if not self._family_enabled(family):
                    raise HomeAssistantError("Action consent changed before dispatch")
                await self.client.perform(target, action, value=value, other=other)
                if action == "associated":
                    observed = await self.client.read_association(target, other)
                    if observed is not value:
                        raise InvalidResponse("Association readback did not match")
                # These actions may remove their own communication path and have
                # no meaningful readback. Do not imply state or issue a recovery write.
                if action not in ("sendCEC", "changeInputSource", "muteToggle"):
                    await self._refresh_known(state)
            except (BetterDisplayError, ValueError, HomeAssistantError) as error:
                self._publish(state)
                if isinstance(error, HomeAssistantError):
                    raise
                raise HomeAssistantError(
                    "Action failed or could not be verified. It may already have taken "
                    "effect; no retry or rollback was sent."
                ) from None
            self._publish(state)

    async def async_stop(self) -> None:
        self.stopped = True
        async with self._request_lock:
            pass
