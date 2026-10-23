# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_battery.py, Version: 0.27.1 (2026-10-23)

"""Which cells are going to be low: the rows, rates and forecast.

The battery report page this module drew retired with the www folder
in 0.23.5 (#470): Home Assistant served it to anyone who asked. The
dashboard's Battery Trends tab, the Battery: Falling sensor, the
Problem List and the brief read the rows kept here.

One of the four report modules split out of reports.py, which
had grown past two thousand lines and held every report the
integration writes. The seam is the report rather than the
audience: a split by reader was considered and does not survive
contact with the code, because one writer produces both kinds
and the shared helpers serve both (ruling #199).

Still a file split rather than a boundary. These methods are
mixed into the coordinator and read its state freely, so `self`
is the coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


from .battery_level import level_text
from .records import SERIES_MEMO_SIZE, series_key
from .battery_projection import accelerating_pace, battery_projection, time_left_range
from homeassistant.util import dt as dt_util

from .daily_dates import FAMILY_BATTERY, on_calendar
from .const import (
    BATTERY_FALLING_MIN_PACE,
    BATTERY_FALLING_WEEK_DROP,
    BATTERY_FIT_MIN_DAYS,
    BATTERY_FIT_WINDOW_DAYS,
    BATTERY_WEEK_DAYS,
    BATTERY_WEEKS_SHOWN,
    READING_ACCELERATING,
    READING_FALLING,
    BATTERY_STEPS_SMOOTH,
    BATTERY_LEFT_BANDS,
    BATTERY_LEFT_BEYOND,
    BATTERY_READABLE_MAX,
    BATTERY_REPORT_CEILING_FACTOR,
    CONF_BATTERY_DAYS,
    DEFAULT_BATTERY_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_FIRST_LOW,
    DEV_BATTERY_LOW,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)


def battery_weeks(series: list[float | None], count: int = BATTERY_WEEKS_SHOWN) -> list[float | None]:
    """Return the average level of each of the last whole weeks,
    oldest first, at most count of them (0.23.6).

    The weeks are counted back from the newest day, so the last is
    always the seven days just folded. A week not yet whole is left
    out rather than averaged over fewer days.
    """
    weeks: list[float | None] = []
    end = len(series)
    while end >= BATTERY_WEEK_DAYS and len(weeks) < count:
        week = series[end - BATTERY_WEEK_DAYS:end]
        # The series is laid out one slot a day (0.24.4, issue #18): a
        # day the device was not heard is None, and a week averages the
        # days it measured, or has no average at all.
        measured = [v for v in week if isinstance(v, (int, float)) and not isinstance(v, bool)]
        weeks.append(sum(measured) / len(measured) if measured else None)
        end -= BATTERY_WEEK_DAYS
    weeks.reverse()
    return weeks


def _least_squares(columns: list[list[float]], y: list[float]) -> tuple[list[float], float] | None:
    """Solve the normal equations for a small fit; return the terms
    and the sum of squared residuals, or None when they are singular.

    Two or three terms and at most six weeks of days, so a direct
    solve is exact enough and keeps the integration free of numpy.
    """
    k = len(columns)
    matrix = [
        [sum(a * b for a, b in zip(columns[i], columns[j])) for j in range(k)]
        + [sum(a * b for a, b in zip(columns[i], y))]
        for i in range(k)
    ]
    for col in range(k):
        pivot = max(range(col, k), key=lambda row: abs(matrix[row][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            return None
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for row in range(k):
            if row != col:
                factor = matrix[row][col] / matrix[col][col]
                matrix[row] = [a - factor * b for a, b in zip(matrix[row], matrix[col])]
    terms = [matrix[i][k] / matrix[i][i] for i in range(k)]
    residual = sum(
        (sum(terms[i] * columns[i][n] for i in range(k)) - y[n]) ** 2
        for n in range(len(y))
    )
    return terms, residual


def battery_line(series: list[float]) -> dict[str, Any] | None:
    """The six-week straight line for a series, worked out once per
    series.

    A cell's daily series changes only at the midnight fold or a
    replacement, but its line was asked for every minute: twice by the
    problem list, again by the notification card, and by every report
    and screen. On the second house with a year of history per device
    that was most of the minute check (0.23.19). Kept by the series'
    values, so any change to them is a new entry; the caller gets its
    own copy.
    """
    key = series_key(series)
    found = _LINE_MEMO.get(key)
    if found is None and key not in _LINE_MEMO:
        found = _battery_line_of(tuple(series))
        _LINE_MEMO[key] = found
        while len(_LINE_MEMO) > SERIES_MEMO_SIZE:
            _LINE_MEMO.pop(next(iter(_LINE_MEMO)))
    return dict(found) if found is not None else None


# The line memo: a fingerprint and its answer, oldest dropped first.
_LINE_MEMO: dict[tuple[Any, ...], dict[str, Any] | None] = {}


def _battery_line_of(series: tuple[float, ...]) -> dict[str, Any] | None:
    """Fit the last six weeks with one straight line.

    The pace is in points a week, positive for a fall. Returns None
    for fewer than BATTERY_FIT_MIN_DAYS heard days. The result carries
    the drawn line as two [days ago, level] points, so the page draws
    what was fitted rather than fitting again. Until 0.27.0 two lines
    joined at a knee were fitted too, for the accelerating test; the
    curve decides that now (ruling #725).
    """
    window = series[-BATTERY_FIT_WINDOW_DAYS:]
    # Only the days the device was heard are fitted, each at its own day
    # (0.24.4, issue #18): a fall from 84 to 81 across three silent days
    # is a fall over four days, not one.
    span = len(window)
    pairs = [
        (float(i), float(v)) for i, v in enumerate(window)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if len(pairs) < BATTERY_FIT_MIN_DAYS:
        return None
    t = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    single = _least_squares([[1.0] * len(pairs), t], values)
    if single is None:
        return None
    (a1, b1), _ = single
    last = span - 1
    return {
        "pace": -b1 * BATTERY_WEEK_DAYS,
        "line": [[last, a1], [0, a1 + b1 * last]],
    }


def battery_calendar(record: dict[str, Any]) -> list[Any]:
    """A device's battery history laid out one slot a day, ending
    yesterday (0.24.4, issue #18): a day the device was not heard is an
    empty slot, so a fall is measured over the days it really took.
    The one way every reader gets a battery series."""
    end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    return on_calendar(record, FAMILY_BATTERY, list(record.get(DEV_BATTERY_DAILY) or []), end)


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def battery_latched(record: dict[str, Any]) -> bool:
    """Whether the cell has been judged low since its last replacement
    (ruling #735). A cell low now counts even before its first-low time
    is written, as one already low when 0.27.1 was installed is."""
    if record.get(DEV_BATTERY_LOW):
        return True
    first = _moment(record.get(DEV_BATTERY_FIRST_LOW))
    if first is None:
        return False
    replaced = _moment(record.get(DEV_BATTERY_REPLACED_AT))
    return replaced is None or first > replaced


def battery_heard_days(series: list[Any]) -> int:
    """How many of the last 42 days hold a reading (ruling #733)."""
    return sum(
        1 for value in series[-BATTERY_FIT_WINDOW_DAYS:]
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )


def battery_trend(
    series: list[float], level: float, smooth: bool, ceiling: float | None = None
) -> dict[str, Any]:
    """Everything the screens and the rules say about a cell's trend.

    Nothing is judged until the cell has been heard on at least 28 of
    the last 42 days (ruling #733): a shorter history gave a new
    battery a time left from two weeks of readings.

    Falling: the last week averages at least a point below the week
    before, and the six-week fitted line is going down at least half a
    point a week. Accelerating: the six-week
    curve the time left reads passes its guarded test (ruling #725,
    `accelerating_pace`), so the reading, the sentence and the range
    agree. Either needs a cell that reports in small steps (a coarse
    cell is judged against the low threshold alone, 0.23.1) with charge
    left, and at or under the ceiling, three times the low threshold (#725):
    above it the weeks are kept and nothing is judged. The pace is the
    curve's fall today for an accelerating cell, the line's for a
    falling one.
    """
    weeks = battery_weeks(series)
    line = battery_line(series) if smooth else None
    trend: dict[str, Any] = {
        "weeks": weeks,
        "reading": "",
        "pace": None,
        "fit": None,
    }
    # A week the device was never heard has no average; the comparison
    # steps over it to the nearest weeks that have one (0.24.4).
    averaged = [w for w in weeks if w is not None]
    if not smooth or level <= 0 or len(averaged) < 2:
        return trend
    if ceiling is not None and level > ceiling:
        return trend
    if battery_heard_days(series) < BATTERY_FIT_MIN_DAYS:
        return trend
    week_drop = averaged[-2] - averaged[-1]
    today = accelerating_pace(series)
    if today is not None:
        trend.update(reading=READING_ACCELERATING, pace=today)
    elif week_drop >= BATTERY_FALLING_WEEK_DROP and (
        line is None or line["pace"] >= BATTERY_FALLING_MIN_PACE
    ):
        pace = line["pace"] if line is not None else week_drop
        trend.update(reading=READING_FALLING, pace=pace, fit=line)
    return trend


def battery_month_drop(series: list[float]) -> float | None:
    """Points lost from the first to the last of the last four weekly
    averages, positive for a fall; None with under four weeks."""
    weeks = battery_weeks(series, 4)
    if len(weeks) < 4:
        return None
    averaged = [w for w in weeks if w is not None]
    if len(averaged) < 2:
        return None
    return averaged[0] - averaged[-1]


def battery_sentence(
    trend: dict[str, Any],
    projection: dict[str, Any] | None = None,
) -> str:
    """One sentence under the device page's table, saying what the
    weeks show (0.23.6); empty for a cell that is not falling.

    A fall that is speeding up is said at the curve's pace today, so
    the sentence agrees with the range beside it (ruling #713): Door
    2nd Bedroom read "at a steady pace" beside a curved range of about
    4 to 5 weeks. An accelerating cell is always said so (ruling #725),
    and a falling one whose time left follows a curve.
    """
    if trend.get("reading") == READING_ACCELERATING and trend.get("pace"):
        return f"Falling faster each week, about {trend['pace']:.1f} points a week today."
    if trend.get("reading") == READING_FALLING and trend.get("pace"):
        pace = (projection or {}).get("pace")
        if (projection or {}).get("curved") and isinstance(pace, (int, float)) and pace > 0:
            return f"Falling faster each week, about {pace:.1f} points a week today."
        return f"Falling about {trend['pace']:.1f} points a week, at a steady pace."
    return ""


class BatteryReportMixin:
    """Which cells are going to be low: the rows, rates and forecast."""

    @staticmethod
    def _battery_slope(levels: list[float]) -> float:
        """Return points lost per day, as a median of pairwise slopes.

        Theil-Sen rather than a least-squares fit, because the shape
        this has to survive is a cell sagging under load and
        recovering: the device that proved it dropped ten points and
        came back eight and a half the next day. A fit is dragged by
        both. A median of every pairwise slope puts them in the tails
        and returns what the other nineteen pairs agree on.

        Negative means falling, which is the ordinary direction.
        """
        n = len(levels)
        if n < 2:
            return 0.0
        slopes = [
            (levels[j] - levels[i]) / (j - i)
            for i in range(n)
            for j in range(i + 1, n)
        ]
        slopes.sort()
        middle = len(slopes) // 2
        if len(slopes) % 2:
            return slopes[middle]
        return (slopes[middle - 1] + slopes[middle]) / 2.0

    def _battery_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Sort every watched cell into what Battery Trends has to say.

        Five groups, because five different things are true and one
        table cannot hold them: falling with a projection, low
        against the threshold, flat, unreadable, and devices with no
        battery at all.

        Muted devices are absent entirely. Every rechargeable on
        the reference fleet is muted by integration already, which
        is why nothing here tries to detect one: a rule watching for
        a jump back up was tried against the fleet and flagged a coin
        cell that reported one high reading, while catching nothing
        the muting had not caught first (ruling #194).
        """
        falling: list[dict[str, Any]] = []
        low: list[dict[str, Any]] = []
        flat: list[dict[str, Any]] = []
        unreadable: list[dict[str, Any]] = []
        absent: list[dict[str, Any]] = []
        for device_id, record in self.watched_records():
            if device_id in self._muted_devices:
                continue
            if self._battery_muted(device_id):
                continue
            level = record.get(DEV_BATTERY_VALUE)
            name = self._device_name(device_id)
            if level is None:
                absent.append({"device_id": device_id, "name": name})
                continue
            row = {
                # Carried so the Battery: Falling sensor can name the
                # device in an automation rather than only in prose
                # (ruling #209).
                "device_id": device_id,
                "name": name,
                "level": float(level),
                "low": bool(record.get(DEV_BATTERY_LOW)),
                "since": record.get(DEV_BATTERY_SINCE),
            }
            if row["level"] > BATTERY_READABLE_MAX:
                unreadable.append(row)
                continue
            series = battery_calendar(record)
            row["series"] = series
            # A cell that reports in coarse steps, or has fallen by one
            # such step and not yet shown which it is, is not
            # forecast: it is judged against the low threshold alone
            # (0.23.1).
            row["steps"] = self.battery_steps(record)
            trend = battery_trend(
                series, row["level"], row["steps"] == BATTERY_STEPS_SMOOTH,
                self.battery_ceiling,
            )
            row["weeks"] = trend["weeks"]
            row["reading"] = trend["reading"]
            row["fit"] = trend["fit"]
            if trend["reading"] and trend["pace"]:
                # The Problem List's forecast item and the Battery:
                # Falling sensor read a rate per day and days left. The
                # days are a range since 0.26.7 (ruling #704), curved
                # where the fall is speeding up; the near end decides
                # Days Till Low. A cell with too few heard days for
                # the fit keeps its straight pace, one figure.
                row["slope"] = -trend["pace"] / BATTERY_WEEK_DAYS
                target = self.battery_target(row["level"], record)
                row["target"] = target
                straight = (row["level"] - target) / (trend["pace"] / BATTERY_WEEK_DAYS)
                projection = battery_projection(series, row["level"], target)
                row["projection"] = projection
                row["days"] = projection["near"] if projection else straight
                row["days_far"] = (
                    projection["far"] if projection else straight
                )
                falling.append(row)
            elif not row["low"]:
                flat.append(row)
            if row["low"]:
                low.append(row)
        falling.sort(key=lambda r: r["days"])
        low.sort(key=lambda r: r["level"])
        flat.sort(key=lambda r: r["level"])
        return {
            "falling": falling,
            "low": low,
            "flat": flat,
            "unreadable": unreadable,
            "absent": sorted(absent, key=lambda r: r["name"] or ""),
        }

    def battery_trend_summary(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """A cell's weekly averages and trend, for the diagnostics
        download (0.23.6), so a capture shows the rule working without
        opening the dashboard. None for a device with no readable
        battery."""
        level = record.get(DEV_BATTERY_VALUE)
        if not isinstance(level, (int, float)) or not 0 <= level <= BATTERY_READABLE_MAX:
            return None
        series = battery_calendar(record)
        trend = battery_trend(
            series, float(level), self.battery_steps(record) == BATTERY_STEPS_SMOOTH,  # type: ignore[attr-defined]
            self.battery_ceiling,
        )
        return {
            # A week the device was never heard has no average (0.24.4);
            # rounding it failed the whole download (0.24.6).
            "weeks": [round(week, 2) if week is not None else None for week in trend["weeks"]],
            "reading": trend["reading"],
            "pace_per_week": round(trend["pace"], 2) if trend["pace"] else None,
        }

    def battery_target(self, level: float, record: dict[str, Any] | None = None) -> float:
        """Where a cell's time left ends: the low threshold, the level a
        person acts on and can see arrive (#730); 0 for a cell at or
        under it, and for one judged low since its last replacement,
        even if it reads above the threshold again (#735)."""
        threshold = float(self.low_threshold)  # type: ignore[attr-defined]
        if level <= threshold or (record is not None and battery_latched(record)):
            return 0.0
        return threshold

    @property
    def battery_ceiling(self) -> float:
        """The level at or under which a cell is judged falling and given
        a time left: three times the low threshold (#725)."""
        return BATTERY_REPORT_CEILING_FACTOR * self.low_threshold  # type: ignore[attr-defined]

    def _battery_days(self) -> float:
        """Return how far ahead a falling cell is called out."""
        return float(
            self.entry.options.get(
                CONF_BATTERY_DAYS, DEFAULT_BATTERY_DAYS
            )
        )

    @staticmethod
    def battery_time_left_range(near: float, far: float | None) -> str:
        """The time left as a range, in #197's words (ruling #704)."""
        return time_left_range(near, far)

    def battery_until_words(self, row: dict[str, Any]) -> str:
        """What a falling cell's time left reaches, with the range: "reaches
        15% in about 3 to 5 weeks", or "empty in ..." for a cell already
        under the threshold (#730)."""
        left = self.battery_time_left_range(row["days"], row.get("days_far"))
        target = row.get("target")
        if isinstance(target, (int, float)) and target > 0:
            shown = int(target) if float(target).is_integer() else target
            return f"reaches {shown}% in {left}"
        return f"empty in {left}"

    @staticmethod
    def battery_time_left(days: float) -> str:
        """Return how long is left, in words rather than a number.

        The projection moved from twelve days to seven in a single
        afternoon on the cell that proved it, about forty percent. The
        same relative error on a device reading 1122 days puts the
        truth between 670 and 1570, so the number claims a precision
        it does not have while the words do not (ruling #197). Bands
        widen with distance, which is how the error behaves.
        """
        for limit, words in BATTERY_LEFT_BANDS:
            if days <= limit:
                return words
        return BATTERY_LEFT_BEYOND

    def _battery_brief_rows(self) -> list[dict[str, Any]]:
        """Return the accelerating cells close enough to warn about.

        The full warning, the Problem List, the phone, the brief and the
        Battery: Falling sensor, goes only to a cell speeding up whose
        near end is inside Days Till Low (#731): measured on both houses
        on 22 October 2026, a warning on a cell falling at a steady pace
        came true about half the time, since most rest between steps,
        and one on an accelerating cell 85 percent. The report's own
        table is unfiltered on purpose (ruling #195), and a cell already
        under the threshold is left out, since it has its own row.
        """
        return [
            row
            for row in self._battery_rows()["falling"]
            if row["reading"] == READING_ACCELERATING
            and row["days"] <= self._battery_days() and not row["low"]
        ]

    def battery_watch_rows(self) -> list[dict[str, Any]]:
        """The cells falling at a steady pace whose near end is inside
        Days Till Low: listed as Batteries to Watch in the brief and on
        Battery Trends, with no push and no Problem List item (#731)."""
        return [
            row
            for row in self._battery_rows()["falling"]
            if row["reading"] != READING_ACCELERATING
            and row["days"] <= self._battery_days() and not row["low"]
        ]

    def _format_battery_cell(self, record: dict[str, Any]) -> str:
        """Render the battery as a level and its recent trend.

        Ninety daily levels will not fit in a table cell and would not
        be read if they did. What this column is for is
        whether a cell is falling and how fast, which is the level
        plus two changes: over the last week and over the last month.

        Each figure appears only once there is history to support it,
        so a fresh install shows a bare level, gains the weekly change
        after a week and the monthly one after a month. An empty
        placeholder for a month would be punctuation rather than
        information.

        A reading outside nought to a hundred is shown as what it is
        rather than dressed as a percentage. It is still recorded
        (ruling #128): every value is recorded as reported, however
        implausible, and classified when it is read. A value discarded
        at the recorder is unrecoverable without waiting out the whole
        retention window again.
        """
        levels = list(record.get(DEV_BATTERY_DAILY) or [])
        level = record.get(DEV_BATTERY_VALUE)
        if level is None:
            return "-" if not levels else f"{levels[-1]:g} (stale)"
        if level > 100 or level < 0:
            return f"{level:g} out of range"
        parts = [level_text(level)]
        if level <= self.low_threshold:
            parts = [f"**{level_text(level)}**"]
        for days, label in ((7, "wk"), (30, "mo")):
            if len(levels) >= days + 1:
                parts.append(f"{levels[-1] - levels[-1 - days]:+g}/{label}")
        return " ".join(parts)
