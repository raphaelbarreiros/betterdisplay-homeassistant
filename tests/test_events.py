"""Explicit event enrollment and real HA webhook HTTP delivery."""

import json

import pytest
from homeassistant.data_entry_flow import FlowResultType

from test_integration import configure, entity


async def events(hass, entry, keys):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "events"})
    assert result["step_id"] == "events"
    return await hass.config_entries.options.async_configure(result["flow_id"], {"display_ids": keys})


async def save_events(hass, entry, keys):
    result = await events(hass, entry, keys)
    assert result["step_id"] == "events_confirm", result
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_event_opt_in_requires_internal_url_and_does_not_scan(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    mac.requests.clear()
    hass.config.internal_url = None
    hass.config.external_url = None
    hass.config.api = None
    result = await events(hass, entry, ["1:uuid-one"])
    assert result["step_id"] == "events"
    assert result["errors"]["base"] == "internal_url_required"
    assert not entry.options.get("webhooks")
    assert not mac.requests


async def test_webhook_confirmation_is_private_and_ids_are_stable_until_opt_out(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    hass.config.internal_url = "http://homeassistant.test:8123"
    mac.requests.clear()
    result = await events(hass, entry, ["1:uuid-one"])
    assert result["step_id"] == "events_confirm"
    assert not entry.options.get("webhooks")
    placeholders = json.dumps(result["description_placeholders"])
    assert "http://homeassistant.test:8123/api/webhook/" in placeholders
    assert "?hook=[*:EVENT_HOOK:*]" in placeholders
    assert "displayID=" not in placeholders
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    identifier = entry.options["webhooks"]["1:uuid-one"]
    assert len(identifier) >= 43
    await save_events(hass, entry, ["1:uuid-one"])
    assert entry.options["webhooks"]["1:uuid-one"] == identifier
    state = hass.states.get(entity(hass, entry, "1:uuid-one_event", "event"))
    assert identifier not in json.dumps(dict(state.attributes))
    await save_events(hass, entry, [])
    assert not entry.options["webhooks"]
    await save_events(hass, entry, ["1:uuid-one"])
    assert entry.options["webhooks"]["1:uuid-one"] != identifier
    assert not mac.requests


@pytest.mark.parametrize(("hook", "event_type"), [
    ("softDisconnect", "soft_disconnect"), ("softReconnect", "soft_reconnect"),
    ("hardDisconnect", "hard_disconnect"), ("hardReconnect", "hard_reconnect"),
    ("systemSleep", "system_sleep"), ("systemWakeImmediate", "system_wake_immediate"),
    ("systemWake", "system_wake"),
])
async def test_get_webhook_delivers_only_selected_event_without_outbound_requests(hass, hass_client, mac_factory, hook, event_type):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    hass.config.internal_url = "http://homeassistant.test:8123"
    await save_events(hass, entry, ["1:uuid-one", "2:uuid-two"])
    client = await hass_client()
    mac.requests.clear()
    identifier = entry.options["webhooks"]["1:uuid-one"]
    response = await client.get(f"/api/webhook/{identifier}", params={"hook": hook})
    assert response.status == 200
    await hass.async_block_till_done()
    state = hass.states.get(entity(hass, entry, "1:uuid-one_event", "event"))
    assert state.attributes["event_type"] == event_type
    other = hass.states.get(entity(hass, entry, "2:uuid-two_event", "event"))
    assert other.state == "unknown"
    assert not mac.requests


async def test_webhook_malformed_post_and_opted_out_ids_never_trigger(hass, hass_client, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    hass.config.internal_url = "http://homeassistant.test:8123"
    await save_events(hass, entry, ["1:uuid-one"])
    old_id = entry.options["webhooks"]["1:uuid-one"]
    client = await hass_client()
    event_id = entity(hass, entry, "1:uuid-one_event", "event")
    mac.requests.clear()
    for query in ([], [("hook", "unknown")], [("hook", "systemWake"), ("hook", "systemSleep")], [("hook", "")]):
        await client.get(f"/api/webhook/{old_id}", params=query)
        await hass.async_block_till_done()
        assert hass.states.get(event_id).state == "unknown"
    await client.post(f"/api/webhook/{old_id}", params={"hook": "systemWake"})
    await hass.async_block_till_done()
    assert hass.states.get(event_id).state == "unknown"
    await save_events(hass, entry, [])
    await save_events(hass, entry, ["1:uuid-one"])
    await client.get(f"/api/webhook/{old_id}", params={"hook": "systemWake"})
    await hass.async_block_till_done()
    assert hass.states.get(entity(hass, entry, "1:uuid-one_event", "event")).state == "unknown"
    assert not mac.requests


async def test_local_only_webhook_rejects_public_forwarded_source(hass, hass_client_no_auth, mac_factory):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "http", {"http": {
        "use_x_forwarded_for": True, "trusted_proxies": ["127.0.0.1", "::1"],
    }})
    mac = await mac_factory()
    entry = await configure(hass, mac)
    hass.config.internal_url = "http://homeassistant.test:8123"
    await save_events(hass, entry, ["1:uuid-one"])
    client = await hass_client_no_auth()
    identifier = entry.options["webhooks"]["1:uuid-one"]
    mac.requests.clear()
    await client.get(f"/api/webhook/{identifier}", params={"hook": "systemWake"}, headers={"X-Forwarded-For": "8.8.8.8"})
    await hass.async_block_till_done()
    event_id = entity(hass, entry, "1:uuid-one_event", "event")
    assert hass.states.get(event_id).state == "unknown"
    response = await client.get(f"/api/webhook/{identifier}", params={"hook": "systemWake"})
    assert response.status == 200
    await hass.async_block_till_done()
    assert hass.states.get(event_id).attributes["event_type"] == "system_wake"
    assert not mac.requests


async def test_deselection_removes_webhook_and_old_url_stays_inert(hass, hass_client, mac_factory):
    from test_integration import rescan

    mac = await mac_factory()
    entry = await configure(hass, mac)
    hass.config.internal_url = "http://homeassistant.test:8123"
    await save_events(hass, entry, ["1:uuid-one", "2:uuid-two"])
    removed_id = entry.options["webhooks"]["2:uuid-two"]
    retained_id = entry.options["webhooks"]["1:uuid-one"]
    result = await rescan(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "selection_mode": "selected", "display_ids": ["1:uuid-one"],
    })
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.options["webhooks"] == {"1:uuid-one": retained_id}
    client = await hass_client()
    mac.requests.clear()
    await client.get(f"/api/webhook/{removed_id}", params={"hook": "systemWake"})
    await hass.async_block_till_done()
    assert hass.states.get(entity(hass, entry, "1:uuid-one_event", "event")).state == "unknown"
    assert not mac.requests
