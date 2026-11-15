# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/firmware_updates.py, Version: 0.29.2 (2026-11-15)

"""Devices behind on firmware, one Recommendations row a model (rule REC-12).

Which devices are behind, in this order:

1. A device with a firmware update entity of its own, switched on: the
   entity decides. It is behind only while Home Assistant offers it an
   update. A device whose model stands for none (rule DEV-06), such as
   an ESPHome board, has a row of its own, named for the device.
2. A device with no update entity switched on that gives a hardware
   version: it is compared with the devices of its maker, model and
   hardware version, counting only versions written with dots. It is
   behind when it is below the newest version in that group. An update entity switched off counts as none: an integration
   that ships it off does not push its updates, and Device Sentinel does
   not ask for it to be turned on. A single number, such as a build
   number or a date, is read as text and never compared.
3. Neither: never behind. One model name can hold different hardware,
   each on its own current firmware, so a mix of versions alone says
   nothing. A device with no model is never compared.

Watched devices only, muted ones included, as the model groups count
them (rule DEV-14).
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.helpers import device_registry as dr

from .const import Z2M_IDENTIFIER_MARK
from .device_fields import device_field
from .power_source import model_key, stands_for_none

# A version number: digits and dots, with an optional leading "v".
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$", re.IGNORECASE)
# A first-generation Shelly's firmware, as Home Assistant shows it: the
# build's date and time, then its version, such as
# "20230913-111730/v1.14.0-gcb84623", or on older firmware
# "20200827-070450/v1.8.3@4a8bc427".
_SHELLY_GEN1 = re.compile(r"^\d{8}-\d{6}/v(\d+(?:\.\d+)+)(?:[-@][0-9A-Za-z_.]+)?$")
# Names in a type that keep their capitals in the plural.
_PROPER = frozenset({"Zigbee", "Z-Wave", "Thread", "Matter", "Bluetooth", "ESPHome", "IR", "NAS", "UPS"})


def version_number(value: Any) -> tuple[int, ...] | None:
    """A version as numbers to compare, or None when it is not one."""
    if not isinstance(value, str):
        return None
    match = _VERSION.match(value.strip())
    if match is None:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    # Trailing zeros say nothing: a version written with them is the same version.
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def comparable_version(value: Any) -> tuple[int, ...] | None:
    """A version written with dots, as numbers to compare; None for a
    single number, a build number or a date, which is read as text. A
    first-generation Shelly's firmware is read by its version."""
    if not isinstance(value, str):
        return None
    shelly = _SHELLY_GEN1.match(value.strip())
    if shelly is not None:
        return version_number(shelly.group(1))
    if "." not in value:
        return None
    return version_number(value)


def plural_type(words: str | None) -> str:
    """A device type as a plural noun for a sentence, or "devices"."""
    if not words or not words.strip():
        return "devices"
    parts = words.strip().split(" ")

    def common(word: str) -> str:
        # A capitalised common word is lowered; a name keeps its capitals.
        if word in _PROPER or not word[:1].isupper() or (word[1:] and not word[1:].islower()):
            return word
        return word.lower()

    shown = ["/".join(common(piece) for piece in part.split("/")) for part in parts]
    last = shown[-1]
    # A name in brackets, or letters standing for words (UPS, NAS),
    # has no plural to trust.
    if "(" in last or ")" in last or (len(last) > 1 and last.isupper()):
        return "devices"
    if last.lower().endswith(("s", "x", "ch", "sh")):
        last += "es"
    elif last.lower().endswith("y") and last[-2:-1].lower() not in "aeiou":
        last = last[:-1] + "ies"
    else:
        last += "s"
    shown[-1] = last
    return " ".join(shown)


def _is(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _is_z2m(device: Any) -> bool:
    for identifier in getattr(device, "identifiers", None) or ():
        if (
            isinstance(identifier, tuple) and len(identifier) == 2
            and identifier[0] == "mqtt" and str(identifier[1]).startswith(Z2M_IDENTIFIER_MARK)
        ):
            return True
    return False


class FirmwareUpdatesMixin:
    """The coordinator's firmware card (rule REC-12)."""

    def _firmware_entity(self, device_id: str) -> tuple[bool, Any]:
        """Whether the device has a firmware update entity of its own
        switched on, and the state to read: the first one offering an
        update, as a device may have several (a coordinator's own
        firmware and its radio's), or else the first one switched on.
        One switched off counts as none."""
        found = False
        first = None
        for ent in self._own_entities_of(device_id, "firmware"):  # type: ignore[attr-defined]
            if ent.disabled_by is not None:
                continue
            state = self.hass.states.get(ent.entity_id)  # type: ignore[attr-defined]
            if state is not None and state.state == "on":
                return True, state
            if not found:
                found, first = True, state
        return found, first

    def firmware_rows(self) -> list[dict[str, Any]]:
        """One row a model with devices behind on firmware, in name order."""
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        models: dict[str, list[dict[str, Any]]] = {}
        for device_id in self._watched:  # type: ignore[attr-defined]
            device = registry.async_get(device_id)
            if device is None:
                continue
            maker = device_field(device, "manufacturer")
            model = device_field(device, "model")
            key = (
                None if not maker or not model or stands_for_none(maker, model)
                else model_key(maker, model, device_field(device, "model_id"))
            )
            has_entity, state = self._firmware_entity(device_id)
            if key is None:
                # No model: only its own update entity can say it is
                # behind, and it is a row of its own.
                if not has_entity:
                    continue
                key = f"device:{device_id}"
            installed = device_field(device, "sw_version")
            latest = None
            offered = False
            if state is not None:
                attributes = state.attributes or {}
                if isinstance(attributes.get("installed_version"), str):
                    installed = attributes["installed_version"]
                if isinstance(attributes.get("latest_version"), str):
                    latest = attributes["latest_version"]
                offered = state.state == "on"
            models.setdefault(key, []).append({
                "device_id": device_id,
                "name": self._device_name(device_id),  # type: ignore[attr-defined]
                "maker": str(maker or ""),
                "model": str(model or ""),
                "alone": key.startswith("device:"),
                "hw": device_field(device, "hw_version"),
                "installed": installed if isinstance(installed, str) and installed.strip() else None,
                "latest": latest,
                "has_entity": has_entity,
                "offered": offered,
                "z2m": _is_z2m(device),
            })
        rows = []
        for key, devices in models.items():
            row = self._firmware_row(key, devices)
            if row is not None:
                rows.append(row)
        rows.sort(key=lambda row: (str(row["name"]).casefold(), row["model_key"]))
        return rows

    def _firmware_row(self, key: str, devices: list[dict[str, Any]]) -> dict[str, Any] | None:
        behind: list[dict[str, Any]] = []
        newest: list[str] = []
        # 1. The update entity decides.
        for item in devices:
            if item["has_entity"] and item["offered"]:
                behind.append(item)
                if item["latest"]:
                    newest.append(item["latest"])
        # 2. No update entity, a hardware version given: the newest of the
        # same maker, model and hardware version.
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in devices:
            hw = item["hw"]
            if item["alone"] or not isinstance(hw, str) or not hw.strip():
                continue
            if comparable_version(item["installed"]) is None:
                continue
            groups.setdefault(hw.strip(), []).append(item)
        for members in groups.values():
            # A device whose update entity decides still shows the
            # version its group can reach; only the others are judged here.
            top = max(members, key=lambda m: comparable_version(m["installed"]) or ())
            top_number = comparable_version(top["installed"])
            late = [
                m for m in members
                if not m["has_entity"] and comparable_version(m["installed"]) != top_number
            ]
            if late:
                behind.extend(late)
                newest.append(top["installed"])
        if not behind:
            return None
        def number(value: Any) -> tuple[int, ...] | None:
            return comparable_version(value) or version_number(value)

        new = max(newest, key=lambda v: number(v) or ()) if newest else None
        new_number = number(new)
        on_new = len([
            item for item in devices
            if new_number is not None and number(item["installed"]) == new_number
        ])
        not_reported = len([item for item in devices if item["installed"] is None])
        olds = sorted(
            {item["installed"] for item in behind if item["installed"]},
            key=lambda v: number(v) or (), reverse=True,
        )
        behind.sort(key=lambda item: (str(item["name"]).casefold(), item["device_id"]))
        first = behind[0]
        if first["alone"]:
            return self._firmware_alone(key, first)
        model = f"{first['maker']} {first['model']}"
        kinds = {self.type_words(item["device_id"]) for item in devices}  # type: ignore[attr-defined]
        noun = plural_type(next(iter(kinds)) if len(kinds) == 1 else None)
        count = len(behind)
        text = f"{count} of your {model} {noun} {_is(count, 'requires', 'require')} a firmware update."
        if new:
            if on_new:
                text += f" {on_new} {_is(on_new, 'is', 'are')} on the new firmware: {new}."
            else:
                text += f" The new firmware is {new}."
        if olds:
            text += (
                f" {count} {_is(count, 'is', 'are')} on an old firmware: {olds[0]}."
                if len(olds) == 1
                else f" {count} {_is(count, 'is', 'are')} on old firmware: {', '.join(olds)}."
            )
        if not_reported:
            text += f" {not_reported} {_is(not_reported, 'is', 'are')} not reported."
        return {
            "model_key": key,
            "device_id": first["device_id"],
            "name": model,
            "text": text,
            "zigbee2mqtt": any(item["z2m"] for item in behind),
            "behind": [
                {"device_id": item["device_id"], "name": item["name"], "installed": item["installed"]}
                for item in behind
            ],
        }

    def _firmware_alone(self, key: str, item: dict[str, Any]) -> dict[str, Any]:
        """A device with no model that its update entity says is behind:
        a row of its own, named for the device."""
        text = f"{item['name']} requires a firmware update."
        if item["installed"]:
            text += f" It is on {item['installed']}."
        if item["latest"]:
            text += f" The new firmware is {item['latest']}."
        return {
            "model_key": key,
            "device_id": item["device_id"],
            "name": item["name"],
            "text": text,
            "zigbee2mqtt": item["z2m"],
            "behind": [{"device_id": item["device_id"], "name": item["name"], "installed": item["installed"]}],
        }
