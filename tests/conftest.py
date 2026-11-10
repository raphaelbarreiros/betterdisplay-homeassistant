"""Real Home Assistant with a loopback-only BetterDisplay HTTP simulator."""

from dataclasses import dataclass, field
import json

from aiohttp import web
import pytest


NORMALIZED = frozenset({
    "brightness", "volume", "temperature", "nightShiftValue", "hardwareContrast",
    "contrast", "gamma", "gain", "rGamma", "gGamma", "bGamma", "rGain", "gGain",
    "bGain", "redHardwareGain", "greenHardwareGain", "blueHardwareGain",
    "redHardwareBlackLevel", "greenHardwareBlackLevel", "blueHardwareBlackLevel",
})


@dataclass
class Mac:
    token: str = "test-secret"
    displays: list[dict] = field(default_factory=lambda: [
        {"deviceType": "Display", "tagID": "1", "UUID": "uuid-one", "name": "Desk", "productName": "Panel"},
        {"deviceType": "Display", "tagID": "2", "UUID": "uuid-two", "name": "Desk", "productName": "Panel"},
    ])
    brightness: dict[str, str] = field(default_factory=lambda: {"1": "0.4", "2": "0.6"})
    values: dict[str, dict[str, str]] = field(default_factory=dict)
    lists: dict[str, dict[str, str]] = field(default_factory=dict)
    associations: dict[tuple[str, str], str] = field(default_factory=dict)
    fail_sets: set[str] = field(default_factory=set)
    fail_features: set[tuple[str, str]] = field(default_factory=set)
    requests: list[tuple[str, dict]] = field(default_factory=list)
    writes: list[tuple[str, str, float]] = field(default_factory=list)
    commands: list[tuple[str, dict]] = field(default_factory=list)
    discovery_body: str | None = None
    pro: str | None = "off"
    port: int = 0
    invalidate_discovery_after_set: bool = False
    simulate_connections: bool = False
    missing_connection_readback: bool = True
    disconnected: dict[str, dict] = field(default_factory=dict)
    pending_reconnect: dict[str, int] = field(default_factory=dict)
    reconnect_tags: dict[str, str] = field(default_factory=dict)
    reconnect_delay_reads: int = 2
    never_reconnect: bool = False

    def by_uuid(self, wire_uuid):
        if not isinstance(wire_uuid, str) or wire_uuid != wire_uuid.upper():
            return None
        return next((display for display in [*self.displays, *self.disconnected.values()]
                     if display["deviceType"] == "Display"
                     and display["UUID"].upper() == wire_uuid), None)

    def disconnect(self, uuid):
        display = self.by_uuid(uuid.upper())
        self.displays = [item for item in self.displays if item is not display]
        self.disconnected[uuid.lower()] = display
        self.values.setdefault(str(display["tagID"]), {})["connected"] = "off"

    def advance_reconnections(self):
        for uuid, remaining in list(self.pending_reconnect.items()):
            if self.never_reconnect:
                continue
            if remaining > 0:
                self.pending_reconnect[uuid] = remaining - 1
                continue
            display = self.disconnected.pop(uuid)
            old_tag = str(display["tagID"])
            tag = self.reconnect_tags.get(uuid, old_tag)
            display["tagID"] = tag
            if tag != old_tag:
                self.values[tag] = self.values.pop(old_tag, {})
                if old_tag in self.brightness:
                    self.brightness[tag] = self.brightness.pop(old_tag)
            self.values.setdefault(tag, {})["connected"] = "on"
            self.displays.append(display)
            del self.pending_reconnect[uuid]

    @property
    def config(self):
        return {"label": "Test Mac", "host": "127.0.0.1", "port": self.port, "token": self.token}

    async def handle(self, request):
        query = dict(request.query)
        self.requests.append((request.path, query))
        if query.get("token") != self.token:
            return web.Response(status=401)
        if request.path == "/get" and "identifiers" in query:
            self.advance_reconnections()
            body = self.discovery_body
            if body is None:
                body = ",".join(json.dumps(display) for display in self.displays)
            return web.Response(text=body)
        if request.path == "/get" and "proAvailable" in query:
            return web.Response(text=self.pro) if self.pro is not None else web.Response(status=404)
        if "UUID" in query:
            identity = self.by_uuid(query["UUID"])
            if identity is None:
                return web.Response(status=404, text="Failed.")
            if query.get("type") != "Display" or "tagID" in query:
                return web.Response(status=400, text="One explicit uppercase UUID required")
            tag = str(identity["tagID"])
        else:
            tag = query.get("tagID", "mac")
            identity = next((d for d in self.displays if str(d["tagID"]) == tag), None)
            if tag != "mac" and (identity is None or identity["deviceType"] == "Display" or query.get("type") != identity["deviceType"]):
                return web.Response(status=400, text="Explicit matching device identity required")
        other = self.by_uuid(query.get("targetUUID")) if "targetUUID" in query else None
        if "targetUUID" in query and other is None:
            return web.Response(status=404, text="Failed.")
        target_tag = str(other["tagID"]) if other is not None else query.get("targetTagID")
        features = set(query) - {"token", "tagID", "UUID", "type", "min", "max", "value", "targetTagID", "targetUUID", "specifier", "CECAddress"}
        if len(features) != 1:
            return web.Response(status=400, text="Exactly one feature required")
        feature = features.pop()
        if request.path == "/get":
            if (feature == "connected" and identity is not None
                    and identity.get("UUID", "").lower() in self.disconnected
                    and self.missing_connection_readback):
                return web.Response(status=404, text="Failed.")
            if (tag, feature) in self.fail_features:
                return web.Response(status=404, text="Failed.")
            if feature == "associated":
                value = self.associations.get((tag, target_tag))
            elif feature == "brightness":
                value = self.brightness.get(tag)
            else:
                value = self.lists.get(tag, {}).get(feature, self.values.get(tag, {}).get(feature))
            if value is None:
                return web.Response(status=404, text="Failed.")
            if feature in NORMALIZED and query.get("min") == "0" and query.get("max") == "1":
                # Actual CLI returns bounds alone unless the value flag is present.
                value = f"{value},0.0,1.0" if "value" in query else "0.0,1.0"
            return web.Response(text=value)
        if request.path not in {"/set", "/perform", "/toggle"}:
            return web.Response(status=404)
        self.commands.append((request.path, query))
        if feature == "brightness":
            if query.get("min") != "0" or query.get("max") != "1" or "value" in query:
                return web.Response(status=400, text="Normalized write required")
            self.writes.append((tag, identity["UUID"], float(query[feature])))
        if tag in self.fail_sets or (tag, feature) in self.fail_features:
            return web.Response(status=500)
        if request.path == "/set":
            if feature == "brightness":
                self.brightness[tag] = query[feature]
            elif feature == "associated":
                self.associations[(tag, target_tag)] = query[feature]
            else:
                self.values.setdefault(tag, {})[feature] = query[feature]
            if feature == "connected" and self.simulate_connections and identity["deviceType"] == "Display":
                uuid = identity["UUID"].lower()
                if query[feature] == "off":
                    self.disconnect(uuid)
                elif uuid in self.disconnected:
                    self.values[tag]["connected"] = "off"
                    self.pending_reconnect[uuid] = self.reconnect_delay_reads
            if self.invalidate_discovery_after_set:
                self.discovery_body = "invalid discovery response"
        return web.Response(text="")


@pytest.fixture
async def mac_factory(aiohttp_server, socket_enabled):
    async def create(**kwargs):
        mac = Mac(**kwargs)
        app = web.Application()
        for operation in ("get", "set", "perform", "toggle"):
            app.router.add_get(f"/{operation}", mac.handle)
        server = await aiohttp_server(app, host="127.0.0.1")
        mac.port = server.port
        return mac
    return create
