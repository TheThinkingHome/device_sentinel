# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_battery.py, Version: 0.20.12 (2026-09-10)

"""The battery report: which cells are going to be low.

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

import os
from datetime import datetime
from html import escape
from statistics import median
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_ACCELERATING_GAP,
    BATTERY_BLOCK_DAYS,
    BATTERY_BLOCK_MIN_DAYS,
    BATTERY_STABILIZED_RATIO,
    BATTERY_TREND_COLOURS,
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
    BATTERY_CURVE_HEIGHT,
    BATTERY_CURVE_WIDTH,
    BATTERY_FALLING_SLOPE,
    BATTERY_HISTORY_WIDTH,
    BATTERY_LEFT_BANDS,
    BATTERY_LEFT_BEYOND,
    BATTERY_READABLE_MAX,
    BATTERY_SLOPE_DAYS,
    BATTERY_STEADY_CHARTED,
    CONF_BATTERY_DAYS,
    DEFAULT_BATTERY_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    REPORT_BATTERY_HTML,
    REPORT_BATTERY_PREFIX,
    REPORT_BATTERY_URL,
    REPORT_WWW_DIR,
    WIKI_BASE_URL,
)


class BatteryReportMixin:
    """The battery report: which cells are going to be low."""

    @staticmethod
    def _battery_when(stamp: Any) -> str:
        """Return a readable local time from the stored ISO stamp."""
        if not stamp:
            return "-"
        try:
            moment = datetime.fromisoformat(str(stamp))
        except ValueError:
            return "-"
        return dt_util.as_local(moment).strftime("%b %-d, %-I:%M %p")

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
            if slope < BATTERY_FALLING_SLOPE and row["level"] > 0:
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

    def _battery_panel(
        self,
        points: list[float],
        left: float,
        width: float,
        height: float,
        trends: bool,
        dots: int = 0,
        caption: str = "",
    ) -> str:
        """Return one panel of a cell's curve, on its own scale.

        Each panel carries its own high and low, which is the whole
        point of splitting them: on a year of retention a recent
        movement of two points drawn against a hundred point axis is
        a single pixel, and the trend it represents is invisible
        (ruling #395).
        """
        low, high = min(points), max(points)
        if high - low < 1:
            low, high = low - 1, high + 1
        count = len(points)

        def x_at(index: int) -> float:
            return left + 6 + index * (width - 40) / max(1, count - 1)

        def y_at(value: float) -> float:
            return 12 + (high - value) * (height - 26) / (high - low)

        parts = [
            f"<rect x='{left}' y='1' width='{width}' height='{height - 2}' "
            f"fill='none' stroke='#D3D1C7'/>"
        ]
        if dots:
            parts.append(
                f"<rect x='{left}' y='1' width='{x_at(dots) - left - 4:.0f}' "
                f"height='{height - 2}' fill='#000' opacity='0.05'/>"
            )
        line = " ".join(
            f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(points)
        )
        parts.append(
            f"<polyline fill='none' stroke='#2A78D6' stroke-width='1.8' "
            f"points='{line}'/>"
        )
        for index in range(dots):
            parts.append(
                f"<circle cx='{x_at(index):.1f}' cy='{y_at(points[index]):.1f}' "
                f"r='2.2' fill='#2A78D6'/>"
            )
        if trends:
            for days, colour in BATTERY_TREND_COLOURS:
                if count < days:
                    continue
                slope = self._battery_slope(points[-days:])
                last = points[-1]
                first = max(low, min(high, last - slope * (days - 1)))
                parts.append(
                    f"<line x1='{x_at(count - days):.1f}' y1='{y_at(first):.1f}' "
                    f"x2='{x_at(count - 1):.1f}' "
                    f"y2='{y_at(max(low, min(high, last))):.1f}' "
                    f"stroke='{colour}' stroke-width='1.6' "
                    f"stroke-dasharray='3,2'/>"
                )
            parts.append(
                f"<text x='{x_at(0):.1f}' y='{y_at(points[0]) - 7:.1f}' "
                f"font-size='10' class='lbl'>{points[0]:.0f}%</text>"
            )
            parts.append(
                f"<text x='{x_at(count - 1):.1f}' "
                f"y='{y_at(points[-1]) - 7:.1f}' font-size='10' class='lbl' "
                f"text-anchor='end'>{points[-1]:.0f}%</text>"
            )
        parts.append(
            f"<text x='{left + width - 4}' y='13' font-size='10' "
            f"fill='#8a8a86' text-anchor='end'>{high:.0f}%</text>"
        )
        parts.append(
            f"<text x='{left + width - 4}' y='{height - 5}' font-size='10' "
            f"fill='#8a8a86' text-anchor='end'>{low:.0f}%</text>"
        )
        if caption:
            parts.append(
                f"<text x='{left + 5}' y='{height - 5}' font-size='10' "
                f"fill='#8a8a86'>{caption}</text>"
            )
        return "".join(parts)

    def _battery_months(self, series: list[float]) -> list[float]:
        """Return one median a month, oldest first, for the whole series."""
        months: list[float] = []
        rest = list(series)
        while rest:
            block = rest[-BATTERY_BLOCK_DAYS:]
            rest = rest[:-BATTERY_BLOCK_DAYS]
            if len(block) >= BATTERY_BLOCK_MIN_DAYS:
                months.append(median(block))
        months.reverse()
        return months

    def _battery_curve(self, series: list[float]) -> str:
        """Return a cell's history and its last month, side by side."""
        if len(series) < 3:
            return ""
        recent = series[-BATTERY_BLOCK_DAYS:]
        months = self._battery_months(series[:-BATTERY_BLOCK_DAYS])
        history = months + recent
        gap = 16
        left_width = int((BATTERY_CURVE_WIDTH - gap) * 0.42)
        right_width = BATTERY_CURVE_WIDTH - gap - left_width
        height = BATTERY_CURVE_HEIGHT
        return (
            f"<svg viewBox='0 0 {BATTERY_CURVE_WIDTH} {height}' "
            f"width='{BATTERY_CURVE_WIDTH}' height='{height}' role='img' "
            f"aria-label='This cell over time'>"
            + self._battery_panel(
                history, 0, left_width, height, False,
                dots=len(months), caption="all history",
            )
            + self._battery_panel(
                recent, left_width + gap, right_width, height, True,
                caption="last 30 days",
            )
            + "</svg>"
        )

    def _battery_history_chart(self, series: list[float]) -> str:
        """Return one point a month, each carrying the level it sat at.

        For cells that are not falling. Nothing is moving, so there
        is no trend to draw and no reason to spend half the width on
        a second panel.
        """
        points = self._battery_months(series)
        if len(points) < 2:
            return ""
        width, height = BATTERY_HISTORY_WIDTH, BATTERY_CURVE_HEIGHT
        low, high = min(points), max(points)
        if high - low < 1:
            low, high = low - 1, high + 1
        count = len(points)

        def x_at(index: int) -> float:
            return 26 + index * (width - 52) / max(1, count - 1)

        def y_at(value: float) -> float:
            return 18 + (high - value) * (height - 38) / (high - low)

        parts = [
            f"<svg viewBox='0 0 {width} {height}' width='{width}' "
            f"height='{height}' role='img' aria-label='A month at a time'>",
            f"<rect x='0' y='1' width='{width}' height='{height - 2}' "
            f"fill='none' stroke='#D3D1C7'/>",
            "<polyline fill='none' stroke='#2A78D6' stroke-width='1.8' "
            "points='"
            + " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(points))
            + "'/>",
        ]
        for index, value in enumerate(points):
            parts.append(
                f"<circle cx='{x_at(index):.1f}' cy='{y_at(value):.1f}' "
                f"r='2.6' fill='#2A78D6'/>"
            )
            parts.append(
                f"<text x='{x_at(index):.1f}' y='{y_at(value) - 7:.1f}' "
                f"font-size='10' class='lbl' text-anchor='middle'>"
                f"{value:.0f}%</text>"
            )
        parts.append(
            f"<text x='4' y='{height - 5}' font-size='10' "
            f"fill='#8a8a86'>oldest</text>"
        )
        parts.append(
            f"<text x='{width - 4}' y='{height - 5}' font-size='10' "
            f"fill='#8a8a86' text-anchor='end'>newest</text></svg>"
        )
        return "".join(parts)

    @staticmethod
    def _battery_rate(slope: float | None) -> str:
        """Return a slope as a cell, or a dash where there is none."""
        if slope is None:
            return "<td>&ndash;</td>"
        return f"<td>{slope:+.3f}/day</td>"

    def _battery_falling_table(self, rows: list[dict[str, Any]]) -> str:
        """Return the falling table: the trend, the reading, the curve.

        The columns run oldest on the left to newest on the right, so
        reading across is reading the cell's history in order. The
        dated ones each cover their own period and nothing since; the
        last three end today and are what the reading is drawn from
        (ruling #395).

        Every period any cell can show becomes a column, because a
        table where one row's third column means a different stretch
        of time from another row's cannot be read across.
        """
        periods: list[tuple[int, int]] = []
        for row in rows:
            for start, end, _slope in row.get("blocks") or []:
                if (start, end) not in periods:
                    periods.append((start, end))
        periods.sort(reverse=True)

        head = ["<table><tr><th>DEVICE</th><th>LEVEL</th>"]
        head += [f"<th>DAY {start}&ndash;{end}</th>" for start, end in periods]
        head += [f"<th>{days} DAY</th>" for days in BATTERY_TREND_WINDOWS]
        head.append(
            "<th>READING</th><th>LEFT</th>"
            "<th>ALL HISTORY &nbsp;|&nbsp; LAST 30 DAYS</th></tr>"
        )
        html = ["".join(head)]

        horizon = self._battery_days()
        for row in rows:
            blocks = {
                (start, end): slope
                for start, end, slope in (row.get("blocks") or [])
            }
            cells = [
                f"<tr><td>{escape(row['name'] or '')}</td>",
                f"<td>{row['level']:.0f}%</td>",
            ]
            cells += [self._battery_rate(blocks.get(p)) for p in periods]
            cells += [
                self._battery_rate((row.get("windows") or {}).get(days))
                for days in BATTERY_TREND_WINDOWS
            ]
            reading = row.get("reading") or ""
            cells.append(f"<td>{reading}</td>")
            left = self.battery_time_left(row["days"])
            cells.append(
                f"<td style='color:#D03B3B'>{left}</td>"
                if row["days"] <= horizon
                else f"<td>{left}</td>"
            )
            cells.append(f"<td>{self._battery_curve(row.get('series') or [])}</td>")
            cells.append("</tr>")
            html.append("".join(cells))
        html.append("</table>")
        return "".join(html)

    def _battery_steady_table(self, rows: list[dict[str, Any]]) -> str:
        """Return the steady cells: the lowest few charted, the rest gridded.

        A chart per cell reads well for twelve and badly for five
        hundred, which is the fleet the grid of ruling #379 was built
        for. So the lowest cells, the ones nearest the threshold and
        therefore the ones a person has a reason to look at, get a
        month-by-month chart, and everything above them keeps the
        grid. The section is a bounded length whatever the fleet size
        (ruling #395).
        """
        ordered = sorted(rows, key=lambda r: r["level"])
        charted = ordered[:BATTERY_STEADY_CHARTED]
        gridded = ordered[BATTERY_STEADY_CHARTED:]

        html = ["<table><tr><th>DEVICE</th><th>LEVEL</th><th>HISTORY</th></tr>"]
        for row in charted:
            chart = self._battery_history_chart(row.get("series") or [])
            html.append(
                f"<tr><td>{escape(row['name'] or '')}</td>"
                f"<td>{row['level']:.0f}%</td><td>{chart}</td></tr>"
            )
        html.append("</table>")
        if gridded:
            html.append(
                f"<p>{len(gridded)} more cell(s) above these, holding steady.</p>"
            )
            html.append(
                self._battery_grid(
                    [(r["name"] or "", f"{r['level']:.0f}%") for r in gridded],
                    2,
                )
            )
        return "".join(html)

    def _battery_bank_svg(self, rows: list[dict[str, Any]]) -> str:
        """Return the whole bank as ten-point bands, as inline SVG.

        A healthy fleet is lopsided by nature, most of it sitting at
        the top with a thin tail below, so the picture is meant to be
        one tall bar and a few short ones. What it answers at a
        glance is whether that shape still holds.
        """
        if not rows:
            return "<p class='empty'>No readable cells.</p>"
        bands = [0] * 10
        for row in rows:
            bands[min(int(row["level"] // 10), 9)] += 1
        top = max(bands)
        # Ten bands have to fit inside the viewBox with room for the
        # unit under the axis. 20 + 9 * 60 + 48 is 608, which leaves
        # a margin; the first cut used 50 wide on 14 gaps and ran to
        # 646 inside a 640 box, so the top band was clipped and the
        # unit sat on top of its label.
        width, bar_w, gap, floor_y = 640, 48, 12, 150
        parts = [
            f"<svg viewBox='0 0 {width} 180' width='100%' role='img' "
            f"aria-label='Cells per ten point band, "
            f"{len(rows)} in total'>"
        ]
        for index, count in enumerate(bands):
            x = 20 + index * (bar_w + gap)
            height = 0 if not count else max(3.0, 110.0 * count / top)
            colour = "#D03B3B" if index < 2 else "#2A78D6"
            if count:
                parts.append(
                    f"<rect x='{x}' y='{floor_y - height:.0f}' "
                    f"width='{bar_w}' height='{height:.0f}' rx='2' "
                    f"fill='{colour}'/>"
                    f"<text x='{x + bar_w / 2:.0f}' "
                    f"y='{floor_y - height - 5:.0f}' class='lbl' "
                    f"font-size='11' text-anchor='middle'>{count}</text>"
                )
            parts.append(
                f"<text x='{x + bar_w / 2:.0f}' y='{floor_y + 14}' "
                f"class='lbl' font-size='11' text-anchor='middle'>"
                f"{index * 10}</text>"
            )
        parts.append(
            f"<text x='{width - 20}' y='{floor_y + 26}' class='lbl' "
            f"font-size='11' text-anchor='end'>percent</text></svg>"
        )
        return "".join(parts)

    @staticmethod
    def _battery_columns(
        items: list[str], columns: int
    ) -> list[list[str]]:
        """Return items dealt into columns of equal length.

        Split by count rather than by value, so the columns are the
        same height whatever the data does. Reading order is down the
        first column and then down the next, which is why the split
        is a slice rather than a deal: a person scanning for one
        device follows the sorted order without crossing back.

        An odd count puts the extra entry in the earlier column.
        """
        if not items:
            return []
        per = -(-len(items) // columns)
        return [
            items[index * per : (index + 1) * per]
            for index in range(columns)
        ]

    def _battery_grid(
        self, cells: list[tuple[str, str]], columns: int
    ) -> str:
        """Return a multi-column table of name and value pairs.

        The steady list was a paragraph of forty-seven names and
        levels, which is a wall nobody reads. The same names in two
        columns take a third of the height and can be scanned, and
        the table matches every other table on the page.
        """
        blocks = self._battery_columns(cells, columns)
        if not blocks:
            return "<p class='empty'>None.</p>"
        header = "".join(
            "<th>DEVICE</th><th>LEVEL</th>" for _ in blocks
        )
        rows: list[str] = [f"<table><tr>{header}</tr>"]
        for index in range(len(blocks[0])):
            body: list[str] = []
            for block in blocks:
                if index < len(block):
                    name, value = block[index]
                    body.append(
                        f"<td>{escape(name)}</td><td>{value}</td>"
                    )
                else:
                    body.append("<td></td><td></td>")
            rows.append("<tr>" + "".join(body) + "</tr>")
        rows.append("</table>")
        return "".join(rows)

    def _battery_name_grid(
        self, names: list[str], columns: int
    ) -> str:
        """Return a multi-column table of names with no value."""
        blocks = self._battery_columns(names, columns)
        if not blocks:
            return "<p class='empty'>None.</p>"
        header = "".join("<th>DEVICE</th>" for _ in blocks)
        rows: list[str] = [f"<table><tr>{header}</tr>"]
        for index in range(len(blocks[0])):
            body = [
                f"<td>{escape(block[index])}</td>"
                if index < len(block)
                else "<td></td>"
                for block in blocks
            ]
            rows.append("<tr>" + "".join(body) + "</tr>")
        rows.append("</table>")
        return "".join(rows)

    def _write_battery_html(self) -> None:
        """Write the battery report (ruling #194).

        A threshold answers which cells are low. This answers which
        are going to be, which is the question a person actually has,
        and it answers it from the daily level series #62 has been
        collecting since 0.4.2.

        Nothing here alarms. The projection moves while the series is
        short, and the cell that motivated the page moved from twelve
        days to seven in an afternoon, so it is shown and not pushed
        until a soak says how far it swings. The threshold keeps the
        alarming to itself in the meantime.
        """
        groups = self._battery_rows()
        readable = groups["falling"] + groups["flat"]
        readable += [r for r in groups["low"] if r not in readable]
        written = dt_util.now().strftime("%B %d, %Y at %-I:%M %p")

        if groups["falling"]:
            falling_block = self._battery_falling_table(groups["falling"])
        else:
            falling_block = "<p class='empty'>No cell is measurably falling.</p>"

        if groups["low"]:
            low_html = ["<table><tr><th>DEVICE</th><th>LEVEL</th>"
                        "<th>SINCE</th></tr>"]
            for row in groups["low"]:
                low_html.append(
                    f"<tr><td>{escape(row['name'] or '')}</td>"
                    f"<td>{row['level']:.0f}%</td>"
                    f"<td>{self._battery_when(row['since'])}</td></tr>"
                )
            low_html.append("</table>")
            low_block = "".join(low_html)
        else:
            low_block = "<p class='empty'>Nothing under the threshold.</p>"

        flat_block = (
            f"<p>{len(groups['flat'])} cell(s) holding steady. The lowest "
            "are charted, one point a month, each carrying the level that "
            "month sat at.</p>"
            + self._battery_steady_table(groups["flat"])
            + "<p>These cells have not moved. A battery holds its "
            "level for most of its life and then falls, so a steady "
            "reading is a healthy one rather than a stale one.</p>"
            if groups["flat"]
            else "<p class='empty'>None.</p>"
        )
        unreadable_block = (
            self._battery_grid(
                [
                    (r["name"] or "", f"{r['level']:.0f}%")
                    for r in groups["unreadable"]
                ],
                1,
            )
            + "<p>These devices report a raw sensor reading rather "
            "than a valid battery level between 0 to 100 percent. "
            "They will never be flagged low. Turn Battery off for "
            "them on their Device Sentinel device page.</p>"
            if groups["unreadable"]
            else "<p class='empty'>None.</p>"
        )
        # The list and the count come from one source, so the page
        # can never name a different number of devices than it shows.
        absent_block = (
            f"<p>{len(groups['absent'])} watched device(s) report no "
            "battery.</p>"
            + self._battery_name_grid(
                [r["name"] or "" for r in groups["absent"]], 3
            )
            + "<p>These devices report no battery level. Most are "
            "mains powered. If one of these runs on batteries, turn "
            "Battery on for it on its Device Sentinel device "
            "page.</p>"
            if groups["absent"]
            else "<p class='empty'>None.</p>"
        )

        html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Device Sentinel Battery Report</title>
<style>
body {{ font-family: sans-serif; margin: 16px; background: #fff;
  color: #1a1a19; max-width: 760px; }}
h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 24px; }}
p, td, th {{ font-size: 13px; }} .lbl {{ fill: #1a1a19; }}
.empty {{ color: #5F5E5A; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
td, th {{ border: 1px solid #D3D1C7; padding: 4px 8px;
  text-align: left; }}
footer {{ margin-top: 24px; font-size: 13px; color: #5F5E5A; }}
footer code {{ font-size: 12px; background: #F0EFE9; padding: 1px 4px;
  border-radius: 3px; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #eee; }}
  .lbl {{ fill: #eee; }}
  td, th {{ border-color: #444; }}
  footer code {{ background: #2a2a28; }}
  footer, .empty {{ color: #B4B2A9; }} }}
</style></head><body>
<h1>Device Sentinel Battery Report</h1>
<p>Written {written}. {len(readable)} watched cell(s) reporting a
readable level: {len(groups['falling'])} falling,
{len(groups['flat'])} steady, {len(groups['low'])} under the
threshold.</p>
<h2>The Bank</h2>
{self._battery_bank_svg(readable)}
<h2>Falling</h2>
{falling_block}
<p>This table isolates batteries that are losing charge. It tracks the
daily drain rate across time. The READING column interprets the raw
data by comparing recent decay against the cells long-term trend. To
interpret the history, observe how the drain rates shift from left to
right:</p>
<ul>
<li><b>Accelerating:</b> Drain rates increase as you move right. For
lithium coin cells, this indicates the steep voltage drop immediately
preceding failure.</li>
<li><b>Steady:</b> Drain rates remain consistent across all columns.
The projected lifespan estimate is reliable.</li>
<li><b>Slopes do not agree:</b> The 30, 14 and 7 day rates do not form
a consistent progression, so the recent decline is not confirmed by
the period between. Treat the estimate with caution.</li>
<li><b>Stabilized:</b> High drain in older columns is followed by flat
recent columns. This indicates a temporary voltage dip (e.g., cold
weather, mesh storm) that has since recovered. Replacement is not yet
required.</li>
</ul>
<p>Times are deliberately vague, because a cell can hold its charge
for weeks and then drop in days. A time shown in red falls inside
your <b>Days Till Empty Warning</b> setting, on the Low Battery
settings screen.</p>
<h2>Under the Threshold</h2>
{low_block}
<p>A cell appears in this table when its level is at or below your
<b>Low Battery Threshold</b>, on the Low Battery settings screen. That
setting is what raises an alert; this page only reports.</p>
<h2>Steady</h2>
{flat_block}
<h2>Unreadable</h2>
{unreadable_block}
<h2>No Battery Reported</h2>
{absent_block}
<footer>Written beside the daily brief, and again whenever you run
Regenerate Reports. To keep it on a dashboard, add a Webpage card
pointing at <code>{REPORT_BATTERY_URL}</code>. How to read this page:
<a href="{WIKI_BASE_URL}/The-Battery-Report">The Battery Report</a>
on the Device Sentinel wiki.</footer>
</body></html>
"""
        directory = self.hass.config.path(REPORT_WWW_DIR)
        os.makedirs(directory, exist_ok=True)
        # Named for the day it was written, which under #190 is also
        # the day it covers: its headline figures are the levels now
        # rather than a day that has closed.
        stamp = dt_util.now().strftime("%Y-%m-%d")
        self._write_file(
            os.path.join(directory, f"{REPORT_BATTERY_PREFIX}{stamp}.html"),
            html,
        )
        self._write_file(
            os.path.join(directory, REPORT_BATTERY_HTML),
            html,
        )
        self._trim_dated(directory, REPORT_BATTERY_PREFIX)

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
