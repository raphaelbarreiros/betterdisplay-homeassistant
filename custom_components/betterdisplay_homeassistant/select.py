"""Selectors retain the exact explicitly scanned wire-to-label mapping."""
from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from .entity import BetterDisplayEntity, saved_features

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([BetterDisplaySelect(entry.runtime_data, key, feature)
                        for key, feature in saved_features(entry.runtime_data, "select")
                        if feature.key != "changeInputSource"])
    entry.runtime_data.completed_platforms.add("select")


class BetterDisplaySelect(BetterDisplayEntity, SelectEntity):
    def __init__(self, coordinator, key, feature):
        super().__init__(coordinator, key, feature)
        self._choices = dict(coordinator.capability(key, feature.key).choices)
        # Distinct wire values must remain distinct even if their labels coincide.
        labels = list(self._choices.values())
        self._labels = {wire: (f"{label} [{wire}]" if labels.count(label) > 1 else label)
                        for wire, label in self._choices.items()}
        self._attr_options = list(self._labels.values())

    @property
    def current_option(self) -> str | None:
        return self._labels.get(str(self.control_value)) if self.control_value is not None else None

    async def async_select_option(self, option: str) -> None:
        wire = next((wire for wire, label in self._labels.items() if label == option), None)
        if wire is None:
            raise HomeAssistantError("Choose an option from the saved scan")
        await self.coordinator.async_set_feature(self.key, self.feature.key, wire)
