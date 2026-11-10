"""Informational readings, never inferred physical-device acknowledgement."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from .entity import BetterDisplayEntity, saved_features

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([BetterDisplaySensor(entry.runtime_data, key, feature)
                        for key, feature in saved_features(entry.runtime_data, "sensor")])
    entry.runtime_data.completed_platforms.add("sensor")


class BetterDisplaySensor(BetterDisplayEntity, SensorEntity):
    def __init__(self, coordinator, key, feature):
        super().__init__(coordinator, key, feature)
        if feature.key == "ambientLight":
            self._attr_device_class = SensorDeviceClass.ILLUMINANCE
            self._attr_native_unit_of_measurement = "lx"
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.feature.key == "associatedDisplays":
            return len(self.control_value) if isinstance(self.control_value, (list, tuple, dict)) else None
        return self.control_value

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        if self.feature.key == "associatedDisplays":
            # Never expose raw UUIDs, names, or untrusted server strings.
            value = self.control_value
            attrs["associations"] = ([{"index": index + 1} for index in range(len(value))]
                                     if isinstance(value, (list, tuple, dict)) else [])
        return attrs
