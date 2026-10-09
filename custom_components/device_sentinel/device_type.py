# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_type.py, Version: 0.25.1 (2026-10-08)

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

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .power_source import NOT_KNOWN, clean_other, is_model_key

TYPE_OTHER = "Other"
SOURCE_ENTITIES = "entities"
SOURCE_OWNER = "owner"

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

# The kinds of entity that settle a type on their own, checked first.
# A camera with a switch for its spotlight is still a camera, and a
# voice satellite with an LED light is still a voice assistant.
DOMAIN_TYPES: tuple[tuple[str, str], ...] = (
    ("camera", CAMERA),
    ("assist_satellite", VOICE_ASSISTANT),
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
SWITCH_DOMAINS = frozenset({"switch", "light"})

TYPE_CHOICES: tuple[str, ...] = (
    *sorted({
        CAMERA, VOICE_ASSISTANT, COVER, LEAK_SENSOR, DOOR_WINDOW_SENSOR,
        VIBRATION_SENSOR, MOTION_SENSOR, PRESENCE_SENSOR, SMOKE_ALARM, CO_ALARM,
        SWITCH, PLUG, SOIL_SENSOR, TEMPERATURE_SENSOR, BUTTON,
    }),
    TYPE_OTHER,
)


def type_from_entities(entities: list[Any]) -> str | None:
    """A device's type from its registry entities, or None.

    Each entity needs `domain`, `entity_category`, `disabled_by` and a
    device class (`device_class` or `original_device_class`), as Home
    Assistant's registry entries carry.
    """
    main = [
        e for e in entities
        if getattr(e, "disabled_by", None) is None and getattr(e, "entity_category", None) is None
    ]
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
    # A blind and a shade are both a cover (James, 8 October 2026):
    # Motionblinds gives all six of the reference rig's the class
    # "shade", so a split by class called two blinds shades.
    if "cover" in domains:
        return COVER
    binary = classes("binary_sensor")
    for device_class, words in BINARY_CLASSES:
        if device_class in binary:
            return words
    sensors = classes("sensor")
    if domains & SWITCH_DOMAINS:
        return PLUG if "power" in sensors else SWITCH
    if "moisture" in sensors:
        return SOIL_SENSOR
    if sensors & {"temperature", "humidity"}:
        return TEMPERATURE_SENSOR
    if "event" in domains:
        return BUTTON
    return None


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
        """What the device's own entities say it is."""
        registry = er.async_get(self.hass)  # type: ignore[attr-defined]
        return type_from_entities(er.async_entries_for_device(registry, device_id))

    def _type_entry(self, device_id: str) -> tuple[dict[str, Any] | None, str | None]:
        entry = self._type_entries.get(device_id)
        if entry is not None:
            return entry, None
        key = self._power_key(device_id)  # type: ignore[attr-defined]
        if key is not None and key in self._type_models:
            return self._type_models[key], key
        return None, key

    def type_of(self, device_id: str, covers: bool = False) -> dict[str, Any]:
        """The device's type and where it came from: the owner, its entities,
        or nothing. covers, as power_of's, only for the device page."""
        entry, key = self._type_entry(device_id)
        auto = self.type_from_registry(device_id)
        if entry is not None:
            return {
                "words": entry["type"],
                "source": SOURCE_OWNER,
                "auto": auto,
                "set_on": entry.get("device_id", device_id),
                "covers": (self._model_covers(key, self._type_entries) if key else 1) if covers else None,  # type: ignore[attr-defined]
            }
        return {"words": auto, "source": SOURCE_ENTITIES if auto else None, "auto": auto}

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
        return {"words": known["words"], "source": known["source"], "from_entities": known["auto"]}

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
            elif now["words"]:
                used = f", {now['words']} from its entities used"
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

