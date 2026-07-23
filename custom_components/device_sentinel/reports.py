# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.8.1 (2026-07-23)

"""The report writers, split out of the coordinator for legibility.

This is a file split rather than a boundary, and saying so plainly
matters: the methods here read a great deal of coordinator state and
are mixed in rather than composed, so `self` is the coordinator and
nothing in this file can be instantiated or tested on its own. The
coordinator had grown past four thousand lines and the writers are a
fifth of it, cohesive and almost entirely read-only, so they were the
honest first cut.

What lives here is the text-producing half of the integration: the
shared formatters every report uses, and the writer for
silence_episodes.md. The remaining writers follow in later releases,
one slice at a time, each proven by regenerating the reports and
comparing them byte for byte against the previous version's output.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_EPISODES,
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
    REPORT_EPISODES,
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

