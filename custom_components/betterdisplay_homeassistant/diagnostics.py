"""Diagnostics use a safe allowlist, not recursive dumping of private metadata."""
from __future__ import annotations

import math
from .const import MAC_KEY
from .features import CATALOG


def _safe_value(feature: str, value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if feature == "associatedDisplays" and isinstance(value, (list, tuple, dict)):
        return {"count": len(value)}
    # Text can contain profile paths, device names, hardware identifiers or URLs.
    return "[REDACTED]"


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    coordinator = entry.runtime_data
    targets = []
    for index, (key, target) in enumerate(coordinator.displays.items(), start=1):
        capabilities = coordinator.capabilities.get(key, {})
        values = coordinator.data.values.get(key, {})
        targets.append({
            "index": index,
            "device_type": target.device_type,
            "capabilities": sorted(feature for feature in capabilities if feature in CATALOG),
            "values": {feature: _safe_value(feature, value) for feature, value in values.items()
                       if feature in CATALOG},
            "unavailable": key in coordinator.data.unavailable,
            "unavailable_features": sorted(feature for target_key, feature
                                           in coordinator.data.feature_unavailable
                                           if target_key == key and feature in CATALOG),
            "events_enabled": key in entry.options.get("webhooks", {}),
        })
    return {
        "selection_mode": entry.options.get("selection_mode"),
        "families": sorted(set(entry.options.get("families", ()))
                           & {feature.family for feature in CATALOG.values()}),
        "target_count": len(targets),
        "targets": targets,
        "mac_values": {feature: _safe_value(feature, value)
                       for feature, value in coordinator.data.values.get(MAC_KEY, {}).items()
                       if feature in CATALOG},
        "pro_available": coordinator.data.pro_available,
        "last_read": coordinator.data.last_read.isoformat() if coordinator.data.last_read else None,
        "stopped": coordinator.stopped,
        "state_source": "Manual BetterDisplay app readbacks and optional local events; no background polling",
    }
