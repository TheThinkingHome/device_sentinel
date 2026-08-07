# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.12.10 (2026-08-07)

"""The report writers, split out of the coordinator for legibility.

This is a file split rather than a boundary, and saying so plainly
matters: the methods here read a great deal of coordinator state and
are mixed in rather than composed, so `self` is the coordinator and
nothing in this file can be instantiated or tested on its own. The
coordinator had grown past four thousand lines and the writers are a
fifth of it, cohesive and almost entirely read-only, so they were the
honest first cut.

What lives here now is the shared half: the formatters every report
uses, the address resolver, the dated-file trim, and the orchestrator
that calls the four writers. Each report is its own module beside
this one (ruling #199), because the file had grown past two thousand
lines and held every report the integration writes.

The seam is the report rather than the audience. A split into
maintainer files and human files was considered first and does not
survive contact with the code: one orchestrator writes both kinds,
the address resolver and the cell escaper serve both, and the column
showing how fast a signal floor is moving is a maintainer column
computed from the same data the person-facing chart draws.

The composition is inheritance rather than delegation because that is
what the whole file already was. These are mixins on the coordinator,
so moving a method between them changes nothing about how it runs.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BRIEF_KEEP_DAYS,
    BRIEF_LIVE_WINDOW_SECONDS,
    BRIEF_TRIGGER,
    REPORT_CLASSIFICATION,
    REPORT_DIAGNOSTIC_DIR,
    REPORT_DIR,
    REPORT_EPISODES,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
)


from .report_battery import BatteryReportMixin
from .report_brief import BriefMixin
from .report_dwell import DwellChartMixin
from .report_maintainer import MaintainerReportMixin


class ReportWritingMixin(
    BriefMixin,
    BatteryReportMixin,
    DwellChartMixin,
    MaintainerReportMixin,
):
    """Text production for the coordinator.

    Mixed into DeviceSentinelCoordinator, so every attribute these
    methods reach for belongs to that class. Splitting them out
    changes nothing about how they run; it only puts them where they
    can be read.

    The four report modules are inherited rather than imported and
    called, so the coordinator sees one mixin and every method keeps
    the name it always had. No caller anywhere changed.
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


    @staticmethod
    def _write_file(path: str, text: str) -> None:
        """Write a report so a reader never sees half of one.

        Every report is written to a temporary name in the same
        directory and then moved onto the destination, which os
        .replace makes atomic on the same filesystem. Opening the
        destination directly leaves a truncated file if the write is
        interrupted, and a person opening a dashboard card mid-crash
        would see half a page (ruling #208).

        Nothing is lost either way, because every report regenerates
        at the next write. What this buys is that the file on disk is
        always a whole report, the old one or the new one and never a
        piece of both. The temporary name sits beside the target so
        the move stays within one filesystem; a temp directory
        elsewhere would make os.replace a copy and lose the property.

        Failure is left to the caller, which catches it. An executor
        job handles nothing on its own: an OSError raised in one
        escapes into Home Assistant's task machinery and lands in a
        person's log as an unretrieved task exception, so this
        docstring once named a handler that did not exist
        (ruling #234). A report that cannot be written is a worse
        report rather than a broken integration.
        """
        temporary = f"{path}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temporary, path)
        except OSError:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise

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
