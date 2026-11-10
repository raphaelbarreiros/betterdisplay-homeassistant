# BetterDisplay for Home Assistant

<img src="custom_components/betterdisplay_homeassistant/brand/icon.png" width="96" alt="BetterDisplay for Home Assistant integration icon">

Connect the **BetterDisplay macOS app to Home Assistant**. Select displays on each Mac, control supported features, and use them in dashboards and automations. This is an independent custom integration, not an official BetterDisplay or Home Assistant product.

- **Multiple computers:** separate connection, token and selected devices for every Mac.
- **All displays or individual selection:** an explicitly confirmed snapshot, never automatic enrollment.
- **Manual refresh:** no background polling, startup probes or automatic write retries.
- **Free/Pro-aware:** licensing information before setup completes; Pro checked again before gated writes.
- **Capability-aware:** unsupported controls are not invented. Risky controls require opt-in.

**Requirements:** Home Assistant **2026.11.1+**, BetterDisplay running on a reachable Mac, and compatible displays/controllers. Development uses BetterDisplay **5.2.1** reference/read-only CLI results. Automated write verification uses simulated HTTP devices, not physical monitors. There is no universal monitor compatibility guarantee.

[Feature status and licensing](docs/FEATURES.md) · [Distribution and verification](docs/HACS.md) · [Issues](https://github.com/raphaelbarreiros/betterdisplay-homeassistant/issues)

## What you can control

Brightness and audio; screen backlight; input commands; display modes and refresh rates; HDR and brightness upscaling; color temperature, contrast and calibration; Mac Night Shift/True Tone/Dark Mode; existing virtual screens and groups; layout/favorite-mode actions; curated CEC commands. Optional local event webhooks receive BetterDisplay connection/sleep/wake notifications.

Controls appear only when their selected family and capability support allow them. Some commands, such as favorite slots and toggle-only mute, cannot be discovered safely and need explicit configuration. The [feature tracker](docs/FEATURES.md) records the exact limitations.

## Do I need BetterDisplay Pro?

**HTTP access, its token, and ordinary supported brightness/audio controls do not require Pro.** Advanced operations such as API color-temperature adjustment, HDR/upscaling, physical-display disconnection and layout actions require Pro. A Pro license does not add missing hardware capabilities.

Setup shows current Pro availability and the selected controls. Pro-only writes require a fresh affirmative response; an unknown or expired entitlement never counts as Pro. Read-only ambient-light API licensing is contradictory upstream, so a readable sensor is allowed without claiming that access is Free.

“Free” means feature access. BetterDisplay's [license comparison](https://betterdisplay.pro/guide/licensing/free-and-pro-features/) states that business users must purchase Pro after the trial; consult its terms. This project's own code uses the [MIT license](LICENSE).

## 1. Prepare BetterDisplay on each Mac

1. Open BetterDisplay and confirm the desired controls work in its menu. Hardware brightness, software dimming and power are different controls; docks and adapters can affect support.
2. Ensure HA can reach the Mac's LAN hostname/IP. `localhost` on another HA computer does **not** mean your Mac. A DHCP reservation helps keep the address stable.
3. Open **BetterDisplay Settings > Application > Integration**.
4. If an existing client uses HTTP, preserve its token/port. For a new setup, keep **Enable integrated HTTP server** off while preparing authentication:
   - Temporarily enable **Enable custom URL scheme access**.
   - Open **Integration Settings…**, enter a long random **Security token**, and commit it with Enter or by moving focus.
   - Close the sheet and restore the URL-scheme switch to its previous state. Avoid untrusted integration URLs during preparation.
5. Enable **Enable integrated HTTP server** and confirm the running-status message. The checkbox alone is not proof that the listener started.
6. Check **Listening HTTP port**. The default is **55777**; enter the actual port in HA. Saving a port change restarts the listener.
7. Permit the necessary local-network access through macOS prompts/firewall without disabling unrelated safeguards. Ordinary HTTP brightness control does not itself require Accessibility or Screen Recording permission.

**Security:** this server uses plaintext HTTP on network interfaces, with the token in the query URL. The token can appear in traffic, app logs or exported preferences. Keep it and completed URLs private. Do not expose or port-forward the server to the internet. Authentication does not encrypt traffic.

Official references: [Home Assistant tutorial](https://betterdisplay.pro/guide/tutorials/home-assistant-monitor-control/) and [App Integration settings](https://betterdisplay.pro/guide/interface-reference/settings/application/integration/).

## 2. Install in Home Assistant

### HACS / Marketplace custom repository

The [HACS transition guide](https://www.hacs.xyz/docs/marketplace/) directs HA 2026.11+ users to the built-in **Marketplace**. This integration requires HA 2026.11.1+, so do not install legacy HACS on that version.

1. Open **Settings > Marketplace > Add from link**.
2. Add `https://github.com/raphaelbarreiros/betterdisplay-homeassistant`; connect GitHub if requested and choose type **Integration** if asked.
3. Open **BetterDisplay for Home Assistant**, review the community-code warning, and install a release. Follow any restart prompt. Integration updates require an HA restart.
4. If configuration does not open automatically, choose **Settings > Devices & services > Add integration > BetterDisplay for Home Assistant**.

Custom-repository installation and default-catalog inclusion are different. This project does not claim default-catalog approval.

### Manual installation

Copy `custom_components/betterdisplay_homeassistant` into your HA configuration directory's `custom_components/` directory, then restart HA. The integration domain is **`betterdisplay_homeassistant`**, distinct from other projects using `betterdisplay`.

If you installed this project's earlier unpublished `betterdisplay` development code, remove that old configuration/component deliberately and add this integration again. There is no cross-domain migration or compatibility alias; do not remove an unrelated community component accidentally.

## 3. Configure a computer and choose targets

1. Enter a recognizable **Mac name**, bare hostname/IP, port and nonempty token. Select the control families you want to inspect. The scan is read-only.
2. Choose one explicit scope:
   - **All displays found on this Mac:** all eligible system `Display` records from this scan only.
   - **Individual devices:** selected displays; existing virtual screens or groups are offered only after opting into those families.
   - **Mac-only controls:** explicitly use Mac-wide controls without selecting displays.
3. Review the exact list, supported controls, Pro status and warnings. Confirm to save. Neither an empty selection nor a missing selector means “all.”
4. Add another integration entry for each additional computer. The same display IDs on different Macs remain independent.

Names include device type/tag information to distinguish duplicates; you do not need to type BetterDisplay IDs. System `Display` records can include Sidecar. **All** never silently includes virtual-screen definitions, groups, another Mac or future monitors.

**Risky controls are disabled by default in HA even after selecting their family.** Enable the specific entity on its device's entity page when you are ready. Typed actions also enforce the saved family consent and current Pro availability. Keep an independent desktop, monitor buttons or TV remote available before experimenting with power, input or layout controls.

## 4. Control, refresh and change selection

- Each display has separate entities for its supported controls. Each Mac also has **All selected displays brightness**, affecting only its saved brightness-capable display snapshot.
- Use exact entity targets for generic actions such as `number.set_value` or `switch.turn_on`. A whole-device target can affect several number/switch controls, not just brightness. Prefer this integration's brightness actions when selecting a device through a picker.
- **Refresh display states** reads known selected controls and Pro availability; it does not add devices or write settings.
- **Configure > Rescan devices and controls** performs a new manual scan. Choose the new scope and confirm additions/removals. Retained entity IDs, user names and areas stay intact; removing controls can require repairing automations.
- **Reconfigure** changes host/port/token while checking existing identities. A different computer needs its own entry. Token rejection during a manual refresh starts a reauthentication flow.

There are **no idle or startup network requests**. State starts unknown after HA restart; eligible controls can perform their first explicit action without a preliminary refresh. State changes made outside HA are not noticed until the next explicit request. A successful manual refresh recovers observed failures. Mixed aggregate brightness is **unknown**, not an invented average.

Before writes, the integration checks the current target identity and consent. Pro controls recheck entitlement, and list-based commands recheck their selected mapping. All-display brightness preflights every target and then sends individually targeted writes. A failure stops the sequence and reports partial completion: no retries, queued offline writes or rollback.

**Limits:** discovery and a subsequent write are not atomic. BetterDisplay can propagate changes through synchronization, associations or layout protection outside the selected targets. HTTP acceptance is not a physical acknowledgement; app readback is not a panel measurement. A timeout does not undo an accepted request.

### Connection recovery (0.1.1)

System displays are addressed by uppercase UUID, not their volatile tag. Existing HA entity/device IDs are preserved when a tag changes, including on a later confirmed rescan.

The **Connected** switch stays actionable as a recovery control even when the display is absent or its last request failed. If the Mac cannot be reached, state is unknown and an explicit action reports an error instead of being silently skipped by HA.

Turning off accepts an `off` readback or confirmed absence from a successful device-list response. Turning on sends one UUID-targeted write and waits up to five seconds for the same UUID to be visible and report connected. Only those confirmation reads repeat; writes are never replayed and no idle polling is introduced. Other controls remain unavailable while a display is disconnected.

After upgrading, restart HA; do not delete/re-add the integration or rename your existing switch entities. Confirm the returning display is on before disconnecting your recovery display. Existing HA scripts and disabled fallback scripts are not modified by this update.

### Typed actions

Find these under **BetterDisplay for Home Assistant** in HA's action picker:

- Set brightness for a selected device; set all selected display brightness for one computer.
- Move a display relative to another on the same Mac; apply a previously saved favorite mode.
- Set one existing virtual screen's association with a selected display on the same Mac.
- Switch to a confirmed input; generated per-input buttons are the simpler UI. The button's `choice` attribute supplies the exact value for advanced service use.
- Send a curated CEC command; toggle mute only on an explicitly enrolled toggle-only controller.
- Apply **all active group layout protections** on one Mac, with explicit Mac-wide confirmation. This action cannot be limited to individual displays.

Input and CEC buttons are stateless: no guessed active input or TV power state. Favorite actions do not create or overwrite saved slots. Factory resets, virtual-screen creation/deletion, raw DDC/EDID writes and app lifecycle commands are intentionally excluded.

## Optional: receive BetterDisplay events

Events do not poll the Mac and do not automatically refresh other entities.

1. In HA, open this computer's **Configure > Event webhooks** and select already configured system displays.
2. Review and confirm the generated private URL for each display. HA needs a usable internal URL, configured or automatically detected. External/cloud URLs are not used.
3. On the corresponding Mac display, use **Settings > Displays > [display] > Device Control > Control Integration > Configure Events…**. For each desired hook, choose **Invoke URL** and paste that display's URL, including `?hook=[*:EVENT_HOOK:*]`.
4. Check existing Control Integration settings carefully: adding the controller can affect control ownership. Recheck ordinary brightness afterward. Do not replace unrelated event definitions.

Supported hooks: soft disconnect/reconnect, hard disconnect/reconnect, system sleep, immediate wake and delayed wake. HA exposes the received notification as an event, **not** as proof of physical connectivity. It performs no outbound request in response. Events may be lost or duplicated; there is no replay guarantee. Your own automation may explicitly press Refresh if wanted.

Endpoints accept **local GET requests only** and are bound to one selected display by a random secret. Treat the entire URL as a password; do not publish it or put it in screenshots/logs. Plain HTTP exposes it on the LAN. HA proxy configuration affects source-IP checks; cloud/public sources and some VPN address ranges are rejected. Disabling/re-enabling events rotates the secret. Also set the Mac-side action to **Do nothing** when disabling; an unregistered HA webhook can still answer HTTP 200.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect | Mac awake, BetterDisplay running, listener status, LAN host/port and relevant firewall permissions. |
| Authentication failed | Commit the same token in BetterDisplay; reauthenticate/reconfigure HA. Never remove authentication to debug. |
| No eligible device/control | Test that exact control in BetterDisplay, enable its family, and manually rescan. A failed read is not proof of support. |
| Control absent or disabled | Capability, family consent, current Pro status and HA entity enablement are separate checks. |
| State stale/unknown/unavailable | Press Refresh. Startup is intentionally unknown; a mixed brightness aggregate stays unknown. |
| New monitor missing | Rescan and confirm; neither normal refresh nor All automatically enrolls it. |
| Pro control stops working | Check license/trial availability. Unknown status blocks Pro writes; Free controls remain independent. |
| Input/power action removes the picture | Use the tested manual recovery path; the inactive connection may no longer accept commands. |
| Events do not arrive | Correct per-display URL/hook, internal-network reachability, local-only source restrictions and configured Mac event action. |

## Development and evidence

Use Python **3.14.2+** with `uv sync --locked --group dev`, then `uv run --no-sync pytest -q`. CI runs the HA regression suite, Hassfest and HACS validation. See [release readiness](docs/HACS.md) for actual results and remaining hardware limitations.

Tests use real HA config/options flows, device/entity actions and local simulated BetterDisplay HTTP endpoints. Read-only CLI checks on BetterDisplay 5.2.1 confirmed identity, numeric, mode/rate, profile, controller and several state formats. **No display-changing commands were sent to physical monitors.** Real hardware and licensed-write behavior still need device-specific acceptance testing.

The requested [GitHub CLI wiki](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI) is marked legacy. Current references: [integration overview](https://betterdisplay.pro/guide/integration/), [CLI/API reference](https://betterdisplay.pro/guide/integration/cli-reference/), [Home Assistant FAQ](https://betterdisplay.pro/guide/faq/general/home-assistant/).
