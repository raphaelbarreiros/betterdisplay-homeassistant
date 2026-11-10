"""Manual numeric controls and the stable selected-display brightness control."""
from __future__ import annotations

import math
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import BetterDisplayEntity, device_info, saved_features

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    entities = [BetterDisplayNumber(coordinator, key, feature)
                for key, feature in saved_features(coordinator, "number")]
    keys = tuple(key for key, feature in saved_features(coordinator, "number")
                 if feature.key == "brightness" and coordinator.displays[key].device_type == "Display")
    if keys:
        entities.append(BetterDisplayBrightness(coordinator, keys, aggregate=True))
    async_add_entities(entities)
    coordinator.completed_platforms.add("number")


class BetterDisplayNumber(BetterDisplayEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, key, feature):
        super().__init__(coordinator, key, feature)
        if feature.key == "temperature":
            self._attr_native_min_value = -100
        if feature.key == "brightness":
            self._attr_icon = "mdi:brightness-6"

    @property
    def native_value(self) -> float | None:
        value = self.control_value
        if value is None:
            return None
        return round(float(value) * (200 if self.feature.key == "temperature" else 100)
                     - (100 if self.feature.key == "temperature" else 0), 2)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_feature(self.key, self.feature.key, value)


class BetterDisplayBrightness(CoordinatorEntity, NumberEntity):
    """Aggregate never expands beyond the saved brightness-capable targets."""
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:brightness-6"

    def __init__(self, coordinator, keys, *, aggregate=False):
        super().__init__(coordinator)
        self._keys = keys
        self._attr_name = "All selected displays brightness" if aggregate else "Brightness"
        suffix = "all_brightness" if aggregate else f"{keys[0]}_brightness"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{suffix}"
        coordinator.registered_unique_ids.add(self._attr_unique_id)
        self._attr_device_info = device_info(coordinator) if aggregate else device_info(coordinator, keys[0])

    @property
    def available(self) -> bool:
        return (not self.coordinator.stopped and self.coordinator.permits(self._keys)
                and all(self.coordinator.feature_allowed(key, "brightness")
                        and key not in self.coordinator.data.unavailable
                        and (key, "brightness") not in self.coordinator.data.feature_unavailable
                        for key in self._keys))

    @property
    def native_value(self) -> float | None:
        values = self.coordinator.data.brightness
        if not self._keys or any(key not in values for key in self._keys):
            return None
        first = values[self._keys[0]]
        if any(not math.isclose(values[key], first, abs_tol=0.0001) for key in self._keys):
            return None
        return round(first * 100, 2)

    @property
    def extra_state_attributes(self) -> dict:
        return {"state_source": "BetterDisplay app readback; manually refreshed",
                "last_read": self.coordinator.data.last_read, "target_count": len(self._keys)}

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_brightness(self._keys, value)
