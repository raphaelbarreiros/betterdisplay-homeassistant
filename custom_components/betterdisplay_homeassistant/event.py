"""Opt-in local BetterDisplay events; receiving never initiates a request."""
from __future__ import annotations

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from .const import DOMAIN
from .entity import device_info

PARALLEL_UPDATES = 0
EVENT_TYPES = {
    "softDisconnect": "soft_disconnect",
    "softReconnect": "soft_reconnect",
    "hardDisconnect": "hard_disconnect",
    "hardReconnect": "hard_reconnect",
    "systemSleep": "system_sleep",
    "systemWakeImmediate": "system_wake_immediate",
    "systemWake": "system_wake",
}


def _signal(entry_id: str, key: str) -> str:
    return f"{DOMAIN}_{entry_id}_{key}_event"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([BetterDisplayEvent(coordinator, key)
                        for key in entry.options.get("webhooks", {})
                        if key in coordinator.displays
                        and coordinator.displays[key].device_type == "Display"])
    coordinator.completed_platforms.add("event")


@callback
def setup_webhooks(hass, entry) -> None:
    """Register exactly the saved endpoints and clean them up on entry unload."""
    coordinator = entry.runtime_data
    for key, webhook_id in entry.options.get("webhooks", {}).items():
        if (key not in coordinator.displays
                or coordinator.displays[key].device_type != "Display"
                or not isinstance(webhook_id, str) or not webhook_id):
            continue

        async def handle(hass, received_id, request, *, target=key, expected_id=webhook_id):
            if (coordinator.stopped or not coordinator.permits((target,))
                    or entry.options.get("webhooks", {}).get(target) != expected_id
                    or received_id != expected_id or request.method != "GET"):
                return web.Response(status=200)
            hooks = request.query.getall("hook", [])
            if len(hooks) == 1 and hooks[0] in EVENT_TYPES:
                async_dispatcher_send(hass, _signal(entry.entry_id, target), EVENT_TYPES[hooks[0]])
            return web.Response(status=200)

        webhook.async_register(hass, DOMAIN, "BetterDisplay event", webhook_id, handle,
                               allowed_methods=["GET"], local_only=True)
        entry.async_on_unload(lambda identifier=webhook_id: webhook.async_unregister(hass, identifier))


class BetterDisplayEvent(EventEntity):
    _attr_has_entity_name = True
    _attr_name = "Display event"
    _attr_event_types = list(EVENT_TYPES.values())
    _attr_icon = "mdi:monitor-eye"
    _attr_should_poll = False

    def __init__(self, coordinator, key):
        self.coordinator = coordinator
        self.key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}_event"
        coordinator.registered_unique_ids.add(self._attr_unique_id)
        self._attr_device_info = device_info(coordinator, key)

    @property
    def available(self) -> bool:
        return (not self.coordinator.stopped and self.coordinator.permits((self.key,))
                and self.key in self.coordinator.entry.options.get("webhooks", {}))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, _signal(self.coordinator.entry.entry_id, self.key), self._receive))

    @callback
    def _receive(self, event_type: str) -> None:
        if self.available and event_type in self._attr_event_types:
            self._trigger_event(event_type)
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        return {"state_source": "BetterDisplay local event; not a live connection state"}
