# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: diagnostics_names.py, Version: 0.29.5 (2026-11-17)

"""The house's names taken out of the diagnostics download (rule STOR-21).

A download is often attached to a public issue. Every device, area and
label is named by its stand-in from the book (stand_ins.py), and the
name part of each entity id by its device's: binary_sensor.terrace_door
_contact reads binary_sensor.device_37_contact. A name is replaced where
it stands alone and where a sentence says it, as the Problem List and
the house events do. A row that names its device is given that device's
stand-in whatever name it recorded, so a device renamed since is hidden
under its old name too.

What a device is stays: its maker, model, model id, hardware and
firmware, its integration, and what powers it. So do every number and
date. Two devices in one area read the same "Area 3", and a device whose
name another shares says which.
"""

from __future__ import annotations

import re
from typing import Any, cast

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import slugify

from .const import SYS_DEVICE_PAGE
from .device_actions import MUTE_SOURCES_SAID
from .naming import composed_name, fitted_name, integration_label
from .stand_ins import StandInBook

# Keys whose value names the device of its row, or a device.
NAME_KEYS = frozenset({"name", "sort_name", "removed_name"})
AREA_KEYS = frozenset({"area"})
# What a device is, and Device Sentinel's own words: never changed, so a
# device named after its model leaves the model readable.
KEEP_KEYS = frozenset({
    "manufacturer", "model", "model_id", "model_name", "maker", "sw_version",
    "hw_version", "firmware", "hardware", "integration", "platform", "domain",
    "device_class", "unit", "category", "power", "type", "connects", "kind",
    "version", "last_version", "tunables",
})
# Entity domains whose ids are hidden. A router's trackers are hidden as
# trackers, by the address pass that runs first.
_DOMAINS = sorted(
    ({p.value for p in Platform} | {
        "person", "zone", "automation", "script", "input_boolean", "input_number",
        "input_select", "input_text", "input_datetime", "input_button", "counter",
        "timer", "group", "schedule",
    }) - {"device_tracker"},
    key=len,
    reverse=True,
)
_ENTITY = re.compile(
    r"(?<![\w.])(" + "|".join(map(re.escape, _DOMAINS)) + r")\.([a-z0-9_]+)(?![a-z0-9_])"
)
_ID = re.compile(r"[0-9a-f]{32}|[0-9A-Z]{26}")
# What a device page records, its name, area or label in the words: a
# name since changed, or an area since deleted, is known nowhere else.
_PAGE_ACTS = (
    (re.compile(r"^(renamed |name reset to )(.+)$", re.DOTALL), "device"),
    (re.compile(r"^(moved to )(.+?)((?:, a new area)?)$", re.DOTALL), "area"),
    (re.compile(r"^(set to its parent's area, )(.+)$", re.DOTALL), "area"),
    (re.compile(r"^(label )(.+?)( added(?:, a new label)?| removed)$", re.DOTALL), "label"),
    # As an earlier release worded a mute set by a label.
    (re.compile(r"^(\w+ (?:un)?muted by label )(.+?)((?:, on \d+ devices?)?)$", re.DOTALL), "label"),
)


def _trie_pattern(words: list[str]) -> str:
    """One pattern for many names, branching on each character, so a long
    list costs little more to search than a short one."""
    trie: dict[str, Any] = {}
    for word in words:
        node = trie
        for ch in word:
            node = node.setdefault(ch, {})
        node[""] = True

    def build(node: dict[str, Any]) -> str:
        ends = "" in node
        branches = [re.escape(ch) + build(child) for ch, child in sorted(node.items()) if ch]
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        # Longest first: a branch that goes on is tried before stopping here.
        return f"(?:{body})?" if ends else body

    return build(trie)


def _said_in_sentences(name: str) -> bool:
    """A name is looked for inside sentences only when it is long enough
    and holds a letter, so a device named "100" is never found in
    "battery 100%". Such a name is still hidden where it stands alone."""
    return len(name) >= 3 and any(ch.isalpha() for ch in name)


class NameHider:
    """Builds the names to hide from the registries, then walks the payload."""

    def __init__(self, hass: HomeAssistant, book: StandInBook, all_devices: list[Any]) -> None:
        self.book = book
        self.devices = dr.async_get(hass)
        self.entities = er.async_get(hass)
        self.areas = ar.async_get(hass)
        self.labels = lr.async_get(hass)
        # Text to what it names: (kind, key, name for the key).
        self.names: dict[str, list[tuple[str, str, str]]] = {}
        self.entity_words: dict[str, str] = {}
        self._slugs: set[str] = set()
        for device in all_devices:
            shown = composed_name(cast(Any, device), self.devices) or device.name_by_user or device.name
            for text in (device.name_by_user, device.name, shown):
                self._add(text, "device", device.id, shown)
        for area in self.areas.async_list_areas():
            self._add(area.name, "area", area.id, area.name)
        for label in self.labels.async_list_labels():
            self._add(label.name, "label", label.label_id, label.name)
        self._pattern: re.Pattern[str] | None = None
        self._leak: re.Pattern[str] | None = None
        # An integration's own name, as Device Sentinel's sentences say
        # it ("Tado stopped updating"), is never taken for a device of
        # that name inside a sentence.
        self._integrations = {
            integration_label(entry.domain).casefold()
            for entry in hass.config_entries.async_entries()
        }
        self._eligible: set[str] | None = None

    def _add(self, text: Any, kind: str, key: str, shown: Any) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        # A name past the length a page or sentence shows is said cut,
        # "Hallway motion sensor by the…": the cut form is hidden too.
        for said in {text.strip(), fitted_name(text.strip())}:
            targets = self.names.setdefault(said, [])
            if not any(t[0] == kind and t[1] == key for t in targets):
                targets.append((kind, key, shown if isinstance(shown, str) else text))
        slug = slugify(text)
        if len(slug) >= 3 and any(ch.isalpha() for ch in slug):
            self._slugs.add(slug)
        self._pattern = None
        self._eligible = None

    # ----------------------------------------------------------- words

    def device_word(self, device_id: str, name: Any = None) -> str:
        """A device's stand-in. The key keeps the name Home Assistant gives
        it now; a device no longer there keeps the first name it was kept
        under, never a row's older one."""
        device = self.devices.async_get(device_id)
        if device is not None:
            current = composed_name(cast(Any, device), self.devices)
            return self.book.word("device", device_id, current)
        if device_id in self.book.names["device"]:
            name = None
        return self.book.word("device", device_id, name if isinstance(name, str) and name else None)

    def _target_word(self, target: tuple[str, str, str]) -> str:
        kind, key, shown = target
        if kind == "device":
            return self.device_word(key, shown)
        return self.book.word(kind, key, shown)

    def _word_for(self, text: str, own: str | None, said: bool = False) -> str | None:
        targets = self.names.get(text.strip())
        if said and targets:
            targets = [target for target in targets if target[0] != "label"]
        if not targets:
            return None
        # A name two devices share: the row's own device where it is one.
        if own is not None:
            for target in targets:
                if target[0] == "device" and self.device_word(target[1], target[2]) == own:
                    return own
        return self._target_word(targets[0])

    def entity_word(self, entity_id: str) -> str:
        """An entity id with its name part hidden."""
        if entity_id in self.entity_words:
            return self.entity_words[entity_id]
        domain, _, object_id = entity_id.partition(".")
        shown: str | None = None
        entry = self.entities.async_get(entity_id)
        device = self.devices.async_get(entry.device_id) if entry and entry.device_id else None
        if device is not None:
            n = self.device_word(device.id).rsplit(" ", 1)[1]
            prefixes = {
                slugify(text)
                for text in (device.name_by_user, device.name, composed_name(cast(Any, device), self.devices))
                if isinstance(text, str) and text.strip()
            }
            for prefix in sorted(prefixes, key=len, reverse=True):
                if object_id == prefix:
                    shown = f"{domain}.device_{n}"
                elif prefix and object_id.startswith(prefix + "_"):
                    rest = object_id[len(prefix) + 1:]
                    if not self._leaks(rest):
                        shown = f"{domain}.device_{n}_{rest}"
                if shown:
                    break
        if shown is None:
            shown = f"{domain}.entity_{self.book.number('entity', entity_id)}"
        self.entity_words[entity_id] = shown
        return shown

    def _leaks(self, rest: str) -> bool:
        """Whether what follows the device's name in an entity id says a
        name of the house: an area, a label, another device."""
        if self._leak is None:
            slugs = sorted(self._slugs, key=len, reverse=True)
            self._leak = re.compile(
                r"(?:^|_)(?:" + _trie_pattern(slugs) + r")(?:_|$)" if slugs else r"(?!x)x"
            )
        return bool(self._leak.search(rest))

    # ------------------------------------------------------------ text

    def _sentence_names(self) -> set[str]:
        """The names looked for in a sentence or a whole value: a device's
        or an area's. A label is said only where a device page records
        it, and in the lists of labels; "Battery" as a label is never
        taken from "Battery 10% since ..."."""
        if self._eligible is None:
            self._eligible = {
                name for name, targets in self.names.items()
                if _said_in_sentences(name)
                and name.casefold() not in self._integrations
                and any(target[0] != "label" for target in targets)
            }
        return self._eligible

    def _sentence_pattern(self) -> re.Pattern[str]:
        if self._pattern is None:
            said = self._sentence_names()
            body = _trie_pattern(sorted(said)) if said else r"(?!x)x"
            self._pattern = re.compile(rf"(?<!\w)(?:{body})(?!\w)")
        return self._pattern

    def text(self, value: str, own: str | None = None) -> str:
        if not value or _ID.fullmatch(value):
            return value
        value = _ENTITY.sub(lambda m: self.entity_word(m.group(0)), value)
        whole = self._word_for(value, own, said=True) if value.strip() in self._sentence_names() else None
        if whole is not None:
            return whole
        return self._sentence_pattern().sub(
            lambda m: self._word_for(m.group(0), own, said=True) or m.group(0), value
        )

    # --------------------------------------------------------- the walk

    def collect(self, value: Any) -> None:
        """First pass: each row's name for its device, old names included."""
        if isinstance(value, dict):
            device_id = value.get("device_id")
            if isinstance(device_id, str) and device_id:
                for key in NAME_KEYS:
                    name = value.get(key)
                    if isinstance(name, str) and name.strip():
                        self._add(name, "device", device_id, None)
            for key, inner in value.items():
                if key not in KEEP_KEYS:
                    self.collect(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                self.collect(inner)

    def walk(self, value: Any, own: str | None = None, key: Any = None) -> Any:
        if isinstance(value, str):
            return self.text(value, own)
        if isinstance(value, (list, tuple, set)):
            if isinstance(key, str) and key.endswith("_labels"):
                return [
                    self.book.word("label", item, self._label_name(item)) if isinstance(item, str) else item
                    for item in value
                ]
            return [self.walk(inner, own) for inner in value]
        if not isinstance(value, dict):
            return value
        device_id = value.get("device_id")
        if isinstance(device_id, str) and device_id:
            own = self.device_word(device_id, next(
                (value[k] for k in ("name", "removed_name", "sort_name") if isinstance(value.get(k), str)),
                None,
            ))
        out: dict[Any, Any] = {}
        for k, v in value.items():
            new_key = self.text(k, own) if isinstance(k, str) else k
            if k == "detail" and value.get("kind") == SYS_DEVICE_PAGE and isinstance(v, str):
                out[new_key] = self._page_detail(v, own)
            elif k in KEEP_KEYS:
                out[new_key] = v
            elif k in NAME_KEYS and isinstance(v, str) and v.strip():
                out[new_key] = own if own is not None else (self._word_for(v, None) or self.text(v))
            elif k in AREA_KEYS and isinstance(v, str) and v.strip():
                out[new_key] = self._area_word(v)
            else:
                out[new_key] = self.walk(v, own, k)
        return out

    def _page_detail(self, detail: str, own: str | None) -> str:
        """A device page's act with its name, area or label as a stand-in,
        known or long gone."""
        where = ""
        for said in MUTE_SOURCES_SAID.values():
            if detail.endswith(f", {said}"):
                detail, where = detail[: -len(said) - 2], f", {said}"
                break
        for pattern, kind in _PAGE_ACTS:
            found = pattern.match(detail)
            if not found:
                continue
            name = found.group(2).strip()
            tail = found.group(3) if found.lastindex and found.lastindex >= 3 else ""
            if kind == "device":
                word = own or self._word_for(name, None) or self.book.word("device", f"name:{name}", name)
            elif kind == "area":
                word = self._area_word(name)
            else:
                label = next((x for x in self.labels.async_list_labels() if x.name == name), None)
                word = self.book.word("label", label.label_id if label else f"name:{name}", name)
            return f"{found.group(1)}{word}{tail}{where}"
        return self.text(detail, own) + where

    def _label_name(self, label_id: str) -> str | None:
        label = self.labels.async_get_label(label_id)
        return label.name if label else None

    def _area_word(self, text: str) -> str:
        area = self.areas.async_get_area(text) or self.areas.async_get_area_by_name(text)
        if area is not None:
            return self.book.word("area", area.id, area.name)
        return self.book.word("area", f"name:{text}", text)


def hide_names(
    hass: HomeAssistant, payload: Any, book: StandInBook, all_devices: list[Any]
) -> tuple[Any, dict[str, str]]:
    """The payload with the house's names replaced; the entity ids hidden.
    `all_devices` is every device in the registry, each once."""
    hider = NameHider(hass, book, all_devices)
    hider.collect(payload)
    # The devices the download is about take their numbers first, in order.
    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(devices, dict):
        return hider.walk(payload), dict(hider.entity_words)
    words = {}
    for device_id, row in devices.items():
        name = row.get("name") if isinstance(row, dict) else None
        words[device_id] = hider.device_word(device_id, name)
    hidden = hider.walk({k: v for k, v in payload.items() if k != "devices"})
    # Each device's row is its own, whatever name it shares.
    hidden["devices"] = {
        device_id: hider.walk(row, words[device_id]) for device_id, row in devices.items()
    }
    # Devices of one name each say which others share it, since the
    # stand-ins no longer show it.
    by_name: dict[str, list[str]] = {}
    for device_id, row in devices.items():
        name = row.get("name") if isinstance(row, dict) else None
        if isinstance(name, str) and name.strip():
            by_name.setdefault(name.strip().casefold(), []).append(device_id)
    for device_id, row in hidden["devices"].items():
        if not isinstance(row, dict):
            continue
        name = devices[device_id].get("name") if isinstance(devices[device_id], dict) else None
        group = by_name.get(name.strip().casefold(), []) if isinstance(name, str) and name.strip() else []
        row["shares_name_with"] = sorted(
            (words[other] for other in group if other != device_id),
            key=lambda word: int(word.rsplit(" ", 1)[1]),
        )
    return hidden, dict(hider.entity_words)
