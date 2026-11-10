# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_watch.py, Version: 0.28.10 (2026-11-10)

"""Problem sensors and polled integrations, recorded and never judged
(rule STACK-14).

A tester's Alarm.com showed two things Device Sentinel cannot yet judge.
Its integration polls a cloud and updates every device at once, so
what is heard from each device is the poll: when the poll stopped for
six hours with the integration loaded, fifteen devices were reported
frozen one by one and the gap was learned as their rhythm. And each
device publishes its own health as a Malfunction sensor, a binary
sensor of class problem, which nothing reads.

Problem sensors mean other things elsewhere: a printer's can mean it is
out of paper. So before either is judged, this records what they say,
under the Extended Diagnostics choice Problem Sensors and Polling:

- every problem sensor's state, a line when it changes with Device
  Sentinel's view of the device beside it, and a count a day;
- which integrations update in lockstep, measured from their devices'
  own daily longest gaps, once at the start and at each fold;
- each stop of a lockstep integration's updates: when it began, how
  long it lasted, how many devices it covered, and how many of them
  Device Sentinel listed meanwhile.

Nothing here is stored; a restart begins again. Nothing here changes a
verdict.
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DATA_POLLERS,
    DEV_LAST_ACTIVITY,
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NODE,
    PROBE_NOW,
    PROBE_SENTINEL,
    PROBE_STACK,
    PROBE_WAS,
    PROBE_WHEN,
    STATUS_LEARNING,
    STATUS_NEVER_REPORTED,
    STATUS_REPORTING,
    STATUS_SET_ASIDE,
    WATCH_LOCKSTEP_DAYS,
    WATCH_LOCKSTEP_MIN_DEVICES,
    WATCH_LOCKSTEP_SHARE,
    WATCH_LOCKSTEP_TOLERANCE,
    WATCH_PROBLEM_CAP,
    WATCH_STOP_FACTOR,
    WATCH_STOP_FLOOR,
)
from .removed_days import counted_gaps
from .study import PROBE_MUTED

PROBLEM_CLASS = "problem"
NODE_PROBLEM = "problem"
NODE_POLLING = "polling"
# Device Sentinel's views that say nothing about whether the device is
# quiet: not judged, not yet judged, or muted.
_NOT_A_VERDICT = ("", STATUS_SET_ASIDE, STATUS_NEVER_REPORTED, STATUS_LEARNING, STATUS_REPORTING, PROBE_MUTED)


def lockstep(records: dict[str, dict[str, Any]], watched: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Each integration's lockstep measure, from its devices' daily maxima.

    A device is in step when each of its last WATCH_LOCKSTEP_DAYS daily
    longest gaps sits within WATCH_LOCKSTEP_TOLERANCE of the median of
    its integration's devices that day. An integration whose devices
    report on their own scatter; one that polls a cloud and updates them
    all at once does not: on a tester's house Alarm.com's 15 devices were
    all in step and nothing else was. Integrations with fewer than
    WATCH_LOCKSTEP_MIN_DEVICES measurable devices are left out.
    """
    by_integration: dict[str, list[tuple[str, list[float]]]] = {}
    for device_id, integration in watched.items():
        record = records.get(device_id) or {}
        # A day removed by hand is not counted (rule FRZ-25).
        maxima = [
            value for value in counted_gaps(record)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value >= 0
        ]
        if len(maxima) < WATCH_LOCKSTEP_DAYS:
            continue
        by_integration.setdefault(integration, []).append(
            (device_id, [float(v) for v in maxima[-WATCH_LOCKSTEP_DAYS:]])
        )
    found: dict[str, dict[str, Any]] = {}
    for integration, devices in by_integration.items():
        if len(devices) < WATCH_LOCKSTEP_MIN_DEVICES:
            continue
        days = list(zip(*(maxima for _device, maxima in devices)))
        medians = [statistics.median(day) for day in days]
        in_step = [
            device_id for device_id, maxima in devices
            if all(
                abs(value - middle) <= WATCH_LOCKSTEP_TOLERANCE * max(middle, 1.0)
                for value, middle in zip(maxima, medians)
            )
        ]
        share = len(in_step) / len(devices)
        found[integration] = {
            "devices": len(devices),
            "in_step": len(in_step),
            "share": round(share, 2),
            "lockstep": share >= WATCH_LOCKSTEP_SHARE,
            # The usual longest gap of a day, the middle of the middles.
            "gap": statistics.median(statistics.median(maxima) for _device, maxima in devices),
        }
    return found


# Attributes every entity carries, which say nothing about a problem.
_PLAIN_ATTRIBUTES = frozenset({
    "friendly_name", "device_class", "icon", "entity_picture", "attribution",
    "supported_features", "assumed_state", "restored",
})
_SAID_CAP = 300


def _attributes_said(state: Any) -> str:
    """A problem sensor's own attributes, short and in a stable order."""
    attributes = getattr(state, "attributes", None) or {}
    parts = [
        f"{key}={attributes[key]}"
        for key in sorted(attributes)
        if key not in _PLAIN_ATTRIBUTES
    ]
    said = "; ".join(parts)
    return said if len(said) <= _SAID_CAP else f"{said[:_SAID_CAP - 1]}…"


class WatchStudyMixin:
    """Problem sensors and polling, recorded beside Device Sentinel's view."""

    # Set in the coordinator.
    _watch_last: dict[str, str]
    _watch_since: dict[str, float]
    _watch_lockstep: dict[str, dict[str, Any]] | None
    _watch_stops: dict[str, dict[str, Any]]
    _watch_ended: deque[dict[str, Any]]

    # ------------------------------------------------------ the tick

    @callback
    def _watch_clear(self) -> None:
        """Forget everything, when the choice is taken off."""
        self._watch_last.clear()
        self._watch_since.clear()
        self._watch_lockstep = None
        self._watch_stops.clear()

    def _problem_sensors(self) -> list[tuple[str, str, str]]:
        """Every enabled problem sensor on a device: entity, device, integration."""
        registry = er.async_get(self.hass)  # type: ignore[attr-defined]
        found = []
        for entry in registry.entities.values():
            if entry.domain != "binary_sensor" or entry.disabled_by or not entry.device_id:
                continue
            if (entry.device_class or entry.original_device_class) != PROBLEM_CLASS:
                continue
            found.append((entry.entity_id, entry.device_id, entry.platform))
        return sorted(found)

    def _watch_view(self, device_id: str, now: float) -> str:
        """Device Sentinel's view of a device, as the probe writes it."""
        return self._probe_views(  # type: ignore[attr-defined]
            {"stack": "", "node": "", "now": "", "device_id": device_id, "quiet": None}, now
        )["sentinel"]

    @callback
    def _watch_tick(self, now: float) -> None:
        """A line for each problem sensor that changed, and for each stop
        or return of a lockstep integration's updates."""
        seen = set()
        for entity_id, device_id, platform in self._problem_sensors():
            seen.add(entity_id)
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            now_state = state.state if state is not None else "no state"
            # What the sensor says beside its state, such as which
            # Alarm.com trouble turned it on, so a change of reason is a
            # change too (rule STACK-14).
            said = _attributes_said(state)
            before = self._watch_last.get(entity_id)
            self._watch_last[entity_id] = f"{now_state}|{said}" if said else now_state
            if before == self._watch_last[entity_id]:
                continue
            before = (before or "").split("|", 1)[0]
            self._watch_since[entity_id] = now
            self._probe_queue({  # type: ignore[attr-defined]
                PROBE_WHEN: now,
                PROBE_STACK: platform,
                PROBE_NODE: NODE_PROBLEM,
                PROBE_DEVICE_ID: device_id,
                PROBE_WAS: before or "",
                PROBE_NOW: now_state,
                PROBE_SENTINEL: self._watch_view(device_id, now),
                PROBE_AGREES: "",
                PROBE_DETAIL: f"{entity_id} {said}" if said else entity_id,
            })
        for gone in [entity_id for entity_id in self._watch_last if entity_id not in seen]:
            self._watch_last.pop(gone, None)
            self._watch_since.pop(gone, None)
        if self._watch_lockstep is None:
            self._watch_measure(now, write=False)
        self._watch_polling(now)

    def _watch_measure(self, now: float, *, write: bool) -> None:
        """Measure lockstep, and at the fold write a line per integration."""
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        self._watch_lockstep = lockstep(records, dict(self._watched))  # type: ignore[attr-defined]
        if not write:
            return
        for integration, measure in sorted(self._watch_lockstep.items()):
            self._probe_queue({  # type: ignore[attr-defined]
                PROBE_WHEN: now,
                PROBE_STACK: integration,
                PROBE_NODE: NODE_POLLING,
                PROBE_DEVICE_ID: "",
                PROBE_WAS: "",
                PROBE_NOW: "lockstep" if measure["lockstep"] else "independent",
                PROBE_SENTINEL: "",
                PROBE_AGREES: "",
                PROBE_DETAIL: (
                    f"{measure['in_step']} of {measure['devices']} devices in step over "
                    f"{WATCH_LOCKSTEP_DAYS} days, usual longest gap "
                    f"{self._episode_duration(measure['gap'])}"  # type: ignore[attr-defined]
                ),
            })

    def _watch_polling(self, now: float) -> None:
        """Open a stop when no device of a lockstep integration has been
        heard for its threshold, and close it at the first one heard."""
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        members: dict[str, list[str]] = {}
        for device_id, integration in self._watched.items():  # type: ignore[attr-defined]
            members.setdefault(integration, []).append(device_id)
        in_grace = now < getattr(self, "_grace_until", 0.0)
        for integration, measure in (self._watch_lockstep or {}).items():
            open_stop = self._watch_stops.get(integration)
            if not measure["lockstep"]:
                if open_stop is not None:
                    self._watch_stops.pop(integration, None)
                continue
            devices = members.get(integration) or []
            heard = [
                stamp for stamp in (
                    (records.get(device_id) or {}).get(DEV_LAST_ACTIVITY) for device_id in devices
                ) if isinstance(stamp, (int, float))
            ]
            if not heard:
                continue
            newest = max(heard)
            threshold = max(WATCH_STOP_FLOOR, WATCH_STOP_FACTOR * measure["gap"])
            listed = sum(
                1 for device_id in devices
                if self._watch_view(device_id, now) not in _NOT_A_VERDICT
            )
            if open_stop is None:
                if in_grace or now - newest <= threshold:
                    continue
                self._watch_stops[integration] = {
                    "since": newest, "devices": len(devices), "listed": listed,
                }
                self._probe_queue({  # type: ignore[attr-defined]
                    PROBE_WHEN: now,
                    PROBE_STACK: integration,
                    PROBE_NODE: NODE_POLLING,
                    PROBE_DEVICE_ID: "",
                    PROBE_WAS: "updating",
                    PROBE_NOW: "stopped",
                    PROBE_SENTINEL: f"{listed} of {len(devices)} listed",
                    PROBE_AGREES: "",
                    PROBE_DETAIL: (
                        f"no device heard since {self._episode_stamp(newest)}, "  # type: ignore[attr-defined]
                        f"{len(devices)} devices"
                    ),
                })
                continue
            open_stop["listed"] = max(open_stop["listed"], listed)
            if newest <= open_stop["since"]:
                continue
            self._watch_stops.pop(integration, None)
            lasted = max(0.0, newest - open_stop["since"])
            ended = {
                "integration": integration,
                "since": dt_util.utc_from_timestamp(open_stop["since"]).isoformat(),
                "seconds": round(lasted),
                "devices": open_stop["devices"],
                "listed": open_stop["listed"],
            }
            self._watch_ended.append(ended)
            self._probe_queue({  # type: ignore[attr-defined]
                PROBE_WHEN: now,
                PROBE_STACK: integration,
                PROBE_NODE: NODE_POLLING,
                PROBE_DEVICE_ID: "",
                PROBE_WAS: "stopped",
                PROBE_NOW: "updating",
                PROBE_SENTINEL: f"up to {open_stop['listed']} of {open_stop['devices']} listed",
                PROBE_AGREES: "",
                PROBE_DETAIL: (
                    f"stopped {self._episode_duration(lasted)}, "  # type: ignore[attr-defined]
                    f"from {self._episode_stamp(open_stop['since'])}, {open_stop['devices']} devices"  # type: ignore[attr-defined]
                ),
            })

    # ------------------------------------------------------ the fold

    @callback
    def _watch_fold(self, now: float) -> None:
        """A count a day of problem sensors by integration and state, and
        the lockstep measure taken again."""
        counts: dict[str, dict[str, int]] = {}
        for entity_id, _device_id, platform in self._problem_sensors():
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            by_state = counts.setdefault(platform, {})
            word = state.state if state is not None else "no state"
            by_state[word] = by_state.get(word, 0) + 1
        for platform, by_state in sorted(counts.items()):
            self._probe_queue({  # type: ignore[attr-defined]
                PROBE_WHEN: now,
                PROBE_STACK: platform,
                PROBE_NODE: NODE_PROBLEM,
                PROBE_DEVICE_ID: "",
                PROBE_WAS: "",
                PROBE_NOW: "day",
                PROBE_SENTINEL: "",
                PROBE_AGREES: "",
                PROBE_DETAIL: ", ".join(f"{word} {count}" for word, count in sorted(by_state.items())),
            })
        self._watch_measure(now, write=True)

    def _refresh_schedule(self, domain: str) -> dict[str, Any]:
        """Whether an integration's update coordinator can be read from
        its entries, and if so its interval and last result.

        Read and never called: an integration that keeps its state some
        other way, as the Alarm.com fork keeps a hub, says so and
        nothing breaks (rule STACK-08)."""
        found: list[dict[str, Any]] = []
        for entry in self.hass.config_entries.async_entries(domain):  # type: ignore[attr-defined]
            runtime = getattr(entry, "runtime_data", None)
            holder = runtime if hasattr(runtime, "last_update_success") else getattr(runtime, "coordinator", None)
            if holder is None or not hasattr(holder, "last_update_success"):
                found.append({"coordinator": False, "holds": type(runtime).__name__ if runtime is not None else None})
                continue
            interval = getattr(holder, "update_interval", None)
            try:
                seconds = interval.total_seconds() if interval is not None else None
            except AttributeError:
                seconds = None
            found.append({
                "coordinator": True,
                "interval_seconds": seconds,
                "last_ok": bool(getattr(holder, "last_update_success", False)),
            })
        return {"entries": found}

    # ---------------------------------------------------- diagnostics

    def watch_diagnostics(self, now: float | None = None) -> dict[str, Any]:
        """What problem sensors and polling say now, for the download."""
        now = dt_util.utcnow().timestamp() if now is None else now
        sensors = []
        for entity_id, device_id, platform in self._problem_sensors():
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            since = self._watch_since.get(entity_id)
            sensors.append({
                "entity_id": entity_id,
                "device_id": device_id,
                "integration": platform,
                "state": state.state if state is not None else None,
                "since": dt_util.utc_from_timestamp(since).isoformat() if since is not None else None,
                "sentinel": self._watch_view(device_id, now),
                "attributes": _attributes_said(state),
            })
        return {
            "problem_sensors": sensors[:WATCH_PROBLEM_CAP],
            # Which pollers Home Assistant's own update schedule can be
            # read for: whether each could later be judged by its own
            # refresh rather than by timing (rule UP-17).
            "refresh_readable": {
                domain: self._refresh_schedule(domain)
                for domain in sorted(set(self._watch_lockstep or {}) | set(self.data.get(DATA_POLLERS) or {}))  # type: ignore[attr-defined]
            },
            "problem_sensors_total": len(sensors),
            "polling": dict(sorted((self._watch_lockstep or {}).items())),
            "stops_open": {
                integration: {
                    "since": dt_util.utc_from_timestamp(stop["since"]).isoformat(),
                    "devices": stop["devices"],
                    "listed": stop["listed"],
                }
                for integration, stop in sorted(self._watch_stops.items())
            },
            "stops_ended": list(self._watch_ended),
        }
