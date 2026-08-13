# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: records.py, Version: 0.13.5 (2026-08-13)

"""The device record shape, and the two helpers that read it.

Small on purpose. These three names are the only module-level ones
the coordinator split left needing a home of their own: the record
schema is the authority both the core and the storage module read,
and putting it in either would have made the other import from it
and closed a circle (ruling #201).

_new_device_record is the one authoritative field set. A key a
stored record carries that a fresh one does not was written by a
past version; a key a fresh one carries that a stored one does not
belongs to a version newer than the file. Both are reconciled on
load (ruling #189).
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_LINE,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
)

BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _span(seconds: float) -> str:
    """A compact human span for the capped label: 74m, 4.1h, 2.3d.

    The label the resurrection cap prints when it holds a gap down
    (ruling #166).

    Minutes under ninety, hours under two days, days beyond, one
    decimal where the unit is coarse. The label is read in a table
    cell, so compactness beats precision.
    """
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f}m"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _reset_signal_day(record: dict[str, Any]) -> None:
    """Clear the day's signal accumulators and estimators.

    The fold calls this at midnight and the load-time repair calls it
    on a day a broken version corrupted (rulings #254, #256). One
    place, because a field added to the day's working set and cleared
    in only one of the two would leave the other reading yesterday.
    """
    record[DEV_SIGNAL_COUNT] = 0
    record[DEV_SIGNAL_READS] = 0
    record[DEV_SIGNAL_MEAN_RUN] = 0.0
    record[DEV_SIGNAL_M2] = 0.0
    record[DEV_SIGNAL_P5_STATE] = None
    record[DEV_SIGNAL_P50_STATE] = None


def _new_device_record(now_iso: str, seed_ts: float | None) -> dict[str, Any]:
    """Return a fresh per-device statistics record."""
    return {
        DEV_LAST_ACTIVITY: seed_ts,
        DEV_DAILY_MAX: [],
        DEV_TODAY_MAX: None,
        DEV_FIRST_OBSERVED: now_iso,
        DEV_EVENT_COUNT: 0,
        DEV_TAINTED: False,
        # None while the device is watched; the moment it was set
        # aside otherwise, so a gap spanning a disabling is refused
        # rather than learned (ruling #257).
        DEV_SET_ASIDE_SINCE: None,
        DEV_SIGNAL_VALUE: None,
        DEV_SIGNAL_TODAY_MIN: None,
        DEV_SIGNAL_DAILY_MIN: [],
        DEV_SIGNAL_BELOW_SINCE: None,
        DEV_SIGNAL_BELOW_TODAY: 0.0,
        DEV_SIGNAL_DWELL_DAILY: [],
        DEV_SIGNAL_COUNT: 0,
        DEV_SIGNAL_READS: 0,
        DEV_SIGNAL_MEAN_RUN: 0.0,
        DEV_SIGNAL_M2: 0.0,
        DEV_SIGNAL_P5_STATE: None,
        DEV_SIGNAL_P50_STATE: None,
        DEV_SIGNAL_PSQ_VALUE: None,
        DEV_SIGNAL_PSQ_TS: None,
        DEV_SIGNAL_DAILY_P5: [],
        DEV_SIGNAL_DAILY_P50: [],
        DEV_SIGNAL_TODAY_MAX: None,
        DEV_SIGNAL_DAILY_MEAN: [],
        DEV_SIGNAL_DAILY_SD: [],
        DEV_SIGNAL_DAILY_MAX: [],
        DEV_SIGNAL_DAILY_COUNT: [],
        DEV_SIGNAL_DAILY_LINE: [],
        DEV_SIGNAL_DAILY_RAIL: [],
        DEV_SIGNAL_RAIL_COUNT: 0,
        DEV_SIGNAL_LAST_CHANGE: None,
        DEV_BATTERY_LOW: False,
        DEV_BATTERY_SINCE: None,
        DEV_BATTERY_VALUE: None,
        DEV_BATTERY_DAILY: [],
        DEV_FROZEN_CATEGORY: None,
        DEV_FROZEN_SINCE: None,
    }
