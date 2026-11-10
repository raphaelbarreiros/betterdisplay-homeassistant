"""Explicit HA device actions; no arbitrary BetterDisplay command passthrough."""
from __future__ import annotations

import probatio

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .const import DOMAIN, MAC_KEY
from .features import CEC_COMMANDS, MOVE_POSITIONS


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Expose selectors for real HA devices, never a mutable global target."""

    def resolve(device_id: str):
        device, entry = service.async_get_device_and_config_entry(hass, DOMAIN, device_id)
        coordinator = entry.runtime_data
        keys = [key for key in coordinator.displays
                if (DOMAIN, f"{entry.entry_id}_{key}") in device.identifiers]
        if len(keys) != 1:
            raise ServiceValidationError("Choose a configured display, virtual screen or group device")
        return coordinator, keys[0]

    async def perform(call: ServiceCall) -> None:
        if call.service == "set_all_brightness":
            entry = service.async_get_config_entry(hass, DOMAIN, call.data["config_entry_id"])
            coordinator = entry.runtime_data
            keys = tuple(key for key, target in coordinator.displays.items()
                         if target.device_type == "Display"
                         and coordinator.capability(key, "brightness") is not None)
            await coordinator.async_set_brightness(keys, call.data["value"])
            return
        if call.service == "apply_layout_protection":
            entry = service.async_get_config_entry(hass, DOMAIN, call.data["config_entry_id"])
            await entry.runtime_data.async_perform(MAC_KEY, "applyLayoutProtection")
            return
        coordinator, key = resolve(call.data["device_id"])
        if call.service == "set_brightness":
            await coordinator.async_set_brightness((key,), call.data["value"])
            return
        other_key = None
        if "target_device_id" in call.data:
            other_coordinator, other_key = resolve(call.data["target_device_id"])
            if coordinator is not other_coordinator:
                raise ServiceValidationError("Both devices must belong to the same Mac integration entry")
        action, field = {
            "move_display": ("moveTo", "position"),
            "set_virtual_screen_association": ("associated", "associated"),
            "apply_favorite_mode": ("favoriteMode", "slot"),
            "switch_input": ("changeInputSource", "choice"),
            "send_cec": ("sendCEC", "command"),
            "toggle_mute": ("muteToggle", None),
        }[call.service]
        await coordinator.async_perform(
            key, action, value=call.data[field] if field is not None else None,
            other_key=other_key,
        )

    device = {probatio.Required("device_id"): cv.string}
    pair = {**device, probatio.Required("target_device_id"): cv.string}
    brightness = {probatio.Required("value"): probatio.All(probatio.Any(int, float), probatio.Range(min=0, max=100))}
    schemas = {
        "set_brightness": {**device, **brightness},
        "set_all_brightness": {probatio.Required("config_entry_id"): cv.string, **brightness},
        "move_display": {**pair, probatio.Required("position"): probatio.In(MOVE_POSITIONS)},
        "set_virtual_screen_association": {**pair, probatio.Required("associated"): cv.boolean},
        "apply_favorite_mode": {**device, probatio.Required("slot"): probatio.All(int, probatio.Range(min=1, max=5))},
        "switch_input": {**device, probatio.Required("choice"): cv.string},
        "send_cec": {**device, probatio.Required("command"): probatio.In(CEC_COMMANDS)},
        "toggle_mute": device,
        "apply_layout_protection": {
            probatio.Required("config_entry_id"): cv.string,
            probatio.Required("confirm_global"): probatio.Equal(True),
        },
    }
    for name, schema in schemas.items():
        if name in ("move_display", "set_virtual_screen_association", "apply_layout_protection"):
            service.async_register_admin_service(
                hass, DOMAIN, name, perform, schema=probatio.Schema(schema),
            )
        else:
            hass.services.async_register(DOMAIN, name, perform, schema=probatio.Schema(schema))
