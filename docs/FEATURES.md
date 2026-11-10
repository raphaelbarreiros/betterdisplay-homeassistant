# Feature status and licensing

[Setup guide](../README.md) · [Release readiness](HACS.md)

All **F01–F19** have runtime implementations under [`custom_components/betterdisplay_homeassistant`](../custom_components/betterdisplay_homeassistant). This means the controls/actions exist and have protocol/regression coverage—not that every monitor supports them or that every physical write has been tested.

The governing behavior is unchanged: separate Mac entries, explicit target snapshots, manual discovery/state refresh, no periodic/startup requests, no automatic enrollment, and no replay of failed writes. Optional inbound events do not trigger outbound requests.

## Status and license legend

- **Implemented:** real runtime behavior, not a documentation-only promise. Hardware support remains conditional.
- **Free:** upstream positively describes the underlying feature as available without Pro. Business-use license terms still apply.
- **Pro:** API documentation requires it; every gated write checks current availability.
- **Mixed / unclear:** scope, operation or upstream documentation changes the answer. These distinctions are not silently converted into Free access.

Default families are basic controls, audio and informational sensors. Other families require explicit selection. Potentially disruptive entities are additionally disabled by default in HA. A failed read does not enable a write-only control automatically.

## Implemented roadmap

| ID | Feature and HA surface | Free / Pro and capability constraints | Implementation / evidence |
| --- | --- | --- | --- |
| F01 | Per-Mac connection, capability scan, All/individual/Mac-only setup, options and reconfiguration | HTTP access Free. All is a confirmed system-display snapshot; virtual screens/groups require explicit picks. No network polling or automatic enrollment. | [Config flow](../custom_components/betterdisplay_homeassistant/config_flow.py), [lifecycle](../custom_components/betterdisplay_homeassistant/__init__.py), [integration tests](../tests/test_integration.py) |
| F02 | Pro availability before confirmation and as a diagnostic | Reports current availability, including trials—not purchase status. Off/unknown blocks Pro writes, not independently supported Free controls. | [Client](../custom_components/betterdisplay_homeassistant/api.py), [coordinator](../custom_components/betterdisplay_homeassistant/coordinator.py), [feature tests](../tests/test_features.py) |
| F03 | Per-display brightness; per-Mac all-selected brightness; device-picker brightness actions | Ordinary hardware/software brightness Free. Normalized 0–100% control position, not measured luminance. Extra-brightness modes are separate Pro features. | [Numbers](../custom_components/betterdisplay_homeassistant/number.py), [typed actions](../custom_components/betterdisplay_homeassistant/services.py), [tests](../tests/test_integration.py) |
| F04 | Screen backlight switch | Free where DDC/smart control and readable state exist. Power family opt-in; disabled by default. Not a substitute for hardware power-off, Mac wake or display disconnection. Recovery may require monitor controls. | [Switches](../custom_components/betterdisplay_homeassistant/switch.py), [tests](../tests/test_features.py) |
| F05 | Volume number, readable mute switch, explicitly enrolled toggle-only mute action/button | Ordinary DDC/software volume and mute Free. Failed mute read does not establish toggle-only support. Volume/mute can affect each other; related state is refreshed after a verified write. | [Numbers](../custom_components/betterdisplay_homeassistant/number.py), [buttons](../custom_components/betterdisplay_homeassistant/button.py), [tests](../tests/test_features.py) |
| F06 | Stateless input buttons and typed switch-input action | Free controller input selection. Choices can be generic assignments rather than physical ports. Exact controller/ID/label mapping is rechecked before `perform changeInputSource`. No active-input state is invented. | [Client choice parser](../custom_components/betterdisplay_homeassistant/api.py), [buttons](../custom_components/betterdisplay_homeassistant/button.py), [tests](../tests/test_features.py) |
| F07 | Display-mode and refresh-rate selectors | Ordinary selection Free. Returned modes only; unsafe/invalid modes excluded. Mode-number remapping is rejected until rescan. Fixed/fractional/VRR options remain distinct. Mode changes can affect other layout rules. | [Selects](../custom_components/betterdisplay_homeassistant/select.py), [tests](../tests/test_features.py); real CLI list formats observed |
| F08 | Color-temperature adjustment number | Pro. −100% to +100% adjustment, zero neutral; normalized API range is 0–1. **Not kelvin.** Supported image-adjustment controller required. | [Numbers](../custom_components/betterdisplay_homeassistant/number.py), [tests](../tests/test_features.py); real neutral conversion observed |
| F09 | HDR, software brightness upscaling and direct upscaling switches | Pro; different hardware prerequisites. HDR mode and upscaling are separate. Writes can affect related brightness/Mac color settings. HDR family opt-in, disabled by default. | [Switches](../custom_components/betterdisplay_homeassistant/switch.py), [coordinator](../custom_components/betterdisplay_homeassistant/coordinator.py), [tests](../tests/test_features.py) |
| F10 | Manually refreshed ambient-light sensor | **API licensing unclear:** CLI says Pro, comparison/UI say Free. A valid readable result is allowed, with the uncertainty disclosed. Lux is read without normalization; missing/invalid values never become zero. | [Sensors](../custom_components/betterdisplay_homeassistant/sensor.py), [tests](../tests/test_features.py); built-in CLI reading observed |
| F11 | Auto-brightness and HiDPI switches; main-display sensor and Set as main button | Basic controls Free. Auto-brightness needs controller support; HiDPI cannot create unsupported modes. Main is only set to on; no bogus off switch. Layout/HiDPI changes are opt-in. | [Switches](../custom_components/betterdisplay_homeassistant/switch.py), [binary sensors](../custom_components/betterdisplay_homeassistant/binary_sensor.py), [buttons](../custom_components/betterdisplay_homeassistant/button.py) |
| F12 | Mac-level Night Shift, normalized strength, True Tone and Dark Mode | Pro according to API docs; UI licensing differs for some toggles. One entity per Mac, not duplicated per display. Hardware/system availability still applies. | [Catalog](../custom_components/betterdisplay_homeassistant/features.py), [platforms](../custom_components/betterdisplay_homeassistant), [tests](../tests/test_features.py) |
| F13 | Hardware/software contrast, color profile/preset selectors, RGB hardware gain/black levels, software gamma/gain and RGB variants | Basic contrast/profile/preset/hardware adjustments Free; software gamma/gain Pro. The BetterDisplay XDR preset is a Pro exception to ordinary preset selection. Image family opt-in; calibration controls disabled by default. Unsupported/ambiguous list formats fail closed. | [Catalog/client](../custom_components/betterdisplay_homeassistant/api.py), [numbers](../custom_components/betterdisplay_homeassistant/number.py), [selects](../custom_components/betterdisplay_homeassistant/select.py), [tests](../tests/test_features.py) |
| F14 | Physical-display connection switch | Pro, supported connection path required. Connections family opt-in, disabled by default. Independent of brightness availability; not monitor power. Keep a recovery desktop. | [Switches](../custom_components/betterdisplay_homeassistant/switch.py), [tests](../tests/test_features.py) |
| F15 | Existing virtual-screen connection, association-count sensor and typed association action | Basic virtual connection/association queries Free; association changes Pro. Source and destination must be explicitly selected on the same Mac. Saved association policies can connect, mirror or stream. **No creation/deletion.** | [Typed actions](../custom_components/betterdisplay_homeassistant/services.py), [client](../custom_components/betterdisplay_homeassistant/api.py), [tests](../tests/test_features.py) |
| F16 | Group enabled/active, synchronization, layout protection and UI scale matching | Default Group/basic sync Free; custom-group activation and advanced settings conservatively Pro-gated. Negative group tags and missing UUID are supported. Group changes can affect nonselected displays through saved rules. | [Catalog](../custom_components/betterdisplay_homeassistant/features.py), [switches](../custom_components/betterdisplay_homeassistant/switch.py), [tests](../tests/test_features.py) |
| F17 | Rotation selector, Set as main, move-relative action, favorite slots and Mac-wide Apply layout protections | Rotation Pro per CLI despite conflicting UI docs; move/favorites/layout Pro. Exact same-Mac source/destination selection. Global apply is explicitly Mac-wide, including unselected displays. No slot overwrites or automatic rollback. | [Actions](../custom_components/betterdisplay_homeassistant/services.py), [buttons](../custom_components/betterdisplay_homeassistant/button.py), [tests](../tests/test_features.py) |
| F18 | Curated CEC command buttons and action | Free, compatible Apple silicon/HDMI/controller required. Configured CEC controller is checked. TV logical address only; no arbitrary/broadcast addresses. Stateless dispatch, not verified power/volume state. | [Client allowlist](../custom_components/betterdisplay_homeassistant/api.py), [buttons](../custom_components/betterdisplay_homeassistant/button.py), [tests](../tests/test_features.py) |
| F19 | Opt-in, per-display connection/sleep/wake event webhooks | Free event integration. User configures Mac-side Invoke URL hooks. Local GET only, seven known hook names, per-display secret, unregister on removal. Receiving an event never polls/enrolls/controls anything. No missed-event replay guarantee. | [Event platform](../custom_components/betterdisplay_homeassistant/event.py), [event tests](../tests/test_events.py) |

## Exact targeting and state rules

- Device/entity identities are scoped to the HA config entry. Names and mutable host addresses are not unique identities. Duplicate endpoints are checked by normalized host/port; DNS aliases cannot be reliably deduplicated without a server identity.
- System displays use normalized UUID identity independently of their volatile tag. Existing HA registry keys are preserved separately, including across rescans after tag changes. Virtual/group definitions retain type/tag identity with their existing UUID/name guards.
- Physical-display requests use `type=Display` plus the canonical uppercase `UUID`; physical destination selectors use `targetUUID`. Virtual screens/groups still use typed tags. No request combines tag and UUID selectors or falls back to a different display.
- Normalized reads explicitly request `value`, `min=0`, `max=1` and parse exactly three finite values. Returned bounds must be 0 and 1. Native scalar image-adjustment values are not assumed to be normalized.
- Scope, family consent, selected identity and Pro entitlement are revalidated before a write. Select/input commands compare current wire mapping with the confirmed semantic mapping.
- Setup, reload, event reception and ordinary idle time do not write controls. Startup/reload also make no BetterDisplay network requests.
- State starts unknown but eligible controls remain actionable. Per-feature failures do not disable unrelated controls. Refresh remains available for recovery. No control claims that app readback is a physical measurement.
- The physical **Connected** switch is a recovery exception: it remains actionable when absent or after a failed request, so HA does not silently skip a reconnect. A successful discovery that omits a saved display means disconnected, not unreachable-Mac. Reconnect sends one UUID-targeted write and performs bounded confirmation reads for up to five seconds; no write is retried.
- An all-brightness preflight failure writes nothing. A write-time failure reports partial completion and stops; no retry or compensating write is sent. A verified value is not discarded merely because refreshing unrelated controls failed.
- Generic HA device targets can operate multiple entities on a device. Use exact entity targets or the integration's typed brightness/device actions to avoid changing unintended controls.
- No API can make the separate discovery/write requests atomic. BetterDisplay synchronization, associations and layout protection can intentionally propagate effects outside the selected snapshot.

## Deliberate exclusions

These are not unfinished roadmap items: factory reset, virtual-screen create/discard, arbitrary raw DDC/EDID/framebuffer commands, low-level connection-mode changes, app quit/restart, unrestricted command passthrough and the streaming/PIP/image-effect catalog remain outside this integration. They have disproportionate destructive/recovery risk or a different purpose. No placeholders or no-op controls stand in for them.

## Evidence and remaining limitations

Local verification uses real HA **2026.11.1** config/options flows, native entity/device actions and loopback HTTP fixtures. Development dependencies are pinned in `uv.lock`. The suite covers selection/isolation, manual-only requests, malformed responses, Pro expiry/unknown state, partial failure, list remapping, virtual/group identity, webhooks, diagnostics redaction and lifecycle recovery.

Read-only CLI inspection of BetterDisplay **5.2.1 build 54014** confirmed actual comma-separated identifier objects, negative UUID-less Default Group IDs, normalized numeric triples, neutral image-adjustment conversion, mode/rate/profile/controller lists, true/on/off booleans and an ambient-light value. Committed fixtures are sanitized; local hardware identifiers and profile paths are not published.

The 0.1.1 hotfix has regression coverage for disappearing displays, uppercase UUID selectors, delayed reconnect with changed tags, failed/expired-Pro requests that remain explicitly retryable, confirmation timeout without background work, and preservation of legacy entity/device IDs. Read-only UUID probes confirmed uppercase succeeds while lowercase fails on the installed BetterDisplay. Real physical reconnect writes remain unverified.

**No physical display-changing commands were executed.** Input/preset variants, CEC behavior, real virtual associations, recovery after physical disconnection and licensed writes still depend on each device/controller. Unsupported or unrecognized responses are surfaced rather than guessed. Passing simulated tests is not hardware certification.

For each new change, keep its status tied to actual code, regression evidence and release—not merely an upstream API annotation. Publication/catalog status is tracked separately in [HACS.md](HACS.md).

## Primary sources

- [Current CLI/API reference](https://betterdisplay.pro/guide/integration/cli-reference/) and [worked examples](https://betterdisplay.pro/guide/integration/cli-examples/)
- [Free/Pro comparison](https://betterdisplay.pro/guide/licensing/free-and-pro-features/)
- [Home Assistant tutorial](https://betterdisplay.pro/guide/tutorials/home-assistant-monitor-control/)
- [Input source semantics](https://betterdisplay.pro/guide/interface-reference/app-menu/device-menu/input-source/)
- [Virtual-screen settings](https://betterdisplay.pro/guide/interface-reference/settings/displays/virtual-screen/)
- [Event hooks](https://betterdisplay.pro/guide/interface-reference/settings/displays/display/device-control/control-integration/events/)
- The requested [legacy wiki](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI) is retained as historical context, not the primary contract.
