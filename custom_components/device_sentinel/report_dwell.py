# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_dwell.py, Version: 0.16.3 (2026-08-20)

"""The signal dwell chart and the signal cells of the telemetry.

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
from datetime import timedelta
from html import escape
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_VALUE,
    REPORT_SIGNAL_DWELL,
    REPORT_SIGNAL_DWELL_PREFIX,
    REPORT_SIGNAL_DWELL_URL,
    REPORT_WWW_DIR,
    SIGNAL_DAYS_KEEP,
    SIGNAL_GREEN_CEILING,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    SIGNAL_TRIM_PER_WEEK,
    WIKI_BASE_URL,
)


class DwellChartMixin:
    """The signal dwell chart and the signal cells of the telemetry."""

    def _dwell_chart_rows(
        self, window: int
    ) -> list[tuple[str, str, float]]:
        """Return (device_id, name, dwell) for the window, descending.

        Window 1 is yesterday's rolled percentage; larger windows are
        the mean of the last N rolled days, which reads smoothly while
        the anomaly section catches what a mean would hide. Devices at
        exactly zero are left out: the chart is the nonzero tail, and
        the header says how many sat at zero so the count is not lost.
        """
        rows: list[tuple[str, str, float]] = []
        for device_id, record in self.watched_records():
            # Both ladders apply. The signal-only list is this
            # surface's own release valve, and the global ladder
            # excludes the device from judgment and reporting
            # everywhere, which a chart and its anomaly table are
            # (fault found live 2026-08-02: two globally excluded
            # mobile_app devices charted, one as an anomaly).
            if self._signal_excluded(device_id):
                continue
            if device_id in self._excluded_devices:
                continue
            series = record.get(DEV_SIGNAL_DWELL_DAILY) or []
            if not series:
                continue
            tail = series[-window:]
            value = sum(tail) / len(tail)
            if value > 0:
                rows.append(
                    (device_id, self._device_name(device_id), value)
                )
        rows.sort(key=lambda row: -row[2])
        return rows

    def _dwell_zero_count(self) -> int:
        """Return how many recorded devices sat at exactly zero
        yesterday, for the chart header."""
        zeros = 0
        for device_id, record in self.watched_records():
            if self._signal_excluded(device_id) or (
                device_id in self._excluded_devices
            ):
                continue
            series = record.get(DEV_SIGNAL_DWELL_DAILY) or []
            if series and series[-1] == 0:
                zeros += 1
        return zeros

    def _dwell_anomalies(
        self, red: float
    ) -> list[dict[str, Any]]:
        """Return the devices above red plus the lift, described.

        Red is the cut: every device above the red threshold stays on
        the chart and is also pulled out here with everything known
        that helps build a picture: integration, area, the learned
        floor, the current reading, and how many consecutive days the
        dwell has exceeded the red threshold, which is the fact that
        separates a bad day from a bad device.
        """
        dev_reg = dr.async_get(self.hass)
        from homeassistant.helpers import area_registry as ar

        area_reg = ar.async_get(self.hass)
        out: list[dict[str, Any]] = []
        for device_id, name, value in self._dwell_chart_rows(1):
            if value <= red:
                continue
            record = self.data[DATA_DEVICES][device_id]
            series = record.get(DEV_SIGNAL_DWELL_DAILY) or []
            streak = 0
            for pct in reversed(series):
                if pct > red:
                    streak += 1
                else:
                    break
            device = dev_reg.async_get(device_id)
            area_name = ""
            if device and device.area_id:
                area = area_reg.async_get_area(device.area_id)
                area_name = area.name if area else device.area_id
            history = self._signal_history(record)
            floor = None
            if history:
                floor = sorted(history)[
                    self._signal_effective_k(len(history))
                ]
            # LQI runs positive, RSSI negative; a table mixing 176 and
            # -68 with no tag is unreadable to anyone who does not
            # know the fleet (ruling #176). The sign of the floor
            # is the type, and the floor exists for every device that
            # can be an anomaly, since without one there is no line to
            # dwell under.
            kind = ""
            if floor is not None:
                kind = "RSSI" if floor < 0 else "LQI"
            previous = series[-2] if len(series) >= 2 else None
            out.append(
                {
                    # Carried so the Signal: Problems sensor can name
                    # the device in an automation, and so the low kind
                    # can be checked against the signal exclusions
                    # (ruling #210).
                    "device_id": device_id,
                    "name": name,
                    "dwell": value,
                    "previous": previous,
                    "streak": streak,
                    "integration": self._watched.get(device_id, "?"),
                    "area": area_name or "Unassigned",
                    "floor": floor,
                    "kind": kind,
                    "value": record.get(DEV_SIGNAL_VALUE),
                    "mean": (record.get(DEV_SIGNAL_DAILY_MEAN) or [None])[
                        -1
                    ],
                    "sd": (record.get(DEV_SIGNAL_DAILY_SD) or [None])[-1],
                    "p5": (record.get(DEV_SIGNAL_DAILY_P5) or [None])[-1],
                    "p50": (record.get(DEV_SIGNAL_DAILY_P50) or [None])[-1],
                }
            )
        return out

    def _dwell_bar_svg(
        self, rows: list[tuple[str, str, float]], red: float
    ) -> str:
        """Return one section's chart as inline SVG, banded by color.

        Static SVG with no scripts, so the file renders in a browser,
        an email client, and a dashboard Webpage card alike. Green to
        the fixed ceiling, yellow to the red threshold, red above it;
        an anomaly (red plus the lift) keeps its red bar here and is
        described in its own section. Bars scale to the largest value
        or the red line plus ten, whichever is larger, so the
        threshold always sits inside the picture.
        """
        if not rows:
            return "<p class='empty'>Nothing above zero.</p>"
        top = max(max(v for _, _, v in rows), red + 10.0)
        # 13px bars on 4px gaps with 12px labels (revised 2026-08-02,
        # same day): the first cut to 12 on 3 with 11px labels went
        # too far and the text was hard to read. 17px per device is
        # still a 39 percent cut against the original 22 on 6.
        width, bar_h, gap, label_w = 640, 13, 4, 240
        chart_w = width - label_w - 60
        height = len(rows) * (bar_h + gap) + 30
        parts = [
            f"<svg viewBox='0 0 {width} {height}' width='100%' "
            f"role='img' aria-label='Dwell bars, one per device, "
            f"colored by band'>"
        ]
        red_x = label_w + chart_w * red / top
        green_x = label_w + chart_w * SIGNAL_GREEN_CEILING / top
        parts.append(
            f"<line x1='{green_x:.0f}' y1='0' x2='{green_x:.0f}' "
            f"y2='{height - 18}' stroke='#B4B2A9' "
            f"stroke-dasharray='3,3'/>"
            f"<line x1='{red_x:.0f}' y1='0' x2='{red_x:.0f}' "
            f"y2='{height - 18}' stroke='#D03B3B' "
            f"stroke-dasharray='3,3'/>"
            f"<text x='{red_x:.0f}' y='{height - 5}' fill='#D03B3B' "
            f"font-size='11' text-anchor='middle'>{red:.0f}%</text>"
        )
        y = 4
        for device_id, name, value in rows:
            if value <= SIGNAL_GREEN_CEILING:
                color = "#1D9E75"
            elif value <= red:
                color = "#EDA100"
            else:
                color = "#D03B3B"
            bar = max(2.0, chart_w * value / top)
            area = self._device_area(device_id)
            shown = f"{name} ({area})" if area else name
            if len(shown) > 36:
                shown = shown[:35] + "\u2026"
            # Escaped on the way into the page, like every other name
            # in every other report (ruling #231). A device name is
            # not always the reader's own words: MQTT discovery lets
            # a device advertise its own, so an angle bracket can
            # arrive from the network rather than the keyboard, and
            # this file is served to a dashboard.
            parts.append(
                f"<text x='{label_w - 8}' y='{y + 11}' class='lbl' "
                f"font-size='12' text-anchor='end'>{escape(shown)}</text>"
                f"<rect x='{label_w}' y='{y}' width='{bar:.0f}' "
                f"height='{bar_h}' rx='2' fill='{color}'/>"
                f"<text x='{label_w + bar + 6:.0f}' y='{y + 11}' "
                f"class='lbl' font-size='11'>{value:.1f}%</text>"
            )
            y += bar_h + gap
        parts.append("</svg>")
        return "".join(parts)

    def _write_signal_dwell_html(self) -> None:
        """Write the dwell chart to www for browsers and dashboards."""
        red = self._signal_red()
        rows_day = self._dwell_chart_rows(1)
        rows_week = self._dwell_chart_rows(7)
        rows_month = self._dwell_chart_rows(30)
        anomalies = self._dwell_anomalies(red)
        zeros = self._dwell_zero_count()
        written = dt_util.now().strftime("%B %d, %Y at %-I:%M %p")
        # The newest closed day, which is the day this page is about.
        # Dwell rolls at midnight, so the last figure in every series
        # is always the day before this write, whatever hour it runs
        # at. Every heading names its own days rather than saying
        # yesterday and leaving a reader to work out yesterday of
        # what (ruling #190).
        covered = dt_util.now().date() - timedelta(days=1)
        day_label = covered.strftime("%b %-d")
        week_label = (
            f"{(covered - timedelta(days=6)).strftime('%b %-d')} to "
            f"{day_label}"
        )
        month_label = (
            f"{(covered - timedelta(days=29)).strftime('%b %-d')} to "
            f"{day_label}"
        )

        anomaly_html = ""
        if anomalies:
            cells = []
            for a in anomalies:
                kind = f" {a['kind']}" if a["kind"] else ""
                floor = (
                    f"{a['floor']:.0f}{kind}"
                    if a["floor"] is not None
                    else "?"
                )
                value = f"{a['value']:.0f}" if a["value"] is not None else "?"
                mean = (
                    f"{a['mean']:.0f}\u00b1{a['sd']:.0f}"
                    if a["mean"] is not None and a["sd"] is not None
                    else "from tonight"
                )
                p5 = (
                    f"{a['p5']:.0f}" if a["p5"] is not None else "from tonight"
                )
                p50 = (
                    f"{a['p50']:.0f}"
                    if a["p50"] is not None
                    else "from tonight"
                )
                if a["previous"] is None:
                    trend = "first day"
                else:
                    arrow = (
                        "\u2191"
                        if a["dwell"] > a["previous"]
                        else "\u2193"
                        if a["dwell"] < a["previous"]
                        else "\u2192"
                    )
                    trend = f"{a['previous']:.1f}% {arrow}"
                cells.append(
                    f"<tr><td>{escape(str(a['name'] or ''))}</td>"
                    f"<td>{a['dwell']:.1f}%</td>"
                    f"<td>{trend}</td>"
                    f"<td>{a['streak']} day(s)</td>"
                    f"<td>{escape(str(a['integration'] or ''))}</td>"
                    f"<td>{escape(str(a['area'] or ''))}</td>"
                    f"<td>{floor}</td><td>{value}</td>"
                    f"<td>{p5}</td><td>{p50}</td>"
                    f"<td>{mean}</td></tr>"
                )
            anomaly_html = (
                "<h2>Anomalies</h2>"
                f"<p>Devices over the red threshold on {day_label}. "
                "PRIOR DAY is the day before against that day, so the "
                "arrow is the direction the link is moving. "
                "DAYS OVER RED is how many "
                "consecutive days the dwell has exceeded the red "
                "threshold: one is a bad day, a run is a bad link.</p>"
                "<table><tr><th>Device</th><th>Dwell</th>"
                "<th>Prior Day</th>"
                "<th>Days Over Red</th><th>Integration</th>"
                "<th>Area</th><th>Floor</th><th>Now</th>"
                "<th>P5</th><th>Median</th>"
                "<th>Mean\u00b1SD</th></tr>"
                + "".join(cells)
                + "</table>"
                + "<p class='legend'>"
                "<b>Dwell</b> is the share of the day the device spent "
                "below its own danger line. "
                "<b>Prior Day</b> is the day before, with an arrow for "
                "the direction. "
                "<b>Days Over Red</b> counts consecutive days above the "
                "red threshold. "
                "<b>Floor</b> is the learned baseline the danger line "
                "is built on, the worst level the link repeatably "
                "reaches. "
                "<b>Now</b> is the latest reading. "
                "<b>P5</b> is the level the link stayed above for 95 "
                "percent of the day, weighted by how long each value "
                "was held, so a single dropped packet does not set it. "
                "<b>Median</b> is the middle of the day on the same "
                "weighting. "
                "<b>Mean\u00b1SD</b> is the day's average and how far "
                "the readings spread around it, counted once per "
                "reading rather than by duration. "
                "A column reads <i>from tonight</i> where the series "
                "has no entry yet, which is every device on the first "
                "day after a change to what is recorded."
                "</p>"
            )

        html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Signal Dwell</title>
<style>
body {{ font-family: sans-serif; margin: 16px; background: #fff;
  color: #1a1a19; }}
h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 24px; }}
p, td, th {{ font-size: 13px; }} .lbl {{ fill: #1a1a19; }}
.empty {{ color: #5F5E5A; }}
table {{ border-collapse: collapse; }}
td, th {{ border: 1px solid #D3D1C7; padding: 4px 8px;
  text-align: left; }}
.legend span {{ display: inline-block; margin-right: 14px; }}
.swatch {{ display: inline-block; width: 11px; height: 11px;
  border-radius: 2px; margin-right: 4px; vertical-align: -1px; }}
footer {{ margin-top: 24px; font-size: 12px; color: #5F5E5A; }}
@media (min-width: 1000px) {{
  .charts {{ display: flex; gap: 24px; align-items: flex-start; }}
  .charts section {{ flex: 1; min-width: 0; }} }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #eee; }}
  .lbl {{ fill: #eee; }}
  td, th {{ border-color: #444; }}
  footer, .empty {{ color: #B4B2A9; }} }}
</style></head><body>
<h1>Signal Dwell</h1>
<p>Written {written}. The share of each day a device spent below
its line. {zeros} device(s) sat at exactly zero on
{day_label} and are not charted.</p>
<p class='legend'>
<span><span class='swatch' style='background:#1D9E75'></span>0 to
{SIGNAL_GREEN_CEILING:.0f}%: a healthy link brushing its line</span>
<span><span class='swatch' style='background:#EDA100'></span>to
{red:.0f}%: worth a glance</span>
<span><span class='swatch' style='background:#D03B3B'></span>over
{red:.0f}%: weak</span></p>
{anomaly_html}
<div class='charts'>
<section><h2>{day_label}</h2>
{self._dwell_bar_svg(rows_day, red)}</section>
<section><h2>7 Days, {week_label} (Mean)</h2>
{self._dwell_bar_svg(rows_week, red)}</section>
<section><h2>30 Days, {month_label} (Mean)</h2>
{self._dwell_bar_svg(rows_month, red)}</section>
</div>
<footer>The red threshold is the Red Threshold slider on the Signal
Strength configuration screen: Settings, Devices and Services, Device
Sentinel, Configure, Signal Strength. Green is fixed at
{SIGNAL_GREEN_CEILING:.0f}%. The 7 and 30 day spans are the windows
the means are taken over; a device with less history than the span
contributes the days it has. This page covers {day_label}, the most
recent day that has closed, and its dated copy is named for that day
rather than for the day it was written. It is written beside the
daily brief and on Regenerate Reports, and renders on a dashboard
with a Webpage card pointed at {REPORT_SIGNAL_DWELL_URL}. How to read
this page: <a href="{WIKI_BASE_URL}/The-Signal-Dwell-Chart">The
Signal Dwell Chart</a> on the Device Sentinel wiki.</footer>
</body></html>
"""
        directory = self.hass.config.path(REPORT_WWW_DIR)
        os.makedirs(directory, exist_ok=True)
        # Named for the day it describes, not the day it was
        # written, which is how the brief is named and was not how
        # this was. A chart written on the 3rd carries the 2nd's
        # dwell, so the file called signal_dwell_2026-08-02 held the
        # 1st, and two files with the same date meant different days
        # (ruling #190). There is therefore no dated chart for today
        # until tomorrow, which is correct: today's dwell has not
        # finished.
        stamp = covered.strftime("%Y-%m-%d")
        dated = os.path.join(
            directory, f"{REPORT_SIGNAL_DWELL_PREFIX}{stamp}.html"
        )
        self._write_file(dated, html)
        self._write_file(
            os.path.join(directory, REPORT_SIGNAL_DWELL),
            html,
        )
        self._trim_dated(directory, REPORT_SIGNAL_DWELL_PREFIX)

    def _floor_drift_cell(self, record: dict[str, Any]) -> str:
        """Return how fast this device's floor is moving, per week.

        The floor is what dwell is measured against, so a floor that
        moves makes dwell unreadable across days: a reading of ten
        percent last week and ten this week mean different things if
        the line moved between them. On the reference fleet forty-three
        of seventy-nine floors were moving a point a week or more and
        one was moving thirty-four, which is the whole reason dwell
        spiked and collapsed rather than trending (ruling #196).

        Per week rather than per day, because the floor is a trimmed
        minimum over thirty days and a daily figure would be mostly
        rounding. Points rather than percent, because neither LQI nor
        dBm is a percentage.
        """
        lows = [
            value
            for value in (record.get(DEV_SIGNAL_DAILY_MIN) or [])
            if value not in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        ]
        if len(lows) < SIGNAL_TRIM_PER_WEEK + 2:
            return "-"
        floors: list[float] = []
        for end in range(len(lows) - SIGNAL_TRIM_PER_WEEK, len(lows) + 1):
            window = lows[:end][-SIGNAL_DAYS_KEEP:]
            if not window:
                continue
            trim = self._signal_effective_k(len(window))
            floors.append(sorted(window)[min(trim, len(window) - 1)])
        if len(floors) < 3:
            return "-"
        weekly = self._battery_slope(floors) * SIGNAL_TRIM_PER_WEEK
        if abs(weekly) < 0.5:
            return f"{floors[-1]:g} flat"
        return f"{floors[-1]:g} {weekly:+.0f}/wk"

    def _format_signal_lows_cell(self, record: dict[str, Any]) -> str:
        """Render the daily signal lows newest-first with the marks.

        Three states, and a value is only ever one of them: the floor
        is bold, values strictly below the floor are struck through
        (the trimmed lows, set aside so a spurious bad reading does
        not define the line), and rail fill values are italic (seen
        and shown, but never fed to the floor).

        Two rules make repeated values read cleanly, settled after a
        flat button series showed one 48 bold, one struck, and two
        plain. The floor mark lands on the EARLIEST recorded
        occurrence of the floor value, so a reader sees when the
        device first reached its low. And a value equal to the floor
        is never struck: only values strictly below the floor are
        trimmed, so the same number is never both the line and an
        outlier. This can leave more than k values struck when the
        trimmed lows repeat, or fewer, which is correct: the marks now
        describe the values, not the positions the trim happened to
        pick.
        """
        # The column shows exactly the window the floor is computed
        # over, which is thirty days rather than the fortnight it was
        # (ruling #196). Showing fourteen while judging on thirty
        # would leave the marked value outside the cell on any device
        # whose worst days sit further back, so a reader would see
        # every reading struck and none marked.
        stored = list(record.get(DEV_SIGNAL_DAILY_MIN) or [])[
            -SIGNAL_DAYS_KEEP:
        ]
        if not stored:
            return "-"
        rails = (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        floor = self._danger_line(record)
        # The earliest (lowest stored index) occurrence of the floor
        # value is the one to bold, so its first appearance is marked.
        floor_index = None
        if floor is not None:
            for index, value in enumerate(stored):
                if value == floor:
                    floor_index = index
                    break
        parts = []
        for index in reversed(range(len(stored))):
            value = stored[index]
            text = f"{value:g}"
            if value in rails:
                parts.append(f"*{text}*")
            elif index == floor_index:
                parts.append(f"**{text}**")
            elif floor is not None and value < floor:
                # Strictly below the floor: a trimmed low. A value
                # equal to the floor is never struck.
                parts.append(f"~~{text}~~")
            else:
                parts.append(text)
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
