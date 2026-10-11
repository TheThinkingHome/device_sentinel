# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/power_source.py, Version: 0.25.5 (2026-10-10)

"""What powers each device (0.24.7, Project__0_24_7.md).

Two sources, in this order: what the owner entered on the device page,
then the Battery Notes device library shipped inside Device Sentinel
(Andrew Jackson's library.json, MIT, see data/BATTERY_LIBRARY_LICENSE.md).
Nothing here reads an installed Battery Notes.

The library is a read-only file in the integration's own folder, read
once at start and replaced only when a release replaces it. Owner
entries live in the answers file with the device types (0.25.1,
answers_store.py), written only when a pencil is used, so the main
storage file never carries them.

The matcher is a port of Battery Notes' own get_device_battery_details,
so a device gets the answer Battery Notes would give it: manufacturer
compared without regard to case; model exact unless the entry names a
match method; model ID and hardware version handled as Battery Notes
handles them; several answers that disagree give none; an entry marked
MANUAL gives none, as Battery Notes skips it.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DATA_DEVICES, LOGGER
from .device_fields import device_field

LIBRARY_PATH = Path(__file__).parent / "data" / "battery_library.json"

# The ten battery types the library names most often, most used first
# (5 October 2026: 94.8% of the library's devices, 97.1% of the
# matched devices in three real houses), then the two that are not
# batteries, then Other.
BATTERY_CHOICES: tuple[str, ...] = (
    "AA", "AAA", "CR2032", "CR2450", "Rechargeable",
    "CR123A", "CR2", "CR2477", "CR1632", "CR2430",
)
POWER_MAINS = "Mains Powered"
POWER_USB = "USB Powered"
# Plugged straight into the Home Assistant machine, so it goes down with
# it (0.25.3, James's Z-Wave stick).
POWER_USB_SERVER = "USB Direct to Server"
POWER_POE = "PoE Powered"  # Power over Ethernet (0.24.8)
POWER_OTHER = "Other"
POWER_WIRED: tuple[str, ...] = (POWER_MAINS, POWER_USB, POWER_USB_SERVER, POWER_POE)
POWER_CHOICES: tuple[str, ...] = (*BATTERY_CHOICES, *POWER_WIRED, POWER_OTHER)
QUANTITY_MIN = 1
QUANTITY_MAX = 8
OTHER_MAX_LENGTH = 40

SOURCE_OWNER = "owner"
SOURCE_LIBRARY = "library"
KIND_BATTERY = "battery"
KIND_MAINS = "mains"
KIND_USB = "usb"
KIND_POE = "poe"
WIRED_KINDS = {POWER_MAINS: KIND_MAINS, POWER_USB: KIND_USB, POWER_USB_SERVER: KIND_USB, POWER_POE: KIND_POE}

REPORT_FORM = "https://github.com/andrew-codechimp/HA-Battery-Notes/issues/new"
REPORT_TEMPLATE = "new_device_request.yaml"
LIBRARY_HOME = "https://github.com/andrew-codechimp/HA-Battery-Notes"
NOT_KNOWN = "Not known"


def power_words(battery_type: str, quantity: int | None) -> str:
    """The type as people say it: "2× AAA", or "CR2032" for one."""
    if quantity is not None and quantity > 1:
        return f"{quantity}× {battery_type}"
    return battery_type


def _fold(value: Any) -> str:
    return str(value or "").casefold()


def model_key(manufacturer: Any, model: Any, model_id: Any) -> str | None:
    """What makes two devices the same model, for an owner's entry
    (0.24.8): manufacturer, model and model ID, exactly as Home
    Assistant reports them. The hardware version is left out, because
    one model reports a version on some devices and none on others.
    None for a device with no manufacturer or no model.
    """
    if not manufacturer or not model:
        return None
    return json.dumps([str(manufacturer), str(model), str(model_id or "")])


def is_model_key(key: Any) -> bool:
    """Whether a stored key has the shape model_key gives (0.25.1): the
    JSON text of three strings, the first two not empty. A damaged key
    is left out at load rather than carried into the diagnostics."""
    if not isinstance(key, str):
        return False
    try:
        parts = json.loads(key)
    except ValueError:
        return False
    return (
        isinstance(parts, list) and len(parts) == 3
        and all(isinstance(p, str) for p in parts) and bool(parts[0]) and bool(parts[1])
    )


@dataclass(frozen=True)
class LibraryAnswer:
    """One library entry's answer for a device."""

    battery_type: str
    quantity: int | None

    @property
    def words(self) -> str:
        return power_words(self.battery_type, self.quantity)


class BatteryLibrary:
    """Battery Notes' library, indexed by manufacturer, with its rules."""

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.size = 0
        self._by_maker: dict[str, list[dict[str, Any]]] = {}
        skipped = 0
        for entry in devices:
            if not _library_entry_usable(entry):
                skipped += 1
                continue
            self._by_maker.setdefault(entry["manufacturer"].casefold(), []).append(entry)
            self.size += 1
        if skipped:
            LOGGER.warning(
                "Device Sentinel left %s malformed entries out of its battery library; "
                "those devices read \"Not known\" until the library is corrected",
                skipped,
            )

    @staticmethod
    def _model_matches(entry: dict[str, Any], model: str | None) -> bool:
        wanted = _fold(entry.get("model"))
        have = _fold(model)
        method = entry.get("model_match_method")
        if method == "startswith":
            return have.startswith(wanted)
        if method == "endswith":
            return have.endswith(wanted)
        if method == "contains":
            return wanted in have
        if method:
            # A method this port does not know matches nothing, as in
            # Battery Notes, which only knows these three.
            return False
        return wanted == have

    def match(
        self,
        manufacturer: str | None,
        model: str | None,
        model_id: str | None = None,
        hw_version: str | None = None,
    ) -> LibraryAnswer | None:
        """Battery Notes' answer for a device, or None.

        Battery Notes' own search and nothing looser: a looser second
        search was built for 0.24.8 and withdrawn the same day, because
        a match that is not certain is worse than "Not known" and a
        report to the library.
        """
        if not manufacturer or not all(
            value is None or isinstance(value, str)
            for value in (manufacturer, model, model_id, hw_version)
        ):
            # A question that is not text has no answer (0.24.11); the
            # device's own fields are made text before they are asked.
            return None
        model_id = model_id or None
        hw_version = hw_version or None
        found = [
            e for e in self._by_maker.get(manufacturer.casefold(), ())
            if self._model_matches(e, model)
        ]
        if not found:
            return None
        if model_id is None and hw_version is None:
            # A device with neither matches only entries with neither.
            found = [e for e in found if e.get("model_id") is None and e.get("hw_version") is None]
            if not found:
                return None
        else:
            found = [
                e for e in found
                if not (model_id is None and e.get("model_id") is not None)
                and not (hw_version is None and e.get("hw_version") is not None)
                and not (model_id is not None and e.get("model_id") is not None
                         and _fold(e["model_id"]) != _fold(model_id))
                and not (hw_version is not None and e.get("hw_version") is not None
                         and _fold(e["hw_version"]) != _fold(hw_version))
            ]
            if not found:
                return None
        if len(found) > 1:
            def partial(e: dict[str, Any]) -> bool:
                if hw_version is None and model_id is None:
                    return e.get("hw_version") is None and e.get("model_id") is None
                if (hw_version is not None and model_id is not None
                        and _fold(e.get("hw_version")) == _fold(hw_version)
                        and _fold(e.get("model_id")) == _fold(model_id)):
                    return True
                if hw_version is not None and _fold(e.get("hw_version")) == _fold(hw_version):
                    return True
                return model_id is not None and _fold(e.get("model_id")) == _fold(model_id)

            narrowed = [e for e in found if partial(e)]
            if narrowed:
                found = narrowed
                if len(found) > 1:
                    full = [
                        e for e in found
                        if _fold(e.get("hw_version")) == _fold(hw_version)
                        and _fold(e.get("model_id")) == _fold(model_id)
                    ]
                    if full:
                        found = full
        first = found[0]
        fields = ("manufacturer", "model", "model_id", "hw_version",
                  "model_match_method", "battery_type", "battery_quantity")
        if any(any(e.get(f) != first.get(f) for f in fields) for e in found[1:]):
            # Answers that disagree give none, as in Battery Notes.
            return None
        kind = first["battery_type"]
        if kind.strip().upper() == "MANUAL":
            return None
        quantity = _quantity(first.get("battery_quantity"))
        return LibraryAnswer(kind, quantity)


def _library_entry_usable(entry: Any) -> bool:
    """Whether a library entry can be shown as it stands (0.24.11).

    The library is copied unchanged from Battery Notes, so a malformed
    entry in a future copy reaches every surface that names a battery.
    An entry is kept only when the pencil would accept the same answer
    from the owner: a type of visible characters, at most 40, already
    tidy, and a quantity of 1 to 8 or none. The fields the search reads
    must be text where present. No entry Battery Notes ships breaks
    these rules, so leaving one out costs only that device's answer,
    which reads "Not known" as an unlisted device does.
    """
    if not isinstance(entry, dict):
        return False
    if not all(isinstance(entry.get(f), str) for f in ("manufacturer", "model", "battery_type")):
        return False
    if not all(entry.get(f) is None or isinstance(entry.get(f), str)
               for f in ("model_id", "hw_version", "model_match_method")):
        return False
    kind = entry["battery_type"]
    try:
        if clean_other(kind) != kind:
            return False
    except ValueError:
        return False
    quantity = entry.get("battery_quantity")
    return quantity is None or (
        isinstance(quantity, int) and not isinstance(quantity, bool)
        and QUANTITY_MIN <= quantity <= QUANTITY_MAX
    )


def _as_text(value: Any) -> str | None:
    """A registry field as text, as Home Assistant 2026.6 and later store a
    new registration (0.24.11). A field saved as a number by 2026.5 is
    still loaded as one, and the library search compares text."""
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _quantity(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def load_library(path: Path = LIBRARY_PATH) -> BatteryLibrary | None:
    """Read the shipped library; None, with one warning, if it cannot be."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        devices = data["devices"]
        if not isinstance(devices, list):
            raise ValueError("devices is not a list")
    except (OSError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning(
            "Device Sentinel cannot read its battery library, so battery types "
            "come only from what owners enter on device pages (%s)",
            err,
        )
        return None
    return BatteryLibrary(devices)


def power_choices() -> dict[str, Any]:
    """The pencil's choices, for any page that sets power (0.24.9)."""
    return {
        "choices": list(POWER_CHOICES),
        "battery_choices": list(BATTERY_CHOICES),
        "wired": list(POWER_WIRED),
        "mains": POWER_MAINS,
        "usb": POWER_USB,
        "other": POWER_OTHER,
        "quantity": [QUANTITY_MIN, QUANTITY_MAX],
    }


def clean_other(text: str | None) -> str:
    """The owner's own type, tidied, or ValueError with the reason."""
    words = " ".join(str(text or "").split())
    if not words:
        raise ValueError("Type the battery or power source.")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in words):
        raise ValueError("That text holds characters that cannot be shown.")
    if len(words) > OTHER_MAX_LENGTH:
        raise ValueError(f"Keep it to {OTHER_MAX_LENGTH} characters.")
    return words


def _clean_entry(raw: Any) -> dict[str, Any] | None:
    """A stored owner entry as it must be, or None if it is not one."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    battery_type = raw.get("type")
    if kind not in (KIND_BATTERY, *WIRED_KINDS.values()) or not isinstance(battery_type, str):
        return None
    try:
        battery_type = clean_other(battery_type)
    except ValueError:
        return None
    quantity = raw.get("quantity")
    if kind == KIND_BATTERY and battery_type in WIRED_KINDS:
        # A wired source typed under Other, as a battery, before it was a
        # choice: read as the choice (0.25.3, James's "USB Direct to
        # Server", saved as one battery).
        kind = WIRED_KINDS[battery_type]
    if kind == KIND_BATTERY:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not (
            QUANTITY_MIN <= quantity <= QUANTITY_MAX
        ):
            return None
    else:
        quantity = None
    set_at = raw.get("set") if isinstance(raw.get("set"), str) else None
    return {"kind": kind, "type": battery_type, "quantity": quantity, "set": set_at}


class PowerMixin:
    """The coordinator's side of the Power row."""

    _power_library: BatteryLibrary | None = None
    _power_entries: dict[str, dict[str, Any]] = {}
    _power_models: dict[str, dict[str, Any]] = {}

    async def async_load_power(self) -> None:
        """Read the library; a missing or damaged one never stops a start.
        The owner's entries are read with the answers file (0.25.1)."""
        hass = self.hass  # type: ignore[attr-defined]
        self._power_library = await hass.async_add_executor_job(load_library)

    def _power_reset(self) -> None:
        self._power_entries = {}
        self._power_models = {}

    def _power_read(self, payload: dict[str, Any], legacy: bool = False) -> int:
        """Take the owner's entries from a stored payload; the number left out.

        Since 0.24.8 an entry belongs to a model, so one set on one
        Third Reality button covers all four. Read from the old power
        file (legacy), 0.24.7's entries, held per device, become model
        entries; a device with no manufacturer or model keeps its entry
        to itself. The copies 0.25.0 and earlier wrote for 0.24.7,
        marked with their model, are skipped.

        Read from the answers file, a device's own entry stays its own,
        as the page showed it, even once the device reports a model: a
        restart turned it into an answer for the whole model, or dropped
        it when the model had one (0.25.1, found by testing).
        """
        dropped = 0
        models = payload.get("models")
        for key, raw in (models.items() if isinstance(models, dict) else ()):
            entry = _clean_entry(raw)
            setter = raw.get("device_id") if isinstance(raw, dict) else None
            if is_model_key(key) and entry is not None and isinstance(setter, str):
                self._power_models[key] = {**entry, "device_id": setter}
            else:
                dropped += 1
        devices = payload.get("devices")
        for device_id, raw in (devices.items() if isinstance(devices, dict) else ()):
            if isinstance(raw, dict) and "model" in raw:
                continue  # the copy kept for 0.24.7, not an entry of its own
            entry = _clean_entry(raw)
            if not isinstance(device_id, str) or entry is None:
                dropped += 1
                continue
            key = self._power_key(device_id) if legacy else None
            if key is not None and key not in self._power_models:
                self._power_models[key] = {**entry, "device_id": device_id}
            else:
                # No model, or the model already has an answer: the entry
                # stays the device's own, never dropped (found by review).
                self._power_entries[device_id] = entry
        return dropped

    def _power_payload(self) -> dict[str, Any]:
        return {
            "models": {k: dict(v) for k, v in sorted(self._power_models.items())},
            "devices": {k: dict(v) for k, v in sorted(self._power_entries.items())},
        }

    def _power_save(self) -> None:
        self._answers_save()  # type: ignore[attr-defined]

    def _power_device_fields(self, device_id: str) -> tuple[Any, ...]:
        device = dr.async_get(self.hass).async_get(device_id)  # type: ignore[attr-defined]
        return (
            _as_text(device_field(device, "manufacturer")),
            _as_text(device_field(device, "model")),
            _as_text(device_field(device, "model_id")),
            _as_text(device_field(device, "hw_version")),
        )

    def _power_key(self, device_id: str) -> str | None:
        maker, model, model_id, _hw = self._power_device_fields(device_id)
        return model_key(maker, model, model_id)

    def _model_devices_anywhere(self, key: str, leaving: str | None = None) -> list[str]:
        """Devices of this model in Home Assistant, watched or not (0.25.1).

        A model answer is handed on from a deleted device to one of
        these, so an excluded device of the model keeps it.
        """
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        return sorted(
            device.id
            for device in self._registry_devices(registry)  # type: ignore[attr-defined]
            if device.id != leaving and self._power_key(device.id) == key
        )

    def _model_covers(self, key: str, own: dict[str, Any], device_id: str | None = None) -> int:
        """How many devices a model answer covers: those of the model with
        no answer of their own (0.25.1, found by review). device_id counts
        as covered, since setting a model answer on it replaces its own."""
        return len([d for d in self._power_same_model(key) if d not in own or d == device_id])

    def _power_same_model(self, key: str, leaving: str | None = None) -> list[str]:
        """Devices Device Sentinel knows that are this model."""
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        # Not a removed device's held record (ruling #622): an old
        # composite id could still answer to the model (found by review).
        return [
            d for d in records
            if d != leaving and not self.is_held(d) and self._power_key(d) == key  # type: ignore[attr-defined]
        ]

    def _power_entry(self, device_id: str) -> tuple[dict[str, Any] | None, str | None]:
        """The owner's entry that covers the device, and its model key."""
        entry = self._power_entries.get(device_id)
        if entry is not None:
            return entry, None
        key = self._power_key(device_id)
        if key is not None and key in self._power_models:
            return self._power_models[key], key
        return None, key

    def _power_model_words(self, device_id: str) -> str | None:
        if device_id not in self._power_entries:
            return None
        key = self._power_key(device_id)
        model = self._power_models.get(key) if key else None
        return power_words(model["type"], model["quantity"]) if model else None

    def power_library_answer(self, device_id: str) -> LibraryAnswer | None:
        if self._power_library is None:
            return None
        return self._power_library.match(*self._power_device_fields(device_id))

    def power_of(self, device_id: str, covers: bool = False) -> dict[str, Any] | None:
        """What powers the device, and where that came from, or None.

        covers counts the devices of the model, which walks every record;
        only the device page asks for it (0.25.1: every list asked, so a
        Devices tab on a big house cost the square of its size).
        """
        entry, key = self._power_entry(device_id)
        if entry is not None:
            setter = entry.get("device_id", device_id)
            return {
                "words": power_words(entry["type"], entry["quantity"]),
                "source": SOURCE_OWNER,
                "kind": entry["kind"],
                "type": entry["type"],
                "quantity": entry["quantity"],
                "set_on": setter,
                "covers": (self._model_covers(key, self._power_entries) if key else 1) if covers else None,
            }
        answer = self.power_library_answer(device_id)
        if answer is not None:
            return {
                "words": answer.words,
                "source": SOURCE_LIBRARY,
                "kind": KIND_BATTERY,
                "type": answer.battery_type,
                "quantity": answer.quantity,
            }
        return None

    def power_text(self, device_id: str) -> str | None:
        """The plain words for a list or the brief, or None if unknown."""
        known = self.power_of(device_id)
        return known["words"] if known else None

    def power_report_url(self, device_id: str) -> str | None:
        """Battery Notes' New Device form, filled in, or None.

        Offered for a battery type the owner set that the library does
        not already give, on a device with a manufacturer and a model,
        which the form requires. Mains and USB are not batteries, so
        the library has no place for them. The title is filled too,
        "[Device]: Third Reality Smart button (3RSB22BZ)" (0.24.8).
        """
        entry, _key = self._power_entry(device_id)
        if entry is None or entry["kind"] != KIND_BATTERY:
            return None
        maker, model, model_id, _hw = self._power_device_fields(device_id)
        if not maker or not model:
            return None
        answer = self.power_library_answer(device_id)
        if answer is not None and answer.battery_type == entry["type"] and (
            (answer.quantity or 1) == (entry["quantity"] or 1)
        ):
            return None
        title = f"[Device]: {maker} {model}" + (f" ({model_id})" if model_id else "")
        fields = [("template", REPORT_TEMPLATE), ("title", title), ("manufacturer", maker), ("model", model)]
        if model_id:
            fields.append(("model_id", model_id))
        fields += [("battery_type", entry["type"]), ("battery_quantity", str(entry["quantity"] or 1))]
        return f"{REPORT_FORM}?{urlencode(fields, quote_via=quote)}"

    def power_view(self, device_id: str) -> dict[str, Any]:
        """What the device page's Power row needs."""
        known = self.power_of(device_id, covers=True)
        entry, _key = self._power_entry(device_id)
        answer = self.power_library_answer(device_id)
        set_on = known.get("set_on") if known else None
        return {
            "words": known["words"] if known else NOT_KNOWN,
            "source": known["source"] if known else None,
            "entry": {f: entry[f] for f in ("kind", "type", "quantity", "set")} if entry else None,
            # Where an owner's entry was set, and how many devices it
            # covers (0.24.8): "set on Button Master Shower, covers 4".
            "set_on": set_on,
            # Named only while Home Assistant still has that device;
            # otherwise the page says "another device".
            "set_on_name": (
                self._device_name(set_on)  # type: ignore[attr-defined]
                if set_on and dr.async_get(self.hass).async_get(set_on) is not None  # type: ignore[attr-defined]
                else None
            ),
            "covers": known.get("covers") if known else None,
            # The model's answer, when this device has its own: what
            # clearing its own puts in place (found by review).
            "model_answer": self._power_model_words(device_id),
            "library": answer.words if answer else None,
            "library_home": LIBRARY_HOME,
            "report_url": self.power_report_url(device_id),
            "choices": list(POWER_CHOICES),
            "battery_choices": list(BATTERY_CHOICES),
            "mains": POWER_MAINS,
            "usb": POWER_USB,
            # The choices that take no quantity and no report (0.24.8).
            "wired": list(POWER_WIRED),
            "other": POWER_OTHER,
            "quantity": [QUANTITY_MIN, QUANTITY_MAX],
        }

    def power_diagnostics(self, device_id: str) -> dict[str, Any] | None:
        known = self.power_of(device_id)
        if known is None:
            return None
        entry, key = self._power_entry(device_id)
        return {"words": known["words"], "source": known["source"], "entry": entry, "model": key}

    def page_set_power(
        self,
        device_id: str,
        choice: str | None,
        quantity: int | None = None,
        other: str | None = None,
    ) -> None:
        """Set the owner's answer from the device page; None clears it.

        Since 0.24.8 the answer covers every device of the same model,
        and clearing it clears it for all of them.
        """
        self._device(device_id)  # type: ignore[attr-defined]
        entry: dict[str, Any]
        key = self._power_key(device_id)
        covers = self._model_covers(key, self._power_entries, device_id) if key else 1
        many = f", for all {covers} devices of this model" if covers > 1 else ""
        if not choice:
            # A device's own answer, from before it reported a model, is
            # cleared alone; the model's answer, set on another device,
            # stays for the rest (0.25.1, found by review).
            had_own = self._power_entries.pop(device_id, None) is not None
            had_model = not had_own and key is not None and self._power_models.pop(key, None) is not None
            if not (had_own or had_model):
                return
            if had_own:
                many = ""
            self._power_save()
            now = self.power_of(device_id)
            if now is not None and now["source"] == SOURCE_OWNER:
                used = f", the model's {now['words']} used"
            elif now is not None:
                used = f", the library's {now['words']} used"
            else:
                used = ""
            self._page_done(device_id, f"power entry removed{used}{many}")  # type: ignore[attr-defined]
            return
        if choice in WIRED_KINDS:
            entry = {"kind": WIRED_KINDS[choice], "type": choice, "quantity": None}
        else:
            if choice in BATTERY_CHOICES:
                battery_type = choice
            elif choice == POWER_OTHER:
                battery_type = clean_other(other)
            else:
                raise ValueError("Choose from the list.")
            if quantity is None:
                quantity = 1
            if isinstance(quantity, bool) or not isinstance(quantity, int) or not (
                QUANTITY_MIN <= quantity <= QUANTITY_MAX
            ):
                raise ValueError(f"The quantity is {QUANTITY_MIN} to {QUANTITY_MAX}.")
            entry = {"kind": KIND_BATTERY, "type": battery_type, "quantity": quantity}
        entry["set"] = dt_util.utcnow().isoformat()
        if key is not None:
            self._power_models[key] = {**entry, "device_id": device_id}
            self._power_entries.pop(device_id, None)
        else:
            self._power_entries[device_id] = entry
        self._power_save()
        self._page_done(  # type: ignore[attr-defined]
            device_id, f"power set to {power_words(entry['type'], entry['quantity'])}{many}"
        )

    @callback
    def _power_forget(self, device_id: str | None, hold: bool = False) -> None:
        """A device gone from Home Assistant takes its own entry with it.

        A model entry it set passes to another device of the model, a
        watched one first, then any in Home Assistant (0.25.1), or goes
        with the last of them.

        hold: the device's record is held after its removal (ruling
        #622), so its own answer stays and a model answer with no other
        device to pass to stays with it until the purge.
        """
        if not device_id:
            return
        changed = not hold and self._power_entries.pop(device_id, None) is not None
        for key, entry in list(self._power_models.items()):
            if entry.get("device_id") != device_id:
                continue
            others = self._power_same_model(key, leaving=device_id) or self._model_devices_anywhere(
                key, leaving=device_id
            )
            if others:
                entry["device_id"] = others[0]
            elif hold:
                continue
            else:
                del self._power_models[key]
            changed = True
        if changed:
            self._power_save()
