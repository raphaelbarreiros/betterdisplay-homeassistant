"""Saved-capability entities with independently observed availability."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAC_KEY
from .coordinator import BetterDisplayCoordinator
from .features import CATALOG, Feature, family_for, pro_required


def device_info(coordinator: BetterDisplayCoordinator, key: str = MAC_KEY) -> DeviceInfo:
    entry = coordinator.entry
    if key == MAC_KEY:
        return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
                          manufacturer="BetterDisplay", model="Mac HTTP connection")
    target = coordinator.displays[key]
    return DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_{key}")},
                      name=target.name, model=target.product_name or target.device_type,
                      via_device_id=coordinator.mac_device_id)


def saved_features(coordinator: BetterDisplayCoordinator, platform: str):
    """Enrollment comes only from the explicit configuration snapshot."""
    families = coordinator.entry.options.get("families", ("basic", "audio", "sensors"))
    for key in (*coordinator.displays, MAC_KEY):
        scope = "Mac" if key == MAC_KEY else coordinator.displays[key].device_type
        for feature in CATALOG.values():
            if (feature.platform == platform and scope in feature.scopes
                    and family_for(feature.key, coordinator.displays.get(key)) in families
                    and coordinator.capability(key, feature.key) is not None):
                yield key, feature


class BetterDisplayEntity(CoordinatorEntity[BetterDisplayCoordinator]):
    """Do not confuse failed brightness with failure of another control."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BetterDisplayCoordinator, key: str, feature: Feature) -> None:
        super().__init__(coordinator)
        self.key = key
        self.feature = feature
        self._attr_name = feature.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}_{feature.key}"
        coordinator.registered_unique_ids.add(self._attr_unique_id)
        self._attr_device_info = device_info(coordinator, key)
        self._attr_entity_registry_enabled_default = not feature.risky

    @property
    def available(self) -> bool:
        return (not self.coordinator.stopped
                and self.coordinator.feature_allowed(self.key, self.feature.key)
                and self.key not in self.coordinator.data.unavailable
                and (self.key, self.feature.key) not in self.coordinator.data.feature_unavailable)

    @property
    def control_value(self):
        return self.coordinator.data.values.get(self.key, {}).get(self.feature.key)

    @property
    def extra_state_attributes(self) -> dict:
        target = self.coordinator.displays.get(self.key)
        return {
            "target_key": self.key,
            "state_source": "BetterDisplay app readback; manually refreshed",
            "last_read": self.coordinator.data.last_read,
            "requires_pro": pro_required(self.feature.key, target),
            "license_note": ("API licensing may differ from the BetterDisplay UI"
                             if self.feature.key == "ambientLight" else "Checked before writes"),
            "potentially_disruptive": self.feature.risky,
        }
