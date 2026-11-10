"""Consumer-facing feature controls exercised against a local HTTP Mac."""

import json
import probatio

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from test_integration import DOMAIN, begin, configure, entity, refresh, set_value

BASE = ["basic", "audio", "sensors"]


async def enable(hass, entry, suffix, platform):
    entity_id = entity(hass, entry, suffix, platform)
    registry = er.async_get(hass)
    if registry.async_get(entity_id).disabled_by is not None:
        registry.async_update_entity(entity_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    return entity_id


async def switch(hass, entry, suffix, on=True):
    entity_id = await enable(hass, entry, suffix, "switch")
    await hass.services.async_call("switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


def device(hass, entry, key):
    result = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_{key}"), entry.entry_id)
    assert result is not None, key
    return result.id


async def service(hass, name, **data):
    await hass.services.async_call(DOMAIN, name, data, blocking=True)
    await hass.async_block_till_done()


async def test_normalized_reads_require_value_and_write_has_no_value_flag(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    await refresh(hass, entry)
    assert float(hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state) == 40
    await set_value(hass, entry, 23, "1:uuid-one_brightness")
    reads = [q for path, q in mac.requests if path == "/get" and "brightness" in q]
    assert reads and all(q.get("value") == "" and q.get("min") == "0" and q.get("max") == "1" for q in reads)
    assert mac.writes == [("1", "uuid-one", 0.23)]
    assert all("value" not in q for path, q in mac.commands if path == "/set")


@pytest.mark.parametrize("value", ["nan", "inf", "-0.01", "1.01", "0.4,0.0,1.0", ""])
async def test_malformed_normalized_feature_cannot_become_a_plausible_state(hass, mac_factory, value):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    mac.brightness["1"] = value
    await refresh(hass, entry)
    assert hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state in {"unknown", "unavailable"}
    assert float(hass.states.get(entity(hass, entry, "2:uuid-two_brightness")).state) == 60
    assert not mac.commands


async def test_family_consent_prevents_optional_probe_and_entities(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"hardwareBacklight": "on", "temperature": "0.5", "connected": "on"}})
    entry = await configure(hass, mac)
    forbidden = {"hardwareBacklight", "temperature", "connected", "displayModeList", "inputSourceList"}
    assert not any(forbidden.intersection(q) for _, q in mac.requests)
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_1:uuid-one_hardwareBacklight") is None
    with pytest.raises(HomeAssistantError):
        await service(hass, "apply_favorite_mode", device_id=device(hass, entry, "1:uuid-one"), slot=1)
    assert not mac.commands


@pytest.mark.parametrize("pro", ["off", None, "unsupported"])
async def test_pro_expiry_or_unknown_blocks_previously_discovered_control(hass, mac_factory, pro):
    mac = await mac_factory(pro="on", values={"1": {"rotation": "0"}})
    entry = await configure(hass, mac, families=BASE + ["layout"])
    control = await enable(hass, entry, "1:uuid-one_rotation", "select")
    mac.pro = pro
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("select", "select_option", {"entity_id": control, "option": "90°"}, blocking=True)
    assert not mac.commands


async def test_audio_boolean_and_normalized_volume_readback(hass, mac_factory):
    mac = await mac_factory(values={"1": {"volume": "0.35", "mute": "false"}})
    entry = await configure(hass, mac)
    await refresh(hass, entry)
    assert float(hass.states.get(entity(hass, entry, "1:uuid-one_volume")).state) == 35
    assert hass.states.get(entity(hass, entry, "1:uuid-one_mute", "switch")).state == "off"
    await set_value(hass, entry, 63, "1:uuid-one_volume")
    await switch(hass, entry, "1:uuid-one_mute")
    assert mac.values["1"]["volume"] == "0.63"
    assert mac.values["1"]["mute"] in {"on", "true", "1"}
    assert hass.states.get(entity(hass, entry, "1:uuid-one_mute", "switch")).state == "on"


async def test_unsupported_mute_does_not_authorize_toggle(hass, mac_factory):
    mac = await mac_factory(values={"1": {"volume": "0.2"}})
    entry = await configure(hass, mac)
    with pytest.raises(HomeAssistantError):
        await service(hass, "toggle_mute", device_id=device(hass, entry, "1:uuid-one"))
    assert not mac.commands


async def test_brightness_failure_does_not_disable_backlight_or_connection(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"hardwareBacklight": "off", "connected": "on"}})
    entry = await configure(hass, mac, families=BASE + ["power", "connections"])
    await enable(hass, entry, "1:uuid-one_hardwareBacklight", "switch")
    await enable(hass, entry, "1:uuid-one_connected", "switch")
    mac.fail_features.add(("1", "brightness"))
    await refresh(hass, entry)
    await switch(hass, entry, "1:uuid-one_hardwareBacklight")
    await switch(hass, entry, "1:uuid-one_connected", False)
    assert mac.values["1"]["hardwareBacklight"] == "on"
    assert mac.values["1"]["connected"] == "off"
    assert hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state in {"unavailable", "unknown"}


@pytest.mark.parametrize(("feature", "ui_value", "wire"), [
    ("temperature", -100, "0"), ("temperature", 0, "0.5"), ("temperature", 100, "1"),
    ("hardwareContrast", 25, "0.25"), ("gamma", 75, "0.75"),
])
async def test_image_normalized_ranges(hass, mac_factory, feature, ui_value, wire):
    mac = await mac_factory(pro="on", values={"1": {feature: "0.5"}})
    entry = await configure(hass, mac, families=BASE + ["image"])
    await enable(hass, entry, f"1:uuid-one_{feature}", "number")
    await set_value(hass, entry, ui_value, f"1:uuid-one_{feature}")
    command = next(q for path, q in mac.commands if path == "/set" and feature in q)
    assert float(command[feature]) == float(wire)
    assert command["min"] == "0" and command["max"] == "1"
    assert float(hass.states.get(entity(hass, entry, f"1:uuid-one_{feature}")).state) == ui_value


async def test_ambient_lux_readable_without_pro_and_main_true_boolean(hass, mac_factory):
    mac = await mac_factory(values={"1": {"ambientLight": "9.0", "main": "true"}})
    entry = await configure(hass, mac)
    await refresh(hass, entry)
    light = hass.states.get(entity(hass, entry, "1:uuid-one_ambientLight", "sensor"))
    assert float(light.state) == 9
    assert light.attributes["unit_of_measurement"] == "lx"
    assert hass.states.get(entity(hass, entry, "1:uuid-one_main", "binary_sensor")).state == "on"
    assert all("min" not in q and "max" not in q for _, q in mac.requests if "ambientLight" in q)


async def test_mode_remapping_rejects_old_label_without_write(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"displayModeNumber": "0"}}, lists={"1": {"displayModeList": "0 - 1920x1080 HiDPI 60Hz 8bpc (Current)\n1 - 2560x1440 HiDPI 60Hz 8bpc\n2 - 3840x2160 60Hz Unsafe"}})
    entry = await configure(hass, mac, families=BASE + ["modes"])
    control = await enable(hass, entry, "1:uuid-one_displayModeNumber", "select")
    await refresh(hass, entry)
    options = hass.states.get(control).attributes["options"]
    assert not any("Unsafe" in option for option in options)
    desired = next(option for option in options if "2560x1440" in option)
    mac.lists["1"]["displayModeList"] = "0 - 1920x1080 HiDPI 60Hz 8bpc\n1 - 1280x720 HiDPI 60Hz 8bpc"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("select", "select_option", {"entity_id": control, "option": desired}, blocking=True)
    assert not mac.commands


async def test_refresh_labels_keep_variable_and_fractional_rates(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"refreshRate": "48-240Hz"}}, lists={"1": {"refreshRateList": "48-240Hz\n59.94Hz\n60Hz"}})
    entry = await configure(hass, mac, families=BASE + ["modes"])
    control = await enable(hass, entry, "1:uuid-one_refreshRate", "select")
    await refresh(hass, entry)
    assert set(hass.states.get(control).attributes["options"]) == {"48-240Hz", "59.94Hz", "60Hz"}
    await hass.services.async_call("select", "select_option", {"entity_id": control, "option": "59.94Hz"}, blocking=True)
    assert mac.values["1"]["refreshRate"] == "59.94Hz"


async def test_negative_group_without_uuid_is_explicit_not_all(hass, mac_factory):
    mac = await mac_factory(values={"-1001": {"enabled": "on", "active": "on", "synchronization": "off"}})
    mac.displays.append({"deviceType": "DisplayGroup", "tagID": "-1001", "name": "Default Group"})
    entry = await configure(hass, mac, families=BASE + ["groups"])
    assert all(d["device_type"] == "Display" for d in entry.options["displays"])
    assert not mac.commands


async def test_default_group_free_write_and_rename_identity_guard(hass, mac_factory):
    mac = await mac_factory(values={"-1001": {"enabled": "on", "active": "on"}})
    mac.displays.append({"deviceType": "DisplayGroup", "tagID": "-1001", "name": "Default Group"})
    entry = await configure(hass, mac, mode="selected", ids=["DisplayGroup:-1001"], families=BASE + ["groups"])
    await switch(hass, entry, "DisplayGroup:-1001_enabled", False)
    assert mac.values["-1001"]["enabled"] == "off"
    mac.commands.clear()
    mac.displays[-1]["name"] = "Renamed Group"
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "DisplayGroup:-1001_enabled")
    assert not mac.commands


async def test_virtual_association_requires_selected_same_mac_targets(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"7": {"connected": "on"}})
    mac.displays.append({"deviceType": "VirtualScreen", "tagID": "7", "name": "Virtual Desk"})
    mac.associations[("7", "1")] = "off"
    entry = await configure(hass, mac, mode="selected", ids=["1:uuid-one", "VirtualScreen:7"], families=BASE + ["virtual", "connections"])
    await service(hass, "set_virtual_screen_association", device_id=device(hass, entry, "VirtualScreen:7"), target_device_id=device(hass, entry, "1:uuid-one"), associated=True)
    assert mac.associations[("7", "1")] == "on"
    mac.commands.clear()
    with pytest.raises(HomeAssistantError):
        await service(hass, "set_virtual_screen_association", device_id=device(hass, entry, "VirtualScreen:7"), target_device_id="not-a-selected-device", associated=False)
    assert not mac.commands


async def test_typed_service_cannot_broadcast_or_cross_macs(hass, mac_factory):
    first, second = await mac_factory(pro="on"), await mac_factory(pro="on")
    a = await configure(hass, first, mode="selected", ids=["1:uuid-one"], families=BASE + ["layout"])
    b = await configure(hass, second, mode="selected", ids=["2:uuid-two"], families=BASE + ["layout"])
    with pytest.raises(HomeAssistantError):
        await service(hass, "move_display", device_id=device(hass, a, "1:uuid-one"), target_device_id=device(hass, b, "2:uuid-two"), position="right")
    with pytest.raises(HomeAssistantError):
        await service(hass, "apply_favorite_mode", device_id="all", slot=1)
    assert not first.commands and not second.commands
    await service(hass, "apply_favorite_mode", device_id=device(hass, b, "2:uuid-two"), slot=2)
    assert not first.commands
    assert len(second.commands) == 1
    path, query = second.commands[0]
    assert path == "/set" and query["favoriteMode"] == "2" and query["tagID"] == "2"


async def test_mac_only_controls_are_explicit_and_have_no_display_target(hass, mac_factory):
    mac = await mac_factory(pro="on", displays=[], brightness={}, values={"mac": {"nightShift": "off", "trueTone": "on", "darkMode": "off", "nightShiftValue": "0.5"}})
    entry = await configure(hass, mac, mode="mac_only", families=BASE + ["mac"])
    assert not entry.options["displays"]
    await switch(hass, entry, "mac_darkMode")
    assert mac.values["mac"]["darkMode"] == "on"
    assert all("tagID" not in q and "targetTagID" not in q for _, q in mac.commands)


async def test_diagnostics_redacts_endpoint_identity_profiles_and_webhooks(hass, mac_factory):
    from custom_components.betterdisplay_homeassistant.diagnostics import async_get_config_entry_diagnostics

    profile = "file:///Users/private-user/Library/ColorSync/Profiles/Secret%20Profile.icc"
    mac = await mac_factory(token="unique-secret-token", pro="on", values={"1": {"colorProfileURL": profile}}, lists={"mac": {"installedColorProfileURLs": profile}})
    entry = await configure(hass, mac, families=BASE + ["image"])
    hass.config_entries.async_update_entry(entry, options={**entry.options, "webhooks": {"1:uuid-one": "secret-webhook-identifier"}})
    await refresh(hass, entry)
    result = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (mac.token, "127.0.0.1", "uuid-one", "uuid-two", "Desk", "private-user", "Secret%20Profile", "secret-webhook-identifier"):
        assert secret not in result
    assert "brightness" in result


async def test_input_uses_refreshed_controller_specific_choice_without_false_state(hass, mac_factory):
    mac = await mac_factory(pro="on", lists={"1": {"inputSourceList": "3 - HDMI 1 [DDCController]\n3 - HDMI 2 [OtherController]"}})
    entry = await configure(hass, mac, families=BASE + ["input"])
    choice = '["DDCController","3"]'
    await service(hass, "switch_input", device_id=device(hass, entry, "1:uuid-one"), choice=choice)
    path, command = mac.commands[-1]
    assert path == "/perform"
    assert command["changeInputSource"] == "3"
    assert command["specifier"] == "DDCController"
    assert command["tagID"] == "1"
    assert er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_1:uuid-one_changeInputSource") is None
    mac.commands.clear()
    mac.lists["1"]["inputSourceList"] = "3 - DisplayPort [DDCController]"
    with pytest.raises(HomeAssistantError):
        await service(hass, "switch_input", device_id=device(hass, entry, "1:uuid-one"), choice=choice)
    assert not mac.commands


@pytest.mark.parametrize("controller", ["CECController", "DDCController"])
async def test_cec_requires_controller_evidence_and_fixed_nonbroadcast_address(hass, mac_factory, controller):
    mac = await mac_factory(pro="on", lists={"1": {"configuredControllerList": controller}})
    entry = await configure(hass, mac, families=BASE + ["cec"])
    if controller != "CECController":
        with pytest.raises(HomeAssistantError):
            await service(hass, "send_cec", device_id=device(hass, entry, "1:uuid-one"), command="standby")
        assert not mac.commands
        return
    await service(hass, "send_cec", device_id=device(hass, entry, "1:uuid-one"), command="standby")
    path, command = mac.commands[-1]
    assert path == "/perform" and command["sendCEC"] == "standby"
    assert command["CECAddress"] == "tv" and command["tagID"] == "1"


async def test_global_layout_requires_explicit_confirmation_and_family(hass, mac_factory):
    mac = await mac_factory(pro="on")
    entry = await configure(hass, mac, families=BASE + ["layout"])
    with pytest.raises(probatio.Invalid):
        await service(hass, "apply_layout_protection", config_entry_id=entry.entry_id, confirm_global=False)
    assert not mac.commands
    await service(hass, "apply_layout_protection", config_entry_id=entry.entry_id, confirm_global=True)
    path, command = mac.commands[-1]
    assert path == "/perform" and "applyLayoutProtection" in command
    assert "tagID" not in command


@pytest.mark.parametrize(("feature", "family"), [
    ("autoBrightness", "basic"), ("hiDPI", "modes"),
    ("hdr", "hdr"), ("brightnessUpscaling", "hdr"), ("directBrightnessUpscaling", "hdr"),
])
async def test_boolean_controls_have_native_readback(hass, mac_factory, feature, family):
    mac = await mac_factory(pro="on", values={"1": {feature: "false"}})
    entry = await configure(hass, mac, families=list(dict.fromkeys(BASE + [family])))
    await switch(hass, entry, f"1:uuid-one_{feature}")
    assert mac.values["1"][feature] == "on"
    assert hass.states.get(entity(hass, entry, f"1:uuid-one_{feature}", "switch")).state == "on"


async def test_color_profile_uses_exact_url_and_global_list(hass, mac_factory):
    first = "file:///Library/ColorSync/Profiles/Studio%20RGB.icc"
    second = "file:///Library/ColorSync/Profiles/Display%20P3.icc"
    mac = await mac_factory(pro="on", values={"1": {"colorProfileURL": first}}, lists={"mac": {"installedColorProfileURLs": first + "\n" + second}})
    entry = await configure(hass, mac, families=BASE + ["image"])
    control = await enable(hass, entry, "1:uuid-one_colorProfileURL", "select")
    await refresh(hass, entry)
    option = next(value for value in hass.states.get(control).attributes["options"] if "Display" in value)
    await hass.services.async_call("select", "select_option", {"entity_id": control, "option": option}, blocking=True)
    assert mac.values["1"]["colorProfileURL"] == second
    assert all("tagID" not in query for _, query in mac.requests if "installedColorProfileURLs" in query)


async def test_duplicate_discovery_tags_rejected_even_across_device_types(hass, mac_factory):
    mac = await mac_factory()
    mac.displays.append({"deviceType": "VirtualScreen", "tagID": "1", "name": "Ambiguous"})
    result = await begin(hass, mac, families=BASE + ["virtual"])
    assert result["step_id"] == "user" and result["errors"]
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not mac.commands


async def test_preset_names_are_literal_not_guessed_indices(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"1": {"xdrPreset": "Standard"}}, lists={"1": {"xdrPresetList": "Standard\nReference Video"}})
    entry = await configure(hass, mac, families=BASE + ["image"])
    control = await enable(hass, entry, "1:uuid-one_xdrPreset", "select")
    await hass.services.async_call("select", "select_option", {"entity_id": control, "option": "Reference Video"}, blocking=True)
    assert mac.values["1"]["xdrPreset"] == "Reference Video"


async def test_mac_temperature_is_one_per_mac_and_normalized(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"mac": {"nightShift": "off", "nightShiftValue": "0.5", "trueTone": "true"}})
    entry = await configure(hass, mac, families=BASE + ["mac"])
    await enable(hass, entry, "mac_nightShiftValue", "number")
    await set_value(hass, entry, 80, "mac_nightShiftValue")
    assert float(mac.values["mac"]["nightShiftValue"]) == 0.8
    await switch(hass, entry, "mac_nightShift")
    await switch(hass, entry, "mac_trueTone", False)
    assert mac.values["mac"]["nightShift"] == "on"
    assert mac.values["mac"]["trueTone"] == "off"
    assert all("tagID" not in query for _, query in mac.commands)


async def test_custom_group_write_requires_current_pro_but_virtual_connection_does_not(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"-1002": {"enabled": "on"}, "7": {"connected": "off"}})
    mac.displays.extend([
        {"deviceType": "DisplayGroup", "tagID": "-1002", "name": "Custom Group"},
        {"deviceType": "VirtualScreen", "tagID": "7", "name": "Virtual Desk"},
    ])
    entry = await configure(hass, mac, mode="selected", ids=["DisplayGroup:-1002", "VirtualScreen:7"], families=BASE + ["groups", "virtual"])
    await enable(hass, entry, "DisplayGroup:-1002_enabled", "switch")
    await enable(hass, entry, "VirtualScreen:7_connected", "switch")
    mac.pro = "off"
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "DisplayGroup:-1002_enabled", False)
    assert not mac.commands
    await switch(hass, entry, "VirtualScreen:7_connected")
    assert mac.values["7"]["connected"] == "on"


async def test_selected_nonbrightness_display_can_control_supported_audio(hass, mac_factory):
    mac = await mac_factory(brightness={}, values={"1": {"volume": "0.3"}})
    entry = await configure(hass, mac, mode="selected", ids=["1:uuid-one"])
    await set_value(hass, entry, 20, "1:uuid-one_volume")
    assert float(mac.values["1"]["volume"]) == 0.2
    assert not mac.writes


async def test_explicit_mute_toggle_opt_in_never_invents_mute_state(hass, mac_factory):
    mac = await mac_factory()
    result = await begin(hass, mac)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "selection_mode": "selected", "display_ids": ["1:uuid-one"], "mute_toggle_targets": ["1:uuid-one"],
    })
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    entry = result["result"]
    await service(hass, "toggle_mute", device_id=device(hass, entry, "1:uuid-one"))
    path, query = mac.commands[-1]
    assert path == "/toggle" and query["mute"] == "" and query["tagID"] == "1"
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_1:uuid-one_mute") is None


async def test_verified_value_survives_failure_refreshing_related_controls(hass, mac_factory):
    mac = await mac_factory()
    entry = await configure(hass, mac)
    mac.invalidate_discovery_after_set = True
    with pytest.raises(HomeAssistantError):
        await set_value(hass, entry, 53, "1:uuid-one_brightness")
    assert mac.writes == [("1", "uuid-one", 0.53)]
    assert float(hass.states.get(entity(hass, entry, "1:uuid-one_brightness")).state) == 53


async def test_replaced_virtual_uuid_requires_new_selection(hass, mac_factory):
    mac = await mac_factory(pro="on", values={"7": {"connected": "off"}})
    mac.displays.append({"deviceType": "VirtualScreen", "tagID": "7", "UUID": "virtual-old", "name": "Virtual"})
    entry = await configure(hass, mac, mode="selected", ids=["VirtualScreen:7"], families=BASE + ["virtual"])
    await enable(hass, entry, "VirtualScreen:7_connected", "switch")
    mac.displays[-1]["UUID"] = "virtual-new"
    with pytest.raises(HomeAssistantError):
        await switch(hass, entry, "VirtualScreen:7_connected")
    assert not mac.commands


async def test_platform_failure_preserves_registered_user_customizations(hass, mac_factory, monkeypatch):
    from custom_components.betterdisplay_homeassistant import number

    mac = await mac_factory()
    entry = await configure(hass, mac)
    control = entity(hass, entry, "1:uuid-one_brightness")
    registry = er.async_get(hass)
    registry.async_update_entity(control, name="Retain this control")

    async def fail_setup(*args):
        raise RuntimeError("Simulated platform startup failure")

    monkeypatch.setattr(number, "async_setup_entry", fail_setup)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(control).name == "Retain this control"


async def test_token_rejection_starts_reauth_without_background_retries(hass, mac_factory):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant.common import async_fire_time_changed

    mac = await mac_factory(pro="on", values={"mac": {"darkMode": "off"}})
    entry = await configure(hass, mac, families=BASE + ["mac"])
    await refresh(hass, entry)
    mac.token = "replacement-secret"
    with pytest.raises(HomeAssistantError):
        await refresh(hass, entry)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    reauth = next(flow for flow in flows if flow["context"]["source"] == "reauth")
    mac.requests.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1))
    await hass.async_block_till_done()
    assert mac.requests == []
    await hass.config_entries.flow.async_configure(reauth["flow_id"], {"token": mac.token})
    await hass.async_block_till_done()
    await refresh(hass, entry)
    assert hass.states.get(entity(hass, entry, "mac_darkMode", "switch")).state == "off"


async def test_device_brightness_action_never_changes_other_numeric_controls(hass, mac_factory):
    first = await mac_factory(values={"1": {"volume": "0.8"}})
    second = await mac_factory()
    a, b = await configure(hass, first), await configure(hass, second)
    await service(hass, "set_brightness", device_id=device(hass, a, "1:uuid-one"), value=27)
    assert first.writes == [("1", "uuid-one", 0.27)]
    assert first.values["1"]["volume"] == "0.8"
    assert second.commands == []
    await service(hass, "set_all_brightness", config_entry_id=b.entry_id, value=61)
    assert second.writes == [("1", "uuid-one", 0.61), ("2", "uuid-two", 0.61)]
    assert len(first.commands) == 1


async def test_pro_preset_cannot_bypass_license_through_free_selector(hass, mac_factory):
    mac = await mac_factory(values={"1": {"xdrPreset": "Standard"}}, lists={"1": {"xdrPresetList": "Standard\nBetterDisplay XDR"}})
    entry = await configure(hass, mac, families=BASE + ["image"])
    control = await enable(hass, entry, "1:uuid-one_xdrPreset", "select")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("select", "select_option", {
            "entity_id": control, "option": "BetterDisplay XDR (Pro)",
        }, blocking=True)
    assert not mac.commands
    await hass.services.async_call("select", "select_option", {
        "entity_id": control, "option": "Standard",
    }, blocking=True)
    assert mac.values["1"]["xdrPreset"] == "Standard"
