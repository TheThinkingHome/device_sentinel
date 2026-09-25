# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_battery.py, Version: 0.23.6 (2026-09-25)

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

from datetime import date, timedelta
from typing import Any


from .const import (
    BATTERY_FALLING_MIN_PACE,
    BATTERY_FALLING_WEEK_DROP,
    BATTERY_KNEE_AFTER_DAYS,
    BATTERY_KNEE_AFTER_MIN,
    BATTERY_KNEE_BEFORE_FLOOR,
    BATTERY_KNEE_EDGE_DAYS,
    BATTERY_KNEE_MIN_DAYS,
    BATTERY_KNEE_MIN_F,
    BATTERY_KNEE_RATIO,
    BATTERY_KNEE_WINDOW_DAYS,
    BATTERY_WEEK_DAYS,
    BATTERY_WEEKS_SHOWN,
    READING_ACCELERATING,
    READING_FALLING,
    BATTERY_STEPS_SMOOTH,
    BATTERY_LEFT_BANDS,
    BATTERY_LEFT_BEYOND,
    BATTERY_READABLE_MAX,
    CONF_BATTERY_DAYS,
    DEFAULT_BATTERY_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)


def battery_weeks(series: list[float], count: int = BATTERY_WEEKS_SHOWN) -> list[float]:
    """Return the average level of each of the last whole weeks,
    oldest first, at most count of them (0.23.6).

    The weeks are counted back from the newest day, so the last is
    always the seven days just folded. A week not yet whole is left
    out rather than averaged over fewer days.
    """
    weeks: list[float] = []
    end = len(series)
    while end >= BATTERY_WEEK_DAYS and len(weeks) < count:
        week = series[end - BATTERY_WEEK_DAYS:end]
        weeks.append(sum(week) / BATTERY_WEEK_DAYS)
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


def battery_knee(series: list[float]) -> dict[str, Any] | None:
    """Fit the last six weeks with one line and with two joined lines.

    The standard way to find where a slope changed (segmented
    regression, the knee point of battery research): every day with a
    week on each side is tried as the join, and the one leaving the
    least error is kept. Paces are in points a week, positive for a
    fall. Returns None for fewer than BATTERY_KNEE_MIN_DAYS days.

    The result carries the drawn line as [days ago, level] points:
    two for a single line, three for a knee, so the page draws what
    was fitted rather than fitting again.
    """
    window = series[-BATTERY_KNEE_WINDOW_DAYS:]
    n = len(window)
    if n < BATTERY_KNEE_MIN_DAYS:
        return None
    t = [float(i) for i in range(n)]
    ones = [1.0] * n
    single = _least_squares([ones, t], window)
    if single is None:
        return None
    (a1, b1), sse1 = single
    best = None
    for join in range(BATTERY_KNEE_EDGE_DAYS, n - BATTERY_KNEE_AFTER_DAYS):
        hinge = [max(0.0, i - join) for i in t]
        fitted = _least_squares([ones, t, hinge], window)
        if fitted is not None and (best is None or fitted[1] < best[2]):
            best = (join, fitted[0], fitted[1])
    one_pace = -b1 * BATTERY_WEEK_DAYS
    last = n - 1
    result: dict[str, Any] = {
        "knee": False,
        "pace": one_pace,
        "line": [[last, a1], [0, a1 + b1 * last]],
    }
    if best is None:
        return result
    join, (a2, b2, c2), sse2 = best
    f_value = ((sse1 - sse2) / 2) / (sse2 / (n - 4)) if sse2 > 1e-9 else float("inf")
    before = -b2 * BATTERY_WEEK_DAYS
    after = -(b2 + c2) * BATTERY_WEEK_DAYS
    if (
        f_value >= BATTERY_KNEE_MIN_F
        and after >= BATTERY_KNEE_AFTER_MIN
        and after >= BATTERY_KNEE_RATIO * max(before, BATTERY_KNEE_BEFORE_FLOOR)
    ):
        at_knee = a2 + b2 * join
        result.update({
            "knee": True,
            "knee_ago": last - join,
            "before": before,
            "pace": after,
            "line": [
                [last, a2],
                [last - join, at_knee],
                [0, a2 + b2 * last + c2 * (last - join)],
            ],
        })
    return result


def battery_trend(series: list[float], level: float, smooth: bool) -> dict[str, Any]:
    """Everything the screens and the rules say about a cell's trend.

    Falling: the last week averages at least a point below the week
    before, and once four weeks are held, the six-week fitted line is
    going down at least half a point a week. Accelerating: the knee fit finds a join where the pace
    became at least two points a week and at least twice what it was.
    Either needs a cell that reports in small steps (a coarse cell is
    judged against the low threshold alone, 0.23.1) with charge left.
    The pace a cell is projected on is the fitted one: after the knee
    when there is one, the single line otherwise.
    """
    weeks = battery_weeks(series)
    knee = battery_knee(series) if smooth else None
    trend: dict[str, Any] = {
        "weeks": weeks,
        "reading": "",
        "pace": None,
        "fit": None,
    }
    if not smooth or level <= 0 or len(weeks) < 2:
        return trend
    week_drop = weeks[-2] - weeks[-1]
    if knee is not None and knee["knee"]:
        trend.update(reading=READING_ACCELERATING, pace=knee["pace"], fit=knee)
    elif week_drop >= BATTERY_FALLING_WEEK_DROP and (
        knee is None or knee["pace"] >= BATTERY_FALLING_MIN_PACE
    ):
        pace = knee["pace"] if knee is not None else week_drop
        trend.update(reading=READING_FALLING, pace=pace, fit=knee)
    return trend


def battery_month_drop(series: list[float]) -> float | None:
    """Points lost from the first to the last of the last four weekly
    averages, positive for a fall; None with under four weeks."""
    weeks = battery_weeks(series, 4)
    if len(weeks) < 4:
        return None
    return weeks[0] - weeks[-1]


def battery_sentence(trend: dict[str, Any], last_day: date | None = None) -> str:
    """One sentence under the device page's table, saying what the
    weeks show (0.23.6); empty for a cell that is not falling.

    last_day is the day the newest point describes, yesterday, so the
    knee can be named as a date rather than a count of days.
    """
    fit = trend.get("fit") or {}
    if trend.get("reading") == READING_ACCELERATING:
        ago = int(fit.get("knee_ago") or 0)
        when = (
            f"about {(last_day - timedelta(days=ago)).strftime('%b %-d')}"
            if last_day is not None
            else f"{ago} days ago"
        )
        return (
            f"Accelerating: steady until {when}, "
            f"then falling about {trend['pace']:.1f} points a week since."
        )
    if trend.get("reading") == READING_FALLING and trend.get("pace"):
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
        """Sort every watched cell into what the report has to say.

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
            series = [
                level
                for level in (record.get(DEV_BATTERY_DAILY) or [])
                if isinstance(level, (int, float))
            ]
            row["series"] = series
            # A cell that reports in coarse steps, or has fallen by one
            # such step and not yet shown which it is, is not
            # forecast: it is judged against the low threshold alone
            # (0.23.1).
            row["steps"] = self.battery_steps(record)
            trend = battery_trend(
                series, row["level"], row["steps"] == BATTERY_STEPS_SMOOTH
            )
            row["weeks"] = trend["weeks"]
            row["reading"] = trend["reading"]
            row["fit"] = trend["fit"]
            if trend["reading"] and trend["pace"]:
                # The Problem List's forecast item and the Battery:
                # Falling sensor read a rate per day and days left.
                row["slope"] = -trend["pace"] / BATTERY_WEEK_DAYS
                row["days"] = row["level"] / (trend["pace"] / BATTERY_WEEK_DAYS)
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
        series = [v for v in (record.get(DEV_BATTERY_DAILY) or []) if isinstance(v, (int, float))]
        trend = battery_trend(
            series, float(level), self.battery_steps(record) == BATTERY_STEPS_SMOOTH  # type: ignore[attr-defined]
        )
        fit = trend["fit"] or {}
        return {
            "weeks": [round(week, 2) for week in trend["weeks"]],
            "reading": trend["reading"],
            "pace_per_week": round(trend["pace"], 2) if trend["pace"] else None,
            "knee_days_ago": fit.get("knee_ago"),
            "pace_before_knee": round(fit["before"], 2) if "before" in fit else None,
        }

    def _battery_days(self) -> float:
        """Return how far ahead a falling cell is called out."""
        return float(
            self.entry.options.get(
                CONF_BATTERY_DAYS, DEFAULT_BATTERY_DAYS
            )
        )

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
        """Return the falling cells close enough for the brief.

        The report's own table is unfiltered on purpose: somebody who
        opened it wants the whole picture. The brief arrives whether
        it was wanted or not, so it carries only what is near
        (ruling #195). A cell already under the threshold is left out
        as well, since it has its own row in Now and saying it twice
        in one document helps nobody.
        """
        return [
            row
            for row in self._battery_rows()["falling"]
            if row["days"] <= self._battery_days() and not row["low"]
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
        parts = [f"{level:g}%"]
        if level <= self.low_threshold:
            parts = [f"**{level:g}%**"]
        for days, label in ((7, "wk"), (30, "mo")):
            if len(levels) >= days + 1:
                parts.append(f"{levels[-1] - levels[-1 - days]:+g}/{label}")
        return " ".join(parts)
