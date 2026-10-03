# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: records.py, Version: 0.24.0 (2026-10-02)

"""The device record shape, and the small helpers that go with it.

Small on purpose. The record's template, the day's signal reset and the
compact span are the module-level names the coordinator split left
needing a home of their own: the record
schema is the authority both the core and the storage module read,
and putting it in either would have made the other import from it
and closed a circle (ruling #201).

_new_device_record is the one authoritative field set. A key a
fresh one carries that a stored one does not belongs to a version
newer than the file, and is filled on load (ruling #189). A key a
stored record carries that a fresh one does not is either retired,
written by a past version and removed (RETIRED_DEVICE_FIELDS), or
written by a newer version, and kept untouched so a house can go
back a release and forward again without losing it (#189, amended
28 September 2026).
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DEV_LOGNORMAL_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_REPLACED_PENDING,
    DEV_BATTERY_COARSE_DROPS,
    DEV_BATTERY_RAW_SCALE,
    DEV_BATTERY_RAW_FIRST_DAY,
    DEV_FLAP_BACK,
    DEV_FIRMWARE_HISTORY,
    DEV_FLAP_DROPS,
    DEV_FLAP_LONGEST,
    DEV_FLAP_SINCE,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
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
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_SCALE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
)
from .durations import compact_span

BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _shift(seconds: float) -> str:
    """A signed span for a clock that moved: '+2.0h', '-3m'."""
    return ("+" if seconds >= 0 else "-") + _span(abs(seconds))


def _span(seconds: float) -> str:
    """A compact span for a label: 74m, 4.1h, 2.3d, 3.5w.

    First written for the label the resurrection cap prints when it
    holds a gap down (ruling #166); since 0.23.19 it is the one compact
    format, `durations.compact_span`, which every table uses.
    """
    return compact_span(seconds)


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
        DEV_LOGNORMAL_DAYS: None,
        DEV_TODAY_MAX: None,
        DEV_FIRST_OBSERVED: now_iso,
        DEV_EVENT_COUNT: 0,
        DEV_TAINTED: False,
        # None while the device is watched; the moment it was set
        # aside otherwise, so a gap spanning a disabling is refused
        # rather than learned (ruling #257).
        DEV_SET_ASIDE_SINCE: None,
        # Which scale the fields below are measured on, and the
        # second scale when a device publishes one (ruling #285).
        # None until the first reading says.
        DEV_SIGNAL_SCALE: None,
        DEV_SIGNAL_ALT: None,
        DEV_SIGNAL_VALUE: None,
        DEV_SIGNAL_TODAY_MIN: None,
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
        DEV_SIGNAL_DAILY_RAIL: [],
        DEV_SIGNAL_RAIL_COUNT: 0,
        DEV_BATTERY_LOW: False,
        DEV_BATTERY_SINCE: None,
        DEV_BATTERY_DAILY_PREVIOUS: [],
        DEV_BATTERY_REPLACED_AT: None,
        DEV_BATTERY_REPLACED_PENDING: None,
        DEV_BATTERY_COARSE_DROPS: 0,
        DEV_BATTERY_RAW_SCALE: False,
        DEV_BATTERY_RAW_FIRST_DAY: None,
        DEV_FLAP_DROPS: [],
        DEV_FLAP_SINCE: None,
        DEV_FLAP_BACK: None,
        DEV_FLAP_LONGEST: 0.0,
        DEV_FIRMWARE_HISTORY: [],
        DEV_BATTERY_VALUE: None,
        DEV_BATTERY_DAILY: [],
        DEV_FROZEN_CATEGORY: None,
        DEV_FROZEN_SINCE: None,
    }


# The battery memos' size: fingerprints kept, oldest dropped first.
SERIES_MEMO_SIZE = 1024


def series_key(series: Any) -> tuple[Any, ...]:
    """A small fingerprint of a daily series, for the battery memos.

    The series itself as a key held every version of every cell's
    history until the memo filled, about 7 MB of days nobody would
    ask about again (the 0.23.19 adversarial round). Its length, its
    hash and its last three values name it as surely at a fraction of
    the size: two different series agreeing on all three is not a case
    the arithmetic can meet."""
    values = tuple(series)
    return (len(values), hash(values), values[-3:])
