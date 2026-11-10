"""Readback switches; input and toggle-only mute are never represented as state."""
from homeassistant.components.switch import SwitchEntity
from .entity import BetterDisplayEntity, saved_features

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([BetterDisplaySwitch(entry.runtime_data, key, feature)
                        for key, feature in saved_features(entry.runtime_data, "switch")])
    entry.runtime_data.completed_platforms.add("switch")


class BetterDisplaySwitch(BetterDisplayEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        return self.control_value if isinstance(self.control_value, bool) else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_feature(self.key, self.feature.key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_feature(self.key, self.feature.key, False)
