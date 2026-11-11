# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: pollers.py, Version: 0.28.11 (2026-11-10)

"""Integrations that update all their devices together (rule UP-17).

A cloud integration such as Alarm.com or Tado fetches every device's
state in one request and writes it all at once. Device Sentinel then
hears the integration's update, not each device, and every update looks
like a hub reconnecting.

The hour of storms the storm detector reads cannot hold that verdict: a
restart empties the hour, and a poller that slows down at night, as Tado
does when no room calls for heat, falls below it. So the verdict is also
taken once a day, at midnight, on every house, from two records that
outlive both:

- the devices' own daily longest gaps: an integration whose devices
  keep the same longest gap each day, to within 1%, over five days,
  moves together (the measure the Problem Sensors and Polling study
  made first, with no false positive on 17 integrations);
- the day's storm tally: many storms a day on more than one of the last
  seven days, which reaches a new install in two days.

The verdict is stored with the day it was first and last seen, kept
across a restart, and dropped after seven days in which neither record
holds. A poller's storms are counted and never announced, never cut a
silence short, and its stop is told as the integration stopping.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from collections.abc import Callable
from typing import Any

from .const import (
    DATA_DEVICES,
    DATA_POLLERS,
    DATA_STORM_DAYS,
    POLLER_BASIS,
    POLLER_BASIS_LOCKSTEP,
    POLLER_BASIS_STORMS,
    POLLER_DEVICES,
    POLLER_GAP,
    POLLER_KEEP_DAYS,
    POLLER_LOOKBACK_DAYS,
    POLLER_SEEN,
    POLLER_SINCE,
    POLLER_STORM_DAYS,
    POLLER_STORMS_PER_DAY,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_INTERVAL,
)
from .removed_days import counted_gaps
from .study_watch import lockstep


def _day(text: Any) -> date | None:
    """A stored day, or None for one that cannot be read."""
    if not isinstance(text, str):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and value >= 0 else None


def storm_pollers(rows: Any, day: date) -> dict[str, float | None]:
    """The domains whose storm tally reads as a poller's, with the
    usual time between their storms.

    At least POLLER_STORMS_PER_DAY storms on POLLER_STORM_DAYS of the
    POLLER_LOOKBACK_DAYS days ending on `day`. Only storms nothing
    explains are tallied, so a restart's or an outage's do not count.
    """
    earliest = day - timedelta(days=POLLER_LOOKBACK_DAYS - 1)
    # By day, so two rows for one day, as a missed midnight's catch-up
    # can write, count once.
    busy: dict[str, dict[date, float | None]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        when = _day(row.get(STORM_DAY_DATE))
        domain = row.get(STORM_DAY_DOMAIN)
        count = _number(row.get(STORM_DAY_COUNT))
        if when is None or not isinstance(domain, str) or count is None:
            continue
        if not earliest <= when <= day or count < POLLER_STORMS_PER_DAY:
            continue
        busy.setdefault(domain, {})[when] = _number(row.get(STORM_DAY_INTERVAL))
    found: dict[str, float | None] = {}
    for domain, by_day in busy.items():
        if len(by_day) < POLLER_STORM_DAYS:
            continue
        known = [value for value in by_day.values() if value is not None]
        found[domain] = statistics.median(known) if known else None
    return found


def _devices_longest(
    records: Any, watched: dict[str, str], domain: str, rhythm: Callable[[list[Any]], tuple[float | None, Any]]
) -> float | None:
    """The middle of each device's longest daily gap, read as the freeze
    rules read it, for an integration's watched devices.

    `rhythm` is the freeze rule's own reading (rule FRZ-03): the newest
    14 days, the longest of them set aside once there are enough, and a
    day removed by hand not counted (rule FRZ-25). So one stall cannot
    stretch the stop threshold for as long as its day is kept.
    """
    longest = []
    for device_id, owner in watched.items():
        if owner != domain:
            continue
        reading, _aside = rhythm(counted_gaps(records.get(device_id) or {}))
        value = _number(reading)
        if value is not None:
            longest.append(value)
    return statistics.median(longest) if longest else None


class PollerMixin:
    """The lasting poller verdict, taken at midnight (rule UP-17)."""

    data: dict[str, Any]
    _watched: dict[str, str]
    _dirty: bool
    _trimmed_maximum: Callable[[list[Any]], tuple[float | None, Any]]

    def _pollers(self) -> dict[str, Any]:
        """The stored verdicts. A store that is not a mapping is replaced
        with an empty one, never read (rule STOR-07)."""
        stored = self.data.get(DATA_POLLERS)
        if not isinstance(stored, dict):
            stored = self.data[DATA_POLLERS] = {}
        return stored

    def is_known_poller(self, domain: str | None) -> bool:
        """Whether this integration has been read as a poller."""
        if not domain:
            return False
        return isinstance(self._pollers().get(domain), dict)

    def poller_gap(self, domain: str) -> float | None:
        """A poller's usual longest gap between updates, in seconds."""
        record = self._pollers().get(domain)
        if not isinstance(record, dict):
            return None
        return _number(record.get(POLLER_GAP))

    def poller_devices(self, domain: str) -> set[str] | None:
        """The devices a poller known by them was found in step, or None
        when it is known by its storms or the list cannot be read."""
        record = self._pollers().get(domain)
        devices = record.get(POLLER_DEVICES) if isinstance(record, dict) else None
        if not isinstance(devices, list):
            return None
        found = {device for device in devices if isinstance(device, str)}
        return found or None

    def _fold_pollers(self, day: str) -> None:
        """Take the verdict again for the day that has just ended."""
        ended = _day(day)
        if ended is None:
            return
        records = self.data.get(DATA_DEVICES) or {}
        measured = lockstep(records, dict(self._watched))
        by_storms = storm_pollers(self.data.get(DATA_STORM_DAYS), ended)
        stored = self._pollers()
        holding: dict[str, tuple[str, float | None]] = {}
        in_step: dict[str, list[str]] = {}
        for domain, measure in measured.items():
            if measure.get("lockstep"):
                holding[domain] = (POLLER_BASIS_LOCKSTEP, _number(measure.get("gap")))
                in_step[domain] = list(measure.get("in_step_ids") or [])
        for domain, interval in by_storms.items():
            if domain not in holding:
                # The time between storms is a day's middle, and a poller
                # that slows at night, as Tado does, has longer gaps than
                # that. So its devices' own longest gaps, from however
                # many days they hold, raise it where they are longer.
                longest = _devices_longest(records, self._watched, domain, self._trimmed_maximum)
                gaps = [value for value in (interval, longest) if value is not None]
                holding[domain] = (POLLER_BASIS_STORMS, max(gaps) if gaps else None)
        for domain, (basis, gap) in holding.items():
            before = stored.get(domain)
            record = dict(before) if isinstance(before, dict) else {POLLER_SINCE: day}
            if not isinstance(record.get(POLLER_SINCE), str):
                record[POLLER_SINCE] = day
            record[POLLER_SEEN] = day
            record[POLLER_BASIS] = basis
            if in_step.get(domain):
                record[POLLER_DEVICES] = in_step[domain]
            else:
                record.pop(POLLER_DEVICES, None)
            # A gap the storms cannot give keeps the one the devices did.
            if gap is not None or POLLER_GAP not in record:
                record[POLLER_GAP] = gap
            if record != before:
                stored[domain] = record
                self._dirty = True
        for domain in list(stored):
            if domain in holding:
                continue
            record = stored[domain]
            seen = _day(record.get(POLLER_SEEN)) if isinstance(record, dict) else None
            if seen is None or (ended - seen).days >= POLLER_KEEP_DAYS:
                stored.pop(domain, None)
                self._dirty = True
