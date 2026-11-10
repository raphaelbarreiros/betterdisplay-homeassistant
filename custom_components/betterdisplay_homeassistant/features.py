"""Explicitly supported controls, licensing and command allowlists."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import Display


@dataclass(frozen=True)
class Feature:
    """Immutable description; no arbitrary API parameters are exposed."""

    key: str
    name: str
    platform: str
    scopes: tuple[str, ...]
    family: str
    pro: bool = False
    risky: bool = False
    normalized: bool = False
    operation: str = "set"
    read_feature: str | None = None
    list_feature: str | None = None
    unit: str | None = None


DEFAULT_FAMILIES = ("basic", "audio", "sensors")
OPTIONAL_FAMILIES = ("power", "input", "modes", "image", "hdr", "connections", "virtual", "groups", "layout", "cec", "mac")
MAC_KEY = "mac"
DISPLAY = ("Display",)
GROUP = ("DisplayGroup",)
MAC = ("Mac",)
MOVE_POSITIONS = (
    "topLeftCorner", "topLeft", "top", "topRight", "topRightCorner",
    "leftTop", "left", "leftBottom", "rightTop", "right", "rightBottom",
    "bottomLeftCorner", "bottomLeft", "bottom", "bottomRight", "bottomRightCorner",
)
CEC_COMMANDS = (
    "volumeUp", "volumeDown", "mute", "standby", "wake", "input", "select",
    "up", "down", "left", "right", "rootMenu", "setupMenu", "contentsMenu", "exit",
)

_FEATURES = (
    Feature("brightness", "Brightness", "number", DISPLAY, "basic", normalized=True, unit="%"),
    Feature("autoBrightness", "Auto brightness", "switch", DISPLAY, "basic"),
    Feature("volume", "Volume", "number", DISPLAY, "audio", normalized=True, unit="%"),
    Feature("mute", "Mute", "switch", DISPLAY, "audio"),
    Feature("muteToggle", "Toggle mute (state unknown)", "button", DISPLAY, "audio", operation="toggle"),
    Feature("hardwareBacklight", "Screen backlight", "switch", DISPLAY, "power", risky=True),
    Feature("displayModeNumber", "Display mode", "select", DISPLAY, "modes", risky=True, list_feature="displayModeList"),
    Feature("refreshRate", "Refresh rate", "select", DISPLAY, "modes", risky=True, list_feature="refreshRateList"),
    Feature("hiDPI", "HiDPI", "switch", DISPLAY, "modes", risky=True),
    Feature("temperature", "Color temperature adjustment", "number", DISPLAY, "image", pro=True, normalized=True, unit="%"),
    Feature("hdr", "HDR", "switch", DISPLAY, "hdr", pro=True, risky=True),
    Feature("brightnessUpscaling", "Brightness upscaling", "switch", DISPLAY, "hdr", pro=True, risky=True),
    Feature("directBrightnessUpscaling", "Direct brightness upscaling", "switch", DISPLAY, "hdr", pro=True, risky=True),
    Feature("ambientLight", "Ambient light", "sensor", DISPLAY, "sensors", pro=True, operation="get", unit="lx"),
    Feature("main", "Main display", "binary_sensor", DISPLAY, "sensors", operation="get"),
    Feature("setMain", "Set as main display", "button", DISPLAY, "layout", risky=True),
    Feature("nightShift", "Night Shift", "switch", MAC, "mac", pro=True),
    Feature("nightShiftValue", "Night Shift strength", "number", MAC, "mac", pro=True, normalized=True, unit="%"),
    Feature("trueTone", "True Tone", "switch", MAC, "mac", pro=True),
    Feature("darkMode", "Dark Mode", "switch", MAC, "mac", pro=True),
    Feature("colorProfileURL", "Color profile", "select", DISPLAY, "image", risky=True, list_feature="installedColorProfileURLs"),
    Feature("xdrPreset", "Display preset", "select", DISPLAY, "image", risky=True, list_feature="xdrPresetList"),
    Feature("connected", "Connected", "switch", ("Display", "VirtualScreen"), "connections", risky=True),
    Feature("associatedDisplays", "Associated displays", "sensor", ("VirtualScreen",), "sensors", operation="get"),
    Feature("enabled", "Group enabled", "switch", GROUP, "groups", risky=True),
    Feature("active", "Group active", "binary_sensor", GROUP, "sensors", operation="get"),
    Feature("synchronization", "Group synchronization", "switch", GROUP, "groups", risky=True),
    Feature("layoutProtection", "Group layout protection", "switch", GROUP, "groups", pro=True, risky=True),
    Feature("uiScaleMatching", "Group UI scale matching", "switch", GROUP, "groups", pro=True, risky=True),
    Feature("rotation", "Rotation", "select", DISPLAY, "layout", pro=True, risky=True),
    Feature("favoriteMode", "Apply favorite mode", "button", DISPLAY, "layout", pro=True, risky=True),
    Feature("moveTo", "Move display", "button", DISPLAY, "layout", pro=True, risky=True, operation="perform"),
    Feature("associated", "Set virtual screen association", "button", ("VirtualScreen",), "virtual", pro=True, risky=True),
    Feature("applyLayoutProtection", "Apply layout protection", "button", MAC, "layout", pro=True, risky=True, operation="perform"),
    Feature("changeInputSource", "Switch input", "button", DISPLAY, "input", risky=True, operation="perform", list_feature="inputSourceList"),
    Feature("sendCEC", "Send TV command", "button", DISPLAY, "cec", risky=True, operation="perform"),
)
CATALOG: dict[str, Feature] = {feature.key: feature for feature in _FEATURES}
for _key, _name, _pro in (
    ("hardwareContrast", "Hardware contrast", False), ("contrast", "Software contrast", False),
    ("gamma", "Gamma", True), ("gain", "Gain", True),
    ("rGamma", "Red gamma", True), ("gGamma", "Green gamma", True), ("bGamma", "Blue gamma", True),
    ("rGain", "Red gain", True), ("gGain", "Green gain", True), ("bGain", "Blue gain", True),
    ("redHardwareGain", "Hardware red gain", False), ("greenHardwareGain", "Hardware green gain", False),
    ("blueHardwareGain", "Hardware blue gain", False),
    ("redHardwareBlackLevel", "Hardware red black level", False),
    ("greenHardwareBlackLevel", "Hardware green black level", False),
    ("blueHardwareBlackLevel", "Hardware blue black level", False),
):
    CATALOG[_key] = Feature(_key, _name, "number", DISPLAY, "image", pro=_pro, risky=True, normalized=True, unit="%")
del _key, _name, _pro


def pro_required(feature: str, target: Display | None) -> bool:
    """Return conservative, scope-aware write licensing requirements."""
    definition = CATALOG[feature]
    if feature == "connected":
        return target is None or target.device_type == "Display"
    if feature in ("enabled", "synchronization"):
        return target is None or target.device_type != "DisplayGroup" or target.tag_id != "-1001"
    return definition.pro


def family_for(feature: str, target: Display | None) -> str:
    """Resolve consent consistently for controls shared across device types."""
    definition = CATALOG[feature]
    if feature == "connected" and target is not None and target.device_type == "VirtualScreen":
        return "virtual"
    return definition.family
