# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/battery_projection.py, Version: 0.27.10 (2026-10-27)

"""When a falling cell runs empty, as a range (rule BAT-13).

A level over its pace is one straight line and one number. A coin
cell's fall speeds up near the end, and a straight line through a
curve misses it by months: about 91 days where the curve says about a
month.

The projection is for a cell Device Sentinel already calls falling or
accelerating, which it does only at or under twice the low threshold
(rule BAT-10): with no battery yet watched from new to replaced, a date
further out is a guess that misses on the slow side 84 percent of the
time, since most falling cells rest between steps.

- The last six weeks of heard days are fitted twice, with a straight
  line and with a curve (a second-order fit). The curve is used only
  when it fits clearly better (an F of 10 or more) and bends downward,
  a fall that is speeding up; otherwise the straight line, at any
  level the cell is judged at.
- The range comes from the cell's own data, not a fixed allowance.
  Each day's miss from the fit is kept, the misses are reshuffled a
  week at a time, so a run of low readings stays a run, and the fit is
  made again on each of 200 reshuffled histories. Each is projected
  from today's reading to empty. The near and far ends are the 10th
  and 90th percentiles of those days. The reshuffle is seeded from the
  history, so the same history always gives the same range.
- Worked out once for each history and reading, and kept, as the line
  is, so the minute check does not pay for it.

The near end decides Days Till Low, for the chart and for the
falling forecast on the Problem List (rule BAT-13).
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from .const import (
    BATTERY_CURVE_MIN_F,
    BATTERY_CURVE_MIN_FALLS,
    BATTERY_CURVE_MIN_GAIN,
    BATTERY_CURVE_RECENT_DAYS,
    BATTERY_FIT_MIN_DAYS,
    BATTERY_FIT_WINDOW_DAYS,
    BATTERY_WEEK_DAYS,
)
from .records import SERIES_MEMO_SIZE, series_key

# How many reshuffled histories make the range, and which of their
# answers are its ends.
PROJECTION_RESAMPLES = 200
PROJECTION_NEAR = 0.10
PROJECTION_FAR = 0.90
# Days further than this are said as "over a year" and drawn no
# further: past it the arithmetic is guesswork (rule BAT-13).
PROJECTION_LONGEST = 3 * 365

_MEMO: dict[tuple[Any, ...], dict[str, Any] | None] = {}
_CURVE_MEMO: dict[tuple[Any, ...], float | None] = {}


def _solve(columns: list[list[float]], y: list[float]) -> list[float] | None:
    """Least squares for two or three columns, by the normal equations."""
    size = len(columns)
    gram = [[sum(a * b for a, b in zip(columns[i], columns[j], strict=True)) for j in range(size)] for i in range(size)]
    right = [sum(a * b for a, b in zip(columns[i], y, strict=True)) for i in range(size)]
    # Gaussian elimination with partial pivoting.
    rows = [gram[i] + [right[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(size):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][size] / rows[i][i] for i in range(size)]


def _fit(t: list[float], y: list[float], curved: bool) -> list[float] | None:
    """[a, b, c] of a + b t + c t², c zero for a straight line."""
    ones = [1.0] * len(t)
    if curved:
        found = _solve([ones, t, [v * v for v in t]], y)
        return found
    found = _solve([ones, t], y)
    return None if found is None else [found[0], found[1], 0.0]


def _value(p: list[float], t: float) -> float:
    return p[0] + p[1] * t + p[2] * t * t


def _sse(p: list[float], t: list[float], y: list[float]) -> float:
    return sum((_value(p, a) - b) ** 2 for a, b in zip(t, y, strict=True))


def days_to_empty(level: float, slope: float, curve: float) -> float | None:
    """Days until level + slope d + curve d² reaches zero, or None if a
    path that stops falling never does."""
    if level <= 0:
        return 0.0
    if abs(curve) < 1e-12:
        return level / -slope if slope < 0 else None
    # curve d² + slope d + level = 0, the first root after today.
    disc = slope * slope - 4.0 * curve * level
    if disc < 0:
        return None
    root = math.sqrt(disc)
    found = [d for d in ((-slope - root) / (2 * curve), (-slope + root) / (2 * curve)) if d > 0]
    return min(found) if found else None


def battery_projection(
    series: list[Any], level: float, target: float = 0.0
) -> dict[str, Any] | None:
    """The range of days until a falling cell reaches target, the low
    threshold, or empty for a cell already under it (rule BAT-13).

    series is the battery history one slot a day ending yesterday,
    None for a day the device was not heard (rule STOR-16). Returns None when
    fewer than four weeks were heard, or when no path empties. The
    caller has already judged the cell falling, which is only at or
    under twice the low threshold (rule BAT-10).
    """
    key = (tuple(series[-BATTERY_FIT_WINDOW_DAYS:]), round(float(level), 2), round(float(target), 2))
    if key in _MEMO:
        found = _MEMO[key]
        return dict(found) if found is not None else None
    found = _project(series, float(level), float(target))
    _MEMO[key] = found
    while len(_MEMO) > SERIES_MEMO_SIZE:
        _MEMO.pop(next(iter(_MEMO)))
    return dict(found) if found is not None else None


def _project(series: list[Any], level: float, target: float = 0.0) -> dict[str, Any] | None:
    window = series[-BATTERY_FIT_WINDOW_DAYS:]
    span = len(window)
    pairs = [
        (float(i), float(v)) for i, v in enumerate(window)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if len(pairs) < BATTERY_FIT_MIN_DAYS:
        return None
    t = [p[0] for p in pairs]
    y = [p[1] for p in pairs]
    n = len(pairs)
    line = _fit(t, y, False)
    bend = _fit(t, y, True)
    if line is None:
        return None
    # The curve exactly when the cell reads accelerating: one test for
    # the word and the range (rule BAT-12).
    curved = bend is not None and accelerating_pace(series) is not None
    model = bend if curved and bend is not None else line
    # The distance to cover: to the threshold, the level a person acts on
    # and can see arrive, not to an empty many devices never reach (rule BAT-13).
    room = level - target
    # Today is the slot after the newest, yesterday.
    today = float(span)

    def path(p: list[float]) -> tuple[float, float]:
        return p[1] + 2.0 * p[2] * today, p[2]

    slope, curve = path(model)
    centre = days_to_empty(room, slope, curve)
    # Each day's miss, reshuffled a week at a time: a run of low days
    # stays together, so the range carries the cell's own swings.
    misses = [b - _value(model, a) for a, b in zip(t, y, strict=True)]
    weeks = [misses[i:i + int(BATTERY_WEEK_DAYS)] for i in range(0, n, int(BATTERY_WEEK_DAYS))]
    seed = int.from_bytes(hashlib.sha256(repr(tuple(y)).encode()).digest()[:8], "big")
    draw = random.Random(seed)  # noqa: S311  # nosec B311 - a repeatable reshuffle, not security
    answers: list[tuple[float, float, float]] = []
    for _ in range(PROJECTION_RESAMPLES):
        shuffled: list[float] = []
        while len(shuffled) < n:
            shuffled.extend(draw.choice(weeks))
        y_star = [_value(model, a) + e for a, e in zip(t, shuffled[:n], strict=True)]
        refit = _fit(t, y_star, curved)
        if refit is None:
            continue
        s_star, c_star = path(refit)
        days = days_to_empty(room, s_star, c_star)
        answers.append((math.inf if days is None else days, s_star, c_star))
    finite = [a for a in answers if math.isfinite(a[0])]
    if not finite or centre is None:
        return None
    answers.sort(key=lambda a: a[0])
    near = answers[int(PROJECTION_NEAR * (len(answers) - 1))]
    far = answers[int(PROJECTION_FAR * (len(answers) - 1))]
    if not math.isfinite(near[0]):
        return None
    far_days = far[0] if math.isfinite(far[0]) else None
    return {
        "curved": curved,
        "level": level,
        # Where the time left ends: the low threshold, or 0 for a cell
        # already under it.
        "target": target,
        "near": round(min(near[0], PROJECTION_LONGEST), 1),
        "far": round(min(far_days, PROJECTION_LONGEST), 1) if far_days is not None else None,
        "centre": round(min(centre, PROJECTION_LONGEST), 1),
        # The fitted pace today, points a week, positive for a fall: what
        # the sentence above the chart says of a curved fall (rule BAT-17).
        "pace": round(-slope * BATTERY_WEEK_DAYS, 1),
        # Each end's path from today, level + slope d + curve d², so the
        # chart draws what was fitted rather than fitting again.
        "near_path": [round(near[1], 5), round(near[2], 7)],
        "far_path": [round(far[1], 5), round(far[2], 7)] if far_days is not None else None,
    }


def accelerating_pace(series: list[Any]) -> float | None:
    """The fall today, points a week, when the cell is accelerating, or
    None (rule BAT-12).

    The same six weeks and the same two fits the time left reads, at
    any level: the curve must bend down and fit clearly better (an F
    of 10 or more and a gain of at least one square point), it must
    still be falling today, and the newest two weeks must hold at least
    three drops from one heard day to the next, because without the
    drops steady cells read accelerating on single steps. There is no
    floor on the pace: under the ceiling a floor stops no steady cell
    and holds a real fall back. Kept per history, as the line is, so the
    minute check does not pay for it.
    """
    window = series[-BATTERY_FIT_WINDOW_DAYS:]
    key = series_key(window)
    if key in _CURVE_MEMO:
        return _CURVE_MEMO[key]
    found = _accelerating(window)
    _CURVE_MEMO[key] = found
    while len(_CURVE_MEMO) > SERIES_MEMO_SIZE:
        _CURVE_MEMO.pop(next(iter(_CURVE_MEMO)))
    return found


def _accelerating(window: list[Any]) -> float | None:
    pairs = [
        (float(i), float(v)) for i, v in enumerate(window)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    ]
    n = len(pairs)
    if n < BATTERY_FIT_MIN_DAYS:
        return None
    t = [p[0] for p in pairs]
    y = [p[1] for p in pairs]
    line = _fit(t, y, False)
    bend = _fit(t, y, True)
    if line is None or bend is None or bend[2] >= 0:
        return None
    sse1, sse2 = _sse(line, t, y), _sse(bend, t, y)
    if sse1 - sse2 < BATTERY_CURVE_MIN_GAIN:
        return None
    f_value = (sse1 - sse2) / (sse2 / (n - 3)) if sse2 > 1e-9 else math.inf
    if f_value < BATTERY_CURVE_MIN_F:
        return None
    today = float(len(window))
    pace_today = -(bend[1] + 2.0 * bend[2] * today) * BATTERY_WEEK_DAYS
    # Still falling today. There is no floor on the pace, because under
    # the ceiling a floor stops no steady cell and holds a real fall back
    # (rule BAT-12).
    if pace_today <= 0:
        return None
    recent = [
        float(v) for v in window[-BATTERY_CURVE_RECENT_DAYS:]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    ]
    drops = sum(1 for a, b in zip(recent, recent[1:]) if b < a)
    if drops < BATTERY_CURVE_MIN_FALLS:
        return None
    return pace_today


def time_left_range(near: float, far: float | None) -> str:
    """The range in words, as time left is said (rule BAT-13).

    "under a week", "about 4 to 5 weeks", "about 8 to 11 weeks", "about
    13 to 15 weeks", "about 9 weeks to 4 months", "about 3 to 4 months",
    "about 8 months to over a year", "about a year or more", "over a
    year". Each end is said in its own unit, so a near end inside Days
    Till Low never reads as months; an end that never empties reads as
    over a year. A near end under 13 weeks is said in weeks, and so is a
    far end beside it under four months, so no range says one span
    twice, as "about 8 weeks to 2 months" would.
    """
    near = max(0.0, near)
    far_days = PROJECTION_LONGEST + 1 if far is None else max(far, near)
    if far_days < BATTERY_WEEK_DAYS:
        return "under a week"
    if near > 365:
        return "over a year"
    month = 30.4

    def unit(days: float) -> tuple[int, str]:
        if days < 13 * BATTERY_WEEK_DAYS:
            return max(1, round(days / BATTERY_WEEK_DAYS)), "weeks"
        return max(1, round(days / month)), "months"

    def said(count: int, name: str) -> str:
        return f"{count} {name}" if count != 1 else f"1 {name[:-1]}"

    low, low_unit = unit(near)
    low_words = "under a week" if near < BATTERY_WEEK_DAYS else None
    if far_days > 365:
        if low_unit == "months" and low >= 12:
            # Not "about 12 months to over a year".
            return "about a year or more"
        start = low_words or f"about {said(low, low_unit)}"
        return f"{start} to over a year"
    high, high_unit = unit(far_days)
    if low_words:
        if high_unit == "weeks" and high <= 1:
            return "about 1 week"
        return f"under a week to about {said(high, high_unit)}"
    if low_unit != high_unit and high < 4:
        # A far end under four months next to a near end in weeks is
        # said in weeks too: "13 weeks to 3 months" says one span twice.
        high, high_unit = max(low, round(far_days / BATTERY_WEEK_DAYS)), low_unit
    if low_unit != high_unit and high * month <= low * BATTERY_WEEK_DAYS:
        # Months that round below the near end in weeks would read
        # backwards ("9 weeks to 2 months"): both ends in weeks then.
        high, high_unit = max(low, round(far_days / BATTERY_WEEK_DAYS)), low_unit
    if low_unit == high_unit:
        high = max(low, high)
        return f"about {said(low, low_unit)}" if low == high else f"about {low} to {high} {low_unit}"
    return f"about {said(low, low_unit)} to {said(high, high_unit)}"
