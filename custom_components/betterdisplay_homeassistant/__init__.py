"""BetterDisplay for Home Assistant: explicit per-Mac configuration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BetterDisplayClient, Display
from .const import (
    CONF_DISPLAYS, CONF_FAMILIES, CONF_SELECTION_MODE, CONF_TOKEN, DOMAIN, MODE_MAC_ONLY,
)
from .coordinator import BetterDisplayCoordinator
from .event import setup_webhooks
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = (
    Platform.NUMBER, Platform.SWITCH, Platform.SELECT, Platform.SENSOR,
    Platform.BINARY_SENSOR, Platform.BUTTON, Platform.EVENT,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Load saved capabilities without probing or enabling setup retry timers."""
    try:
        selected = [Display.from_dict(item) for item in entry.options[CONF_DISPLAYS]]
        displays = {display.key: display for display in selected}
        if len(displays) != len(selected):
            raise ValueError("Ambiguous selection")
        if not selected and not (
            entry.options.get(CONF_SELECTION_MODE) == MODE_MAC_ONLY
            and "mac" in entry.options.get(CONF_FAMILIES, [])
        ):
            raise ValueError("Empty selection")
        client = BetterDisplayClient(
            async_get_clientsession(hass), entry.data[CONF_HOST],
            entry.data[CONF_PORT], entry.data[CONF_TOKEN],
        )
        coordinator = BetterDisplayCoordinator(hass, entry, client, displays)
    except (KeyError, TypeError, ValueError):
        raise ConfigEntryError("Invalid saved configuration; reconfigure BetterDisplay") from None
    entry.runtime_data = coordinator
    registry = dr.async_get(hass)
    coordinator.mac_device_id = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title, manufacturer="BetterDisplay", model="Mac HTTP connection",
    ).id
    wanted_devices = {(DOMAIN, entry.entry_id)} | {
        (DOMAIN, f"{entry.entry_id}_{key}") for key in displays
    }
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers.intersection(wanted_devices):
            registry.async_remove_device(device.id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if (entity.entity_id.partition(".")[0] in coordinator.completed_platforms
                and entity.unique_id not in coordinator.registered_unique_ids):
            entity_registry.async_remove(entity.entity_id)
    setup_webhooks(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator: BetterDisplayCoordinator = entry.runtime_data
    await coordinator.async_stop()
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
