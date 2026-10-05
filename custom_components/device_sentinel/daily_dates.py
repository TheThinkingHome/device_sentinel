# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/daily_dates.py, Version: 0.24.6 (2026-10-05)

"""The date of every entry in a device's daily histories (0.24.4, issue #18).

Each daily history holds one entry for each day it measured something:
the longest gap, the battery level, the signal figures. Until 0.24.4
the entries carried no dates, and every reader counted back from
yesterday, one entry a day. A day with no measurement broke that: the
gap and signal histories wrote nothing, so every later entry sat one
day early, and the battery history wrote the last level again, so a
silent device showed invented flat days and then a cliff.

A history's dates are kept beside it, compactly, because nearly every
day is measured: the date of its newest entry, how many entries the
dates cover, and the days skipped, as ranges. Every other entry's date
follows by counting back from the newest, stepping over the skipped
days. A history with nothing skipped costs about forty bytes.

Every writer and reader goes through `dates_for` and `set_dates`: a
fold, a trim, a removed entry or a battery change reads the dates as
a list, changes the list, and writes it back, so a block can never
disagree with its history. A history written before 0.24.4, or after
a downgrade to one, has no dates for some of its entries; those are
taken as consecutive days, which is how every reader read them before.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .const import DEV_DAILY_DATES as DAILY_DATES

# One block per family of histories written together at the fold.
FAMILY_GAP = "daily_max"
FAMILY_BATTERY = "battery"
FAMILY_BATTERY_PREVIOUS = "battery_previous"
FAMILY_SIGNAL = "signal"
# The second signal scale's dates sit on the record too: its block must
# hold exactly its recording fields (ruling #286).
FAMILY_SIGNAL_ALT = "signal_alt"

FAMILIES = (
    FAMILY_GAP,
    FAMILY_BATTERY,
    FAMILY_BATTERY_PREVIOUS,
    FAMILY_SIGNAL,
    FAMILY_SIGNAL_ALT,
)

_LAST = "last"
_COUNT = "count"
_SKIPPED = "skipped"


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _block(holder: dict[str, Any], family: str) -> dict[str, Any] | None:
    blocks = holder.get(DAILY_DATES)
    if not isinstance(blocks, dict):
        return None
    block = blocks.get(family)
    return block if isinstance(block, dict) else None


def dates_for(
    holder: dict[str, Any], family: str, length: int, fallback_end: date
) -> list[date]:
    """The date of each of a history's `length` entries, oldest first.

    Without a block, or for entries the block does not cover, the
    entries are taken as consecutive days. Entries beyond the block's
    count were appended by a release that kept no dates, after the
    block's newest day; entries the block covers end on its newest day
    and step back over the skipped days.
    """
    if length <= 0:
        return []
    block = _block(holder, family)
    last = _day(block.get(_LAST)) if block else None
    count = block.get(_COUNT) if block else None
    if (
        last is None
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
    ):
        return [fallback_end - timedelta(days=length - 1 - i) for i in range(length)]
    if block is None:
        # A newest date is only ever read from a block; unreachable, and
        # read as consecutive days if it ever is not.
        return [fallback_end - timedelta(days=length - 1 - i) for i in range(length)]
    covered = min(count, length)
    extra = length - covered
    skipped: set[date] = set()
    for pair in block.get(_SKIPPED) or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        start, end = _day(pair[0]), _day(pair[1])
        if start is None or end is None or end < start or (end - start).days > 3660:
            continue
        day = start
        while day <= end:
            skipped.add(day)
            day += timedelta(days=1)
    dated: list[date] = []
    day = last
    guard = 0
    while len(dated) < covered and guard < 4 * 3660:
        if day not in skipped:
            dated.append(day)
        day -= timedelta(days=1)
        guard += 1
    while len(dated) < covered:
        dated.append(day)
        day -= timedelta(days=1)
    dated.reverse()
    after = [last + timedelta(days=i + 1) for i in range(extra)]
    return dated + after


def set_dates(holder: dict[str, Any], family: str, dates: list[date]) -> None:
    """Write a history's dates back as its block: newest, count, skipped."""
    blocks = holder.get(DAILY_DATES)
    if not isinstance(blocks, dict):
        blocks = holder[DAILY_DATES] = {}
    if not dates:
        blocks.pop(family, None)
        if not blocks:
            # The record's key stays, as None: the shape check expects
            # every record to hold it.
            holder[DAILY_DATES] = None
        return
    skipped: list[list[str]] = []
    for before, after in zip(dates, dates[1:]):
        if (after - before).days > 1:
            skipped.append(
                [
                    (before + timedelta(days=1)).isoformat(),
                    (after - timedelta(days=1)).isoformat(),
                ]
            )
    blocks[family] = {
        _LAST: dates[-1].isoformat(),
        _COUNT: len(dates),
        _SKIPPED: skipped,
    }


def day_appended(
    holder: dict[str, Any],
    family: str,
    length_before: int,
    length_after: int,
    day: date,
    added: bool,
) -> None:
    """Record the fold of `day` on a history that went from one length to
    another: the new entry, if there is one, takes the day's date, and
    any trim from the front drops the oldest dates with it.

    The caller says whether the fold added an entry (0.24.6). A history
    at its History days limit adds one and trims one, so its length does
    not change, and a length read alone took that night for one that
    added nothing: the newest date stopped moving and every entry slid a
    day earlier each night."""
    dates = dates_for(holder, family, length_before, day - timedelta(days=1))
    if added:
        if dates and dates[-1] >= day:
            # Folded twice for one day, which the fold guards against:
            # the newer entry keeps the day and the older steps back.
            dates = [d - timedelta(days=1) for d in dates]
        dates.append(day)
    keep = max(0, length_after)
    set_dates(holder, family, dates[-keep:] if keep else [])


def entry_removed(
    holder: dict[str, Any], family: str, length_before: int, index: int, fallback_end: date
) -> None:
    """Drop one entry's date, so the day it held reads as skipped."""
    dates = dates_for(holder, family, length_before, fallback_end)
    if 0 <= index < len(dates):
        del dates[index]
    set_dates(holder, family, dates)


def trimmed_to(
    holder: dict[str, Any], family: str, length_before: int, length_after: int, fallback_end: date
) -> None:
    """Drop the dates of entries trimmed from the front of a history."""
    if length_after >= length_before:
        return
    dates = dates_for(holder, family, length_before, fallback_end)
    set_dates(holder, family, dates[-length_after:] if length_after > 0 else [])


def on_calendar(
    holder: dict[str, Any], family: str, values: list[Any], end: date
) -> list[Any]:
    """A history laid out one slot a day, oldest first, ending at `end`.

    A skipped day's slot is None, so every reader that counts by
    position counts days: the charts, the weekly averages, the fits.
    The first slot is the oldest entry's day; a history without dates
    reads as consecutive days ending at `end`, as before 0.24.4.
    """
    if not values:
        return []
    dates = dates_for(holder, family, len(values), end)
    start = min(dates[0], end)
    span = (end - start).days + 1
    if span <= 0:
        return []
    slots: list[Any] = [None] * span
    for when, value in zip(dates, values):
        index = (when - start).days
        if 0 <= index < span:
            slots[index] = value
    return slots
