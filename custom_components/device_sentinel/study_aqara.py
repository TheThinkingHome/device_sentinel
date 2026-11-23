# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/study_aqara.py, Version: 0.30.3 (2026-11-23)

"""What an Aqara hub house shows, recorded for Extended Diagnostics.

An Aqara hub (M3, M2, M1S, E1 and others) can share its own Zigbee
devices with Home Assistant as a Matter bridge, or through HomeKit
Device. Its devices then reach Home Assistant from the hub, not from
the radio, and on a tester's house 18 of them reported together on the
hub's timer. Whether Home Assistant ever marks one of them unavailable
when its battery dies behind the hub is not known, and it decides
whether Device Sentinel can see a dead leak sensor at all
(rule STACK-11). Recorded:

- at each change, one line per Aqara device's entity that turns
  unavailable or comes back, and the same for the hub's own entities;
- at each minute, one line when three or more Aqara devices reported
  inside the same two seconds: how many, and from which integration;
- once a day, one line per Aqara device: how long since any of its
  entities last reported, and the hub it sits behind, if any.

Read from Home Assistant's registries and states alone; no hub and no
device is asked anything. It detects nothing and changes no verdict.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    AQARA_KEY,
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NODE,
    PROBE_NOW,
    PROBE_SENTINEL,
    PROBE_STACK,
    PROBE_WAS,
    PROBE_WHEN,
)

# The integrations an Aqara hub reaches Home Assistant through.
AQARA_INTEGRATIONS = ("matter", "homekit_controller")
# Devices that report inside this many seconds of each other reported
# together, the storm detector's window (rule UP-17).
TOGETHER_SECONDS = 2.0
TOGETHER_MIN = 3
NODE_ENTITY = "entity"
NODE_TOGETHER = "together"
NODE_DAY = "day"


def is_aqara(device: Any) -> bool:
    """Whether a registry device is made by Aqara (or Lumi, its maker's
    name on older devices)."""
    maker = str(getattr(device, "manufacturer", None) or "").lower()
    return "aqara" in maker or "lumi" in maker


def aqara_present(hass: Any) -> bool:
    """Whether the house has an Aqara device reaching Home Assistant
    through Matter or HomeKit Device, so the study is offered."""
    registry = dr.async_get(hass)
    return any(
        is_aqara(device)
        for entry in hass.config_entries.async_entries()
        if entry.domain in AQARA_INTEGRATIONS
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
    )


class AqaraStudyMixin:
    """The Aqara recording, on the study's minute and its file."""

    hass: Any
    _aqara_seen: dict[str, Any] | None

    def _aqara_memory(self) -> dict[str, Any]:
        memory = getattr(self, "_aqara_seen", None)
        if memory is None:
            memory = {}
            self._aqara_seen = memory
        return memory

    @callback
    def _aqara_clear(self) -> None:
        self._aqara_seen = None

    def _aqara_devices(self) -> dict[str, tuple[Any, str]]:
        """Each Aqara device on Matter or HomeKit Device, and the
        integration it reaches Home Assistant through."""
        registry = dr.async_get(self.hass)
        found: dict[str, tuple[Any, str]] = {}
        for entry in self.hass.config_entries.async_entries():
            if entry.domain not in AQARA_INTEGRATIONS:
                continue
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                if is_aqara(device) and device.id not in found:
                    found[device.id] = (device, entry.domain)
        return found

    def _aqara_line(self, now: float, node: str, device_id: str, was: str, said: str, detail: str) -> None:
        self._probe_queue({  # type: ignore[attr-defined]
            PROBE_WHEN: now,
            PROBE_STACK: AQARA_KEY,
            PROBE_NODE: node,
            PROBE_DEVICE_ID: device_id,
            PROBE_WAS: was,
            PROBE_NOW: said,
            PROBE_SENTINEL: self._watch_view(device_id, now) if device_id else "",  # type: ignore[attr-defined]
            PROBE_AGREES: "",
            PROBE_DETAIL: detail,
        })

    def _aqara_reported(self, device_id: str) -> float | None:
        """When any of the device's entities last reported."""
        newest = None
        for row in er.async_entries_for_device(er.async_get(self.hass), device_id):
            state = self.hass.states.get(row.entity_id)
            if state is None or state.state == STATE_UNAVAILABLE:
                continue
            stamp = getattr(state, "last_reported", None) or state.last_updated
            value = stamp.timestamp()
            newest = value if newest is None else max(newest, value)
        return newest

    @callback
    def _aqara_tick(self, now: float) -> None:
        """A line for each entity that turned unavailable or came back,
        and one for each new burst of devices reporting together."""
        last = self._aqara_memory()
        devices = self._aqara_devices()
        registry = er.async_get(self.hass)
        for device_id in devices:
            for row in er.async_entries_for_device(registry, device_id):
                if row.disabled_by:
                    continue
                state = self.hass.states.get(row.entity_id)
                said = (
                    "no state" if state is None
                    else "unavailable" if state.state == STATE_UNAVAILABLE
                    else "available"
                )
                key = f"entity|{row.entity_id}"
                if last.get(key) != said:
                    # The first sighting is where it stands, not a change.
                    if key in last:
                        self._aqara_line(now, NODE_ENTITY, device_id, last[key], said, row.entity_id)
                    last[key] = said
        stamps = sorted(
            (stamp, device_id)
            for device_id in devices
            for stamp in (self._aqara_reported(device_id),)
            if stamp is not None
        )
        newest_seen = last.get("together_at", 0.0)
        index = 0
        while index < len(stamps):
            start = stamps[index][0]
            group = [d for s, d in stamps[index:] if s - start <= TOGETHER_SECONDS]
            if len(group) >= TOGETHER_MIN and start > newest_seen:
                by = sorted({devices[d][1] for d in group})
                self._aqara_line(
                    now, NODE_TOGETHER, "", "", f"{len(group)} devices together",
                    f"at {dt_util.utc_from_timestamp(start).isoformat()}, through {', '.join(by)}",
                )
                last["together_at"] = start
            index += max(1, len(group))

    @callback
    def _aqara_fold(self, now: float) -> None:
        """One line a day for each Aqara device: how long since it last
        reported, and the hub it sits behind."""
        registry = dr.async_get(self.hass)
        for device_id, (device, domain) in sorted(self._aqara_devices().items()):
            reported = self._aqara_reported(device_id)
            via = getattr(device, "via_device_id", None)
            hub = registry.async_get(via) if via else None
            self._aqara_line(
                now, NODE_DAY, device_id, "",
                "no report held" if reported is None else f"last reported {int(now - reported)} s ago",
                f"{domain}, {getattr(device, 'model', None) or 'unknown model'}, "
                + (f"behind {getattr(hub, 'model', None) or 'a hub'}" if hub else "no hub named"),
            )

    def aqara_diagnostics(self) -> dict[str, Any]:
        """The Aqara devices now, for the download: what each is, the hub
        it sits behind, and its entities' states."""
        registry = er.async_get(self.hass)
        devices = self._aqara_devices()
        now = dt_util.utcnow().timestamp()
        children: dict[str, int] = {}
        for device, _domain in devices.values():
            via = getattr(device, "via_device_id", None)
            if via:
                children[via] = children.get(via, 0) + 1
        listed = {}
        for device_id, (device, domain) in sorted(devices.items()):
            reported = self._aqara_reported(device_id)
            listed[device_id] = {
                "integration": domain,
                "model": getattr(device, "model", None),
                "model_id": getattr(device, "model_id", None),
                "software": getattr(device, "sw_version", None),
                "via_device_id": getattr(device, "via_device_id", None),
                "devices_behind_it": children.get(device_id, 0),
                "reported_seconds_ago": None if reported is None else int(now - reported),
                "entities": {
                    row.entity_id: (
                        state.state if (state := self.hass.states.get(row.entity_id)) is not None else None
                    )
                    for row in er.async_entries_for_device(registry, device_id)
                    if not row.disabled_by
                },
            }
        return {"devices": listed}
