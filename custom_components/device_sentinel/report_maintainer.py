# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_maintainer.py, Version: 0.22.21 (2026-09-22)

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
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    DAILY_MAX_KEEP,
    SET_ASIDE_EXCLUDED,
    SET_ASIDE_MEANINGS,
    STANDING_MEANINGS,
    TAINT_FLOOR_MINUTES,
    TAINT_SHARE_PCT,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
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
    EPISODE_KEEP_DAYS,
    LEARNING_MIN_DAYS,
    LOGGER,
    REPORT_CLASSIFICATION,
    REPORT_EPISODES,
    REPORT_TELEMETRY,
    SIGNAL_DAYS_KEEP,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_WINDOW_SECONDS,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
    WIKI_LINK_REPORTS,
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
        episodes = list(self.episode_rows())
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
            f"How to read this file: [The Diagnostic Reports]"
            f"({WIKI_LINK_REPORTS}) on the Device Sentinel wiki.",
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

        Set-aside outliers are struck through (muted from the
        window basis); the operative rhythm is bold. They can never
        be the same value styled twice, because the operative rhythm
        is by definition chosen after the outliers are removed.
        """
        # The series holds up to a year; this cell shows the same
        # two weeks it always has, and the indices below are into
        # that window.
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
            f"How to read this file: [The Diagnostic Reports]"
            f"({WIKI_LINK_REPORTS}) on the Device Sentinel wiki.",
            "",
            f"All series read newest first. SIGNAL is each device's "
            f"daily low, its time-weighted 5th percentile (rulings "
            f"#253, #322), over the last {SIGNAL_DAYS_KEEP} days. A bad "
            f"day, one whose low fell below that day's bad-day line, is "
            f"~~struck~~; the lowest day is **bold**; a rail-only day "
            f"shows as a dash. ITS NORMAL and BAD-DAY LINE are today's, "
            f"the figures the dashboard shows on the device's page: a "
            f"link is weak on a day its low falls below the bad-day "
            f"line. A "
            f"warning sign at the front of the cell marks a device "
            f"that spoke for three days and said nothing but the "
            f"rail fill value: a stuck reading that shows as perfect "
            f"signal and is the opposite, a near-certain fault worth "
            f"a power cycle or a re-bind. BAT LEVEL is "
            f"the daily battery level, with any reading at or below "
            f"the low threshold **bold**. excl means signal-muted: "
            f"still recorded, not judged.",
            "",
            "STATUS is Reported (judged for everything) or Muted "
            "with the reason in parentheses: GLB global (all judgment "
            "off), BAT battery, SIG signal, FRZ freeze. GLB shows "
            "alone; the section reasons combine, Muted (BAT, FRZ). "
            "A muted device keeps recording; muting suppresses "
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
            f"{TAINT_FLOOR_MINUTES}"
            f" min + {TAINT_SHARE_PCT}"
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
            f"CLOCK | EVENTS | SIGNAL | "
            f"ITS NORMAL | BAD-DAY LINE | "
            f"BAT LEVEL (floor {self.low_threshold:g}%) |",
            # Nine cells, matching the header and every data row. The
            # Dwell column left all three when the dwell chart went,
            # except this line, which kept its tenth cell and made
            # every renderer print the table as plain text. Reported
            # against 0.19.14 on 15 September; the fault reached
            # 0.21.9 unnoticed because nothing counted the pipes.
            "|---|---|---|---|---|---|---|---|---|",
        ]
        rows = []
        for device_id, record in self.watched_records():
            # Named by the ladder every surface asks (ruling #402); the
            # registry name alone left a nameless device as its id.
            device_name = self._device_name(device_id)
            integration = self._watched.get(device_id, "?")
            device_label = f"{self._report_cell(device_name)} ({integration})"
            daily_maximum_gaps = record.get(DEV_DAILY_MAX) or []
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
                    # prints one device's figure on every row. Today's
                    # normal and bad-day line replaced the floor's
                    # weekly drift and the mean in 0.22.16.
                    *self._signal_today_cells(record),
                    self._format_battery_cell(record),
                    self.signal_railed(record),
                    self._signal_muted(device_id),
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
            its_normal,
            badday_line,
            battery_cell,
            railed,
            sig_muted,
        ) in rows:
            # A confirmed rail (the device spoke for three days and
            # said nothing but the fill value) is marked in the
            # signal cell itself, not a column: a warning sign ahead
            # of the readings so it reads at a glance.
            signal_cell = f"\u26a0\ufe0f {lows_cell}" if railed else lows_cell
            if sig_muted:
                # Muted devices keep recording (their readings still
                # show) but are not judged: no rail mark.
                signal_cell = f"excl {lows_cell}"
            lines.append(
                f"| {device_label} | {status} | "
                f"{maxima_cell} | "
                f"{clock_source} | {event_count} | {signal_cell} | "
                f"{its_normal} | "
                f"{badday_line} | {battery_cell} |"
            )
        lines.append("")
        lines.append(f"{len(rows)} watched devices.")
        path = os.path.join(report_directory, REPORT_TELEMETRY)
        self._write_file(path, "\n".join(lines) + "\n")
        LOGGER.debug("Telemetry report written to %s", path)

    def _mute_source(
        self,
        device_id: str,
        integrations: list[str],
        labels: list[str],
        devices: list[str],
    ) -> str | None:
        """Name why one family's mute applies to a device, or None.

        The ladder every mute uses, broadest first, so the source named
        is the one that would survive a prune: the owning integration,
        then the device's own labels, then the device itself. A label
        is named by its name, not its id, since the name is what a
        person set; several matching labels are named together.
        """
        domain = self._watched.get(device_id)
        if domain in integrations:
            return f"integration: {domain}"
        hit = self._device_labels.get(device_id, frozenset()) & set(labels)
        if hit:
            names = sorted(
                (self._label_names.get(label, label) for label in hit),
                key=str.casefold,
            )
            return f"label: {', '.join(names)}"
        if device_id in devices:
            return "device"
        return None

    def _global_mute_text(self, device_id: str) -> str:
        """The global mute, with its source, or an empty string.

        The level comes from the registry walk, which already decided
        it; only the name of the integration or label is added here,
        so this cell cannot disagree with what the judge does.
        """
        level = self._muted_devices.get(device_id)
        if not level:
            return ""
        if level == "integration":
            return f"Global (integration: {self._watched.get(device_id)})"
        if level == "label":
            source = self._mute_source(
                device_id, [], self.entry.options.get(CONF_MUTED_LABELS, []), []
            )
            return f"Global ({source})" if source else "Global (label)"
        return f"Global ({level})"

    def _family_mute_texts(self, device_id: str) -> list[str]:
        """Freeze, battery and signal mutes, each with its source.

        Invisible on Classification until 0.22.13, so a device muted
        for battery alone read as if nothing were muted (from the
        second fleet's review, ruled 21 September 2026). In the order
        the owner set for 0.22.16: freeze, battery, signal.
        """
        options = self.entry.options
        found = []
        for family, integrations, labels, devices in (
            ("freeze", CONF_FREEZE_MUTED_INTEGRATIONS,
             CONF_FREEZE_MUTED_LABELS, CONF_FREEZE_MUTED_DEVICES),
            ("battery", CONF_BATTERY_MUTED_INTEGRATIONS,
             CONF_BATTERY_MUTED_LABELS, CONF_BATTERY_MUTED_DEVICES),
            ("signal", CONF_SIGNAL_MUTED_INTEGRATIONS,
             CONF_SIGNAL_MUTED_LABELS, CONF_SIGNAL_MUTED_DEVICES),
        ):
            source = self._mute_source(
                device_id,
                options.get(integrations, []),
                options.get(labels, []),
                options.get(devices, []),
            )
            if source is not None:
                found.append(f"{family} ({source})")
        return found

    def mute_text(self, device_id: str) -> str:
        """Every mute on a device, global first, each with its source.

        The one wording behind Classification, classification.md, a
        device's page, the Devices tab and an integration's device
        list (0.22.16), so a device reads the same wherever it is
        named. Empty when nothing is muted.
        """
        global_mute = self._global_mute_text(device_id)
        mutes = ([global_mute] if global_mute else []) + (
            self._family_mute_texts(device_id)
        )
        return "; ".join(mutes)

    def classification_rows(self) -> list[dict[str, Any]]:
        """Return one row per device, watched and set aside together.

        The one builder behind classification.md and the dashboard's
        Classification tab, so the two can never disagree. A watched
        device's MUTED cell holds every mute that applies to it, the
        global one first and then freeze, battery and signal, each
        naming its source; a set-aside device carries why it was set
        aside, and an exclusion names the integration excluded
        (ruling #257; the sources from the second fleet's review,
        0.22.13). `muted_global` keeps the global mute alone, for the
        Integrations tab's count, which counts a device as muted only
        when it is muted from everything.
        COPIES counts watched devices sharing a name, by the naming
        ladder (ruling #402). Sorted by name, case-insensitively.
        """
        name_copy_counts: dict[str, int] = {}
        for device_id in self._watched:
            name = self._device_name(device_id)
            name_copy_counts[name] = name_copy_counts.get(name, 0) + 1
        rows: list[dict[str, Any]] = []
        for device_id, integration_domain in self._watched.items():
            name = self._device_name(device_id)
            rows.append({
                "device_id": device_id,
                "name": name,
                "integration": integration_domain,
                "watched": True,
                "muted": self.mute_text(device_id),
                "muted_global": self._global_mute_text(device_id),
                "set_aside": "",
                "copies": name_copy_counts.get(name, 1),
            })
        for device_id, (name, integration_domain, reason) in self._set_aside.items():
            rows.append({
                "device_id": device_id,
                "name": name,
                "integration": integration_domain,
                "watched": False,
                "muted": "",
                "muted_global": "",
                "set_aside": (
                    f"{reason} (integration: {integration_domain})"
                    if reason == SET_ASIDE_EXCLUDED
                    else reason or ""
                ),
                "copies": 1,
            })
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    def _write_classification(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write classification.md, the audit view.

        One row per device, so a device's whole standing reads across
        a single line: whether it is Watched (has hardware, recording)
        or Set aside (a service device with nothing to watch), and, for
        a watched device, whether the global mute has it and why.
        Every device is watched and recorded; muting only suppresses
        judgment and reporting, so a muted device still carries a
        Watched check, with the reason alongside it. COPIES flags a
        name shared by more than one registry device. Section muting
        (battery, signal, freeze) are not shown here; they live in the
        telemetry STATUS column, because a section-muted device is
        still judged for everything else and is not muted wholesale.
        """

        rows = [
            (
                row["name"],
                row["integration"],
                "yes" if row["watched"] else "",
                row["muted"],
                row["set_aside"],
                str(row["copies"]) if row["copies"] > 1 else "",
            )
            for row in self.classification_rows()
        ]

        total = len(self._watched) + len(self._set_aside)
        lines = [
            f"# Device Sentinel v{self.version} Classification",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            f"How to read this file: [The Diagnostic Reports]"
            f"({WIKI_LINK_REPORTS}) on the Device Sentinel wiki.",
            "",
            # The count of entities with no device left this line in
            # 0.22.13: Device Sentinel never watches them, and "visible
            # only at entity level" said it did. The count stays in the
            # diagnostics.
            f"One row per device. Watching {len(self._watched)} of "
            f"{total}; {len(self._set_aside)} set aside (integrations "
            f"you asked to exclude, service devices, disabled devices, "
            f"duplicate coordinators, and devices with no entities). "
            f"Every device is watched and recorded; MUTED only "
            f"suppresses judgment and reporting, and names every mute "
            f"and its source. COPIES above 1 is a "
            f"name shared by more than one registry device (a "
            f"network-tracker ghost or a multi-homed double).",
            "",
            "| DEVICE | INTEGRATION | WATCHED | MUTED | SET ASIDE | "
            "COPIES |",
            "|---|---|---|---|---|---|",
        ]
        for (
            name,
            integration,
            watched,
            muted,
            aside_reason,
            copies_cell,
        ) in rows:
            watched_mark = "\u2713" if watched else ""
            set_aside_mark = aside_reason or ""
            lines.append(
                f"| {self._report_cell(name)} | {integration} | "
                f"{watched_mark} | "
                f"{self._report_cell(muted)} | "
                f"{self._report_cell(set_aside_mark)} | {copies_cell} |"
            )

        # The key to SET ASIDE, the same words as the tab's (0.22.13).
        lines += ["", "Set aside, by reason:", ""]
        lines += [
            f"- {reason}: {meaning}" for reason, meaning in SET_ASIDE_MEANINGS
        ]

        # Integrations with no hardware of their own own no row above,
        # so they are named here, with the same meaning the
        # Integrations tab gives (0.22.21).
        riders = sorted(self._no_hardware_integrations)
        if riders:
            meaning = dict(STANDING_MEANINGS)["No hardware"]
            lines += [
                "",
                f"## Integrations With No Hardware ({len(riders)})",
                "",
                meaning,
                "",
                "| INTEGRATION | WATCHED DEVICES IT ADDS TO |",
                "|---|---|",
            ]
            for domain in riders:
                adds_to = len([
                    device_id
                    for device_id, counts in self._foreign_by_device.items()
                    if domain in counts and device_id in self._watched
                ])
                lines.append(f"| {self._report_cell(domain)} | {adds_to} |")

        if self._muted_entities:
            lines.append("")
            lines.append(
                f"## Muted Entities ({len(self._muted_entities)})"
            )
            lines.append("")
            lines.append(
                "Individual entities muted from judgment. An "
                "muted entity still vouches for its device."
            )
            lines.append("")
            lines.append("| ENTITY | REASON |")
            lines.append("|---|---|")
            for entity_id, reason in sorted(
                self._muted_entities.items()
            ):
                lines.append(f"| {entity_id} | {reason} |")

        path = os.path.join(report_directory, REPORT_CLASSIFICATION)
        self._write_file(path, "\n".join(lines) + "\n")
        LOGGER.debug("Classification report written to %s", path)
