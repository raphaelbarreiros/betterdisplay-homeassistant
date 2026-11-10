"""Shared configuration keys for BetterDisplay for Home Assistant."""

DOMAIN = "betterdisplay_homeassistant"
NAME = "BetterDisplay for Home Assistant"
VERSION = "0.1.1"
DEFAULT_PORT = 55777
CONF_LABEL = "label"
CONF_TOKEN = "token"
CONF_DISPLAYS = "displays"
CONF_SELECTION_MODE = "selection_mode"
CONF_FAMILIES = "families"
CONF_CAPABILITIES = "capabilities"
CONF_WEBHOOKS = "webhooks"
MODE_ALL = "all"
MODE_SELECTED = "selected"
MODE_MAC_ONLY = "mac_only"
MAC_KEY = "mac"
DEFAULT_FAMILIES = ("basic", "audio", "sensors")
OPTIONAL_FAMILIES = (
    "power", "input", "modes", "image", "hdr", "connections", "virtual",
    "groups", "layout", "cec", "mac",
)
