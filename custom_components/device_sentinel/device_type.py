# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_type.py, Version: 0.25.2 (2026-10-09)

"""What each device is, in plain words (0.25.1, Project__Device_Type.md).

Home Assistant keeps no type for a device, so Device Sentinel reads one
from the device's own entities: the kind of entity Home Assistant made
for it, and the device class the integration gave it. First match wins,
in the order James approved on 8 October 2026 after the rules were run
on the reference rig's 103 devices. Settings and diagnostic entities
are left out, since a radio's configuration switch says nothing about
what the device is. A device nothing matches has no type: the page
says so and offers the pencil, and nothing is guessed.

The owner's answer wins, and like the Power row's it covers every
device of the same model. Owner answers live in the answers file with
the power answers (answers_store.py), written only when a pencil is
used and kept with a last-good copy.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import STACK_Z2M
from .device_fields import device_field
from .power_source import NOT_KNOWN, clean_other, is_model_key
from .stacks import is_plumbing

TYPE_OTHER = "Other"
SOURCE_ENTITIES = "entities"
SOURCE_OWNER = "owner"
# Device Sentinel's own answer from somewhere other than the entities
# (0.25.2): a model it knows, or what the device is to its network.
SOURCE_KNOWN = "known model"
SOURCE_ROLE = "role"

CAMERA = "Camera"
VOICE_ASSISTANT = "Voice Assistant"
COVER = "Cover"
LEAK_SENSOR = "Leak Sensor"
DOOR_WINDOW_SENSOR = "Door/Window Sensor"
VIBRATION_SENSOR = "Vibration Sensor"
MOTION_SENSOR = "Motion Sensor"
PRESENCE_SENSOR = "Presence Sensor"
SMOKE_ALARM = "Smoke Alarm"
CO_ALARM = "CO Alarm"
SWITCH = "Switch"
PLUG = "Plug"
SOIL_SENSOR = "Soil Sensor"
TEMPERATURE_SENSOR = "Temperature Sensor"
BUTTON = "Button"
# Added in 0.25.2 (James, 9 October 2026), in each network's own words:
# Zigbee has a coordinator, Z-Wave a controller, Thread a border router.
ZIGBEE_COORDINATOR_Z2M = "Zigbee Coordinator (Zigbee2MQTT)"
ZIGBEE_COORDINATOR_ZHA = "Zigbee Coordinator (ZHA)"
ZWAVE_CONTROLLER = "Z-Wave Controller"
THREAD_BORDER_ROUTER = "Thread Border Router"
MATTER_BRIDGE = "Matter Bridge"
ZIGBEE_ROUTER = "Zigbee Router"
ZWAVE_REPEATER = "Z-Wave Repeater"
THREAD_ROUTER = "Thread Router"
HUB = "Hub"
PRINTER = "Printer"
DASHBOARD = "Dashboard"
PLANT_WATERER = "Plant Waterer"
MULTI_SENSOR = "Multi Sensor"
LOCK = "Lock"
THERMOSTAT = "Thermostat"
VALVE = "Valve"
SIREN = "Siren"
FAN = "Fan"
LIGHT = "Light"
BLUETOOTH_PROXY = "Bluetooth Proxy"
ESPHOME_DEVICE = "ESPHome Device"

# The kinds of entity that settle a type on their own, checked first.
# A camera with a switch for its spotlight is still a camera, and a
# voice satellite with an LED light is still a voice assistant. A lock
# with a door contact is a lock, a thermostat that reports temperature
# is a thermostat, and a valve with a leak probe is a valve (0.25.2).
DOMAIN_TYPES: tuple[tuple[str, str], ...] = (
    ("camera", CAMERA),
    ("assist_satellite", VOICE_ASSISTANT),
    ("lock", LOCK),
    ("climate", THERMOSTAT),
    # A blind and a shade are both a cover (James, 8 October 2026):
    # Motionblinds gives all six of the reference rig's the class
    # "shade", so a split by class called two blinds shades.
    ("cover", COVER),
    ("valve", VALVE),
    ("fan", FAN),
)
# A binary sensor's device class, most telling first: a smoke and CO
# alarm is a smoke alarm, and a door sensor that also reports
# temperature is a door sensor. Motion and occupancy read alike, since
# integrations give a PIR sensor either; the pencil covers the rest.
BINARY_CLASSES: tuple[tuple[str, str], ...] = (
    ("smoke", SMOKE_ALARM),
    ("carbon_monoxide", CO_ALARM),
    ("moisture", LEAK_SENSOR),
    ("door", DOOR_WINDOW_SENSOR),
    ("window", DOOR_WINDOW_SENSOR),
    ("opening", DOOR_WINDOW_SENSOR),
    ("vibration", VIBRATION_SENSOR),
    ("motion", MOTION_SENSOR),
    ("occupancy", MOTION_SENSOR),
    ("presence", PRESENCE_SENSOR),
)
MOTION_CLASSES = frozenset({"motion", "occupancy", "presence"})
# A motion sensor that also reports all three of these is a multi
# sensor, a 4-in-1; with two of them it is still a motion sensor
# (James, 9 October 2026).
MULTI_READINGS = frozenset({"temperature", "humidity", "illuminance"})
PRINTER_DOMAINS = frozenset({"brother", "ipp"})

# Models whose type their entities cannot show, each answered by an
# owner and checked by James before it is listed (0.25.2, from the
# reference house's answers of 9 October 2026). Keyed exactly as an
# owner's answer is: manufacturer, model and model ID as Home
# Assistant reports them.
KNOWN_MODEL_TYPES: dict[tuple[str, str, str], str] = {
    ("Third Reality", "Zigbee / BLE smart plug", "3RSP019BZ"): PLUG,
    ("Aqara", "PS-S02E", ""): PRESENCE_SENSOR,
    ("Third Reality, Inc", "3RSMR01067Z", ""): PRESENCE_SENSOR,
    ("Sonoff", "NSPanel Pro", ""): DASHBOARD,
    ("Third Reality", "Smart watering kit", "3RWK0148Z"): PLANT_WATERER,
    ("Aeotec", "Range extender Zi", "WG001"): ZIGBEE_ROUTER,
    ("Zooz", "ZST39 LR", ""): ZWAVE_CONTROLLER,
}

TYPE_CHOICES: tuple[str, ...] = (
    *sorted({
        CAMERA, VOICE_ASSISTANT, COVER, LEAK_SENSOR, DOOR_WINDOW_SENSOR,
        VIBRATION_SENSOR, MOTION_SENSOR, PRESENCE_SENSOR, SMOKE_ALARM, CO_ALARM,
        SWITCH, PLUG, SOIL_SENSOR, TEMPERATURE_SENSOR, BUTTON,
        ZIGBEE_COORDINATOR_Z2M, ZIGBEE_COORDINATOR_ZHA, ZWAVE_CONTROLLER,
        THREAD_BORDER_ROUTER, MATTER_BRIDGE, ZIGBEE_ROUTER, ZWAVE_REPEATER,
        THREAD_ROUTER, HUB, PRINTER, DASHBOARD, PLANT_WATERER, MULTI_SENSOR,
        LOCK, THERMOSTAT, VALVE, SIREN, FAN, LIGHT, BLUETOOTH_PROXY, ESPHOME_DEVICE,
    }, key=str.casefold),
    TYPE_OTHER,
)


def _main(entities: list[Any]) -> list[Any]:
    return [
        e for e in entities
        if getattr(e, "disabled_by", None) is None and getattr(e, "entity_category", None) is None
    ]


def type_from_entities(entities: list[Any]) -> str | None:
    """A device's type from its registry entities, or None.

    Each entity needs `domain`, `entity_category`, `disabled_by` and a
    device class (`device_class` or `original_device_class`), as Home
    Assistant's registry entries carry.
    """
    main = _main(entities)
    domains = {getattr(e, "domain", None) for e in main}

    def classes(domain: str) -> set[str]:
        found = set()
        for e in main:
            if getattr(e, "domain", None) == domain:
                value = getattr(e, "device_class", None) or getattr(e, "original_device_class", None)
                if value:
                    found.add(str(value))
        return found

    for domain, words in DOMAIN_TYPES:
        if domain in domains:
            return words
    binary = classes("binary_sensor")
    sensors = classes("sensor")
    if binary & MOTION_CLASSES and MULTI_READINGS <= sensors and not binary & {
        "smoke", "carbon_monoxide", "moisture", "door", "window", "opening", "vibration"
    }:
        return MULTI_SENSOR
    for device_class, words in BINARY_CLASSES:
        if device_class in binary:
            return words
    # After the alarms and cameras, which usually carry a siren too.
    if "siren" in domains:
        return SIREN
    if "switch" in domains:
        return PLUG if "power" in sensors else SWITCH
    # Bulbs and light strips are lights (James, 9 October 2026).
    if "light" in domains:
        return LIGHT
    if "moisture" in sensors:
        return SOIL_SENSOR
    if sensors & {"temperature", "humidity"}:
        return TEMPERATURE_SENSOR
    if "event" in domains:
        return BUTTON
    return None


def type_for_device(
    entities: list[Any],
    *,
    domain: str | None = None,
    model: tuple[str, str, str] | None = None,
    role: str | None = None,
    zigbee_router: bool = False,
    bluetooth_proxy: bool = False,
    hub: bool = False,
) -> tuple[str | None, str | None]:
    """Device Sentinel's own answer and where it came from (0.25.2).

    In order: a model it knows; what the device is to its network when
    that is all it is for (a coordinator, a controller, a border
    router); what its entities say; and last, for a device whose
    entities name nothing, what its integration or network says (a
    printer, an ESPHome board or Bluetooth proxy, a Zigbee router, a
    Z-Wave repeater, a hub). A router plug stays a Plug.
    """
    if model is not None and model in KNOWN_MODEL_TYPES:
        return KNOWN_MODEL_TYPES[model], SOURCE_KNOWN
    if role:
        return role, SOURCE_ROLE
    words = type_from_entities(entities)
    if words:
        return words, SOURCE_ENTITIES
    if domain in PRINTER_DOMAINS:
        return PRINTER, SOURCE_ROLE
    if domain == "esphome":
        # An ESPHome board whose entities named nothing: what it is for,
        # where Home Assistant shows it (a Bluetooth proxy), else the
        # board itself (James, 9 October 2026).
        return (BLUETOOTH_PROXY if bluetooth_proxy else ESPHOME_DEVICE), SOURCE_ROLE
    if zigbee_router:
        return ZIGBEE_ROUTER, SOURCE_ROLE
    main = _main(entities)
    if domain == "zwave_js" and not main:
        return ZWAVE_REPEATER, SOURCE_ROLE
    if hub and not main:
        # ZHA hangs its devices from the coordinator's own device, and
        # a Matter bridge brings others into Matter.
        if domain == "zha":
            return ZIGBEE_COORDINATOR_ZHA, SOURCE_ROLE
        return (MATTER_BRIDGE if domain == "matter" else HUB), SOURCE_ROLE
    return None, None


def clean_type(text: str | None) -> str:
    """The owner's own words for a type, tidied, or ValueError."""
    try:
        words = clean_other(text)
    except ValueError as err:
        if "battery" in str(err):
            raise ValueError("Type what the device is.") from err
        raise
    if words.casefold() == NOT_KNOWN.casefold():
        # The page's own words for no type; as an answer it would read
        # as no answer, and the Devices tab would count it as one
        # (0.25.1, found by testing).
        raise ValueError("Type what the device is.")
    return words


def _host(url: Any) -> str | None:
    """The host of a URL or a socket address, lower case, or None."""
    if not isinstance(url, str) or "://" not in url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "homeassistant", "homeassistant.local"})


def _own_hosts(hass: Any) -> set[str]:
    """The addresses that are Home Assistant's own machine."""
    hosts = set(LOOPBACK_HOSTS)
    for url in (getattr(hass.config, "internal_url", None), getattr(hass.config, "external_url", None)):
        host = _host(url)
        if host:
            hosts.add(host)
    local_ip = getattr(getattr(hass.config, "api", None), "local_ip", None)
    if isinstance(local_ip, str) and local_ip:
        hosts.add(local_ip.lower())
    return hosts


def _zwave_node(device: Any) -> str | None:
    """A Z-Wave JS device's node number, from its "<home>-<node>"
    identifier; the controller is node 1."""
    for item in device_field(device, "identifiers", set()) or ():
        if isinstance(item, (tuple, list)) and len(item) >= 2 and item[0] == "zwave_js":
            parts = str(item[1]).split("-")
            if len(parts) == 2 and parts[1].isdigit():
                return parts[1]
    return None


def _clean_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        return None
    try:
        words = clean_type(raw["type"])
    except ValueError:
        return None
    set_at = raw.get("set") if isinstance(raw.get("set"), str) else None
    return {"type": words, "set": set_at}


class TypeMixin:
    """The coordinator's side of the Type row."""

    _type_models: dict[str, dict[str, Any]] = {}
    _type_entries: dict[str, dict[str, Any]] = {}

    def _type_reset(self) -> None:
        self._type_models = {}
        self._type_entries = {}

    def _type_read(self, payload: dict[str, Any]) -> int:
        """Take the owner's answers from a stored payload; the number left out."""
        dropped = 0
        models = payload.get("models")
        for key, raw in (models.items() if isinstance(models, dict) else ()):
            entry = _clean_entry(raw)
            setter = raw.get("device_id") if isinstance(raw, dict) else None
            if is_model_key(key) and entry is not None and isinstance(setter, str):
                self._type_models[key] = {**entry, "device_id": setter}
            else:
                dropped += 1
        devices = payload.get("devices")
        for device_id, raw in (devices.items() if isinstance(devices, dict) else ()):
            entry = _clean_entry(raw)
            if isinstance(device_id, str) and entry is not None:
                self._type_entries[device_id] = entry
            else:
                dropped += 1
        return dropped

    def _type_payload(self) -> dict[str, Any]:
        return {
            "models": {k: dict(v) for k, v in sorted(self._type_models.items())},
            "devices": {k: dict(v) for k, v in sorted(self._type_entries.items())},
        }

    def _type_save(self) -> None:
        self._answers_save()  # type: ignore[attr-defined]

    # ------------------------------------------------------------- reading

    def type_from_registry(self, device_id: str) -> str | None:
        """Device Sentinel's own answer for the device, owner aside."""
        return self._type_auto(device_id)[0]

    def _type_auto(self, device_id: str) -> tuple[str | None, str | None]:
        """Device Sentinel's own answer and its source (0.25.2)."""
        hass = self.hass  # type: ignore[attr-defined]
        entities = er.async_entries_for_device(er.async_get(hass), device_id)
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            words = type_from_entities(entities)
            return words, (SOURCE_ENTITIES if words else None)
        domain = self._primary_domain(device)  # type: ignore[attr-defined]
        maker, model, model_id, _hw = self._power_device_fields(device_id)  # type: ignore[attr-defined]
        return type_for_device(
            entities,
            domain=domain,
            model=(maker or "", model or "", model_id or "") if maker and model else None,
            role=self._network_role(device, domain),
            zigbee_router=self._zigbee_router(device_id),
            bluetooth_proxy=device_id in getattr(self, "_bluetooth_parents", ()),
            hub=device_id in getattr(self, "_via_parents", ()),
        )

    def _network_role(self, device: Any, domain: str | None) -> str | None:
        """What the device is to its network: a coordinator, a controller,
        a border router, or None (0.25.2)."""
        try:
            if domain and is_plumbing(domain, device):
                # Zigbee2MQTT's bridge device is the coordinator as
                # Zigbee2MQTT shows it (ruling #400 sets it aside).
                return ZIGBEE_COORDINATOR_Z2M
            if domain == "zwave_js" and _zwave_node(device) == "1":
                return ZWAVE_CONTROLLER
            if domain == "otbr":
                return THREAD_BORDER_ROUTER
            host = _host(device_field(device, "configuration_url"))
            if host:
                return self._coordinator_hosts().get(host)
        except Exception:  # noqa: BLE001 - a type is never worth a failure
            return None
        return None

    def _coordinator_hosts(self) -> dict[str, str]:
        """Each network coordinator's host and what it is, from the
        settings of the integrations that use it."""
        hass = self.hass  # type: ignore[attr-defined]
        hosts: dict[str, str] = {}
        for entry in hass.config_entries.async_entries("otbr"):
            host = _host((entry.data or {}).get("url"))
            if host:
                hosts[host] = THREAD_BORDER_ROUTER
        for entry in hass.config_entries.async_entries("zha"):
            device = (entry.data or {}).get("device")
            host = _host(device.get("path") if isinstance(device, dict) else None)
            if host:
                hosts[host] = ZIGBEE_COORDINATOR_ZHA
        reader = (getattr(self, "_bridge_readers", None) or {}).get(STACK_Z2M)
        host = _host(getattr(reader, "serial_port", None))
        if host:
            hosts[host] = ZIGBEE_COORDINATOR_Z2M
        # A coordinator served from Home Assistant's own machine (an
        # add-on) shares its address with every other device served
        # there, such as a camera's add-on; that address names nothing
        # (found by review).
        for own in _own_hosts(hass):
            hosts.pop(own, None)
        return hosts

    def _zigbee_router(self, device_id: str) -> bool:
        """Whether Zigbee2MQTT lists the device as a router."""
        key = (getattr(self, "_stack_keys", None) or {}).get(device_id)
        reader = (getattr(self, "_bridge_readers", None) or {}).get(STACK_Z2M)
        if not key or reader is None or key[0] != STACK_Z2M:
            return False
        try:
            return reader.zigbee_role(key[1]) == "Router"
        except Exception:  # noqa: BLE001
            return False

    def _type_entry(self, device_id: str) -> tuple[dict[str, Any] | None, str | None]:
        entry = self._type_entries.get(device_id)
        if entry is not None:
            return entry, None
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        if key is not None and key in self._type_models:
            return self._type_models[key], key
        return None, key

    def type_of(self, device_id: str, covers: bool = False) -> dict[str, Any]:
        """The device's type and where it came from: the owner, a model
        Device Sentinel knows, a network role, its entities, or nothing.
        covers, as power_of's, only for the device page."""
        entry, key = self._type_entry(device_id)
        auto, auto_source = self._type_auto(device_id)
        if entry is not None:
            return {
                "words": entry["type"],
                "source": SOURCE_OWNER,
                "auto": auto,
                "auto_source": auto_source,
                "set_on": entry.get("device_id", device_id),
                "covers": (self._model_covers(key, self._type_entries) if key else 1) if covers else None,  # type: ignore[attr-defined]
            }
        return {"words": auto, "source": auto_source, "auto": auto, "auto_source": auto_source}

    def type_words(self, device_id: str) -> str | None:
        return self.type_of(device_id)["words"]

    def type_view(self, device_id: str) -> dict[str, Any]:
        """What the device page's Type row needs."""
        known = self.type_of(device_id, covers=True)
        set_on = known.get("set_on")
        key = self._power_key(device_id) if device_id in self._type_entries else None  # type: ignore[attr-defined]
        model = self._type_models.get(key) if key else None
        return {
            **known,
            # The model's answer, when this device has its own: what
            # clearing its own puts in place (found by review).
            "model_answer": model["type"] if model else None,
            "set_on_name": (
                self._device_name(set_on)  # type: ignore[attr-defined]
                if set_on and dr.async_get(self.hass).async_get(set_on) is not None  # type: ignore[attr-defined]
                else None
            ),
            "choices": list(TYPE_CHOICES),
            "other": TYPE_OTHER,
        }

    def type_diagnostics(self, device_id: str) -> dict[str, Any]:
        known = self.type_of(device_id)
        return {
            "words": known["words"], "source": known["source"],
            "from_entities": known["auto"], "auto_source": known["auto_source"],
        }

    # ------------------------------------------------------------- the pencil

    def page_set_type(self, device_id: str, choice: str | None, other: str | None = None) -> None:
        """Set the owner's type from the device page; None goes back to the entities' answer.

        Like the Power row's (0.24.8), the answer covers every device of
        the same model, and clearing it clears it for all of them.
        """
        self._device(device_id)  # type: ignore[attr-defined]
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        covers = self._model_covers(key, self._type_entries, device_id) if key else 1  # type: ignore[attr-defined]
        many = f", for all {covers} devices of this model" if covers > 1 else ""
        if not choice:
            # Its own answer alone when it has one, as on the Power row.
            had_own = self._type_entries.pop(device_id, None) is not None
            had_model = not had_own and key is not None and self._type_models.pop(key, None) is not None
            if not (had_own or had_model):
                return
            if had_own:
                many = ""
            self._type_save()
            now = self.type_of(device_id)
            if now["source"] == SOURCE_OWNER:
                used = f", the model's {now['words']} used"
            elif now["words"] and now["source"] == SOURCE_ENTITIES:
                used = f", {now['words']} from its entities used"
            elif now["words"]:
                # A known model or a network role (0.25.2, found by review).
                used = f", Device Sentinel's {now['words']} used"
            else:
                used = ""
            self._page_done(device_id, f"type entry removed{used}{many}")  # type: ignore[attr-defined]
            return
        if choice == TYPE_OTHER:
            words = clean_type(other)
        elif choice in TYPE_CHOICES:
            words = choice
        else:
            raise ValueError("Choose from the list.")
        entry = {"type": words, "set": dt_util.utcnow().isoformat()}
        if key is not None:
            self._type_models[key] = {**entry, "device_id": device_id}
            self._type_entries.pop(device_id, None)
        else:
            self._type_entries[device_id] = entry
        self._type_save()
        self._page_done(device_id, f"type set to {words}{many}")  # type: ignore[attr-defined]

    @callback
    def _type_forget(self, device_id: str | None) -> None:
        """A device gone from Home Assistant takes its own answer with it;
        a model answer it set passes to another device of the model."""
        if not device_id:
            return
        changed = self._type_entries.pop(device_id, None) is not None
        for key, entry in list(self._type_models.items()):
            if entry.get("device_id") != device_id:
                continue
            others = self._power_same_model(key, leaving=device_id) or self._model_devices_anywhere(  # type: ignore[attr-defined]
                key, leaving=device_id
            )
            if others:
                entry["device_id"] = others[0]
            else:
                del self._type_models[key]
            changed = True
        if changed:
            self._type_save()

