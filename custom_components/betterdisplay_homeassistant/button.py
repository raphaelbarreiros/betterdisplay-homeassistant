"""Explicit, stateless commands and an always-accessible manual refresh."""
from hashlib import sha256

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MAC_KEY
from .entity import BetterDisplayEntity, device_info
from .features import CATALOG, CEC_COMMANDS

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    families = entry.options.get("families", ("basic", "audio", "sensors"))
    entities = [BetterDisplayRefresh(coordinator)]
    for key, display in coordinator.displays.items():
        if display.device_type != "Display":
            continue
        if "audio" in families and key in entry.options.get("mute_toggle_targets", ()):
            entities.append(BetterDisplayAction(coordinator, key, "muteToggle"))
        if "layout" in families:
            if coordinator.capability(key, "main") is not None:
                entities.append(BetterDisplayAction(coordinator, key, "setMain"))
            for slot in range(1, 6):
                entities.append(BetterDisplayAction(coordinator, key, "favoriteMode", value=slot,
                                                   label=f"Apply favorite mode {slot}"))
        if "input" in families:
            capability = coordinator.capability(key, "changeInputSource")
            if capability is not None:
                for wire, label in capability.choices.items():
                    entities.append(BetterDisplayAction(coordinator, key, "changeInputSource",
                                                       value=wire, label=f"Switch input: {label}"))
        if "cec" in families and coordinator.capability(key, "sendCEC") is not None:
            for command in CEC_COMMANDS:
                entities.append(BetterDisplayAction(coordinator, key, "sendCEC", value=command,
                                                   label=f"TV command: {command}"))
    if "layout" in families:
        entities.append(BetterDisplayAction(coordinator, MAC_KEY, "applyLayoutProtection"))
    async_add_entities(entities)
    coordinator.completed_platforms.add("button")


class BetterDisplayRefresh(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Refresh display states"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh"
        coordinator.registered_unique_ids.add(self._attr_unique_id)
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        return not self.coordinator.stopped

    async def async_press(self) -> None:
        await self.coordinator.async_manual_refresh()


class BetterDisplayAction(BetterDisplayEntity, ButtonEntity):
    def __init__(self, coordinator, key, action, *, value=None, label=None):
        super().__init__(coordinator, key, CATALOG[action])
        self._action_value = value
        if value is not None:
            coordinator.registered_unique_ids.discard(self._attr_unique_id)
            self._attr_unique_id += "_" + sha256(str(value).encode()).hexdigest()[:16]
            coordinator.registered_unique_ids.add(self._attr_unique_id)
        if label is not None:
            self._attr_name = label
        # Enabling a command is separate from consenting to its feature family.
        self._attr_entity_registry_enabled_default = False

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        attrs["state_source"] = "Stateless command; no physical acknowledgement"
        if self.feature.key == "changeInputSource":
            attrs["choice"] = self._action_value
        return attrs

    async def async_press(self) -> None:
        await self.coordinator.async_perform(self.key, self.feature.key, value=self._action_value)
