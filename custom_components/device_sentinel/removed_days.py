# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: removed_days.py, Version: 0.28.4 (2026-11-07)

"""Days removed by hand from a device's gap history (rule FRZ-25).

A person who knows why a day's longest gap was long, and that the cause
will not come back, can remove that day on the device page. The day
keeps its figure and its place in the history, and neither freeze rule
counts it: the Trimmed Maximum still reads its 14 days, and the
Log-Normal Percentile its days, with the removed ones left out. Pressed
again, the day counts again.

The history is never changed. The rules read a copy with each removed
day blanked in place, so positions, dates and charts stay as they are,
and a removal can always be taken back.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DEV_DAILY_MAX, DEV_REMOVED_DAYS
from .daily_dates import FAMILY_GAP, dates_for


class _Removed:
    """The mark a removed day reads as in the rules' copy of a history.

    Not None: a None stored in a history is damage, and a history holding
    damage is not judged at all, while a removed day is simply not
    counted."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REMOVED"


REMOVED: Any = _Removed()


def is_counted(gap: Any) -> bool:
    """Whether an entry of the rules' copy is a day the rules count."""
    return gap is not REMOVED


def _yesterday() -> date:
    """The newest day a gap history can hold: the last day folded."""
    return dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()


def removed_dates(record: dict[str, Any]) -> set[date]:
    """The days removed by hand, as dates. Anything unreadable is skipped."""
    out: set[date] = set()
    for value in record.get(DEV_REMOVED_DAYS) or []:
        if isinstance(value, str):
            try:
                out.add(date.fromisoformat(value))
            except ValueError:
                continue
    return out


def gap_dates(record: dict[str, Any], length: int | None = None) -> list[date]:
    """The date of each entry of the gap history, oldest first."""
    daily = record.get(DEV_DAILY_MAX) or []
    return dates_for(record, FAMILY_GAP, len(daily) if length is None else length, _yesterday())


def counted_gaps(record: dict[str, Any]) -> list[Any]:
    """The gap history as the freeze rules read it: each removed day
    marked REMOVED in place, every other entry as stored.

    A record with nothing removed is read as stored, at no cost.
    """
    daily = record.get(DEV_DAILY_MAX)
    if not isinstance(daily, list):
        return []
    removed = removed_dates(record)
    if not removed or not daily:
        return daily
    dates = gap_dates(record, len(daily))
    return [REMOVED if when in removed else gap for when, gap in zip(dates, daily)]


def set_removed(record: dict[str, Any], day: date, removed: bool) -> bool:
    """Remove a day from the count, or count it again.

    True when the day is one of the history's entries and its state
    changed. A day the history does not hold is refused with ValueError,
    so a page that is out of date cannot mark a day that is not there.
    """
    if day not in set(gap_dates(record)):
        raise ValueError("That day is not one of this device's learned days.")
    days = removed_dates(record)
    if (day in days) == removed:
        return False
    if removed:
        days.add(day)
    else:
        days.discard(day)
    record[DEV_REMOVED_DAYS] = [d.isoformat() for d in sorted(days)] or None
    return True


def prune_removed(record: dict[str, Any]) -> int:
    """Drop the removed days the history no longer holds, as the fold
    ages them out. Returns how many were dropped."""
    days = removed_dates(record)
    if not days:
        if record.get(DEV_REMOVED_DAYS) not in (None,):
            record[DEV_REMOVED_DAYS] = None
        return 0
    held = days & set(gap_dates(record))
    dropped = len(days) - len(held)
    if dropped or len(record.get(DEV_REMOVED_DAYS) or []) != len(held):
        record[DEV_REMOVED_DAYS] = [d.isoformat() for d in sorted(held)] or None
    return dropped
