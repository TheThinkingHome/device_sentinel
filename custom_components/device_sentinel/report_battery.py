# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_battery.py, Version: 0.12.13 (2026-08-07)

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
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_FALLING_SLOPE,
    BATTERY_LEFT_BANDS,
    BATTERY_LEFT_BEYOND,
    BATTERY_READABLE_MAX,
    BATTERY_SLOPE_DAYS,
    CONF_BATTERY_DAYS,
    DATA_DEVICES,
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

    def _battery_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Sort every watched cell into what the report has to say.

        Five groups, because five different things are true and one
        table cannot hold them: falling with a projection, low
        against the threshold, flat, unreadable, and devices with no
        battery at all.

        Excluded devices are absent entirely. Every rechargeable on
        the reference fleet is excluded by integration already, which
        is why nothing here tries to detect one: a rule watching for
        a jump back up was tried against the fleet and flagged a coin
        cell that reported one high reading, while catching nothing
        the exclusions had not caught first (ruling #194).
        """
        falling: list[dict[str, Any]] = []
        low: list[dict[str, Any]] = []
        flat: list[dict[str, Any]] = []
        unreadable: list[dict[str, Any]] = []
        absent: list[dict[str, Any]] = []
        for device_id, record in self.data.get(DATA_DEVICES, {}).items():
            if device_id in self._excluded_devices:
                continue
            if self._battery_excluded(device_id):
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
            series = list(record.get(DEV_BATTERY_DAILY) or [])
            slope = self._battery_slope(series[-BATTERY_SLOPE_DAYS:])
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
            falling_html = ["<table><tr><th>DEVICE</th><th>LEVEL</th>"
                            "<th>RATE</th><th>LEFT</th></tr>"]
            horizon = self._battery_days()
            for row in groups["falling"]:
                left = self.battery_time_left(row["days"])
                cell = (
                    f"<td style='color:#D03B3B'>{left}</td>"
                    if row["days"] <= horizon
                    else f"<td>{left}</td>"
                )
                falling_html.append(
                    f"<tr><td>{escape(row['name'] or '')}</td>"
                    f"<td>{row['level']:.0f}%</td>"
                    f"<td>{row['slope']:.2f}/day</td>{cell}</tr>"
                )
            falling_html.append("</table>")
            falling_block = "".join(falling_html)
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

        flat_names = ", ".join(
            f"{escape(r['name'] or '')} {r['level']:.0f}%"
            for r in groups["flat"]
        )
        flat_block = (
            f"<p>{len(groups['flat'])} cell(s) holding steady. "
            f"{flat_names}</p>"
            if groups["flat"]
            else "<p class='empty'>None.</p>"
        )
        unreadable_block = (
            "<p>"
            + ", ".join(
                f"{escape(r['name'] or '')} reads {r['level']:.0f}%"
                for r in groups["unreadable"]
            )
            + ". A percentage cannot be above 100, so this is a raw "
            "scale rather than a level. It can never cross the low "
            "threshold.</p>"
            if groups["unreadable"]
            else "<p class='empty'>None.</p>"
        )
        absent_block = (
            f"<p>{len(groups['absent'])} watched device(s) report no "
            "battery: mains powered, or a battery entity that has "
            "never been switched on. Enable Battery on the Device "
            "Sentinel device page turns on the ones that exist.</p>"
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
footer {{ margin-top: 24px; font-size: 12px; color: #5F5E5A; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #eee; }}
  .lbl {{ fill: #eee; }}
  td, th {{ border-color: #444; }}
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
<p>Sorted by how long is left, which is the order that matters. The
rate is the median daily change over the last {BATTERY_SLOPE_DAYS}
days, and how long is left is the current level divided by it. It is
said in words rather than a count of days on purpose: the projection
moves, and it moves further the further out it reaches.</p>
{falling_block}
<h2>Under the Threshold</h2>
{low_block}
<h2>Steady</h2>
{flat_block}
<h2>Unreadable</h2>
{unreadable_block}
<h2>No Battery Reported</h2>
{absent_block}
<footer>A cell holds a level for most of its life and then falls, so
a steady reading is a healthy one rather than a stale one. Days left
is a projection and it moves: it assumes the last {BATTERY_SLOPE_DAYS}
days continue, which a failing cell often does not. Nothing on this
page raises an alert; the low threshold on the Low Battery
configuration screen is what does that. Written beside the daily
brief and on Regenerate Reports, and renders on a dashboard with a
Webpage card pointed at {REPORT_BATTERY_URL}. How to read this page:
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
