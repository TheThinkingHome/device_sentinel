# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_battery.py, Version: 0.23.5 (2026-09-25)

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

from typing import Any


from .const import (
    BATTERY_STEPS_SMOOTH,
    BATTERY_ACCELERATING_GAP,
    BATTERY_BLOCK_DAYS,
    BATTERY_BLOCK_MIN_DAYS,
    BATTERY_STABILIZED_RATIO,
    BATTERY_TREND_MIN_DAYS,
    BATTERY_TREND_WINDOWS,
    BATTERY_WIDE_BLOCK_AFTER,
    BATTERY_WIDE_BLOCK_DAYS,
    TREND_ACCELERATING,
    TREND_DISAGREE,
    TREND_JUST_STARTED,
    TREND_STABILIZED,
    TREND_STEADY,
    TREND_TOO_NEW,
    BATTERY_FALLING_SLOPE,
    BATTERY_LEFT_BANDS,
    BATTERY_LEFT_BEYOND,
    BATTERY_READABLE_MAX,
    BATTERY_SLOPE_DAYS,
    CONF_BATTERY_DAYS,
    DEFAULT_BATTERY_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)


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

    @staticmethod
    def _battery_spread(levels: list[float]) -> float | None:
        """Return how much the pairwise slopes disagree, in points a day.

        The same slopes the trend is a median of, measured for their
        spread rather than their middle. It is an interquartile range
        and not a standard deviation, because a deviation is dragged
        by the same outliers Theil-Sen exists to ignore, and a
        confidence that moves with the noise is no confidence at all.

        Small means every pair of days tells the same story. Large
        means they do not, and a projection drawn from them would
        only look precise (ruling #395).
        """
        n = len(levels)
        if n < 4:
            return None
        slopes = sorted(
            (levels[j] - levels[i]) / (j - i)
            for i in range(n)
            for j in range(i + 1, n)
        )
        return slopes[3 * len(slopes) // 4] - slopes[len(slopes) // 4]

    def _battery_windows(self, series: list[float]) -> dict[int, float | None]:
        """Return the slope over each nested window that has the days."""
        return {
            days: (
                self._battery_slope(series[-days:])
                if len(series) >= days
                else None
            )
            for days in BATTERY_TREND_WINDOWS
        }

    def _battery_blocks(
        self, series: list[float]
    ) -> list[tuple[int, int, float]]:
        """Return the periods before the nested windows, oldest first.

        Each is (days ago it started, days ago it ended, slope), and
        each covers only itself. A running total back from today
        cannot say a cell fell hard and then held, because the fall
        and the plateau average each other out; separate periods can.

        Blocks are a month wide until day ninety and a quarter wide
        after it, so a year of retention reads as five periods rather
        than eleven (ruling #395).
        """
        older = series[: -BATTERY_BLOCK_DAYS]
        blocks: list[tuple[int, int, float]] = []
        ago_end = BATTERY_BLOCK_DAYS
        while older:
            width = (
                BATTERY_BLOCK_DAYS
                if ago_end < BATTERY_WIDE_BLOCK_AFTER
                else BATTERY_WIDE_BLOCK_DAYS
            )
            block = older[-width:]
            older = older[:-width]
            ago_start = ago_end + len(block)
            if len(block) >= BATTERY_BLOCK_MIN_DAYS:
                blocks.append(
                    (ago_start, ago_end, self._battery_slope(block))
                )
            ago_end = ago_start
        blocks.reverse()
        return blocks

    def _battery_reading(
        self, windows: dict[int, float | None], days_held: int
    ) -> str:
        """Return what the nested windows say about the decline.

        Thirty days sets the baseline pace, fourteen confirms the
        direction, seven is the pace now.

        A window shallower than the falling floor is read as level
        rather than as a decline. A cell reporting in half point
        steps produces a slope of a few hundredths from rounding
        alone, and on the reference fleet five of ten negative thirty
        day slopes sat inside that band. Dividing by one of those is
        comparing a rate against rounding.

        Acceleration is a progression and not a ratio: every window
        steeper than the one before it, and the seven day slope at
        least one falling-step steeper than the thirty. The
        progression alone would call a cell drifting at -0.100,
        -0.104, -0.108 an acceleration, which is not news.

        A verdict the middle window contradicts is not offered. Where
        the three do not form a progression but seven is far steeper
        than thirty, the reading says the slopes disagree rather than
        asserting an acceleration one of the three does not support
        (ruling #395).
        """

        def falling(slope: float | None) -> float | None:
            """The slope, or None where it is inside the rounding band."""
            if slope is None or slope > BATTERY_FALLING_SLOPE:
                return None
            return slope

        short = falling(windows.get(7))
        if short is None:
            return ""
        if days_held < BATTERY_TREND_MIN_DAYS or windows.get(30) is None:
            return TREND_TOO_NEW

        middle = windows.get(14)
        long = windows.get(30)
        ordered = [
            windows[days]
            for days in BATTERY_TREND_WINDOWS
            if windows.get(days) is not None
        ]
        steepening = len(ordered) > 1 and all(
            earlier >= later
            for earlier, later in zip(ordered, ordered[1:])
        )
        gap = (long - short) if long is not None else None

        if steepening:
            if gap is not None and gap >= BATTERY_ACCELERATING_GAP:
                return TREND_ACCELERATING
            return TREND_STEADY

        baseline = falling(long)
        if baseline is None:
            return TREND_JUST_STARTED
        if gap is not None and gap >= BATTERY_ACCELERATING_GAP:
            if middle is not None:
                return TREND_DISAGREE
            return TREND_ACCELERATING
        if short / baseline <= BATTERY_STABILIZED_RATIO:
            return TREND_STABILIZED
        return TREND_STEADY

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
            slope = self._battery_slope(series[-BATTERY_SLOPE_DAYS:])
            row["series"] = series
            row["windows"] = self._battery_windows(series)
            row["blocks"] = self._battery_blocks(series)
            row["reading"] = self._battery_reading(row["windows"], len(series))
            # Carried for the dashboard. It does not decide anything:
            # measured across 667 samples of both fleets and synthetic
            # decliners, neither absolute nor relative spread
            # predicts how a projection then behaves, so no rule is
            # built on it (ruling #395).
            row["spread"] = self._battery_spread(series[-BATTERY_SLOPE_DAYS:])
            # A cell that reports in coarse steps, or has fallen by one
            # such step and not yet shown which it is, is not
            # forecast: it is judged against the low threshold alone
            # (0.23.1).
            row["steps"] = self.battery_steps(record)
            if (
                slope < BATTERY_FALLING_SLOPE
                and row["level"] > 0
                and row["steps"] == BATTERY_STEPS_SMOOTH
            ):
                row["slope"] = slope
                row["days"] = row["level"] / -slope
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
