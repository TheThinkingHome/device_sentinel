# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_signal.py, Version: 0.16.16 (2026-08-22)

"""The signal report and the signal cells of the telemetry.

This replaces the dwell chart (ruling #310). Dwell asked whether a
device was sitting near its own floor, and the floor descends to
meet a degraded device, so a link that broke on 18 August read 68,
then 96, then 30 percent while its P5 sat flat at its new lower
level. Give that arrangement a week and a permanently broken link
reads its way back to healthy. The page now asks the question a
person can act on: did this device just get worse than it has been.

Still a file split rather than a boundary (ruling #199). These
methods are mixed into the coordinator and read its state freely,
so `self` is the coordinator throughout and nothing here stands
alone.
"""

from __future__ import annotations

import math
import os
from datetime import timedelta
from html import escape
from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_SCALE,
    REPORT_SIGNAL,
    REPORT_SIGNAL_PREFIX,
    REPORT_SIGNAL_URL,
    REPORT_WWW_DIR,
    SIGNAL_DAYS_KEEP,
    SIGNAL_TRIM_PER_WEEK,
    WIKI_BASE_URL,
)

# How many folded days the strip shows. Fourteen fits a phone screen
# at a readable cell width and is long enough that two normal weeks
# sit behind any single bad day.
STRIP_DAYS = 14

# Which devices earn a row (ruling #315). Tim Plas read the first
# version of this page and said there was no chance he would read it
# daily: 79 rows, 74 of them entirely green, with the answer buried
# under a chart nobody asked a question of. He wants to be pointed at
# issues rather than to interpret a picture, and he is right.
#
# So the strip shows the devices worth a look and names the rest in a
# line. A device earns its row when its worst day in the window fell
# this many of its own spreads below its normal. Three is where the
# reference fleet goes quiet: 22 devices qualify at two, 15 at three,
# 8 at four, and the colour runs out just past three.
#
# A constant rather than a setting. It shapes a page rather than a
# judgment, and the Signal screen carries four sliders already.
STRIP_WORTH_A_LOOK = 3.0
# Never fewer, so a quiet fleet still shows something to read a band
# against, and never more, so a broker outage that drops everything
# does not put the whole fleet back on the page.
STRIP_MIN_ROWS = 5
STRIP_MAX_ROWS = 20
# How many devices get a full biography. A bad day is rare by design,
# so this is a guard against a fleet-wide event producing a page
# nobody scrolls, not a routine limit.
BIOGRAPHY_MAX = 8

# The strip's shading, worst last. A cell is read in its own device's
# spreads, so a steady device and a jittery one are comparable.
STRIP_BANDS = (
    (1.0, "#7FA86B"),
    (2.0, "#B9C46A"),
    (3.0, "#E3C463"),
    (4.0, "#E09A4E"),
    (6.0, "#D8703C"),
)
STRIP_WORST = "#D03B3B"
STRIP_BLANK = "#E8E6DF"


class SignalReportMixin:
    """The signal report and the signal cells of the telemetry."""

    # ------------------------------------------------ reading the days

    def _signal_report_rows(self) -> list[dict[str, Any]]:
        """Return one row per device with enough history to judge.

        Sorted worst first, by the deepest fall anywhere in the
        strip, so the page opens on what matters and a reader who
        stops after four rows has seen the four that count.
        """
        registry = dr.async_get(self.hass)
        areas = ar.async_get(self.hass)
        rows: list[dict[str, Any]] = []
        for device_id, record in (self.data.get(DATA_DEVICES) or {}).items():
            series = record.get(DEV_SIGNAL_DAILY_P5) or []
            if not series:
                continue
            # Muting suppresses reporting, and this page is
            # reporting: a device muted globally or from signal
            # keeps recording and never renders here.
            if (
                self._signal_muted(device_id)
                or device_id in self._muted_devices
            ):
                continue
            entry = registry.async_get(device_id)
            if entry is None:
                continue
            span = min(STRIP_DAYS, len(series))
            readings = [
                self.signal_badday(record, len(series) - span + offset)
                for offset in range(span)
            ]
            scored = [r for r in readings if r is not None]
            if not scored:
                continue
            rows.append(
                {
                    "device_id": device_id,
                    "name": entry.name_by_user or entry.name or device_id,
                    "area": self._area_name(entry, areas),
                    "scale": record.get(DEV_SIGNAL_SCALE),
                    "series": series[-span:],
                    "reads": (record.get(DEV_SIGNAL_DAILY_COUNT) or [])[-span:],
                    "readings": readings,
                    "worst": max(r["deviations"] for r in scored),
                    "bad_days": sum(1 for r in scored if r["bad"]),
                }
            )
        rows.sort(key=lambda row: -row["worst"])
        return rows

    @staticmethod
    def _area_name(entry: Any, areas: Any) -> str:
        """Return the device's area, or an empty string.

        Shown beside every name (ruling #315). It can mislead, and
        that is not a reason to withhold it: the router unplugged on
        18 August took devices in five different rooms, because a
        router serves by radio topology rather than by the room it
        sits in. A person seeing that scatter repeatedly will work
        out what it means, and hiding a fact because it is not yet
        interpretable is how dwell came to measure against a line
        that moved.
        """
        if entry.area_id is None:
            return ""
        area = areas.async_get_area(entry.area_id)
        return area.name if area is not None else ""

    def _signal_strip_rows(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the devices worth a look, and how many are not.

        Ruling #315. The full fleet is still available behind a
        toggle, for the once-in-a-while troubleshooting a person
        actually opens this page for.
        """
        worth = [
            row for row in rows
            if row["worst"] >= STRIP_WORTH_A_LOOK
        ]
        if len(worth) < STRIP_MIN_ROWS:
            worth = rows[:STRIP_MIN_ROWS]
        if len(worth) > STRIP_MAX_ROWS:
            worth = worth[:STRIP_MAX_ROWS]
        return worth, len(rows) - len(worth)

    def _signal_baddays_today(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return the devices whose most recent judged day was bad."""
        out = []
        for row in rows:
            last = row["readings"][-1] if row["readings"] else None
            if last is not None and last["bad"]:
                out.append(row)
        return out

    def _signal_headline(self, hits: list[dict[str, Any]]) -> str:
        """Return the sentence the brief will one day carry.

        It lives here first on purpose. The wording is judged against
        real mornings on this page before it is allowed into the
        brief, which is the same order signal itself was introduced
        in (ruling #310).

        A cluster is the whole value. Four devices in one sentence
        with the shared-cause hint is the difference between four
        mysteries and one dead router, and on the reference fleet
        that is exactly what happened: an unplugged router took four
        devices, none of them in the room it sat in.
        """
        if not hits:
            return ""
        if len(hits) == 1:
            row = hits[0]
            last = row["readings"][-1]
            quiet = 0
            for reading in reversed(row["readings"][:-1]):
                if reading is not None and reading["bad"]:
                    break
                quiet += 1
            return (
                f"Signal fell sharply on {row['name']}, from "
                f"{last['baseline']:.0f} to {last['today']:.0f}, its "
                f"first bad day in {quiet}."
            )
        names = [row["name"] for row in hits]
        listed = ", ".join(names[:-1]) + " and " + names[-1]
        return (
            f"Signal fell sharply on {len(hits)} devices: {listed}. "
            "Devices failing together usually share a router."
        )

    # ---------------------------------------------------- the drawings

    @staticmethod
    def _strip_shade(reading: dict[str, Any] | None) -> str:
        """Return a cell's colour from its fall, in the device's own
        spreads."""
        if reading is None:
            return STRIP_BLANK
        for edge, colour in STRIP_BANDS:
            if reading["deviations"] < edge:
                return colour
        return STRIP_WORST

    def _signal_strip_svg(self, rows: list[dict[str, Any]]) -> str:
        """Return the fleet strip: every device a row, every day a cell.

        The chart exists for one shape. A vertical band of colour is
        devices failing on the same day, which is a shared cause; a
        single dark cell is one device. Nothing else on the page says
        that as fast, and no table says it at all.
        """
        if not rows:
            return ""
        span = max(len(row["readings"]) for row in rows)
        cell_w, cell_h, gap, left = 44, 13, 12, 214
        width = left + span * (cell_w + gap) + 10
        height = 26 + len(rows) * (cell_h + gap) + 8
        covered = dt_util.now().date() - timedelta(days=1)
        parts = [
            f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' "
            "aria-label='Every device one row, every folded day one cell, "
            "shaded by how far its signal fell below its own normal'>"
        ]
        for index in range(span):
            when = covered - timedelta(days=span - 1 - index)
            x = left + index * (cell_w + gap) + cell_w / 2
            parts.append(
                f"<text x='{x:.0f}' y='16' class='lbl' font-size='10' "
                f"text-anchor='middle'>{when.strftime('%b %-d')}</text>"
            )
        for order, row in enumerate(rows):
            y = 26 + order * (cell_h + gap)
            name = row["name"]
            shown = name if len(name) < 26 else f"{name[:24]}.."
            weight = " font-weight='700'" if row["bad_days"] else ""
            parts.append(
                f"<text x='{left - 6}' y='{y + cell_h - 3}' class='lbl' "
                f"font-size='10' text-anchor='end'{weight}>"
                f"{escape(shown)}</text>"
            )
            if row["area"]:
                parts.append(
                    f"<text x='{left - 6}' y='{y + cell_h + 7}' "
                    f"class='lbl area' font-size='8' text-anchor='end'>"
                    f"{escape(row['area'])}</text>"
                )
            pad = span - len(row["readings"])
            for index in range(span):
                reading = (
                    None
                    if index < pad
                    else row["readings"][index - pad]
                )
                x = left + index * (cell_w + gap)
                ring = (
                    " stroke='#1a1a19' stroke-width='1'"
                    if reading is not None and reading["bad"]
                    else ""
                )
                parts.append(
                    f"<rect x='{x}' y='{y}' width='{cell_w}' "
                    f"height='{cell_h}' rx='1' "
                    f"fill='{self._strip_shade(reading)}'{ring}/>"
                )
        parts.append("</svg>")
        return "".join(parts)

    def _signal_biography_svg(self, row: dict[str, Any]) -> str:
        """Return one device's history with the lines it is judged by.

        Two references are drawn rather than described: the baseline
        the device was holding, and the level a fall has to reach
        before the day counts. A reader can see how far past the line
        it went and whether it came back, which no number does.
        """
        values = [v for v in row["series"] if v is not None]
        if len(values) < 2:
            return ""
        span = len(row["series"])
        low, high = min(values), max(values)
        pad = max(4.0, (high - low) * 0.15)
        low, high = low - pad, high + pad
        width, height, left, top, bottom = 640, 152, 46, 12, 26

        def place_x(index: int) -> float:
            return left + index * (width - left - 8) / max(1, span - 1)

        def place_y(value: float) -> float:
            return top + (high - value) * (height - top - bottom) / (
                high - low
            )

        parts = [
            f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' "
            f"aria-label='{escape(row['name'])} signal over "
            f"{span} days'>"
        ]
        last = next(
            (r for r in reversed(row["readings"]) if r is not None), None
        )
        if last is not None:
            trigger = last["baseline"] - max(
                last["drop_gate"],
                self._badday_sensitivity() * last["spread"],
            )
            for value, colour, dash, words in (
                (last["baseline"], "#5F5E5A", "", "its normal"),
                (trigger, "#D03B3B", " stroke-dasharray='4 3'", "bad-day line"),
            ):
                if not low < value < high:
                    continue
                parts.append(
                    f"<line x1='{left}' y1='{place_y(value):.1f}' "
                    f"x2='{width - 8}' y2='{place_y(value):.1f}' "
                    f"stroke='{colour}' stroke-width='1'{dash}/>"
                )
                parts.append(
                    f"<text x='{width - 10}' y='{place_y(value) - 4:.1f}' "
                    f"class='lbl' font-size='9' text-anchor='end'>"
                    f"{words}</text>"
                )
        points = " ".join(
            f"{place_x(i):.1f},{place_y(v):.1f}"
            for i, v in enumerate(row["series"])
            if v is not None
        )
        parts.append(
            "<polyline fill='none' stroke='#2A78D6' stroke-width='2' "
            f"points='{points}'/>"
        )
        for index, value in enumerate(row["series"]):
            if value is None:
                continue
            reading = row["readings"][index]
            colour = (
                "#D03B3B"
                if reading is not None and reading["bad"]
                else "#2A78D6"
            )
            parts.append(
                f"<circle cx='{place_x(index):.1f}' "
                f"cy='{place_y(value):.1f}' r='3' fill='{colour}'/>"
            )
        for value in (low + pad, high - pad):
            parts.append(
                f"<text x='{left - 6}' y='{place_y(value) + 3:.1f}' "
                f"class='lbl' font-size='9' text-anchor='end'>"
                f"{value:.0f}</text>"
            )
        covered = dt_util.now().date() - timedelta(days=1)
        for index in (0, span // 2, span - 1):
            when = covered - timedelta(days=span - 1 - index)
            parts.append(
                f"<text x='{place_x(index):.0f}' y='{height - 8}' "
                f"class='lbl' font-size='9' text-anchor='middle'>"
                f"{when.strftime('%b %-d')}</text>"
            )
        parts.append("</svg>")
        return "".join(parts)

    # ------------------------------------------------------ the page

    def _write_signal_report_html(self) -> None:
        """Write the signal report to www for browsers and dashboards."""
        rows = self._signal_report_rows()
        worth, quiet = self._signal_strip_rows(rows)
        quiet_line = (
            f"<p class='empty'>{quiet} other device(s) stayed within "
            "their own normal and are not shown.</p>"
            if quiet
            else ""
        )
        hits = self._signal_baddays_today(rows)
        headline = self._signal_headline(hits)
        written = dt_util.now().strftime("%B %d, %Y at %-I:%M %p")
        # Named for the day it describes rather than the day it was
        # written, the same rule the brief and the old chart followed
        # (ruling #190): the last figure in every series is always the
        # day before this write, whatever hour it runs at.
        covered = dt_util.now().date() - timedelta(days=1)
        day_label = covered.strftime("%b %-d")

        if headline:
            lede = f"<p class='lede'>{escape(headline)}</p>"
        else:
            lede = (
                "<p class='empty'>No device had a bad signal day on "
                f"{day_label}. {len(rows)} device(s) judged; nothing "
                "here needs you.</p>"
            )

        biographies = []
        for row in rows[:BIOGRAPHY_MAX]:
            if not row["bad_days"]:
                continue
            worst_at = max(
                (i for i, r in enumerate(row["readings"]) if r is not None),
                key=lambda i: row["readings"][i]["deviations"],
            )
            worst = row["readings"][worst_at]
            when = covered - timedelta(
                days=len(row["readings"]) - 1 - worst_at
            )
            latest = next(
                (r for r in reversed(row["readings"]) if r is not None), None
            )
            back = (
                latest is not None
                and latest["fall"] < latest["drop_gate"]
            )
            reads = row["reads"]
            traffic = ""
            if worst_at > 0 and len(reads) > worst_at:
                before, during = reads[worst_at - 1], reads[worst_at]
                if before and during and during > before * 1.2:
                    traffic = (
                        f" Reporting went from {before:.0f} readings the day "
                        f"before to {during:.0f} on the day, which is the "
                        "link retrying."
                    )
            biographies.append(
                f"<h3>{escape(row['name'])}</h3>\n"
                f"<p>Worst day {when.strftime('%b %-d')}: signal fell from "
                f"{worst['baseline']:.0f} to {worst['today']:.0f}, "
                f"{worst['fall']:.0f} points and "
                f"{worst['deviations']:.0f} of its own spreads. "
                f"{'It has since come back.' if back else 'It has not come back.'}"
                f"{traffic}</p>\n"
                f"{self._signal_biography_svg(row)}"
            )
        biography_html = (
            "\n".join(biographies)
            if biographies
            else "<p class='empty'>No device has had a bad day in the "
            "recorded history.</p>"
        )

        html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Device Sentinel Signal Report</title>
<style>
body {{ font-family: sans-serif; margin: 16px; background: #fff;
  color: #1a1a19; max-width: 860px; }}
h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 28px; }}
h3 {{ font-size: 13px; margin: 18px 0 2px; }}
p, td, th {{ font-size: 13px; }} .lbl {{ fill: #1a1a19; }}
.empty {{ color: #5F5E5A; }}
.lede {{ background: #F5F3EC; border-left: 3px solid #D03B3B;
  padding: 8px 12px; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
td, th {{ border: 1px solid #D3D1C7; padding: 4px 8px;
  text-align: left; }}
.legend span {{ display: inline-block; margin-right: 14px;
  font-size: 12px; }}
.area {{ opacity: 0.6; }}
summary {{ font-size: 14px; cursor: pointer; margin-top: 8px; }}
.swatch {{ display: inline-block; width: 11px; height: 11px;
  border-radius: 2px; margin-right: 4px; vertical-align: -1px; }}
footer {{ margin-top: 28px; font-size: 12px; color: #5F5E5A; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #eee; }}
  .lbl {{ fill: #eee; }}
  .lede {{ background: #262624; }}
  td, th {{ border-color: #444; }}
  footer, .empty {{ color: #B4B2A9; }} }}
</style></head><body>
<h1>Device Sentinel Signal Report</h1>
<p>Written {written}. Covering {day_label}, the most recent day that
has closed. {len(rows)} device(s) have enough history to judge.</p>
<h2>{day_label}</h2>
{lede}
<h2>Devices Worth a Look</h2>
<p>One row per device, worst first, one cell per folded day. A cell is
shaded by how far that day's signal sat below the device's own normal,
measured in that device's own spread, so a steady link and a jittery
one are read on the same scale. A ringed cell is a bad signal day. The
shape to look for is a vertical band: devices falling on the same day
share a cause, which can mean one router rather than several devices.
The area beside each name is where the device sits, which is not
always where its router sits.</p>
<p class='legend'>
<span><span class='swatch' style='background:#7FA86B'></span>normal</span>
<span><span class='swatch' style='background:#E3C463'></span>2 to 3
spreads below</span>
<span><span class='swatch' style='background:#E09A4E'></span>3 to 4
below</span>
<span><span class='swatch' style='background:#D03B3B'></span>6 or more
below</span>
<span><span class='swatch' style='background:#E8E6DF'></span>not
judged</span></p>
{self._signal_strip_svg(worth)}
{quiet_line}
<details>
<summary>Show All {len(rows)} Devices</summary>
<p>The full fleet, worst first, for when you are chasing something
specific.</p>
{self._signal_strip_svg(rows)}
</details>
<h2>Devices That Had a Bad Day</h2>
{biography_html}
<footer>A bad signal day is a fall in a device's own time-weighted
fifth percentile, measured against the median of the days before it:
far enough in the device's own units, and far enough in its own
spread, both together. The four settings are on the Signal Strength
configuration screen: Settings, Devices and Services, Device Sentinel,
Configure, Signal Strength. Nothing on this page alerts or joins the
problem list. This page replaced the dwell chart, which measured
distance from a line that descends to meet a failing device, so a
broken link read its way back to healthy over a week. Its dated copy
is named for the day it covers rather than the day it was written. It
is written beside the daily brief and on Regenerate Reports, and
renders on a dashboard with a Webpage card pointed at
{REPORT_SIGNAL_URL}. How to read this page:
<a href="{WIKI_BASE_URL}/The-Signal-Report">The Signal Report</a> on
the Device Sentinel wiki.</footer>
</body></html>
"""
        directory = self.hass.config.path(REPORT_WWW_DIR)
        os.makedirs(directory, exist_ok=True)
        stamp = covered.strftime("%Y-%m-%d")
        dated = os.path.join(
            directory, f"{REPORT_SIGNAL_PREFIX}{stamp}.html"
        )
        self._write_file(dated, html)
        self._write_file(
            os.path.join(directory, REPORT_SIGNAL),
            html,
        )
        self._trim_dated(directory, REPORT_SIGNAL_PREFIX)

    def _floor_drift_cell(self, record: dict[str, Any]) -> str:
        """Return how fast this device's floor is moving, per week.

        The floor is the lowest daily P5 in the thirty-day window
        (rulings #322, #323), so the drift is the slope of that
        minimum recomputed as the window walks forward a day at a
        time over the last week. Per week rather than per day,
        because a daily figure would be mostly rounding. Points
        rather than percent, because neither LQI nor dBm is a
        percentage.
        """
        history = [
            value
            for value in (record.get(DEV_SIGNAL_DAILY_P5) or [])
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        if len(history) < SIGNAL_TRIM_PER_WEEK + 2:
            return "-"
        floors: list[float] = []
        for end in range(
            len(history) - SIGNAL_TRIM_PER_WEEK, len(history) + 1
        ):
            window = history[:end][-SIGNAL_DAYS_KEEP:]
            if window:
                floors.append(min(window))
        if len(floors) < 3:
            return "-"
        weekly = self._battery_slope(floors) * SIGNAL_TRIM_PER_WEEK
        if abs(weekly) < 0.5:
            return f"{floors[-1]:g} flat"
        return f"{floors[-1]:g} {weekly:+.0f}/wk"

    def _format_signal_lows_cell(self, record: dict[str, Any]) -> str:
        """Render the daily P5 series newest-first with the floor
        marked.

        The column shows exactly the window the floor is computed
        over (rulings #126, #322): each value is the day's
        time-weighted 5th percentile, a rail-only day's null shows
        as a dash, and the floor, the lowest value in the window, is
        bold at its earliest occurrence so a reader sees when the
        device first reached its low. Nothing is struck: the floor
        is the plain minimum (ruling #323), so no value sits below
        it.
        """
        stored = list(record.get(DEV_SIGNAL_DAILY_P5) or [])[
            -SIGNAL_DAYS_KEEP:
        ]
        if not stored:
            return "-"
        real = [
            value
            for value in stored
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        floor = min(real) if real else None
        floor_index = None
        if floor is not None:
            for index, value in enumerate(stored):
                if value == floor:
                    floor_index = index
                    break
        parts = []
        for index in reversed(range(len(stored))):
            value = stored[index]
            if value not in real:
                # A null from a rail-only day (ruling #305), or a
                # poisoned entry the hostile suite plants: the page
                # is written whatever a series holds.
                parts.append("-")
            elif index == floor_index:
                parts.append(f"**{value:g}**")
            else:
                parts.append(f"{value:g}")
        return " ".join(parts)

    @staticmethod
    def _format_signal_mean_cell(record: dict[str, Any]) -> str:
        """Return yesterday's mean and deviation, or a dash.

        These are the good-state statistics the Bayesian successor
        needs (ruling #172), shown so the numbers are visible while
        the
        method that will use them waits on the series maturing. One
        value per day; the newest is enough for a reference table,
        and the full series is in storage.
        """
        means = record.get(DEV_SIGNAL_DAILY_MEAN) or []
        deviations = record.get(DEV_SIGNAL_DAILY_SD) or []
        # The newest day that has statistics. A rail-only day writes
        # null into both series (ruling #305), and this cell read
        # [-1] unguarded: the second of two readers with that fault,
        # missed because the sweep that found the first was
        # truncated. The rail-day test now drives the whole report
        # pipeline over a null day so a further missed reader fails
        # in the suite rather than on a fleet.
        for index in range(len(means) - 1, -1, -1):
            if index < len(deviations) and means[
                index
            ] is not None and deviations[index] is not None:
                return (
                    f"{means[index]:g}\u00b1{deviations[index]:g}"
                )
        return "-"
