"""Bounded, explicitly targeted access to the BetterDisplay HTTP API."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import ipaddress
import json
import math
import re

import aiohttp
from yarl import URL

from .features import CATALOG, CEC_COMMANDS, DEFAULT_FAMILIES, MAC_KEY, MOVE_POSITIONS, OPTIONAL_FAMILIES, Feature, family_for

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_MAX_BODY = 1024 * 1024
_TAG_ID = re.compile(r"-?[1-9][0-9]*\Z")
_CONTROLLER = re.compile(r"[A-Za-z][A-Za-z0-9_]*Controller\Z")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class BetterDisplayError(Exception):
    """A safe-to-display integration failure without server content or credentials."""


class CannotConnect(BetterDisplayError):
    """The endpoint could not be reached or completed no valid HTTP exchange."""


class InvalidAuth(BetterDisplayError):
    """The endpoint rejected authentication."""


class InvalidResponse(BetterDisplayError):
    """The endpoint returned invalid or ambiguous data."""


class UnsupportedControl(BetterDisplayError):
    """The requested operation is unavailable."""


@dataclass(frozen=True)
class Display:
    """A typed installation-specific identity and descriptive metadata."""

    tag_id: str
    uuid: str
    name: str
    product_name: str = ""
    device_type: str = "Display"
    entity_key: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.tag_id, str) or not _TAG_ID.fullmatch(self.tag_id):
            raise ValueError("Invalid display tag ID")
        if self.device_type not in ("Display", "VirtualScreen", "DisplayGroup"):
            raise ValueError("Invalid device type")
        if self.tag_id.startswith("-") and self.device_type != "DisplayGroup":
            raise ValueError("Invalid display tag ID")
        if (
            not isinstance(self.uuid, str)
            or (not self.uuid and self.device_type == "Display")
            or any(character.isspace() or ord(character) < 32 for character in self.uuid)
        ):
            raise ValueError("Invalid display UUID")
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in self.name)
            or not isinstance(self.product_name, str)
        ):
            raise ValueError("Invalid display metadata")
        object.__setattr__(self, "uuid", self.uuid.lower())
        if not isinstance(self.entity_key, str):
            raise ValueError("Invalid saved entity key")
        if self.entity_key:
            if self.device_type == "Display":
                saved_tag, separator, saved_uuid = self.entity_key.partition(":")
                if not separator or not re.fullmatch(r"[1-9][0-9]*", saved_tag) or saved_uuid != self.uuid:
                    raise ValueError("Saved entity key does not match the display UUID")
            elif self.entity_key != f"{self.device_type}:{self.tag_id}":
                raise ValueError("Saved entity key does not match the device")

    @property
    def key(self) -> str:
        """HA registry key, retained across tag changes; not a wire selector."""
        if self.entity_key:
            return self.entity_key
        if self.device_type != "Display":
            return f"{self.device_type}:{self.tag_id}"
        return f"{self.tag_id}:{self.uuid}"

    def resolve(self, devices: Mapping[str, Display]) -> Display | None:
        """Find the same device, ignoring volatile system-display tag IDs."""
        found = None
        for candidate in devices.values():
            if candidate.device_type != self.device_type:
                continue
            if self.device_type == "Display":
                matches = candidate.uuid == self.uuid
            else:
                matches = candidate.tag_id == self.tag_id and (
                    candidate.uuid == self.uuid if self.uuid else candidate.name == self.name
                )
            if matches:
                if found is not None:
                    return None
                found = candidate
        return found

    def to_dict(self) -> dict[str, str]:
        """Serialize the concrete selection snapshot for config entry options."""
        return {
            "tag_id": self.tag_id,
            "uuid": self.uuid,
            "name": self.name,
            "product_name": self.product_name,
            "device_type": self.device_type,
            "entity_key": self.key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Display:
        """Restore a selection snapshot, rejecting incomplete identity."""
        if not isinstance(data, Mapping):
            raise ValueError("Invalid display metadata")
        try:
            return cls(
                tag_id=data["tag_id"],
                uuid=data.get("uuid", ""),
                name=data["name"],
                product_name=data.get("product_name", ""),
                device_type=data.get("device_type", "Display"),
                entity_key=data.get("entity_key", ""),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid display metadata") from None


@dataclass(frozen=True)
class Capability:
    """A readable value and exact wire-to-semantic-choice snapshot."""

    value: object | None = None
    choices: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "choices": dict(self.choices)}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Capability:
        if not isinstance(data, Mapping):
            raise ValueError("Invalid capability")
        choices = data.get("choices", {})
        if not isinstance(choices, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in choices.items()
        ):
            raise ValueError("Invalid capability choices")
        value = data.get("value")
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise ValueError("Invalid capability value") from None
        return cls(value, dict(choices))


@dataclass(frozen=True)
class Snapshot:
    devices: dict[str, Display]
    capabilities: dict[str, dict[str, Capability]]
    pro_available: bool | None


@dataclass(frozen=True)
class Probe:
    """Explicit read-only scan, including independently supported controls."""

    displays: dict[str, Display]
    brightness: dict[str, float]
    pro_available: bool | None
    capabilities: dict[str, dict[str, Capability]] = field(default_factory=dict)

def _normalize_host(host: str) -> str:
    if (
        not isinstance(host, str)
        or not host
        or any(character.isspace() for character in host)
        or any(character in host for character in "/\\@?#[]%")
    ):
        raise ValueError("Host must be a bare hostname or IP address")
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        pass
    try:
        normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("Invalid hostname") from None
    if (
        len(normalized) > 253
        or not all(_HOST_LABEL.fullmatch(label) for label in normalized.split("."))
        or all(character in "0123456789." for character in normalized)
    ):
        raise ValueError("Host must be a bare hostname or IP address")
    return normalized


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Do not let duplicate JSON properties silently replace an identity."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response property")
        result[key] = value
    return result


class BetterDisplayClient:
    """An on-demand client; no timers, retries, discovery writes, or broadcasts."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, port: int, token: str
    ) -> None:
        self.host = _normalize_host(host)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer between 1 and 65535")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("An authentication token is required")
        self.port = port
        self._session = session
        self._token = token
        self._base = URL.build(scheme="http", host=self.host, port=port)

    @property
    def endpoint_key(self) -> str:
        """Return a normalized endpoint key, not a permanent device identity."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    async def _request(self, operation: str, params: dict[str, str]) -> str:
        try:
            async with self._session.get(
                self._base / operation,
                params={**params, "token": self._token},
                timeout=_TIMEOUT,
                allow_redirects=False,
                raise_for_status=False,
            ) as response:
                if response.status in (401, 403):
                    raise InvalidAuth("BetterDisplay authentication was rejected")
                if response.status == 404:
                    raise UnsupportedControl("BetterDisplay operation is unavailable")
                if response.status != 200:
                    raise BetterDisplayError("BetterDisplay returned an unsuccessful HTTP status")
                if response.content_length is not None and response.content_length > _MAX_BODY:
                    raise InvalidResponse("BetterDisplay response is too large")
                body = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    if len(body) + len(chunk) > _MAX_BODY:
                        raise InvalidResponse("BetterDisplay response is too large")
                    body.extend(chunk)
                try:
                    text = body.decode("utf-8").strip()
                except UnicodeError:
                    raise InvalidResponse("BetterDisplay response is not valid UTF-8") from None
                if text.lower() == "failed" or text.lower().startswith("failed."):
                    raise UnsupportedControl("BetterDisplay operation is unavailable")
                return text
        except (aiohttp.ClientError, TimeoutError, OSError):
            # aiohttp exceptions can include the full query string and its token.
            raise CannotConnect("Cannot communicate with BetterDisplay") from None

    async def discover(self) -> dict[str, Display]:
        """Read all system displays, rejecting incomplete or ambiguous identities."""
        text = await self._request("get", {"identifiers": ""})
        if not text:
            return {}
        # BetterDisplay also emits a comma-separated sequence of JSON objects.
        document = text if text.startswith("[") else f"[{text}]"
        try:
            records = json.loads(document, object_pairs_hook=_unique_object)
            if not isinstance(records, list):
                raise ValueError("Invalid identifier collection")
            displays: dict[str, Display] = {}
            tags: set[str] = set()
            uuids: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("Invalid identifier record")
                if record.get("deviceType") not in ("Display", "VirtualScreen", "DisplayGroup"):
                    continue
                tag_id = record["tagID"]
                if isinstance(tag_id, int) and not isinstance(tag_id, bool):
                    tag_id = str(tag_id)
                display = Display(
                    tag_id=tag_id,
                    uuid=record.get("UUID", ""),
                    name=record["name"],
                    product_name=record.get("productName", ""),
                    device_type=record["deviceType"],
                )
                if display.tag_id in tags or (display.device_type == "Display" and display.uuid in uuids):
                    raise ValueError("Ambiguous display identity")
                tags.add(display.tag_id)
                if display.device_type == "Display":
                    uuids.add(display.uuid)
                displays[display.key] = display
            return displays
        except (ValueError, TypeError, KeyError, RecursionError):
            raise InvalidResponse("BetterDisplay returned invalid or ambiguous identifiers") from None

    @staticmethod
    def _target(display: Display) -> dict[str, str]:
        if not isinstance(display, Display):
            raise ValueError("An explicit display identity is required")
        if display.device_type == "Display":
            # BetterDisplay's UUID selector is case-sensitive. Its canonical
            # UUIDs are uppercase, while internal comparisons are normalized.
            return {"type": "Display", "UUID": display.uuid.upper()}
        return {"type": display.device_type, "tagID": display.tag_id}

    async def get_brightness(self, display: Display) -> float:
        """Read the real current,min,max normalized response."""
        return (await self.read_feature(display, "brightness")).value

    async def set_brightness(self, display: Display, value: float) -> None:
        """Write one explicitly identified display."""
        await self.write_feature(display, "brightness", value)

    async def get_pro_available(self) -> bool | None:
        """Read optional app-wide Pro state without hiding auth/network errors."""
        try:
            text = await self._request("get", {"proAvailable": ""})
        except (UnsupportedControl, InvalidResponse):
            return None
        return {"on": True, "true": True, "1": True, "off": False, "false": False, "0": False}.get(
            text.lower()
        )

    @staticmethod
    def _definition(target: Display | None, feature: str) -> Feature:
        if not isinstance(feature, str) or feature not in CATALOG:
            raise ValueError("Unsupported feature")
        definition = CATALOG[feature]
        if target is not None and not isinstance(target, Display):
            raise ValueError("An explicit device identity is required")
        scope = "Mac" if target is None else target.device_type
        if scope not in definition.scopes:
            raise ValueError("Feature does not support this target")
        return definition

    @staticmethod
    def _boolean(text: str) -> bool:
        values = {"on": True, "off": False, "true": True, "false": False, "1": True, "0": False}
        if text.lower() not in values:
            raise InvalidResponse("BetterDisplay returned an invalid Boolean")
        return values[text.lower()]

    @staticmethod
    def _normalized(text: str) -> float:
        try:
            parts = [float(part) for part in text.split(",")]
        except ValueError:
            raise InvalidResponse("BetterDisplay returned an invalid normalized value") from None
        if len(parts) != 3 or not all(math.isfinite(part) for part in parts):
            raise InvalidResponse("BetterDisplay returned an invalid normalized value")
        value, minimum, maximum = parts
        if minimum != 0 or maximum != 1 or not 0 <= value <= 1:
            raise InvalidResponse("BetterDisplay returned an invalid normalized range")
        return value

    @staticmethod
    def _text(text: str) -> str:
        if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise InvalidResponse("BetterDisplay returned invalid text")
        return text

    async def read_feature(self, target: Display | None, feature: str) -> Capability:
        definition = self._definition(target, feature)
        if definition.platform == "button":
            raise ValueError("Stateless actions have no readable state")
        params = {} if target is None else self._target(target)
        params[definition.read_feature or feature] = ""
        if definition.normalized:
            params.update(value="", min="0", max="1")
        text = await self._request("get", params)
        choices: dict[str, str] = {}
        if definition.normalized:
            value: object = self._normalized(text)
        elif definition.platform in ("switch", "binary_sensor"):
            value = self._boolean(text)
        elif feature == "ambientLight":
            try:
                value = float(text)
            except ValueError:
                raise InvalidResponse("BetterDisplay returned invalid illuminance") from None
            if not math.isfinite(value) or value < 0:
                raise InvalidResponse("BetterDisplay returned invalid illuminance")
        elif feature == "associatedDisplays":
            try:
                records = json.loads(text, object_pairs_hook=_unique_object)
                if not isinstance(records, list):
                    raise ValueError
                value = []
                seen: set[str] = set()
                for record in records:
                    if not isinstance(record, dict) or set(record) != {"tagID", "name"}:
                        raise ValueError
                    tag = record["tagID"]
                    if isinstance(tag, int) and not isinstance(tag, bool):
                        tag = str(tag)
                    if not isinstance(tag, str) or not re.fullmatch(r"[1-9][0-9]*", tag) or tag in seen:
                        raise ValueError
                    name = self._text(record["name"]) if isinstance(record["name"], str) else None
                    if name is None:
                        raise ValueError
                    seen.add(tag)
                    value.append({"tagID": tag, "name": name})
            except (ValueError, TypeError, KeyError, RecursionError):
                raise InvalidResponse("BetterDisplay returned invalid associations") from None
        else:
            value = self._text(text)
            if feature == "displayModeNumber" and not re.fullmatch(r"0|[1-9][0-9]*", text):
                raise InvalidResponse("BetterDisplay returned an invalid mode")
            if feature == "rotation" and text not in ("0", "90", "180", "270"):
                raise InvalidResponse("BetterDisplay returned an invalid rotation")
        if definition.platform == "select":
            choices = await self.choices(target, feature)
            if str(value) not in choices:
                raise InvalidResponse("Current selection is absent from supported choices")
        return Capability(value, choices)

    async def write_feature(self, target: Display | None, feature: str, value: object) -> None:
        definition = self._definition(target, feature)
        if definition.platform not in ("number", "switch", "select") or definition.operation != "set":
            raise ValueError("Feature is not writable")
        params = {} if target is None else self._target(target)
        if definition.normalized:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError("Expected a finite normalized value between 0 and 1")
            params.update(min="0", max="1")
            wire = str(value)
        elif definition.platform == "switch":
            if not isinstance(value, bool):
                raise ValueError("Expected a Boolean")
            wire = "on" if value else "off"
        else:
            if not isinstance(value, str):
                raise ValueError("Expected an exact selection wire value")
            wire = self._text(value)
            if feature == "rotation" and wire not in ("0", "90", "180", "270"):
                raise ValueError("Invalid rotation")
            if feature == "displayModeNumber" and not re.fullmatch(r"0|[1-9][0-9]*", wire):
                raise ValueError("Invalid mode number")
        params[feature] = wire
        await self._request("set", params)

    async def choices(self, target: Display | None, feature: str) -> dict[str, str]:
        definition = self._definition(target, feature)
        if feature == "rotation":
            return {str(angle): f"{angle}°" for angle in (0, 90, 180, 270)}
        if definition.list_feature is None:
            raise ValueError("Feature has no choice list")
        params = {} if feature == "colorProfileURL" or target is None else self._target(target)
        text = await self._request("get", {**params, definition.list_feature: ""})
        result: dict[str, str] = {}
        lines = text.splitlines()
        if feature == "xdrPreset" and text.startswith("["):
            try:
                lines = json.loads(text)
                if not isinstance(lines, list) or not all(isinstance(item, str) for item in lines):
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise InvalidResponse("BetterDisplay returned an invalid preset list") from None
        for raw in lines:
            line = self._text(raw.strip())
            if feature == "displayModeNumber":
                match = re.fullmatch(r"(0|[1-9][0-9]*)\s+-\s+(.+)", line)
                if not match:
                    raise InvalidResponse("BetterDisplay returned an invalid mode list")
                wire, label = match.groups()
                if re.search(r"\b(?:unsafe|invalid)\b", label, re.IGNORECASE):
                    continue
                label = re.sub(r"(?:\[\s*Current\s*\]|\(\s*Current\s*\)|\bCurrent\b)", "", label, flags=re.IGNORECASE)
                label = re.sub(r"([\[(])\s*,\s*|,\s*([\])])", lambda match: match.group(1) or match.group(2), label)
                label = re.sub(r"\[\s*\]|\(\s*\)", "", label)
                label = " ".join(label.split()).strip(" ,")
                if not label or not re.search(r"\b[1-9][0-9]*x[1-9][0-9]*\b", label):
                    raise InvalidResponse("BetterDisplay returned an invalid mode description")
            elif feature == "changeInputSource":
                match = re.fullmatch(r"(0|[1-9][0-9]*)\s+-\s+(.+?)\s+\[([A-Za-z][A-Za-z0-9_]*Controller)\]", line)
                if not match:
                    raise InvalidResponse("BetterDisplay returned an invalid input list")
                identifier, name, controller = match.groups()
                wire = json.dumps([controller, identifier], separators=(",", ":"))
                label = f"{name} [{controller}]"
            elif feature == "refreshRate":
                if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?(?:-[0-9]+(?:\.[0-9]+)?)?Hz(?:-VRR)?|ProMotion)", line, re.IGNORECASE):
                    raise InvalidResponse("BetterDisplay returned an invalid refresh rate list")
                wire = label = line
            elif feature == "colorProfileURL":
                try:
                    url = URL(line)
                    valid = (
                        url.scheme == "file"
                        and url.host in (None, "", "localhost")
                        and url.path.startswith("/")
                        and bool(url.name)
                        and not url.query_string
                        and not url.fragment
                    )
                except ValueError:
                    valid = False
                if not valid:
                    raise InvalidResponse("BetterDisplay returned an invalid profile URL")
                wire, label = line, url.name
            else:
                if line.startswith(("{", "[")) or re.match(r"[0-9]+\s+-\s+", line):
                    raise InvalidResponse("BetterDisplay returned an ambiguous preset list")
                wire = label = line
                if feature == "xdrPreset" and line.casefold() == "betterdisplay xdr":
                    label = f"{line} (Pro)"
            if wire in result:
                raise InvalidResponse("BetterDisplay returned duplicate choices")
            result[wire] = label
        return result

    async def controllers(self, target: Display) -> tuple[str, ...]:
        text = await self._request("get", {**self._target(target), "configuredControllerList": ""})
        names = tuple(line.strip() for line in text.splitlines())
        if any(not _CONTROLLER.fullmatch(name) for name in names) or len(names) != len(set(names)):
            raise InvalidResponse("BetterDisplay returned invalid controller identities")
        return names

    async def read_association(self, virtual: Display, other: Display) -> bool:
        self._definition(virtual, "associated")
        if not isinstance(other, Display) or other.device_type != "Display":
            raise ValueError("Association requires a physical display target")
        text = await self._request("get", {**self._target(virtual), "associated": "", "targetUUID": other.uuid.upper()})
        return self._boolean(text)

    async def perform(self, target: Display | None, action: str, *, value: object = None, other: Display | None = None) -> None:
        definition = self._definition(target, action)
        if definition.platform != "button":
            raise ValueError("Unsupported action")
        params = {} if target is None else self._target(target)
        operation = definition.operation
        if action in ("moveTo", "associated"):
            if not isinstance(other, Display) or other.device_type != "Display" or other.key == target.key:
                raise ValueError("A different explicit physical target is required")
            params["targetUUID"] = other.uuid.upper()
        elif other is not None:
            raise ValueError("Unexpected secondary target")
        if action == "changeInputSource":
            try:
                decoded = json.loads(value) if isinstance(value, str) else None
                if not isinstance(decoded, list) or len(decoded) != 2:
                    raise ValueError
                controller, identifier = decoded
                if not isinstance(controller, str) or not _CONTROLLER.fullmatch(controller):
                    raise ValueError
                if not isinstance(identifier, str) or not re.fullmatch(r"0|[1-9][0-9]*", identifier):
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise ValueError("Invalid input choice identity") from None
            params.update(specifier=controller, changeInputSource=identifier)
        elif action == "sendCEC":
            if not isinstance(value, str) or value not in CEC_COMMANDS:
                raise ValueError("Unsupported CEC command")
            params.update(sendCEC=value, CECAddress="tv")
        elif action == "moveTo":
            if not isinstance(value, str) or value not in MOVE_POSITIONS:
                raise ValueError("Unsupported layout position")
            params["moveTo"] = value
        elif action == "associated":
            if not isinstance(value, bool):
                raise ValueError("Expected a Boolean association")
            params["associated"] = "on" if value else "off"
        elif action == "favoriteMode":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError("Favorite slot must be 1 through 5")
            params["favoriteMode"] = str(value)
        else:
            if value is not None:
                raise ValueError("Unexpected action value")
            if action == "setMain":
                params["main"] = "on"
            elif action == "muteToggle":
                params["mute"] = ""
            elif action == "applyLayoutProtection":
                params["applyLayoutProtection"] = ""
            else:
                raise ValueError("Unsupported action")
        await self._request(operation, params)

    async def probe(self, families: list[str] | None = None) -> Probe:
        """Probe only opted-in controls, never by executing a write."""
        enabled = set(DEFAULT_FAMILIES if families is None else families)
        if not enabled <= set(DEFAULT_FAMILIES + OPTIONAL_FAMILIES):
            raise ValueError("Unknown feature family")
        displays = await self.discover()
        pro = await self.get_pro_available()
        capabilities: dict[str, dict[str, Capability]] = {}
        brightness: dict[str, float] = {}
        targets: list[tuple[str, Display | None]] = list(displays.items())
        if "mac" in enabled or "layout" in enabled:
            targets.append((MAC_KEY, None))
        for key, target in targets:
            scope = "Mac" if target is None else target.device_type
            if scope == "VirtualScreen" and "virtual" not in enabled:
                continue
            if scope == "DisplayGroup" and "groups" not in enabled:
                continue
            supported: dict[str, Capability] = {}
            for feature, definition in CATALOG.items():
                family = family_for(feature, target)
                if scope not in definition.scopes or family not in enabled:
                    continue
                try:
                    if feature == "changeInputSource":
                        options = await self.choices(target, feature)
                        if options:
                            supported[feature] = Capability(None, options)
                    elif feature == "sendCEC":
                        if "CECController" in await self.controllers(target):
                            supported[feature] = Capability(None, {command: command for command in CEC_COMMANDS})
                    elif definition.platform != "button":
                        supported[feature] = await self.read_feature(target, feature)
                except (UnsupportedControl, InvalidResponse):
                    continue
            if "main" in supported and "layout" in enabled:
                supported["setMain"] = Capability()
            if supported:
                capabilities[key] = supported
            if "brightness" in supported:
                brightness[key] = supported["brightness"].value
        return Probe(displays, brightness, pro, capabilities)
