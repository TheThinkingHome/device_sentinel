# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.8.4 (2026-07-23)

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
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BRIEF_KEEP_DAYS,
    BRIEF_TRIGGER,
    CONF_REMINDER_TIME,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DEFAULT_REMINDER_TIME,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DWELL_DAILY,
    EPISODE_KEEP_DAYS,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_WINDOW,
    INCIDENT_ACKNOWLEDGED,
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
    REPORT_BRIEF_PREFIX,
    REPORT_CLASSIFICATION,
    REPORT_DIR,
    REPORT_EPISODES,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
    SIGNAL_ARMING_DAYS,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_WINDOW_SECONDS,
    TAINT_DEBOUNCE_SECONDS,
    TODO_DEVICE_ID,
    TODO_KINDS,
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

    def _write_episodes(self, report_directory: str, trigger: str) -> None:
        """Write the silence-episode report.

        The forensic file (#103). One row per episode, newest first,
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
            f"# Device Sentinel v{self.version} silence episodes",
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
            "why not when it did not. Kept "
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
                "ENDED | AT | LAG | LEARNED |",
                "|---|---|---|---|---|---|---|---|---|",
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
                    f"| {row[EP_LEARNED] or ''} |"
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

        The 0.6.1 todo icon lived here for one release and moved to
        the Reporting Devices section at 0.6.2: the same state shown
        twice was redundant and confusing, and the section is where a
        fault's whole story reads, list state included.
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
        """Render the daily battery levels newest-first, with any
        level at or below the low threshold bold. No trim and no
        strike: every recorded level is a real reading, and the point
        is the shape of the discharge over days, not an outlier. A
        healthy battery holds flat then falls; the bold values are the
        days it spent at or below the line."""
        levels = list(record.get(DEV_BATTERY_DAILY) or [])
        if not levels:
            return "-"
        threshold = self.low_threshold
        parts = []
        for index in reversed(range(len(levels))):
            level = levels[index]
            text = f"{level:g}"
            if level <= threshold:
                parts.append(f"**{text}**")
            else:
                parts.append(text)
        return " ".join(parts)

    def _format_signal_lows_cell(self, record: dict[str, Any]) -> str:
        """Render the daily signal lows newest-first with the marks.

        Three states, and a value is only ever one of them: the floor
        is bold, values strictly below the floor are struck through
        (the trimmed lows, set aside so a spurious bad reading does
        not define the line), and rail fill values are italic (seen
        and shown, but never fed to the floor).

        Two rules make repeated values read cleanly (ruled 2026-07-19,
        after a flat button series showed one 48 bold, one struck, and
        two plain). The floor mark lands on the EARLIEST recorded
        occurrence of the floor value, so a reader sees when the
        device first reached its low. And a value equal to the floor
        is never struck: only values strictly below the floor are
        trimmed, so the same number is never both the line and an
        outlier. This can leave more than k values struck when the
        trimmed lows repeat, or fewer, which is correct: the marks now
        describe the values, not the positions the trim happened to
        pick.
        """
        stored = list(record.get(DEV_SIGNAL_DAILY_MIN) or [])
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
            f"# Device Sentinel v{self.version} learned statistics",
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
            f"shifted by the sensitivity word in the header (Calm "
            f"trims fewer lows so the floor sits lower and flags less, "
            f"Sensitive the reverse), applied to readings going "
            f"forward only. DWELL% is the share of each day spent at "
            f"or below the floor: healthy devices brushing their floor "
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
            f"{TAINT_DEBOUNCE_SECONDS} s, arming floor "
            f"{LEARNING_MIN_DAYS} days, keep {DAILY_MAX_KEEP} days.",
            "",
        ]
        lines.extend(self._reporting_lines())
        lines += [
            "## Learned statistics",
            "",
            f"| DEVICE (INTEGRATION) | STATUS | GAPS (K={TRIM_TOP_K}) | "
            f"CLOCK | EVENTS | SIGNAL ({self._signal_slider_label()}) | "
            f"DWELL% | BAT LEVEL (floor {self.low_threshold:g}%) |",
            "|---|---|---|---|---|---|---|---|",
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
                    list(record.get(DEV_SIGNAL_DWELL_DAILY) or []),
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
                f"{dwell_text} | {battery_cell} |"
            )
        lines.append("")
        lines.append(f"{len(rows)} watched devices.")
        path = os.path.join(report_directory, REPORT_TELEMETRY)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.info("Telemetry report written to %s", path)

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
            f"# Device Sentinel v{self.version} classification",
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
                f"## Excluded entities ({len(self._excluded_entities)})"
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
        LOGGER.info("Classification report written to %s", path)

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
        if event == INCIDENT_ACKNOWLEDGED:
            return "acknowledged"
        if kind == "battery":
            # Borrowed from the composer so the table and the prose
            # cannot disagree about the same event (#120): the level
            # belongs in both or neither.
            return self._battery_phrase(row[INC_DEVICE_ID], False)
        wording = {
            "frozen": "stopped reporting",
            "not_reported": "has never reported",
            "unavailable": "went unavailable",
            "unknown": "went unknown",
            "signal": "signal railed",
        }
        if kind == "battery":
            return "battery fell low"
        return wording.get(kind, kind)

    def _brief_now_rows(
        self,
    ) -> list[tuple[str, str, float, str, str]]:
        """Return the standing state: what is wrong right now.

        Read from the problem list rather than recomputed, so the
        brief and the list can never disagree. Excluded devices are
        absent because this is a report, and so are acknowledged ones
        (#123): the brief is a notification that happens to be a file,
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
                    "frozen": "stopped reporting",
                    "not_reported": "never reported",
                    "unavailable": "unavailable",
                    "unknown": "unknown",
                    "signal": "signal railed",
                    "battery": self._brief_battery_text(device_id),
                }.get(kind, kind)
                rows.append((name, problem, since or now, kind, device_id))
        rows.sort(key=lambda row: row[2])
        return rows

    def _brief_prose(
        self,
        incidents: list[dict[str, Any]],
        now_rows: list[tuple[str, str, float, str, str]],
        window_start: float,
    ) -> list[str]:
        """Return the brief's opening prose.

        The same composer that will speak to a phone, read as
        paragraphs (#122): history first in the order it happened,
        then what is standing right now. The tables below stay for
        scanning and for exact times; this is for reading. Every
        sentence comes from the composer, so the prose, the tables,
        and a future notification cannot describe one event three
        ways.
        """
        told: list[str] = []
        for row in sorted(incidents, key=lambda item: item[INC_WHEN]):
            told.append(self._compose_event(row))
        standing: list[str] = []
        for _name, _problem, _since, _kind, device_id in now_rows:
            line = self._compose_device_line(device_id)
            if line is None:
                continue
            if line not in standing:
                standing.append(line)
        lines = ["## In short", ""]
        since_text = self._brief_moment(window_start)
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
    ) -> None:
        """Write the daily brief for a window.

        The one report written for a person rather than a maintainer
        (#116): what is wrong now, what happened in the last 24
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
            else f"In progress. From "
            f"{self._brief_moment(window_start)} to "
            f"{self._brief_moment(window_end)} (incomplete)."
        )
        lines = [
            "# Device Sentinel daily brief",
            "",
            scope,
            "",
        ]
        lines += self._brief_prose(incidents, now_rows, window_start)
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
                # for the moment the device broke (#118).
                when = (
                    f"discovered {self._brief_moment(since)}"
                    if kind == "not_reported"
                    else self._brief_moment(since)
                )
                lines.append(
                    f"| {self._report_cell(name)} | {problem} "
                    f"| {when} "
                    f"| {self._human_span(now - since)} |"
                )
            lines.append("")
        lines += ["## Last 24 hours", ""]
        if not incidents:
            lines += ["Nothing happened.", ""]
        else:
            lines += [
                f"{len(incidents)} event"
                f"{'s' if len(incidents) != 1 else ''}. "
                f"{opened} problem{'s' if opened != 1 else ''} "
                f"started, {resolved} ended.",
                "",
                "| TIME | DEVICE | WHAT HAPPENED |",
                "|---|---|---|",
            ]
            for row in incidents:
                lines.append(
                    f"| {self._brief_moment(row[INC_WHEN])} "
                    f"| {self._report_cell(row[INC_NAME])} "
                    f"| {self._brief_phrase(row)} |"
                )
            lines.append("")
        # Named for the day the window opened, not the moment of
        # writing. Naming by "now" renamed the in-progress brief at
        # midnight, so one window produced two files describing
        # overlapping periods, and neither was ever completed.
        stamp = dt_util.as_local(
            dt_util.utc_from_timestamp(window_start)
        ).strftime("%Y-%m-%d")
        path = os.path.join(
            report_directory, f"{REPORT_BRIEF_PREFIX}{stamp}.md"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self._trim_briefs(report_directory)

    def _trim_briefs(self, report_directory: str) -> None:
        """Keep the most recent briefs, drop the rest."""
        try:
            names = sorted(
                name
                for name in os.listdir(report_directory)
                if name.startswith(REPORT_BRIEF_PREFIX)
                and name.endswith(".md")
            )
        except OSError:
            return
        for name in names[:-BRIEF_KEEP_DAYS]:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(report_directory, name))

    def _write_reports(self, trigger: str = "manual") -> None:
        """Write both diagnostic files to /config/device_sentinel/.

        They live under /config because custom_components is code and
        is overwritten on every update (a ruled decision). Written at
        every setup and after every midnight rollover, so the files
        always exist from first boot and are never staler than the
        last restart or midnight. Stale pre-0.2.6 .txt files are
        removed so the folder holds one truth.
        """
        report_directory = self.hass.config.path(REPORT_DIR)
        os.makedirs(report_directory, exist_ok=True)
        for stale_name in REPORT_STALE_FILES:
            stale_path = os.path.join(report_directory, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)
        self._write_telemetry(report_directory, trigger)
        self._write_classification(report_directory, trigger)
        self._write_episodes(report_directory, trigger)
        # The brief's window runs from the last brief time to now, so
        # a regenerate mid-day writes the in-progress one. The
        # scheduled write closes the day instead, covering the window
        # that just ended rather than the one just beginning (#116).
        closing = trigger == BRIEF_TRIGGER
        if closing:
            window_start, window_end = self._brief_close_bounds()
        else:
            window_end = dt_util.utcnow().timestamp()
            window_start = self._brief_window_start(window_end)
        self._write_brief(
            report_directory,
            trigger,
            window_start,
            window_end,
            complete=closing,
        )
