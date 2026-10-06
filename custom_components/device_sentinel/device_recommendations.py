# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_recommendations.py, Version: 0.24.9 (2026-10-06)

"""Recommendations about single devices, for the Recommendations tab (0.24.9).

Four kinds, each one card listing the devices it covers, worst first:
a device with no power set, one with no area, one whose Last Seen
sensor is switched off, and devices sharing a name. Watched devices
only. Nothing is stored or dismissed: a device leaves its card when
its condition is gone, as the other recommendations do.

The tab lists every device, and each can be put right from the list.
The emailed brief, and its file, carries one line for each kind, with
its count, pointing to the tab; the dashboard's Daily Brief tab does
not (James, 6 October 2026).
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

KIND_POWER = "power"
KIND_AREA = "area"
KIND_LAST_SEEN = "last_seen"
KIND_NAMES = "names"


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
        return cards
