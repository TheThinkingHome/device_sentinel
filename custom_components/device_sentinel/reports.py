# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.11.1 (2026-08-03)

"""The report writers, split out of the coordinator for legibility.

This is a file split rather than a boundary, and saying so plainly
matters: the methods here read a great deal of coordinator state and
are mixed in rather than composed, so `self` is the coordinator and
nothing in this file can be instantiated or tested on its own. The
coordinator had grown past four thousand lines and the writers are a
fifth of it, cohesive and almost entirely read-only, so they were the
honest first cut.

What lives here is the text-producing half of the integration: the
shared formatters every report uses, the writers for all four report
files, and the orchestrator that calls them. It arrived in three
slices, each proven by regenerating the reports and comparing them
byte for byte against the previous version's output.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime, timedelta
from html import escape
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_UNACKNOWLEDGED,
    BATTERY_DAYS_URGENT,
    BATTERY_FALLING_SLOPE,
    BATTERY_READABLE_MAX,
    BATTERY_SLOPE_DAYS,
    BRIEF_KEEP_DAYS,
    BRIEF_LIVE_WINDOW_SECONDS,
    BRIEF_TRIGGER,
    CONF_REMINDER_TIME,
    CONF_TAINT_FLOOR,
    CONF_TAINT_SHARE,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEFAULT_REMINDER_TIME,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEFAULT_TAINT_SHARE_PCT,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_VALUE,
    EPISODE_KEEP_DAYS,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_TAINT_SECONDS,
    EP_WINDOW,
    INCIDENT_ACKNOWLEDGED,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    LEARNING_MIN_DAYS,
    LOGGER,
    REPORT_BATTERY_HTML,
    REPORT_BATTERY_PREFIX,
    REPORT_BATTERY_URL,
    REPORT_BRIEF_HTML,
    REPORT_BRIEF_PREFIX,
    REPORT_CLASSIFICATION,
    REPORT_DIAGNOSTIC_DIR,
    REPORT_DIR,
    REPORT_EPISODES,
    REPORT_SIGNAL_DWELL,
    REPORT_SIGNAL_DWELL_PREFIX,
    REPORT_SIGNAL_DWELL_URL,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
    REPORT_WWW_DIR,
    SIGNAL_ARMING_DAYS,
    SIGNAL_GREEN_CEILING,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_WINDOW_SECONDS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_EPOCH_RESET,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_SCOPE_SYSTEM,
    SYS_UNCLEAN_RESTART,
    SYS_WHEN,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_KIND_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
    TODO_KIND_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_SORT_NAME,
    TODO_STATUS,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)


class ReportWritingMixin:
    """Text production for the coordinator.

    Mixed into DeviceSentinelCoordinator, so every attribute these
    methods reach for belongs to that class. Splitting them out
    changes nothing about how they run; it only puts them where they
    can be read.
    """

    @staticmethod
    def _format_report_time(when: datetime) -> str:
        """Return a local time a person reads at a glance, like
        'July 21, 2026 at 7:19 AM'. Built without strftime's platform
        specific %-d and %-I so it is the same on every host: the
        month name and AM/PM come from strftime, the day and hour are
        integers so they carry no leading zero.
        """
        month = when.strftime("%B")
        hour_24 = when.hour
        hour_12 = hour_24 % 12 or 12
        meridiem = "AM" if hour_24 < 12 else "PM"
        return (
            f"{month} {when.day}, {when.year} at "
            f"{hour_12}:{when.minute:02d} {meridiem}"
        )

    @staticmethod
    def _report_cell(text: str) -> str:
        """Return text safe for a Markdown table cell or report line.

        Device names are user-controlled: a pipe in a name would
        split its table row and a newline would break it entirely.
        Escaping here, at the single choke point every name passes on
        its way into a report, keeps the files intact whatever a
        device is called. Cosmetic hardening, not a security fix; the
        reports are local files.
        """
        return (
            text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
        )

    def _fmt_gap(self, seconds: Any) -> str:
        """Format a gap for the report."""
        if seconds is None:
            return "-"
        if seconds >= 3600:
            return f"{seconds / 3600:.2f}h"
        return f"{seconds:.0f}s"

    # ------------------------------------------------------ freeze margin

    @staticmethod
    def _human_span(seconds: float | None) -> str:
        """Return a duration in the units a person thinks in."""
        if seconds is None:
            return "?"
        seconds = max(0.0, seconds)
        if seconds >= 86400:
            return f"{seconds / 86400:.1f}d"
        if seconds >= 3600:
            return f"{seconds / 3600:.1f}h"
        if seconds >= 60:
            return f"{seconds / 60:.0f}m"
        return f"{seconds:.0f}s"

    @staticmethod
    def _episode_duration(seconds: float | None) -> str:
        """Return a duration in the report's mixed units."""
        if seconds is None:
            return ""
        seconds = max(0.0, seconds)
        if seconds >= 3600:
            return f"{seconds / 3600:.2f}h"
        if seconds >= 60:
            return f"{seconds / 60:.0f}m"
        return f"{seconds:.0f}s"

    def _episode_stamp(self, epoch: float | None) -> str:
        """Return a local timestamp for an episode column."""
        if epoch is None:
            return ""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %d %H:%M")

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
        for device_id, record in self.data[DATA_DEVICES].items():
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

    def _device_area(self, device_id: str) -> str:
        """Return the device's area name, or an empty string.

        The chart labels carry the room (ruling #176) because the
        pattern that pays for the whole page is several weak links
        clustering in one room, and a reader should see that in the
        bars themselves rather than only in the anomaly table.
        """
        from homeassistant.helpers import area_registry as ar

        device = dr.async_get(self.hass).async_get(device_id)
        if not device or not device.area_id:
            return ""
        area = ar.async_get(self.hass).async_get_area(device.area_id)
        return area.name if area else ""

    def _dwell_zero_count(self) -> int:
        """Return how many recorded devices sat at exactly zero
        yesterday, for the chart header."""
        zeros = 0
        for device_id, record in self.data[DATA_DEVICES].items():
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
            parts.append(
                f"<text x='{label_w - 8}' y='{y + 11}' class='lbl' "
                f"font-size='12' text-anchor='end'>{shown}</text>"
                f"<rect x='{label_w}' y='{y}' width='{bar:.0f}' "
                f"height='{bar_h}' rx='2' fill='{color}'/>"
                f"<text x='{label_w + bar + 6:.0f}' y='{y + 11}' "
                f"class='lbl' font-size='11'>{value:.1f}%</text>"
            )
            y += bar_h + gap
        parts.append("</svg>")
        return "".join(parts)

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
                absent.append({"name": name})
                continue
            row = {
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
        width, bar_w, gap, floor_y = 640, 50, 14, 150
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
            f"<text x='{width - 20}' y='{floor_y + 14}' class='lbl' "
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
                            "<th>RATE</th><th>DAYS LEFT</th></tr>"]
            for row in groups["falling"]:
                urgent = row["days"] <= BATTERY_DAYS_URGENT
                cell = (
                    f"<td style='color:#D03B3B'>{row['days']:.0f}</td>"
                    if urgent
                    else f"<td>{row['days']:.0f}</td>"
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
days; days left is the current level divided by it.</p>
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
Webpage card pointed at {REPORT_BATTERY_URL}.</footer>
</body></html>
"""
        directory = self.hass.config.path(REPORT_WWW_DIR)
        os.makedirs(directory, exist_ok=True)
        # Named for the day it was written, which under #190 is also
        # the day it covers: its headline figures are the levels now
        # rather than a day that has closed.
        stamp = dt_util.now().strftime("%Y-%m-%d")
        with open(
            os.path.join(directory, f"{REPORT_BATTERY_PREFIX}{stamp}.html"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(html)
        with open(
            os.path.join(directory, REPORT_BATTERY_HTML),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(html)
        self._trim_dated(directory, REPORT_BATTERY_PREFIX)

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
                    f"<tr><td>{a['name']}</td>"
                    f"<td>{a['dwell']:.1f}%</td>"
                    f"<td>{trend}</td>"
                    f"<td>{a['streak']} day(s)</td>"
                    f"<td>{a['integration']}</td>"
                    f"<td>{a['area']}</td>"
                    f"<td>{floor}</td><td>{value}</td>"
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
                "<th>Mean\u00b1SD</th></tr>"
                + "".join(cells)
                + "</table>"
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
<p>Written {written}. The share of each day a device spent at or
below its line. {zeros} device(s) sat at exactly zero on
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
with a Webpage card pointed at {REPORT_SIGNAL_DWELL_URL}.</footer>
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
        with open(dated, "w", encoding="utf-8") as handle:
            handle.write(html)
        with open(
            os.path.join(directory, REPORT_SIGNAL_DWELL),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(html)
        self._trim_dated(directory, REPORT_SIGNAL_DWELL_PREFIX)

    def _write_episodes(self, report_directory: str, trigger: str) -> None:
        """Write the silence-episode report.

        The forensic file, which explains freeze verdicts and decides
        nothing (ruling #103). One row per episode, newest first,
        recording what the other two reports cannot: whether a long
        silence ended because the device chose to speak or because
        something made it speak. That distinction is the difference
        between a rhythm the statistics should learn and a wedge no
        amount of patience would have fixed, and it is invisible in
        any per-device summary because a device produces one episode
        per occurrence, not one number.
        """
        episodes = list(self.data.get(DATA_EPISODES) or [])
        episodes.sort(key=lambda row: row[EP_SINCE], reverse=True)
        now = dt_util.utcnow().timestamp()
        open_count = sum(1 for row in episodes if row[EP_ENDED] is None)
        lines = [
            f"# Device Sentinel v{self.version} Silence Episodes",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            "",
            "One row per episode: a device whose silence passed its "
            "own learned basis. Devices reporting within their rhythm "
            "never appear. An episode closes when the device reports "
            "again (resumed) or when something intervened (a reboot, "
            "a bridge reconnect), which truncates the silence at a "
            "lower bound. LAG is how long after an intervention the "
            "device took to speak: seconds means the intervention "
            "revived it, hours means it was never stuck. LEARNED says "
            "whether the completed gap reached the statistics, and "
            "why not when it did not. UNAVAIL is how long the device read unavailable when a taint excluded the gap, recorded so the debounce can be tuned from real spread rather than a guess. Kept "
            f"{EPISODE_KEEP_DAYS} days; {len(episodes)} episode(s), "
            f"{open_count} still open.",
            "",
        ]
        if not episodes:
            lines += [
                "No device has been silent past its own rhythm since "
                "this record began.",
                "",
            ]
        else:
            lines += [
                "| SILENT SINCE | DEVICE | BASIS | WINDOW | SILENCE | "
                "ENDED | AT | LAG | LEARNED | UNAVAIL |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ]
            for row in episodes:
                end_epoch = row[EP_AT]
                silence = (
                    (end_epoch - row[EP_SINCE])
                    if end_epoch is not None
                    else (now - row[EP_SINCE])
                )
                lines.append(
                    f"| {self._episode_stamp(row[EP_SINCE])} "
                    f"| {self._report_cell(row[EP_NAME] or row[EP_DEVICE_ID])} "
                    f"| {self._episode_duration(row[EP_BASIS])} "
                    f"| {self._episode_duration(row[EP_WINDOW])} "
                    f"| {self._episode_duration(silence)} "
                    f"| {row[EP_ENDED] or 'open'} "
                    f"| {self._episode_stamp(end_epoch)} "
                    f"| {self._episode_duration(row[EP_LAG])} "
                    f"| {row[EP_LEARNED] or ''} "
                    f"| {self._episode_duration(row.get(EP_TAINT_SECONDS))} |"
                )
            lines.append("")
        path = os.path.join(report_directory, REPORT_EPISODES)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

    def _device_status(self, device_id: str) -> str:
        """Return a device's exclusion status for the report column.

        Two states, one grammar: "Reported" when nothing excludes it,
        or "Excluded (...)" naming why. GLB is the global exclude,
        shown alone because it covers everything and a globally
        excluded device is never offered to the section lists. BAT,
        SIG, and FRZ are the section excludes, listed in column order
        when more than one applies.

        A todo icon lived here for one release and moved to the
        Reporting Devices section: the same state shown twice was
        redundant and confusing, and that section is where a fault's
        whole story reads, list state included.
        """
        if device_id in self._excluded_devices:
            return "Excluded (GLB)"
        tags = []
        if self._battery_excluded(device_id):
            tags.append("BAT")
        if self._signal_excluded(device_id):
            tags.append("SIG")
        if self._freeze_excluded(device_id):
            tags.append("FRZ")
        if tags:
            return f"Excluded ({', '.join(tags)})"
        return "Reported"

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
        # The series holds ninety days; this column shows the same
        # fortnight it always has, so the report is unchanged by the
        # longer retention setting.
        stored = list(record.get(DEV_SIGNAL_DAILY_MIN) or [])[
            -DAILY_MAX_KEEP:
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


    def _format_maxima_cell(self, daily_maximum_gaps: list[float]) -> str:
        """Render the maxima list newest-first with the trim visible.

        Set-aside outliers are struck through (excluded from the
        window basis); the operative rhythm is bold. They can never
        be the same value styled twice, because the operative rhythm
        is by definition chosen after the outliers are removed.
        """
        # The series holds up to a year; this cell shows the same
        # fortnight it always has, and the indices below are into
        # that fortnight.
        daily_maximum_gaps = list(daily_maximum_gaps)[-DAILY_MAX_KEEP:]
        if not daily_maximum_gaps:
            return "-"
        operative, set_aside_indices = self._trimmed_maximum(
            daily_maximum_gaps
        )
        # Bold exactly one survivor equal to the operative rhythm.
        operative_index = None
        for index, gap in enumerate(daily_maximum_gaps):
            if index not in set_aside_indices and gap == operative:
                operative_index = index
                break
        parts = []
        # Storage appends oldest-to-newest; display newest first.
        for index in reversed(range(len(daily_maximum_gaps))):
            text = self._fmt_gap(daily_maximum_gaps[index])
            if index in set_aside_indices:
                parts.append(f"~~{text}~~")
            elif index == operative_index:
                parts.append(f"**{text}**")
            else:
                parts.append(text)
        return ", ".join(parts)

    def _reporting_lines(self) -> list[str]:
        """Return the telemetry report's Reporting Devices section.

        Every device with a fault, grouped by family (freeze, then
        battery, then signal) and alphabetical within each group, so
        the whole trouble picture reads in one place. This is
        diagnostics, not notification: an acknowledged item is shown
        here, tagged acknowledged, because the checkbox silences the
        phone, never the record of what is wrong. A device in two
        families appears in both, each line carrying that family's
        own age. The header count is distinct devices, so it can be
        smaller than the number of lines.

        Age source per family: freeze from its frozen-since, battery
        from its below-threshold-since, signal from when the sync
        listed it (a rail has no stored start of its own).
        """
        now = dt_util.utcnow().timestamp()
        as_of = self._format_report_time(dt_util.now())

        def _elapsed(seconds: float | None) -> str:
            if seconds is None:
                return "?"
            # Clamped: a since ahead of the clock (an NTP correction
            # after an offline boot) must not print a negative age.
            seconds = max(0.0, seconds)
            if seconds >= 3600:
                return f"{seconds / 3600:.1f}h"
            return f"{seconds / 60:.0f}m"

        def _age_from_epoch(since: float | None) -> str:
            return _elapsed(now - since if since is not None else None)

        def _age_from_iso(since: str | None) -> str:
            if not since:
                return "?"
            parsed = dt_util.parse_datetime(since)
            return _elapsed(now - parsed.timestamp() if parsed else None)

        freeze_lines: list[str] = []
        for row in sorted(
            self.frozen_devices_list, key=lambda r: r["name"].lower()
        ):
            tag = self._todo_tag_of(row["device_id"])
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            freeze_lines.append(
                f"- **{shown_name}** ({row['category']}) for "
                f"{_age_from_epoch(row.get('since'))} {tag}"
            )

        battery_lines: list[str] = []
        for row in sorted(
            self.battery_low_list, key=lambda r: r["name"].lower()
        ):
            level = row.get("level")
            if isinstance(level, (int, float)):
                shown = (
                    f"{int(level)}%"
                    if float(level).is_integer()
                    else f"{level}%"
                )
            else:
                shown = "low"
            tag = self._todo_tag_of(row["device_id"])
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            battery_lines.append(
                f"- **{shown_name}** ({shown}) for "
                f"{_age_from_iso(row.get('since'))} {tag}"
            )

        signal_lines: list[str] = []
        for row in sorted(
            self.signal_problem_list,
            key=lambda r: (r["name"] or "").lower(),
        ):
            tag = self._todo_tag_of(row["device_id"])
            age = _age_from_epoch(
                self._todo_signal_since(row["device_id"])
            )
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            signal_lines.append(
                f"- **{shown_name}** ({row['kind']}) for {age} {tag}"
            )

        count = len(self._problem_device_ids())
        if count == 0:
            return [
                "## Reporting Devices (0)",
                "",
                f"As of {as_of}, nothing is frozen, unavailable, "
                f"unknown, low on battery, or railed.",
                "",
            ]
        out = [
            f"## Reporting Devices ({count})",
            "",
            f"As of {as_of}. Every device with a fault, grouped by "
            f"family. A duration is how long the fault had lasted "
            f"when this was written. The tag is the problem list "
            f"state: open, acknowledged (silenced from notifications, "
            f"still shown here), or removed from the list by hand "
            f"while the fault persists.",
            "",
        ]
        if freeze_lines:
            out += ["### Freeze", "", *freeze_lines, ""]
        if battery_lines:
            out += ["### Battery", "", *battery_lines, ""]
        if signal_lines:
            out += ["### Signal", "", *signal_lines, ""]
        return out

    def _write_telemetry(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write device_telemetry.md, the learned-rhythms table.

        The triage view for a doubted detection: each device's full
        daily-maxima history (newest first), the trimmed-maximum
        preview of its window basis, its clock source, and the
        tunables in effect, so the tuning knobs get set against real
        numbers. The trim shown here is display-only during the soak;
        the detection engine adopts the same rule at Step 4.
        """
        dev_reg = dr.async_get(self.hass)
        sample_note = (
            f"k={TRIM_TOP_K} once a device has {TRIM_MIN_SAMPLES} "
            f"daily maxima; below that nothing is trimmed and the "
            f"window basis is the plain maximum (too few samples to "
            f"tell an outlier from the rhythm)."
        )
        lines = [
            f"# Device Sentinel v{self.version} Learned Statistics",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            "",
            f"All series read newest first. SIGNAL is each device's "
            f"daily signal minima; the floor (the line dwell is "
            f"measured against) is **bold**, the trimmed lowest "
            f"readings are ~~struck~~, and rail fill values 255/-128 "
            f"are *italic* (shown but never fed to the floor). A "
            f"warning sign at the front of the cell marks a device "
            f"whose daily low has sat at a rail for three days: a "
            f"stuck reading that shows as perfect signal and is the "
            f"opposite, a near-certain fault worth a power cycle or a "
            f"re-bind. The trim grows with the soak (none under "
            f"{SIGNAL_ARMING_DAYS} days, drop 1 lowest at "
            f"{SIGNAL_ARMING_DAYS}, drop 2 at {2 * SIGNAL_ARMING_DAYS}), "
            f"shifted by the anomaly trim word in the header (None "
            f"trims no lows so the floor sits lower and flags less, "
            f"Deepest the reverse), applied to readings going "
            f"forward only. DWELL% is the share of each day spent at "
            f"or below the line, which sits a sensitivity margin above "
            f"the floor: healthy devices brushing their floor "
            f"read 0-5 percent, which proves the line has teeth; "
            f"sustained dwell is the anomaly, and outliers clustered "
            f"in one room mean that room needs a router. BAT LEVEL is "
            f"the daily battery level, with any reading at or below "
            f"the low threshold **bold**. excl means signal-excluded: "
            f"still recorded, not judged.",
            "",
            "STATUS is Reported (judged for everything) or Excluded "
            "with the reason in parentheses: GLB global (all judgment "
            "off), BAT battery, SIG signal, FRZ freeze. GLB shows "
            "alone; the section reasons combine, Excluded (BAT, FRZ). "
            "An excluded device keeps recording; exclusion suppresses "
            "judgment, not observation.",
            "",
            f"Rule: the window basis is the **trimmed maximum** of "
            f"the rolling daily maxima: the top {TRIM_TOP_K} value(s) "
            f"are ~~set aside~~ as suspected anomalies and the basis "
            f"is the max of the survivors. {sample_note}",
            "",
            f"Tunables: grace {STARTUP_GRACE_SECONDS} s, storm "
            f"{STORM_DEVICE_THRESHOLD} devices/"
            f"{STORM_WINDOW_SECONDS:g} s (exempt at "
            f"{STORM_EXEMPT_PER_HOUR}/h), taint debounce "
            f"{self.entry.options.get(CONF_TAINT_FLOOR, DEFAULT_TAINT_FLOOR_MINUTES)}"
            f" min + {self.entry.options.get(CONF_TAINT_SHARE, DEFAULT_TAINT_SHARE_PCT)}"
            f"% of window, arming floor "
            f"{LEARNING_MIN_DAYS} days, judge on {DAILY_MAX_KEEP} "
            f"days, keep {self.retention_days} days.",
            "",
        ]
        lines.extend(self._reporting_lines())
        lines += [
            "## Learned Statistics",
            "",
            f"| DEVICE (INTEGRATION) | STATUS | GAPS (K={TRIM_TOP_K}) | "
            f"CLOCK | EVENTS | SIGNAL ({self._signal_trim_label()}) | "
            f"DWELL% | MEAN\u00b1SD | "
            f"BAT LEVEL (floor {self.low_threshold:g}%) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        rows = []
        for device_id, record in self.data[DATA_DEVICES].items():
            device = dev_reg.async_get(device_id)
            device_name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            integration = self._watched.get(device_id, "?")
            device_label = f"{self._report_cell(device_name)} ({integration})"
            daily_maximum_gaps = record.get(DEV_DAILY_MAX) or []
            operative, _ = self._trimmed_maximum(daily_maximum_gaps)
            rows.append(
                (
                    device_label,
                    self._device_status(device_id),
                    self._format_maxima_cell(daily_maximum_gaps),
                    "seen"
                    if device_id in self._last_seen_entity
                    else "clock",
                    int(record.get(DEV_EVENT_COUNT, 0)),
                    self._format_signal_lows_cell(record),
                    list(record.get(DEV_SIGNAL_DWELL_DAILY) or [])[
                        -DAILY_MAX_KEEP:
                    ],
                    self._format_signal_mean_cell(record),
                    self._format_battery_cell(record),
                    self.signal_railed(record),
                    self._signal_excluded(device_id),
                )
            )
        # Alphabetical by the device label, case-insensitive: the table
        # is a reference chart a person scans by name, so strict
        # alphabetical is what they expect (the descending-gap order
        # that suited the soak is gone; the Reporting Devices section
        # above already surfaces what is in trouble).
        rows.sort(key=lambda row: row[0].lower())
        for (
            device_label,
            status,
            maxima_cell,
            clock_source,
            event_count,
            lows_cell,
            dwell_daily,
            mean_cell,
            battery_cell,
            railed,
            sig_excluded,
        ) in rows:
            dwell_text = (
                " ".join(f"{pct:g}" for pct in reversed(dwell_daily))
                if dwell_daily
                else "-"
            )
            # A confirmed rail (daily low at the fill value for three
            # days) is marked in the signal cell itself, not a column:
            # a warning sign ahead of the lows so it reads at a glance.
            signal_cell = f"\u26a0\ufe0f {lows_cell}" if railed else lows_cell
            if sig_excluded:
                # Excluded devices keep recording (their lows still
                # show) but are not judged: no dwell, no rail mark.
                dwell_text = "excl"
                signal_cell = lows_cell
            lines.append(
                f"| {device_label} | {status} | "
                f"{maxima_cell} | "
                f"{clock_source} | {event_count} | {signal_cell} | "
                f"{dwell_text} | {mean_cell} | {battery_cell} |"
            )
        lines.append("")
        lines.append(f"{len(rows)} watched devices.")
        path = os.path.join(report_directory, REPORT_TELEMETRY)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.debug("Telemetry report written to %s", path)

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
        if not means or not deviations:
            return "-"
        return f"{means[-1]:g}\u00b1{deviations[-1]:g}"

    def _write_classification(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write classification.md, the audit view.

        One row per device, so a device's whole standing reads across
        a single line: whether it is Watched (has hardware, recording)
        or Set aside (a service device with nothing to watch), and, for
        a watched device, whether the global exclude has it and why.
        Every device is watched and recorded; exclusion only suppresses
        judgment and reporting, so an excluded device still carries a
        Watched check, with the reason alongside it. COPIES flags a
        name shared by more than one registry device. Section excludes
        (battery, signal, freeze) are not shown here; they live in the
        telemetry STATUS column, because a section-excluded device is
        still judged for everything else and is not excluded wholesale.
        """
        dev_reg = dr.async_get(self.hass)

        name_copy_counts: dict[str, int] = {}
        for device_id, integration_domain in self._watched.items():
            device = dev_reg.async_get(device_id)
            name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            name_copy_counts[name] = name_copy_counts.get(name, 0) + 1

        # Build one row per device, watched and set-aside together, so
        # the table reads as a single audit.
        rows: list[tuple[str, str, str, str, str, str]] = []
        for device_id, integration_domain in self._watched.items():
            device = dev_reg.async_get(device_id)
            name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            reason = self._excluded_devices.get(device_id)
            excluded_cell = f"Global ({reason})" if reason else ""
            copies = name_copy_counts.get(name, 1)
            rows.append(
                (
                    name,
                    integration_domain,
                    "yes",  # watched
                    excluded_cell,
                    "",  # set aside
                    str(copies) if copies > 1 else "",
                )
            )
        for name, integration_domain in self._set_aside.values():
            rows.append(
                (name, integration_domain, "", "", "yes", "")
            )
        rows.sort(key=lambda row: row[0].lower())

        total = len(self._watched) + len(self._set_aside)
        lines = [
            f"# Device Sentinel v{self.version} Classification",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            "",
            f"One row per device. Watching {len(self._watched)} of "
            f"{total}; {len(self._set_aside)} set aside (service "
            f"devices with no hardware to watch); {self.deviceless_count} "
            f"deviceless entities visible only at entity level. Every "
            f"device is watched and recorded; EXCLUDED only suppresses "
            f"judgment and reporting, and names why. COPIES above 1 is a "
            f"name shared by more than one registry device (a "
            f"network-tracker ghost or a multi-homed double).",
            "",
            "| DEVICE | INTEGRATION | WATCHED | EXCLUDED | SET ASIDE | "
            "COPIES |",
            "|---|---|---|---|---|---|",
        ]
        for name, integration, watched, excluded, set_aside, copies in rows:
            watched_mark = "\u2713" if watched else ""
            set_aside_mark = "\u2713" if set_aside else ""
            lines.append(
                f"| {self._report_cell(name)} | {integration} | "
                f"{watched_mark} | "
                f"{excluded} | {set_aside_mark} | {copies} |"
            )

        if self._excluded_entities:
            lines.append("")
            lines.append(
                f"## Excluded Entities ({len(self._excluded_entities)})"
            )
            lines.append("")
            lines.append(
                "Individual entities excluded from judgment. An "
                "excluded entity still vouches for its device."
            )
            lines.append("")
            lines.append("| ENTITY | REASON |")
            lines.append("|---|---|")
            for entity_id, reason in sorted(
                self._excluded_entities.items()
            ):
                lines.append(f"| {entity_id} | {reason} |")

        path = os.path.join(report_directory, REPORT_CLASSIFICATION)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.debug("Classification report written to %s", path)

    @staticmethod
    def _brief_moment(epoch: float) -> str:
        """Return a readable local time for the brief."""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %-d, %-I:%M %p")

    def _brief_hour_minute(self) -> tuple[int, int]:
        """Return the configured brief time, as hour and minute."""
        raw = str(
            self.entry.options.get(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME)
        )
        try:
            hour, minute = (int(part) for part in raw.split(":")[:2])
        except ValueError:
            return 8, 0
        return hour, minute

    def _brief_close_bounds(self) -> tuple[float, float]:
        """Return the window that closes at this brief hour.

        The scheduled write finishes the day that just ended rather
        than opening the one just starting, so the completed brief
        covers brief hour to brief hour and is named for the day it
        began. Computed from the configured time rather than from the
        clock, so a callback firing a moment early still closes the
        window it was meant to close.
        """
        local_now = dt_util.now()
        hour, minute = self._brief_hour_minute()
        end_local = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if end_local > local_now:
            end_local -= timedelta(days=1)
        previous = end_local.date() - timedelta(days=1)
        start_local = end_local.replace(
            year=previous.year, month=previous.month, day=previous.day
        )
        return start_local.timestamp(), end_local.timestamp()

    def _brief_window_start(self, now: float) -> float:
        """Return the start of the current brief window.

        The most recent brief hour at or before now, so the window
        always runs brief-to-brief rather than by calendar day: an
        overnight problem stays in one report instead of being split
        across two. A user who wants calendar days sets the brief
        time to midnight.
        """
        local_now = dt_util.as_local(dt_util.utc_from_timestamp(now))
        hour, minute = self._brief_hour_minute()
        candidate = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate > local_now:
            candidate -= timedelta(days=1)
        return candidate.timestamp()

    def _brief_battery_text(self, device_id: str) -> str:
        """Return the battery cell with its level where known."""
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        if isinstance(level, (int, float)):
            shown = (
                f"{int(level)}%"
                if float(level).is_integer()
                else f"{level}%"
            )
            return f"battery {shown}"
        return "battery low"

    def _brief_phrase(self, row: dict[str, Any]) -> str:
        """Return one incident as a sentence a person would write.

        Plain language, never category names: a reader should not
        need to know what "frozen" means inside this integration to
        understand that a device stopped reporting. A resolution
        carries how long it lasted and what ended it in the same
        phrase, which over a fortnight is the column that says
        whether a device recovers on its own or only when levered.
        """
        kind = row[INC_KIND]
        event = row[INC_EVENT]
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            cause = row.get(INC_CAUSE)
            base = f"recovered after {span}"
            return f"{base}, {cause}" if cause else base
        if event == INCIDENT_ACTION:
            return {
                ACTION_ACKNOWLEDGED: "acknowledged",
                ACTION_UNACKNOWLEDGED: "acknowledgment removed",
                ACTION_DELETED: "deleted from the list",
                ACTION_READDED: "re-added, the problem is still there",
            }.get(row.get(INC_CAUSE) or "", "acknowledged")
        if event == INCIDENT_ACKNOWLEDGED:
            # Legacy rows only, removable after 2026-08-11.
            return "acknowledged"
        if kind == TODO_KIND_BATTERY:
            # Borrowed from the composer so the table and the prose
            # cannot disagree about the same event: one composer
            # serves every channel, so nothing is described two ways
            # (ruling #120). The level belongs in both or neither.
            return self._battery_phrase(row[INC_DEVICE_ID], False)
        wording = {
            TODO_KIND_FROZEN: "stopped reporting",
            TODO_KIND_NOT_REPORTED: "has never reported",
            TODO_KIND_UNAVAILABLE: "went unavailable",
            TODO_KIND_UNKNOWN: "went unknown",
            TODO_KIND_SIGNAL: "signal railed",
        }
        return wording.get(kind, kind)

    def _brief_now_rows(
        self,
    ) -> list[tuple[str, str, float, str, str]]:
        """Return the standing state: what is wrong right now.

        Read from the problem list rather than recomputed, so the
        brief and the list can never disagree. Excluded devices are
        absent because this is a report, and so are acknowledged ones
        (ruling #123): acknowledgment silences every human-facing
        channel, and the brief is a notification that happens to be a
        file,
        and acknowledging a problem is the statement that the person
        knows about it and does not want reminding. The diagnostics
        keep every acknowledged fault, which is where an audit
        belongs.
        """
        now = dt_util.utcnow().timestamp()
        rows: list[tuple[str, str, float, str]] = []
        for record in self.todo_items:
            device_id = record.get(TODO_DEVICE_ID)
            if not device_id or device_id in self._excluded_devices:
                continue
            if record.get(TODO_STATUS) == "completed":
                continue
            name = record.get(TODO_SORT_NAME) or device_id
            for kind, since in (record.get(TODO_KINDS) or {}).items():
                problem = {
                    TODO_KIND_FROZEN: "stopped reporting",
                    TODO_KIND_NOT_REPORTED: "never reported",
                    TODO_KIND_UNAVAILABLE: "unavailable",
                    TODO_KIND_UNKNOWN: "unknown",
                    TODO_KIND_SIGNAL: "signal railed",
                    TODO_KIND_BATTERY: self._brief_battery_text(device_id),
                }.get(kind, kind)
                rows.append((name, problem, since or now, kind, device_id))
        rows.sort(key=lambda row: row[2])
        return rows

    def _system_event_sentence(self, row: dict[str, Any]) -> str:
        """One thing that happened to the house, as a sentence.

        Deliberately plain. These sit above the device lines and
        explain them, so the useful part is the fact and the time,
        not the telling of it.
        """
        when = self._brief_moment(row[SYS_WHEN])
        scope = row.get(SYS_SCOPE) or SYS_SCOPE_SYSTEM
        detail = row.get(SYS_DETAIL)
        span = row.get(SYS_DURATION)
        held = self._human_span(span) if span else None
        kind = row.get(SYS_KIND)
        if kind == SYS_RESTART:
            if held:
                return (
                    f"The system restarted at {when} after {held} "
                    "with nothing listening."
                )
            return f"The system restarted at {when}."
        if kind == SYS_BRIDGE_DOWN:
            return f"The {scope} bridge went down at {when}."
        if kind == SYS_BRIDGE_UP:
            if held:
                return (
                    f"The {scope} bridge came back at {when} after "
                    f"{held}."
                )
            return f"The {scope} bridge came back at {when}."
        if kind == SYS_PAIRING_OPEN:
            return f"A {scope} pairing window opened at {when}."
        if kind == SYS_PAIRING_CLOSED:
            if held:
                return (
                    f"The {scope} pairing window closed at {when} "
                    f"after {held}."
                )
            return f"The {scope} pairing window closed at {when}."
        if kind == SYS_UNCLEAN_RESTART:
            # The restart row above already carried the plain fact
            # that the system came back, so this one carries what was
            # different about it. Both are written deliberately
            # (ruling #163)
            # and read as a pair: what happened, then why the clocks
            # moved. On the morning after a real one this is the first
            # sentence read, so it says the count rather than leaving
            # the reader to find it in a diagnostics download.
            extra = f", {detail}" if detail else ""
            if held:
                return (
                    f"That restart followed an unclean shutdown, with "
                    f"{held} unwatched{extra}."
                )
            return f"That restart followed an unclean shutdown{extra}."
        if kind == SYS_EPOCH_RESET:
            extra = f" for {detail}" if detail else ""
            return f"Learned statistics were reset at {when}{extra}."
        if kind == SYS_OPTIONS_CHANGED:
            extra = f": {detail}" if detail else ""
            return f"Settings changed at {when}{extra}."
        return f"{kind} at {when}."

    def _system_event_phrase(self, row: dict[str, Any]) -> str:
        """The same event as a table cell rather than a sentence."""
        scope = row.get(SYS_SCOPE) or SYS_SCOPE_SYSTEM
        detail = row.get(SYS_DETAIL)
        span = row.get(SYS_DURATION)
        held = self._human_span(span) if span else None
        kind = row.get(SYS_KIND)
        if kind == SYS_RESTART:
            return (
                f"system restarted, {held} unwatched"
                if held
                else "system restarted"
            )
        if kind == SYS_BRIDGE_DOWN:
            return f"{scope} bridge went down"
        if kind == SYS_BRIDGE_UP:
            return (
                f"{scope} bridge came back after {held}"
                if held
                else f"{scope} bridge came back"
            )
        if kind == SYS_PAIRING_OPEN:
            return f"{scope} pairing window opened"
        if kind == SYS_PAIRING_CLOSED:
            return (
                f"{scope} pairing window closed after {held}"
                if held
                else f"{scope} pairing window closed"
            )
        if kind == SYS_UNCLEAN_RESTART:
            return (
                f"unclean shutdown ({detail})"
                if detail
                else "unclean shutdown"
            )
        if kind == SYS_EPOCH_RESET:
            return f"learned statistics reset ({detail})" if detail else "learned statistics reset"
        if kind == SYS_OPTIONS_CHANGED:
            return f"settings changed ({detail})" if detail else "settings changed"
        return str(kind)

    def _brief_prose(
        self,
        incidents: list[dict[str, Any]],
        now_rows: list[tuple[str, str, float, str, str]],
        window_start: float,
        sys_events: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Return the brief's opening prose.

        The same composer that will speak to a phone, read as
        paragraphs (ruling #122): history first, then what is
        standing right now. History is told as episodes rather than
        events (ruling #134), so a device stopping and the same device
        recovering are one sentence, ordered by when each episode
        began. The tables below stay for scanning and for exact times;
        this is for reading. Every
        sentence comes from the composer, so the prose, the tables,
        and a future notification cannot describe one event three
        ways.
        """
        told: list[str] = []
        for opened, resolved in self._pair_incidents(incidents):
            told.append(
                self._compose_episode(opened, resolved)
                if resolved is not None
                else self._compose_event(opened)
            )
        standing: list[str] = []
        for _name, _problem, _since, _kind, device_id in now_rows:
            line = self._compose_device_line(device_id)
            if line is None:
                continue
            if line not in standing:
                standing.append(line)
        lines = ["## In Short", ""]
        since_text = self._brief_moment(window_start)
        # Above the device lines, not among them. What happened to
        # the house is the context for what happened to the devices,
        # and a reader who has it will not read fifty consequences as
        # fifty faults.
        house = [
            self._system_event_sentence(row)
            for row in sorted(
                sys_events or [], key=lambda row: row[SYS_WHEN]
            )
        ]
        if house:
            lines += [" ".join(house), ""]
        if told:
            lines += [f"Since {since_text}: " + " ".join(told), ""]
        else:
            lines += [f"Nothing has happened since {since_text}.", ""]
        if standing:
            lines += ["Right now: " + " ".join(standing), ""]
        else:
            lines += ["Nothing needs attention right now.", ""]
        return lines

    def _write_brief(
        self,
        report_directory: str,
        trigger: str,
        window_start: float,
        window_end: float,
        complete: bool,
        stamp_start: float | None = None,
    ) -> str | None:
        """Write the daily brief for a window, and return it when done.

        window_start and window_end are the content: what the brief
        describes. stamp_start is the day the file is named for, and
        it is passed separately because the two stopped agreeing
        when the live copy became a rolling day (ruling #187). Left
        out, it is the window start, which is what a closed brief
        wants.

        The text comes back only for a completed brief, which is the
        one the email carries, since mailing an unfinished document
        would deliver the same day several times (ruling #135).
        Returning it rather than
        re-reading the file guarantees the document sent is the
        document written, byte for byte, with no second read that
        could catch a half-written file.

        The one report written for a person rather than a maintainer
        (ruling #116): what is wrong now, what happened in the last 24
        hours, plain language, human units, no basis or window or
        lag or exclusion reasoning. Regenerating mid-day writes the
        in-progress brief with its scope stated and marked
        incomplete, replacing itself until the real brief publishes
        and starts a new day.
        """
        now_rows = self._brief_now_rows()
        silenced = self._acknowledged_devices()
        incidents = [
            row
            for row in (self.data.get(DATA_INCIDENTS) or [])
            if window_start <= row[INC_WHEN] <= window_end
            and row[INC_DEVICE_ID] not in self._excluded_devices
            and row[INC_DEVICE_ID] not in silenced
        ]
        incidents.sort(key=lambda row: row[INC_WHEN], reverse=True)
        # The house's own events, over the same window. Never
        # filtered by exclusion or acknowledgment: a person silencing
        # one device has not asked to stop hearing that the power
        # failed.
        sys_events = [
            row
            for row in (self.data.get(DATA_SYSTEM_EVENTS) or [])
            if window_start <= row[SYS_WHEN] <= window_end
        ]
        sys_events.sort(key=lambda row: row[SYS_WHEN], reverse=True)
        opened = sum(
            1 for row in incidents if row[INC_EVENT] == INCIDENT_OPENED
        )
        resolved = sum(
            1 for row in incidents if row[INC_EVENT] == INCIDENT_RESOLVED
        )
        scope = (
            f"{self._brief_moment(window_end)}. Covering the 24 hours "
            f"since {self._brief_moment(window_start)}."
            if complete
            else f"From {self._brief_moment(window_start)} to "
            f"{self._brief_moment(window_end)} (in progress)."
        )
        lines = [
            "# Device Sentinel Daily Brief",
            "",
            scope,
            "",
        ]
        lines += self._brief_prose(
            incidents, now_rows, window_start, sys_events
        )
        lines += ["## Now", ""]
        if not now_rows:
            lines += ["Nothing needs attention.", ""]
        else:
            devices = len({row[0] for row in now_rows})
            summary = (
                f"{devices} device{'s' if devices != 1 else ''} "
                f"need{'' if devices != 1 else 's'} attention"
            )
            summary += "."
            now = dt_util.utcnow().timestamp()
            lines += [
                summary,
                "",
                "| DEVICE | PROBLEM | SINCE | FOR |",
                "|---|---|---|---|",
            ]
            for name, problem, since, kind, _device_id in now_rows:
                # A device that has never reported has no last-seen
                # time; the stamp is when it was discovered in the
                # registry, and saying so stops a reader taking it
                # for the moment the device broke (ruling #118).
                when = (
                    f"discovered {self._brief_moment(since)}"
                    if kind == TODO_KIND_NOT_REPORTED
                    else self._brief_moment(since)
                )
                lines.append(
                    f"| {self._report_cell(name)} | {problem} "
                    f"| {when} "
                    f"| {self._human_span(now - since)} |"
                )
            lines.append("")
        # The dwell anomalies get one pointer line, only on mornings
        # there are any (ruling #173). The chart itself is HTML
        # at a fixed URL, so the brief names it rather than embedding
        # it, and a quiet fleet adds nothing here. It sits in Now
        # because yesterday's dwell is the current picture of the
        # link, even though the day it measures has closed.
        anomalies = self._dwell_anomalies(self._signal_red())
        if anomalies:
            named = ", ".join(
                f"{a['name']} ({a['dwell']:.0f}%)" for a in anomalies[:5]
            )
            lines += [
                f"Signal dwell anomalies: {named}. Details and the "
                f"full chart: {REPORT_SIGNAL_DWELL_URL}",
                "",
            ]
        lines += ["## Last 24 Hours", ""]
        if not incidents and not sys_events:
            lines += ["Nothing happened.", ""]
        else:
            lines += [
                f"{len(incidents) + len(sys_events)} event"
                f"{'s' if len(incidents) + len(sys_events) != 1 else ''}. "
                f"{opened} problem{'s' if opened != 1 else ''} "
                f"started, {resolved} ended.",
                "",
                "| TIME | DEVICE | WHAT HAPPENED |",
                "|---|---|---|",
            ]
            merged = [
                (row[INC_WHEN], self._report_cell(row[INC_NAME]),
                 self._brief_phrase(row))
                for row in incidents
            ] + [
                (row[SYS_WHEN], "The system",
                 self._system_event_phrase(row))
                for row in sys_events
            ]
            merged.sort(key=lambda item: item[0], reverse=True)
            for when, who, what in merged:
                lines.append(
                    f"| {self._brief_moment(when)} | {who} | {what} |"
                )
            lines.append("")
        # Named for the day the window opened, not the moment of
        # writing. Naming by "now" renamed the in-progress brief at
        # midnight, so one window produced two files describing
        # overlapping periods, and neither was ever completed.
        stamp = dt_util.as_local(
            dt_util.utc_from_timestamp(
                window_start if stamp_start is None else stamp_start
            )
        ).strftime("%Y-%m-%d")
        text = "\n".join(lines)
        # The Markdown brief is retired: what a person reads moved
        # under www, where a browser and a dashboard card can render
        # it (rulings #178 and #179). The dated HTML files are the
        # record now, named exactly as
        # the Markdown files were, and the undated current file is a
        # copy of the newest write so a dashboard card has one stable
        # URL that never breaks at midnight. Old .md briefs on disk
        # are left as the history they are.
        page = self._render_brief_html(text)
        directory = self.hass.config.path(REPORT_WWW_DIR)
        os.makedirs(directory, exist_ok=True)
        dated = os.path.join(
            directory, f"{REPORT_BRIEF_PREFIX}{stamp}.html"
        )
        with open(dated, "w", encoding="utf-8") as handle:
            handle.write(page)
        with open(
            os.path.join(directory, REPORT_BRIEF_HTML),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(page)
        self._trim_briefs(directory)
        # The page is what a mail client renders; the composed text
        # remains the plain form for the persistent-notification
        # target and the message fallback. Same content by
        # construction, one rendered from the other.
        #
        # The page is stashed together with the text it came from,
        # and only for a completed brief, so the sender can check
        # that the two belong together before mailing the page. The
        # scheduled write closes yesterday and then immediately
        # opens today's in-progress brief a few lines below, and a
        # stash that the second write also updated left the mail
        # carrying the closed day's text beside the new day's page
        # (ruling #184, the paired stash).
        if complete:
            self._last_brief_pair = (text, page)
        self._last_brief_text = text
        return text if complete else None

    @staticmethod
    def _is_brief_table_rule(line: str) -> bool:
        """Return whether a pipe line is a table's header rule.

        Read from the characters rather than from the row's position.
        Position was how the older renderer told the rule apart, and
        it assumed the second line of every table was the separator,
        which is true only while nothing else ever emits a pipe line.
        """
        body = line.strip()
        if not body.startswith("|"):
            return False
        return set(body) <= set("|-: ")

    @staticmethod
    def _brief_cells(line: str) -> list[str]:
        """Return one pipe row's cells, stripped and escaped."""
        return [escape(cell.strip()) for cell in line.strip("|").split("|")]

    def _render_brief_html(self, markdown: str) -> str:
        """Return the brief rendered as a styled page (ruling #178).

        The one renderer. Rendered from the composed Markdown text
        rather than written a second way, so the record and the page
        cannot drift, and every consumer reads this: the dated file,
        the undated current file, the emailed body, and the fallback
        the sender falls back to when the stashed pair does not match
        (rulings #135, #179 and #184).

        It was two renderers until 0.10.22, and they had already
        drifted. Only the other one escaped its content, so from
        0.10.18, when this one became the emailed body, a device
        named with an angle bracket in it reached the file and the
        mail raw. Merging them fixes the escaping as a consequence
        rather than patching the same rule into two places that would
        drift again (ruling #188).

        A closed-subset renderer over our own output, not a Markdown
        parser: the brief emits one h1, h2 sections, plain paragraphs
        and pipe tables, so those four shapes are the whole grammar,
        and anything unrecognized falls through as a paragraph, which
        keeps a future line from vanishing silently.

        Everything is escaped before the chart link is turned into an
        anchor, so the one tag this renderer creates is the only
        markup that survives. The link is resolved to an absolute
        address where Home Assistant knows one, so it works from a
        mail client as well as a dashboard card.
        """
        html_lines: list[str] = []
        table: list[list[str]] = []

        def _flush_table() -> None:
            if not table:
                return
            head, *body_rows = table
            html_lines.append("<table>")
            html_lines.append(
                "<tr>"
                + "".join(f"<th>{cell}</th>" for cell in head)
                + "</tr>"
            )
            for row in body_rows:
                html_lines.append(
                    "<tr>"
                    + "".join(f"<td>{cell}</td>" for cell in row)
                    + "</tr>"
                )
            html_lines.append("</table>")
            table.clear()

        for raw in markdown.split("\n"):
            line = raw.rstrip()
            if line.startswith("|"):
                if not self._is_brief_table_rule(line):
                    table.append(self._brief_cells(line))
                continue
            _flush_table()
            if line.startswith("# "):
                html_lines.append(f"<h1>{escape(line[2:])}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{escape(line[3:])}</h2>")
            elif line.strip():
                text_line = escape(line)
                if REPORT_SIGNAL_DWELL_URL in text_line:
                    href = self._absolute_url(REPORT_SIGNAL_DWELL_URL)
                    text_line = text_line.replace(
                        REPORT_SIGNAL_DWELL_URL,
                        f"<a href='{href}'>the signal dwell chart</a>",
                    )
                html_lines.append(f"<p>{text_line}</p>")
        _flush_table()

        body = "\n".join(html_lines)
        page = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Device Sentinel Daily Brief</title>
<style>
body {{ font-family: sans-serif; margin: 16px; background: #fff;
  color: #1a1a19; max-width: 720px; }}
h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 24px; }}
p, td, th {{ font-size: 13px; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
td, th {{ border: 1px solid #D3D1C7; padding: 4px 8px;
  text-align: left; }}
a {{ color: #2a78d6; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #eee; }}
  td, th {{ border-color: #444; }}
  a {{ color: #6ba6e8; }} }}
</style></head><body>
{body}
</body></html>
"""
        return page

    def _absolute_url(self, path: str) -> str:
        """Return the path resolved against the instance URL, if any.

        A relative /local address is dead inside an email, which has
        no host to resolve it against, so the link is never left
        relative (ruling #183, amending #181). The external URL is
        preferred
        because it works from anywhere, which is when an emailed
        brief is most useful; where none is configured the internal
        URL is used instead, which at least works on home wifi and is
        better than an address that resolves nowhere at all. Home
        Assistant's own resolver already tries them in that order,
        so one call expresses the whole rule.

        The bare path is returned only where neither URL resolves,
        which needs an instance that knows no address for itself. It
        is the same dead link the amendment removed, kept because
        there is nothing better to return and raising here would
        cost the whole brief for one hyperlink.
        """
        try:
            from homeassistant.helpers.network import get_url

            return (
                get_url(
                    self.hass,
                    allow_internal=True,
                    prefer_external=True,
                )
                + path
            )
        except Exception:  # noqa: BLE001 - instance knows no URL at all
            return path

    def _trim_briefs(self, directory: str) -> None:
        """Keep the most recent dated briefs, drop the rest."""
        self._trim_dated(directory, REPORT_BRIEF_PREFIX)

    def _trim_dated(self, directory: str, prefix: str) -> None:
        """Keep the newest dated files of a prefix, drop the rest.

        Every file under www follows one rule (ruling #180):
        dated files as the record, an undated current file for the
        one stable dashboard URL, and a trim on the same fourteen-day
        schedule as the brief. The undated file never matches, since
        a date always follows the underscore.
        """
        try:
            names = sorted(
                name
                for name in os.listdir(directory)
                if name.startswith(f"{prefix}2")
                and name.endswith(".html")
            )
        except OSError:
            return
        for name in names[:-BRIEF_KEEP_DAYS]:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(directory, name))

    def _write_reports(self, trigger: str = "manual") -> str | None:
        """Write the report files, and return a closed brief if one.

        They live under /config because custom_components is code and
        is overwritten on every update (a ruled decision). Written at
        every setup and after every midnight rollover, so the files
        always exist from first boot and are never staler than the
        last restart or midnight. Stale plain-text files from before
        the reports became Markdown are removed so the folder holds
        one truth.
        """
        report_directory = self.hass.config.path(REPORT_DIR)
        os.makedirs(report_directory, exist_ok=True)
        for stale_name in REPORT_STALE_FILES:
            stale_path = os.path.join(report_directory, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)
        # The folder split completed (rulings #178 and #179): what a
        # person reads lives under www/device_sentinel, so this
        # folder is the developer's and the maintainer files come
        # back up out of the diagnostics subfolder. They were put
        # there to keep the briefs alone in this folder, and that
        # reason retired when the Markdown brief did. The old
        # subfolder's three files are removed once; anything else in
        # it, the rig log included, is not this integration's to
        # touch.
        old_diagnostics = os.path.join(
            report_directory, REPORT_DIAGNOSTIC_DIR
        )
        for name in (
            REPORT_TELEMETRY,
            REPORT_CLASSIFICATION,
            REPORT_EPISODES,
        ):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(old_diagnostics, name))
        with contextlib.suppress(OSError):
            os.rmdir(old_diagnostics)
        self._write_telemetry(report_directory, trigger)
        self._write_classification(report_directory, trigger)
        self._write_episodes(report_directory, trigger)
        # The dwell chart is HTML rather than Markdown because the
        # bands are its whole point and Markdown cannot carry color.
        # It lives under www so a dashboard Webpage card can render it
        # at /local/device_sentinel/signal_dwell.html; the reports
        # folder is not web-served and cannot do that job.
        self._write_signal_dwell_html()
        self._write_battery_html()
        # The brief's window runs from the last brief time to now, so
        # a regenerate mid-day writes the in-progress one. The
        # scheduled write closes the day instead, covering the window
        # that just ended rather than the one just beginning (#116).
        closing = trigger == BRIEF_TRIGGER
        if closing:
            window_start, window_end = self._brief_close_bounds()
            stamp_start = None
        else:
            # The live copy carries a rolling day rather than the
            # hours since the brief time (ruling #187). The undated
            # file is the dashboard's address, and for most of the
            # day the brief-to-brief window had almost nothing in it,
            # so a card read "nothing happened" while a full day of
            # events sat in yesterday's dated file. Now stays live
            # either way, since it is read from the problem list
            # rather than from the window. The file is still named
            # for the brief day, so this copy cannot land on top of a
            # closed record.
            window_end = dt_util.utcnow().timestamp()
            stamp_start = self._brief_window_start(window_end)
            window_start = window_end - BRIEF_LIVE_WINDOW_SECONDS
        brief_text = self._write_brief(
            report_directory,
            trigger,
            window_start,
            window_end,
            complete=closing,
            stamp_start=stamp_start,
        )
        # A scheduled write closes the day that just ended, but the
        # day just beginning has no file until something writes the
        # current window, and nothing does until the next startup or
        # regenerate. So the file named for today is absent from the
        # roll until then, which reads as a brief that stopped
        # publishing (ruling #116, completed here). Open the new
        # window's
        # in-progress brief now, so today's file exists the moment
        # the window rolls.
        if closing:
            now = dt_util.utcnow().timestamp()
            self._write_brief(
                report_directory,
                trigger,
                now - BRIEF_LIVE_WINDOW_SECONDS,
                now,
                complete=False,
                stamp_start=self._brief_window_start(now),
            )
        return brief_text
