# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_maintainer.py, Version: 0.11.8 (2026-08-04)

"""The three Markdown files written for whoever maintains the system.

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
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TAINT_FLOOR,
    CONF_TAINT_SHARE,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_EPISODES,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEFAULT_TAINT_SHARE_PCT,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
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
    EP_TAINT_SECONDS,
    EP_WINDOW,
    LEARNING_MIN_DAYS,
    LOGGER,
    REPORT_CLASSIFICATION,
    REPORT_EPISODES,
    REPORT_TELEMETRY,
    SIGNAL_DAYS_KEEP,
    SIGNAL_TRIM_LADDER_MAX,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_WINDOW_SECONDS,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)


class MaintainerReportMixin:
    """The three Markdown files written for whoever maintains the system."""

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

        The forensic file, which explains freeze verdicts and decides
        nothing (ruling #103). One row per episode, newest first,
        recording what no other report can: whether a long
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
        # When the newest row was opened, because an empty stretch and
        # a stopped recorder look identical from the file alone
        # (ruling #203). A quiet fleet can go days without a single
        # device passing its own threshold, and the last thing written
        # here was a mesh-wide event that produced most of the file in
        # one hour, so the file reads as though it stalled.
        newest = (
            f", newest {self._episode_stamp(episodes[0][EP_SINCE])}"
            if episodes
            else ""
        )
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
            f"{open_count} still open{newest}.",
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
        self._write_file(path, "\n".join(lines))

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
            f"daily signal minima; the line dwell is measured "
            f"against is **bold**, readings below that line are "
            f"~~struck~~, and rail fill values 255/-128 "
            f"are *italic* (shown but never fed to the floor). A "
            f"warning sign at the front of the cell marks a device "
            f"whose daily low has sat at a rail for three days: a "
            f"stuck reading that shows as perfect signal and is the "
            f"opposite, a near-certain fault worth a power cycle or a "
            f"re-bind. The trim grows with the soak, one lowest "
            f"reading dropped per full week held up to "
            f"{SIGNAL_TRIM_LADDER_MAX}, over the last "
            f"{SIGNAL_DAYS_KEEP} days, "
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
            f"FLOOR/WK | DWELL% | MEAN\u00b1SD | "
            f"BAT LEVEL (floor {self.low_threshold:g}%) |",
            "|---|---|---|---|---|---|---|---|---|---|",
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
                    # Computed here rather than at render, because the
                    # rows are collected, sorted, and only then
                    # written: a call in the second loop reads
                    # whatever record the first loop left behind and
                    # prints one device's figure on every row.
                    self._floor_drift_cell(record),
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
            floor_drift,
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
                f"{floor_drift} | "
                f"{dwell_text} | {mean_cell} | {battery_cell} |"
            )
        lines.append("")
        lines.append(f"{len(rows)} watched devices.")
        path = os.path.join(report_directory, REPORT_TELEMETRY)
        self._write_file(path, "\n".join(lines) + "\n")
        LOGGER.debug("Telemetry report written to %s", path)

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
        self._write_file(path, "\n".join(lines) + "\n")
        LOGGER.debug("Classification report written to %s", path)
