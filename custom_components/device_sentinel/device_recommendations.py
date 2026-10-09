# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_recommendations.py, Version: 0.25.3 (2026-10-09)

"""Recommendations about single devices, for the Recommendations tab (0.24.9).

Six kinds, each one card listing the devices it covers, worst first:
a device with no power set, one whose Last Seen sensor is switched
off, one with no area, devices sharing a name, and last two about
types (0.25.3): a device with no type, and a model whose devices have
more than one. Watched devices
only. Nothing is stored or dismissed: a device leaves its card when
its condition is gone, as the other recommendations do.

The tab lists every device, and each can be put right from the list.
The emailed brief, and its file, carries one line for each kind, with
its count, pointing to the tab; the dashboard's Daily Brief tab does
not (James, 6 October 2026). The two type cards stay out of the brief:
a missing or mixed type is not a fault (James, 9 October 2026).
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

KIND_POWER = "power"
KIND_AREA = "area"
KIND_LAST_SEEN = "last_seen"
KIND_NAMES = "names"
KIND_TYPE = "type"
KIND_MIXED_TYPES = "mixed_types"


def _count(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


class DeviceRecommendationsMixin:
    """The coordinator's device recommendations."""

    def device_recommendations(self) -> list[dict[str, Any]]:
        """Each kind that applies, with its devices in name order."""
        hass = self.hass  # type: ignore[attr-defined]
        devices = dr.async_get(hass)
        areas = ar.async_get(hass)
        watched = [d for d in self._watched if devices.async_get(d) is not None]  # type: ignore[attr-defined]

        def area_of(device_id: str) -> str | None:
            entry = devices.async_get(device_id)
            area = areas.async_get_area(entry.area_id) if entry and entry.area_id else None
            return area.name if area else None

        def rows(ids: list[str]) -> list[dict[str, Any]]:
            listed = [
                {"device_id": d, "name": self._device_name(d), "area": area_of(d)}  # type: ignore[attr-defined]
                for d in ids
            ]
            return sorted(listed, key=lambda row: (str(row["name"]).casefold(), row["device_id"]))

        cards: list[dict[str, Any]] = []
        power = [d for d in watched if self.power_of(d) is None]  # type: ignore[attr-defined]
        if power:
            cards.append({
                "kind": KIND_POWER,
                "title": "Power Not Set",
                "body": (
                    f"{_count(len(power), 'device has', 'devices have')} no battery or power "
                    "source set. Set each one here, and a low battery warning names "
                    "the battery to buy."
                ),
                "devices": rows(power),
                "brief": (
                    f"{_count(len(power), 'device has', 'devices have')} no battery or power "
                    "source set. Set them from the Recommendations tab, and a low battery "
                    "warning names the battery to buy."
                ),
            })
        last_seen = [d for d in watched if self._switched_off_last_seen(d)]  # type: ignore[attr-defined]
        if last_seen:
            cards.append({
                "kind": KIND_LAST_SEEN,
                "title": "Last Seen Sensor Switched Off",
                "body": (
                    f"{_count(len(last_seen), 'device has', 'devices have')} a Last Seen "
                    "sensor that is switched off. With it on, Device Sentinel notices "
                    "the device going quiet sooner. Turn each one on here."
                ),
                "devices": rows(last_seen),
                "brief": (
                    f"{_count(len(last_seen), 'device has', 'devices have')} a Last Seen "
                    "sensor that is switched off. With it on, Device Sentinel notices a "
                    "device going quiet sooner. Turn them on from the Recommendations tab."
                ),
            })
        no_area = [d for d in watched if area_of(d) is None]
        if no_area:
            cards.append({
                "kind": KIND_AREA,
                "title": "No Area Assigned",
                "body": (
                    f"{_count(len(no_area), 'device has', 'devices have')} no area. The "
                    "Daily Brief and the Problem List name each device with its room, "
                    "so these appear without one. Open a device to assign its area."
                ),
                "devices": rows(no_area),
                "brief": (
                    f"{_count(len(no_area), 'device has', 'devices have')} no area, so the "
                    "Daily Brief and the Problem List show them without a room. Assign "
                    "them from the Recommendations tab."
                ),
            })
        by_name: dict[str, list[str]] = {}
        for device_id in watched:
            name = str(self._device_name(device_id) or "").strip().casefold()  # type: ignore[attr-defined]
            if name:
                by_name.setdefault(name, []).append(device_id)
        shared = [d for ids in by_name.values() if len(ids) > 1 for d in ids]
        if shared:
            cards.append({
                "kind": KIND_NAMES,
                "title": "Devices Sharing A Name",
                "body": (
                    f"{_count(len(shared), 'device shares', 'devices share')} a name with "
                    "another. In the Daily Brief and in notifications they cannot be told "
                    "apart. Open a device to rename it."
                ),
                "devices": rows(shared),
                "brief": (
                    f"{_count(len(shared), 'device shares', 'devices share')} a name with "
                    "another, so they cannot be told apart in this brief or in "
                    "notifications. Rename them from the Recommendations tab."
                ),
            })
        # Last: a missing or mixed type changes no judgment (0.25.3).
        kinds = {d: self.type_words(d) for d in watched}  # type: ignore[attr-defined]
        untyped = [d for d in watched if not kinds[d]]
        if untyped:
            cards.append({
                "kind": KIND_TYPE,
                "title": "Type Not Set",
                "body": (
                    f"{_count(len(untyped), 'device has', 'devices have')} no type. Set each "
                    "one here, and it joins the others of its kind on the Devices, Battery "
                    "Trends and Classification tabs."
                ),
                "devices": rows(untyped),
            })
        # Models whose devices disagree (0.25.3): a device given its own
        # type apart from the rest of its model, by an owner or by its
        # entities. Devices with no type are the card above's.
        by_model: dict[str, list[str]] = {}
        for device_id in watched:
            key = self._power_key(device_id)  # type: ignore[attr-defined]
            if key is not None and kinds[device_id]:
                by_model.setdefault(key, []).append(device_id)
        mixed = [ids for ids in by_model.values() if len({kinds[d] for d in ids}) > 1]
        if mixed:
            listed_mixed = []
            for ids in mixed:
                for row in rows(ids):
                    maker, model, _model_id, _hw = self._power_device_fields(row["device_id"])  # type: ignore[attr-defined]
                    row["model"] = " ".join(part for part in (maker, model) if part)
                    row["type"] = kinds[row["device_id"]]
                    listed_mixed.append(row)
            cards.append({
                "kind": KIND_MIXED_TYPES,
                "title": "Model With More Than One Type",
                "body": (
                    f"{_count(len(mixed), 'model has', 'models have')} devices of more than one "
                    "type. Open the device that is different and set it to match, or give the "
                    "model the type you want."
                ),
                "devices": listed_mixed,
            })
        return cards
