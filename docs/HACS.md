# HACS / Marketplace distribution

[README](../README.md) · [Feature tracker](FEATURES.md)

Repository: **[raphaelbarreiros/betterdisplay-homeassistant](https://github.com/raphaelbarreiros/betterdisplay-homeassistant)**  
Integration domain: **`betterdisplay_homeassistant`**  
Package version: **0.1.1**
License: **[MIT](../LICENSE)**  
Minimum Home Assistant: **2026.11.1**

The public repository is the custom-repository distribution target. See [published releases](https://github.com/raphaelbarreiros/betterdisplay-homeassistant/releases) for actual release availability and [Validate runs](https://github.com/raphaelbarreiros/betterdisplay-homeassistant/actions/workflows/validate.yml) for the checks on each commit. A package version or a Git tag alone is not a published release.

**Default-catalog inclusion has not been requested or approved.** Users add this repository by URL. No Home Assistant core endorsement, universal hardware compatibility or physical-write certification is claimed.

## Installation route

The [official HACS transition guide](https://www.hacs.xyz/docs/marketplace/) directs HA 2026.11+ users to built-in **Settings > Marketplace**. This code requires 2026.11.1+, so legacy HACS/older HA support is not claimed.

1. Prepare authenticated BetterDisplay HTTP access using the [README](../README.md).
2. Open **Settings > Marketplace > Add from link** and add the repository URL above. Connect GitHub if prompted and select type **Integration** if requested.
3. Review the community-code warning and install a published release of **BetterDisplay for Home Assistant**. Follow HA's restart instructions.
4. Configure one entry per Mac and explicitly confirm the control families and target snapshot. Installing files is not configuring BetterDisplay's HTTP server.
5. Use a manually verified, comfortable brightness setting before enabling automations. Retain a recovery desktop/remote for risky controls.

The README also documents manual file installation. The domain is distinct from the community component using `betterdisplay`; this project does not overwrite that folder.

## Packaging implemented

- One runtime integration under `custom_components/betterdisplay_homeassistant/`.
- Complete manifest with real project documentation/issues URLs, codeowner `@raphaelbarreiros`, version, config flow, hub type, local-read IoT classification and webhook dependency.
- Root `hacs.json` with the display name and HA minimum.
- Original 256px/512px PNG icons in `brand/`, not copied BetterDisplay or Home Assistant marks.
- MIT license, README setup/licensing guidance and per-feature evidence.
- Public repository description, topics and issues enabled.
- Pinned development dependencies in `pyproject.toml` / `uv.lock`.
- [Validation workflow](../.github/workflows/validate.yml) on pushes, pull requests and manual dispatch: real HA tests, Hassfest, and HACS Action with `category: integration` and no ignored checks.

`iot_class: local_polling` describes request/response local reads in HA's taxonomy. **There is no periodic poll interval.** The optional webhook path delivers events without polling or automatic outbound requests.

## Verification boundaries

Local tests instantiate real **HA 2026.11.1** and loopback simulated BetterDisplay endpoints. They exercise guided setup/options/reconfigure, multi-Mac identity isolation, per-feature and aggregate actions, typed device actions, Pro/consent checks, normalized triple responses, mapping changes, virtual/group handling, event ingress/opt-out, registry preservation and secret-safe diagnostics.

Read-only local CLI checks used **BetterDisplay 5.2.1 build 54014**. They established actual response formats for system/group identifiers, normalized numeric values, modes, refresh rates, profiles/controllers and selected Boolean/sensor states. Real device identifiers/profile paths were not committed.

The 0.1.1 reconnection hotfix passed 83 local regression tests. Read-only inspection additionally confirmed that BetterDisplay's physical-display UUID selector requires uppercase canonical UUIDs. Physical reconnect/disconnect writes were not run by the assistant. Upgrade and restart HA without deleting the existing integration: the hotfix preserves existing entity IDs and device customizations.

**No physical setting-changing commands were executed.** Display-specific inputs, CEC, disconnection recovery, virtual associations and licensed writes remain subject to real hardware acceptance testing. A local Docker daemon was unavailable; Hassfest/HACS publication checks run in GitHub Actions instead. A successful packaging check is not a live Marketplace UI install or a physical-monitor test.

## Release gates

Before publishing a release:

1. Pass the current full regression suite, not merely a previous partial rerun.
2. Push the intended release commit and require **all Validate jobs** to pass, including Hassfest and HACS validation without ignores.
3. Publish a full GitHub release whose version matches the manifest. Do not substitute a tag-only push.
4. Verify the release/tag points to the validated source. Keep hardware limitations explicit in release notes.

Before requesting default-catalog inclusion:

- Confirm a real custom-repository installation/update and device-specific acceptance testing.
- Confirm current HACS requirements, public/active repository metadata, OSI-recognized license, branding and all checks.
- Have the owner/major contributor submit an editable, correctly completed PR adding the repository alphabetically to `hacs/default`'s `integration` list.
- Record submission/acceptance separately; verify catalog discovery after acceptance and its scheduled scan.

No default-catalog submission is authorized as part of this release task.

## Official references

- [Current Marketplace publishing guide](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [General HACS repository requirements](https://www.hacs.xyz/docs/publish/start/)
- [Integration structure, manifest and branding](https://www.hacs.xyz/docs/publish/integration/)
- [Custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)
- [Default-catalog submission requirements](https://www.hacs.xyz/docs/publish/include/)
- [Marketplace installation documentation](https://next.home-assistant.io/integrations/marketplace/)
