"""Real HA connection actions with disappearing displays and changing tags."""
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.betterdisplay_homeassistant import coordinator
from test_features import BASE, enable, switch
from test_integration import configure, entity, refresh, rescan, set_value


@pytest.fixture(autouse=True)
def fast_connection_confirmation(monkeypatch):
    monkeypatch.setattr(coordinator, "CONNECTION_CONFIRM_INTERVAL", 0.001)


@pytest.mark.parametrize("missing_readback", [True, False])
async def test_round_trip_reconnects_uuid_when_off_disappears_and_tags_change(hass, mac_factory, missing_readback):
    mac = await mac_factory(
        pro="on", simulate_connections=True,
        missing_connection_readback=missing_readback,
        values={"1": {"connected": "on"}, "2": {"connected": "on"}},
        reconnect_tags={"uuid-one": "101", "uuid-two": "202"},
    )
    entry = await configure(hass, mac, families=BASE + ["connections"])
    first = await enable(hass, entry, "1:uuid-one_connected", "switch")
    second = await enable(hass, entry, "2:uuid-two_connected", "switch")
    await switch(hass, entry, "1:uuid-one_connected")
    await switch(hass, entry, "2:uuid-two_connected", False)
    assert hass.states.get(first).state == "on"
    assert hass.states.get(second).state == "off"
    assert "uuid-two" in mac.disconnected

    await switch(hass, entry, "2:uuid-two_connected")
    assert hass.states.get(second).state == "on"
    assert any(d["UUID"] == "uuid-two" and d["tagID"] == "202" for d in mac.displays)
    await switch(hass, entry, "1:uuid-one_connected", False)
    assert hass.states.get(first).state == "off"
    await switch(hass, entry, "1:uuid-one_connected")
    await switch(hass, entry, "2:uuid-two_connected", False)
    assert hass.states.get(first).state == "on"
    assert hass.states.get(second).state == "off"
    assert [(query["UUID"], query["connected"]) for _, query in mac.commands] == [
        ("UUID-TWO", "off"), ("UUID-TWO", "on"), ("UUID-ONE", "off"),
        ("UUID-ONE", "on"), ("UUID-TWO", "off"),
    ]
    assert all("tagID" not in query for _, query in mac.commands)
    await set_value(hass, entry, 37, "1:uuid-one_brightness")
    assert mac.writes == [("101", "uuid-one", 0.37)]


async def test_restart_and_refresh_keep_disconnected_recovery_switch_actionable(hass, mac_factory):
    mac = await mac_factory(pro="on", simulate_connections=True, values={"1": {"connected": "on"}})
    entry = await configure(hass, mac, families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.disconnect("uuid-one")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(control).state == "unknown"
    await refresh(hass, entry)
    assert hass.states.get(control).state == "off"
    assert hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state == "unavailable"
    await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "on"
    assert len(mac.commands) == 1


async def test_confirmation_timeout_never_replays_write_or_disables_recovery(hass, mac_factory, monkeypatch):
    monkeypatch.setattr(coordinator, "CONNECTION_CONFIRM_TIMEOUT", 0.05)
    mac = await mac_factory(
        pro="on", simulate_connections=True, never_reconnect=True,
        values={"1": {"connected": "on"}}, reconnect_delay_reads=0,
    )
    entry = await configure(hass, mac, families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.disconnect("uuid-one")
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "off"
    assert len(mac.commands) == 1
    request_count = len(mac.requests)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=2))
    await hass.async_block_till_done()
    assert len(mac.requests) == request_count
    assert len(mac.commands) == 1
    mac.never_reconnect = False
    await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "on"


async def test_failed_request_can_be_retried_explicitly_without_refresh(hass, mac_factory):
    mac = await mac_factory(pro="on", simulate_connections=True, values={"1": {"connected": "on"}})
    entry = await configure(hass, mac, families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.disconnect("uuid-one")
    mac.fail_sets.add("1")
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "unknown"
    mac.fail_sets.clear()
    await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "on"
    assert [query["connected"] for _, query in mac.commands] == ["on", "on"]


async def test_missing_uuid_never_falls_back_to_reused_tag(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"connected": "on"}})
    entry = await configure(hass, mac, families=BASE + ["connections"])
    await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.displays[0]["UUID"] = "different-display"
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "1:uuid-one_connected")
    assert mac.commands == []
    sent = [query for path, query in mac.requests if path == "/set"]
    assert sent and all(query["UUID"] == "UUID-ONE" and "tagID" not in query for query in sent)


async def test_rescan_after_tag_change_preserves_legacy_entity_ids_and_names(hass, mac_factory):
    mac = await mac_factory(
        pro="on", simulate_connections=True, values={"1": {"connected": "on"}},
        reconnect_tags={"uuid-one": "101"},
    )
    entry = await configure(hass, mac, mode="selected", ids=["1:uuid-one"], families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    registry = er.async_get(hass)
    registry.async_update_entity(control, name="Existing Odyssey connection")
    old_device_id = registry.async_get(control).device_id
    # Model a 0.1.0 entry: it has no explicit entity_key metadata.
    old_displays = [{key: value for key, value in item.items() if key != "entity_key"}
                    for item in entry.options["displays"]]
    hass.config_entries.async_update_entry(entry, options={**entry.options, "displays": old_displays})
    mac.disconnect("uuid-one")
    await switch(hass, entry, "1:uuid-one_connected")
    result = await rescan(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "selection_mode": "selected", "display_ids": ["101:uuid-one"],
    })
    assert result["step_id"] == "confirm"
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.options["displays"][0]["tag_id"] == "101"
    assert entity(hass, entry, "1:uuid-one_connected", "switch") == control
    assert registry.async_get(control).device_id == old_device_id
    assert registry.async_get(control).name == "Existing Odyssey connection"
    await switch(hass, entry, "1:uuid-one_connected", False)
    assert hass.states.get(control).state == "off"


async def test_manual_rescan_retains_verified_configured_disconnected_display(hass, mac_factory):
    mac = await mac_factory(
        pro="on", simulate_connections=True, missing_connection_readback=False,
        values={"1": {"connected": "on"}},
    )
    entry = await configure(hass, mac, families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.disconnect("uuid-one")
    result = await rescan(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"selection_mode": "all"})
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entity(hass, entry, "1:uuid-one_connected", "switch") == control
    await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "on"


async def test_pro_expiry_reports_an_error_instead_of_silently_skipping_reconnect(hass, mac_factory):
    mac = await mac_factory(pro="on", simulate_connections=True, values={"1": {"connected": "on"}})
    entry = await configure(hass, mac, families=BASE + ["connections"])
    control = await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.disconnect("uuid-one")
    mac.pro = "off"
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "off"
    assert mac.commands == []
    mac.pro = "on"
    await switch(hass, entry, "1:uuid-one_connected")
    assert hass.states.get(control).state == "on"
