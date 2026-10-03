# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: rhythm_rules.py, Version: 0.24.0 (2026-10-02)

"""The Log-Normal Percentile, the second freeze rule (#542, amended).

A device's freeze wait is the shorter of two rhythms plus the grace
margin. The first, the Trimmed Maximum, reads the last 14 days'
longest gaps, sets the longest aside and takes the next. Two bad days
in 14 defeat it: the second becomes the rhythm and holds the wait open
for up to 13 more days. The second rule, here, reads up to the last 42
days from a device's 28th, works on the logarithm of each day's longest
gap, sets aside every day more than CLIP_DEVIATIONS spreads above or
below the average, repeating until nothing more is set aside, and
takes the average plus CLIP_TARGET_DEVIATIONS spreads: the 90th
percentile of the fit. The spread never falls below CLIP_SPREAD_FLOOR.

Setting aside short days as well as long ones is the amendment. The
shadow version of 0.23.17 set aside long days only, so a device with a
few very short days had its spread blown up and its target thrown far
past anything it had done: Tim's desk dragon light, longest gap 43
hours in 44 days, would have waited 958 hours. Clipping both sides
brings it to about 40, with no cap.

The days it may read start again at a reset (a firmware update, a
battery replacement, a re-pair): `lognormal_days` on the record counts
the days since, and is None when no reset limits the reading.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from .const import (
    CLIP_DEVIATIONS,
    CLIP_MAX_DAYS,
    CLIP_SPREAD_FLOOR,
    CLIP_START_DAYS,
    CLIP_TARGET_DEVIATIONS,
    DEV_DAILY_MAX,
    DEV_LOGNORMAL_DAYS,
    SLOWDOWN_DAYS,
)


def lognormal_days(record: dict[str, Any]) -> int:
    """Return how many of the newest days the Log-Normal Percentile may read.

    The series length, capped at CLIP_MAX_DAYS, and at the days since
    the last reset where one is recorded. Hostile stored values read as
    no limit rather than raising: the load-time check already refuses
    them, and this stands behind it.
    """
    daily = record.get(DEV_DAILY_MAX) or []
    days = min(len(daily), CLIP_MAX_DAYS)
    since = record.get(DEV_LOGNORMAL_DAYS)
    if isinstance(since, (int, float)) and not isinstance(since, bool) and math.isfinite(since) and since >= 0:
        days = min(days, int(since))
    return days


def slowed_down(daily: list[Any], days: int, fit: dict[str, Any] | None = None) -> bool:
    """Whether the newest SLOWDOWN_DAYS days were all set aside as long.

    Each of them longer than the device's usual and set aside by the
    Log-Normal Percentile: a new, slower habit rather than bad days
    (James, 2 October 2026). Days set aside as too short do not count;
    a device reporting more often is the Trimmed Maximum's to follow.
    False while the rule has no fit.
    """
    if fit is None:
        fit = lognormal_rhythm(daily, days)
    if fit is None or len(daily) < SLOWDOWN_DAYS:
        return False
    aside = set(fit["set_aside"])
    newest = range(len(daily) - SLOWDOWN_DAYS, len(daily))
    return all(
        index in aside
        and isinstance(daily[index], (int, float))
        and daily[index] > fit["typical"]
        for index in newest
    )


def lognormal_rhythm(daily: list[Any], days: int) -> dict[str, Any] | None:
    """The Log-Normal Percentile over the newest `days` of a series, or None.

    Worked out directly each time it is asked. The coordinator keeps
    each device's result until its days change (`_freeze_rhythm`), and
    the device page keeps its chart history the same way, so nothing
    here needs remembering; a remembered-results cache was tried and
    removed in 0.24.0, because building chart histories filled it with
    thousands of one-off spans, 11 to 16 MB on a 243-device house.
    Indices returned are into `daily`.
    """
    if days <= 0:
        return None
    start = max(0, len(daily) - days)
    found = _lognormal_compute(list(daily[start:]))
    if found is None:
        return None
    return {**found, "set_aside": [start + index for index in found["set_aside"]]}


def _lognormal_compute(daily: list[Any]) -> dict[str, Any] | None:
    """The Log-Normal Percentile over the whole of `daily`, or None.

    None below CLIP_START_DAYS usable days in that span. A day that is
    not a positive finite number is not read, as the Trimmed Maximum
    does not read one. Returns the rhythm in seconds, the days read
    (the span asked for, bad days included, as the rule is named), and
    the indices into `daily` of the days set aside, for the chart.
    """
    days = len(daily)
    if days <= 0:
        return None
    start = 0
    span = [
        (index, float(value))
        for index, value in enumerate(daily[start:], start)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    ]
    if len(span) < CLIP_START_DAYS:
        return None
    logs = {index: math.log(value) for index, value in span}
    kept = list(logs)
    for _ in range(len(logs)):
        values = [logs[index] for index in kept]
        mean = statistics.fmean(values)
        spread = max(statistics.pstdev(values), CLIP_SPREAD_FLOOR)
        survivors = [
            index
            for index in kept
            if mean - CLIP_DEVIATIONS * spread
            <= logs[index]
            <= mean + CLIP_DEVIATIONS * spread
        ]
        if len(survivors) == len(kept) or not survivors:
            break
        kept = survivors
    values = [logs[index] for index in kept]
    mean = statistics.fmean(values)
    spread = max(statistics.pstdev(values), CLIP_SPREAD_FLOOR)
    try:
        rhythm = math.exp(mean + CLIP_TARGET_DEVIATIONS * spread)
    except OverflowError:
        return None
    if not (math.isfinite(rhythm) and rhythm > 0):
        return None
    kept_set = set(kept)
    return {
        "rhythm": rhythm,
        "typical": math.exp(mean),
        "spread": spread,
        "days": len(daily) - start,
        "set_aside": [index for index in logs if index not in kept_set],
    }
