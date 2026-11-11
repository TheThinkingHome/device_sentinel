# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_tado.py, Version: 0.28.12 (2026-11-11)

"""What a Tado house shows, recorded for Extended Diagnostics.

Home Assistant's Tado integration fetches the whole house from tado's
cloud in one request, every 5 minutes while a room heats and every 30
when none does, and writes every entity at once. So Device Sentinel
hears the cloud, not each device. A device that drops off tado's own
network reads Connection State off, never unavailable.

The question this answers is whether each device's
`connectionState.timestamp` is when tado last heard from it, a clock
each device could be judged by, or only when its value last changed.
It is read from the data Home Assistant's coordinator already holds;
nothing is ever asked of tado, whose free accounts have 100 requests a
day (rules STACK-08, STACK-11). Recorded:

- at each change, one line per device: its Connection State value,
  its battery state and its firmware;
- once a day, one line per device: how often its timestamp moved and
  where it stands;
- at each refresh: the interval Home Assistant set, whether the
  refresh worked, and the requests left in tado's daily quota;
- each room's link sensor when it changes.

It detects nothing and changes no verdict.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
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

TADO_DOMAIN = "tado"
NODE_REFRESH = "refresh"
NODE_ROOM = "room"
NODE_DAY = "day"
CONNECTION_SUFFIX = "_connection_state"


def _coordinator(entry: Any) -> Any:
    """The entry's update coordinator, or None where it cannot be read."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and hasattr(runtime, "last_update_success"):
        return runtime
    holder = getattr(runtime, "coordinator", None)
    return holder if holder is not None and hasattr(holder, "last_update_success") else None


def _devices(coordinator: Any) -> dict[str, dict[str, Any]]:
    data = getattr(coordinator, "data", None)
    found = data.get("device") if isinstance(data, dict) else None
    return {str(key): value for key, value in found.items() if isinstance(value, dict)} if isinstance(found, dict) else {}


def _connection(record: dict[str, Any]) -> tuple[Any, Any]:
    state = record.get("connectionState")
    if not isinstance(state, dict):
        return None, None
    return state.get("value"), state.get("timestamp")


def _refresh_words(coordinator: Any) -> str:
    interval = getattr(coordinator, "update_interval", None)
    try:
        seconds = int(interval.total_seconds()) if interval is not None else None
    except (AttributeError, TypeError, ValueError):
        seconds = None
    data = getattr(coordinator, "data", None)
    quota = data.get("rate_limit") if isinstance(data, dict) else None
    left = granted = None
    if isinstance(quota, dict):
        left, granted = quota.get("remaining"), quota.get("granted")
    ok = "worked" if getattr(coordinator, "last_update_success", False) else "failed"
    every = f"every {seconds} s" if seconds is not None else "interval unknown"
    left_words = f"{left} of {granted} requests left" if left is not None else "quota unknown"
    return f"{ok}, next {every}, {left_words}"



def _entry_label(entry: Any) -> str:
    """The entry by its id, never its title: Tado names an entry after
    the Tado home, often a family's name or a street (rule STOR-21)."""
    return f"tado entry {str(entry.entry_id)[-6:]}"

class TadoStudyMixin:
    """The Tado recording, on the study's minute and its file."""

    hass: Any
    _tado_seen: dict[str, dict[Any, Any]] | None

    def _tado_memory(self) -> dict[str, Any]:
        memory = getattr(self, "_tado_seen", None)
        if memory is None:
            memory = {"last": {}, "moves": {}, "stamp": {}}
            self._tado_seen = memory
        return memory

    @callback
    def _tado_clear(self) -> None:
        self._tado_seen = None

    def _tado_entries(self) -> list[Any]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(TADO_DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]

    def _tado_device_id(self, serial: str) -> str:
        """The Home Assistant device a Tado serial belongs to, read from
        the Tado entries' own devices (rule STACK-08)."""
        registry = dr.async_get(self.hass)
        for entry in self._tado_entries():
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                if (TADO_DOMAIN, serial) in device.identifiers:
                    return device.id
        return ""

    def _tado_line(self, now: float, node: str, device_id: str, was: str, said: str, detail: str) -> None:
        self._probe_queue({  # type: ignore[attr-defined]
            PROBE_WHEN: now,
            PROBE_STACK: TADO_DOMAIN,
            PROBE_NODE: node,
            PROBE_DEVICE_ID: device_id,
            PROBE_WAS: was,
            PROBE_NOW: said,
            PROBE_SENTINEL: self._watch_view(device_id, now) if device_id else "",  # type: ignore[attr-defined]
            PROBE_AGREES: "",
            PROBE_DETAIL: detail,
        })

    @callback
    def _tado_tick(self, now: float) -> None:
        """A line for each change since the last minute."""
        memory = self._tado_memory()
        last, moves, stamps = memory["last"], memory["moves"], memory["stamp"]
        for entry in self._tado_entries():
            coordinator = _coordinator(entry)
            if coordinator is None:
                key = f"refresh|{entry.entry_id}"
                if last.get(key) != "unreadable":
                    self._tado_line(now, NODE_REFRESH, "", last.get(key, ""), "unreadable",
                                    "no update coordinator on the entry")
                    last[key] = "unreadable"
                continue
            refresh = _refresh_words(coordinator)
            key = f"refresh|{entry.entry_id}"
            if last.get(key) != refresh:
                self._tado_line(now, NODE_REFRESH, "", last.get(key, ""), refresh, _entry_label(entry))
                last[key] = refresh
            for serial, record in sorted(_devices(coordinator).items()):
                value, stamp = _connection(record)
                said = (
                    f"connected {value}, battery {record.get('batteryState')}, "
                    f"firmware {record.get('currentFwVersion')}"
                )
                key = f"device|{serial}"
                if last.get(key) != said:
                    self._tado_line(now, serial, self._tado_device_id(serial), last.get(key, ""), said,
                                    f"{record.get('deviceType')}, timestamp {stamp}")
                    last[key] = said
                if stamp is not None and stamps.get(serial) != stamp:
                    if serial in stamps:
                        moves[serial] = moves.get(serial, 0) + 1
                    stamps[serial] = stamp
        registry = er.async_get(self.hass)
        for row in registry.entities.values():
            if row.platform != TADO_DOMAIN or row.domain != "binary_sensor" or row.disabled_by:
                continue
            if (row.device_class or row.original_device_class) != "connectivity":
                continue
            if row.entity_id.endswith(CONNECTION_SUFFIX):
                continue
            state = self.hass.states.get(row.entity_id)
            said = state.state if state is not None else "no state"
            key = f"room|{row.entity_id}"
            if last.get(key) != said:
                self._tado_line(now, NODE_ROOM, row.device_id or "", last.get(key, ""), said, row.entity_id)
                last[key] = said

    @callback
    def _tado_fold(self, now: float) -> None:
        """One line a day for each device: how often its timestamp moved."""
        memory = self._tado_memory()
        moves, stamps = memory["moves"], memory["stamp"]
        for serial in sorted(stamps):
            count = moves.get(serial, 0)
            self._tado_line(now, NODE_DAY, self._tado_device_id(serial), "", f"timestamp moved {count} times",
                            f"{serial}, timestamp now {stamps[serial]}")
        moves.clear()

    def tado_diagnostics(self) -> dict[str, Any]:
        """What Tado says now, for the download."""
        found: list[dict[str, Any]] = []
        for entry in self._tado_entries():
            coordinator = _coordinator(entry)
            if coordinator is None:
                found.append({"entry": _entry_label(entry), "coordinator": False})
                continue
            found.append({
                "entry": _entry_label(entry),
                "coordinator": True,
                "refresh": _refresh_words(coordinator),
                "devices": {
                    serial: {
                        "type": record.get("deviceType"),
                        "connected": _connection(record)[0],
                        "timestamp": _connection(record)[1],
                        "battery": record.get("batteryState"),
                        "firmware": record.get("currentFwVersion"),
                        "device_id": self._tado_device_id(serial),
                    }
                    for serial, record in sorted(_devices(coordinator).items())
                },
            })
        memory = self._tado_memory()
        return {"entries": found, "timestamp_moves_today": dict(sorted(memory["moves"].items()))}
