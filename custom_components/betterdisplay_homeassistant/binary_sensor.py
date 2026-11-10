"""App-reported binary status and manually observed licensing."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .entity import BetterDisplayEntity, device_info, saved_features

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([BetterDisplayProAvailable(entry.runtime_data)] + [
        BetterDisplayBinarySensor(entry.runtime_data, key, feature)
        for key, feature in saved_features(entry.runtime_data, "binary_sensor")])
    entry.runtime_data.completed_platforms.add("binary_sensor")


class BetterDisplayBinarySensor(BetterDisplayEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        return self.control_value if isinstance(self.control_value, bool) else None


class BetterDisplayProAvailable(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Pro features available"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:license"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_pro_available"
        coordinator.registered_unique_ids.add(self._attr_unique_id)
        self._attr_device_info = device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.pro_available

    @property
    def available(self) -> bool:
        return not self.coordinator.stopped

    @property
    def extra_state_attributes(self) -> dict:
        return {"state_source": "BetterDisplay app readback; manually refreshed",
                "last_read": self.coordinator.data.last_read}
