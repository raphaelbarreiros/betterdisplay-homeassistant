"""Regression coverage at config/options flows and native HA actions only."""

from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

DOMAIN = "betterdisplay_homeassistant"


async def begin(hass, mac, **overrides):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER},
        data=mac.config | overrides,
    )


async def configure(hass, mac, mode="all", ids=None, **overrides):
    result = await begin(hass, mac, **overrides)
    assert result["step_id"] == "targets", result
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"selection_mode": mode, "display_ids": ids or []},
    )
    assert result["step_id"] == "confirm", result
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def rescan(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "rescan"})
    assert result["step_id"] == "rescan"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"families": entry.options["families"]})
    assert result["step_id"] == "targets"
    return result


def entity(hass, entry, suffix, platform="number"):
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")
    assert entity_id is not None, (entry.entry_id, suffix)
    return entity_id


async def refresh(hass, entry):
    await hass.services.async_call("button", "press", {
        "entity_id": entity(hass, entry, "refresh", "button"),
    }, blocking=True)
    await hass.async_block_till_done()


async def set_value(hass, entry, value, suffix="all_brightness"):
    await hass.services.async_call("number", "set_value", {
        "entity_id": entity(hass, entry, suffix), "value": value,
    }, blocking=True)
    await hass.async_block_till_done()


def selected(entry):
    return {(display["tag_id"], display["uuid"]) for display in entry.options["displays"]}


async def test_explicit_selection_rejects_empty_and_foreign_ids(hass, mac_factory):
    mac = await mac_factory()
    result = await begin(hass, mac)
    assert result["step_id"] == "targets"
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(result["flow_id"], {
            "selection_mode": "selected", "display_ids": ["99:foreign"],
        })
    for ids in ([], ["1:uuid-one", "1:uuid-one"]):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "selection_mode": "selected", "display_ids": ids,
        })
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "selection_mode": "selected", "display_ids": ["1:uuid-one"],
    })
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert selected(result["result"]) == {("1", "uuid-one")}
    assert not mac.writes


async def test_all_is_snapshot_until_confirmed_options_scan(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac, ids=["1:uuid-one"])
    assert selected(entry) == {("1", "uuid-one"), ("2", "uuid-two")}
    mac.displays.append({"deviceType": "Display", "tagID": "3", "UUID": "uuid-three", "name": "New"})
    mac.brightness["3"] = "0.8"
    await refresh(hass, entry)
    await set_value(hass, entry, 55)
    assert mac.writes == [("1", "uuid-one", 0.55), ("2", "uuid-two", 0.55)]
    assert selected(entry) == {("1", "uuid-one"), ("2", "uuid-two")}
    result = await rescan(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"selection_mode": "all", "display_ids": []})
    assert result["step_id"] == "confirm"
    assert len(selected(entry)) == 2
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert selected(entry) == {("1", "uuid-one"), ("2", "uuid-two"), ("3", "uuid-three")}
    await set_value(hass, entry, 65)
    assert mac.writes[-3:] == [("1", "uuid-one", 0.65), ("2", "uuid-two", 0.65), ("3", "uuid-three", 0.65)]


async def test_multiple_macs_with_same_display_ids_are_isolated(hass, mac_factory):
    first, second = await mac_factory(), await mac_factory()
    a, b = await configure(hass, first), await configure(hass, second)
    assert entity(hass, a, "1:uuid-one_brightness") != entity(hass, b, "1:uuid-one_brightness")
    await set_value(hass, a, 31, "1:uuid-one_brightness")
    assert first.writes == [("1", "uuid-one", 0.31)]
    assert second.writes == []
    await set_value(hass, b, 72)
    assert second.writes == [("1", "uuid-one", 0.72), ("2", "uuid-two", 0.72)]
    assert len(first.writes) == 1


async def test_reload_and_time_passage_do_not_request_network_but_control_does(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    mac.requests.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert mac.requests == []
    assert hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state == "unknown"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=2))
    await hass.async_block_till_done()
    assert mac.requests == []
    await set_value(hass, entry, 45, "1:uuid-one_brightness")
    assert mac.writes == [("1", "uuid-one", 0.45)]
    assert float(hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state) == 45
    assert mac.requests[0][0] == "/get"
    first_write = next(i for i, (path, _) in enumerate(mac.requests) if path == "/set")
    assert any("identifiers" in query for _, query in mac.requests[:first_write])
    assert any("brightness" in query for _, query in mac.requests[:first_write])


async def test_partial_failure_surfaces_without_replay(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    await refresh(hass, entry)
    mac.fail_sets.add("2")
    with pytest.raises(HomeAssistantError):
        await set_value(hass, entry, 57)
    assert mac.writes == [("1", "uuid-one", 0.57), ("2", "uuid-two", 0.57)]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1))
    await hass.async_block_till_done()
    assert len(mac.writes) == 2
    assert hass.states.get(entity(hass, entry, "all_brightness")).state in {"unknown", "unavailable"}


async def test_missing_identity_blocks_entire_aggregate_preflight(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    await refresh(hass, entry)
    mac.displays[0]["UUID"] = "replacement"
    with pytest.raises(HomeAssistantError):
        await set_value(hass, entry, 50)
    assert not mac.writes
    assert float(hass.states.get(entity(hass, entry, "2:uuid-two_brightness")).state) == 60
    await set_value(hass, entry, 42, "2:uuid-two_brightness")
    assert mac.writes == [("2", "uuid-two", 0.42)]


async def test_options_deselection_preserves_retained_customizations(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    registry = er.async_get(hass)
    kept_id = entity(hass, entry, "1:uuid-one_brightness")
    removed_id = entity(hass, entry, "2:uuid-two_brightness")
    kept = registry.async_get(kept_id)
    registry.async_update_entity(kept_id, name="My desk brightness")
    devices = dr.async_get(hass)
    area = ar.async_get(hass).async_create("Office")
    devices.async_update_device(kept.device_id, name_by_user="My desk display", area_id=area.id)
    result = await rescan(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "selection_mode": "selected", "display_ids": ["1:uuid-one"],
    })
    assert result["step_id"] == "confirm"
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entity(hass, entry, "1:uuid-one_brightness") == kept_id
    assert registry.async_get(kept_id).name == "My desk brightness"
    assert devices.async_get(kept.device_id).name_by_user == "My desk display"
    assert devices.async_get(kept.device_id).area_id == area.id
    assert registry.async_get(removed_id) is None
    await set_value(hass, entry, 48)
    assert mac.writes == [("1", "uuid-one", 0.48)]


@pytest.mark.parametrize("failure", ["auth", "malformed", "unreadable"])
async def test_invalid_probe_never_creates_defaults(hass, mac_factory, failure):
    mac = await mac_factory()
    overrides = {}
    if failure == "auth":
        overrides["token"] = "wrong-token"
    elif failure == "malformed":
        mac.discovery_body = "not identifiers"
    else:
        mac.brightness = {"1": "nan", "2": "Failed."}
    result = await begin(hass, mac, **overrides)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not mac.writes


async def test_reconfigure_cannot_rebind_to_different_uuid(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    replacement = await mac_factory(displays=[
        {"deviceType": "Display", "tagID": "1", "UUID": "other-one", "name": "Desk"},
        {"deviceType": "Display", "tagID": "2", "UUID": "other-two", "name": "Desk"},
    ])
    old_data = dict(entry.data)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={
        "source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id,
    })
    result = await hass.config_entries.flow.async_configure(result["flow_id"], replacement.config)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "identity_mismatch"
    assert dict(entry.data) == old_data
    assert not mac.writes and not replacement.writes


async def test_all_includes_only_brightness_capable_system_displays(hass, mac_factory):
    mac = await mac_factory()
    mac.displays.extend([
        {"deviceType": "DisplayGroup", "tagID": "3", "UUID": "group", "name": "Group"},
        {"deviceType": "Display", "tagID": "4", "UUID": "unsupported", "name": "No brightness"},
    ])
    entry = await configure(hass, mac)
    assert selected(entry) == {("1", "uuid-one"), ("2", "uuid-two")}
    await refresh(hass, entry)
    assert hass.states.get(entity(hass, entry, "pro_available", "binary_sensor")).state == "off"
    mac.pro = "unsupported"
    await refresh(hass, entry)
    assert hass.states.get(entity(hass, entry, "pro_available", "binary_sensor")).state in {"unknown", "unavailable"}
    await set_value(hass, entry, 39)
    assert mac.writes == [("1", "uuid-one", 0.39), ("2", "uuid-two", 0.39)]
