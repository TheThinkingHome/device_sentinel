# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.23.9 (2026-09-26)

"""The report writers, split out of the coordinator for legibility.

This is a file split rather than a boundary, and saying so plainly
matters: the methods here read a great deal of coordinator state and
are mixed in rather than composed, so `self` is the coordinator and
nothing in this file can be instantiated or tested on its own. The
coordinator had grown past four thousand lines and the writers are a
fifth of it, cohesive and almost entirely read-only, so they were the
honest first cut.

What lives here now is the shared half: the formatters every report
uses, the link helper, and the orchestrator that calls the writers. Each report is its own module beside
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

from html import escape

import contextlib
import os
from datetime import datetime
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    CONF_REPORT_LINKS,
    DEFAULT_REPORT_LINKS,
    REPORT_LINKS_EXTERNAL,
    REPORT_LINKS_INTERNAL,
    PANEL_URL_PATH,
    BRIEF_LIVE_WINDOW_SECONDS,
    BRIEF_TRIGGER,
    REPORT_CLASSIFICATION,
    REPORT_DIAGNOSTIC_DIR,
    REPORT_DIR,
    REPORT_EPISODES,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
)
from .durations import LONG_SPAN_SECONDS, long_span


from .report_battery import BatteryReportMixin
from .report_brief import BriefMixin
from .report_signal import SignalReportMixin
from .report_maintainer import MaintainerReportMixin


class ReportWritingMixin(
    BriefMixin,
    BatteryReportMixin,
    SignalReportMixin,
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
        device is called.

        Angle brackets are escaped the same way, with a backslash
        (0.22.19). A name holding markup reached the files as markup,
        and a tester's report pasted into a page that renders Markdown
        would draw it. The backslash is Markdown's own escape, reads
        plainly in the raw file, and is taken back off by the brief's
        page, which escapes for HTML itself.
        """
        return (
            text.replace("\n", " ")
            .replace("\r", " ")
            .replace("|", "\\|")
            .replace("<", "\\<")
            .replace(">", "\\>")
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
        if seconds >= LONG_SPAN_SECONDS:
            return long_span(seconds)
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


    def _report_link(self, path: str) -> str | None:
        """The address a report links to, or None for no link.

        Ruling #453, kept by the owner on 25 September 2026 when the
        www folder retired (amending #470). The brief is a file that
        gets shared and forwarded, so the house's address goes into
        it only when its owner says which address to use, and only
        that address: the setting is off until then, off means the
        name prints as text, and Internal never reaches for the
        external address.
        """
        choice = self.entry.options.get(
            CONF_REPORT_LINKS, DEFAULT_REPORT_LINKS
        )
        if choice not in (REPORT_LINKS_EXTERNAL, REPORT_LINKS_INTERNAL):
            return None
        base = self._configured_url(choice)
        return base + path if base else None

    def _configured_url(self, choice: str) -> str | None:
        """The external or internal address, as Home Assistant knows
        it, or None where that one is not configured."""
        from homeassistant.helpers.network import get_url

        try:
            return get_url(
                self.hass,
                allow_internal=choice == REPORT_LINKS_INTERNAL,
                allow_external=choice == REPORT_LINKS_EXTERNAL,
                prefer_external=choice == REPORT_LINKS_EXTERNAL,
            )
        except Exception:  # noqa: BLE001 - that address is not set
            return None

    def _device_cell(
        self, device_id: str | None, name: str, *, area: bool = True
    ) -> str:
        """A device's name for an HTML report: linked, with its area.

        Issue #13. On a large house a name alone means nothing: every
        temperature sensor can be called "Temperature & Humidity", and
        the person reading the report has to go and find out which one
        it is. The name links to its device page and carries its area
        in square brackets.

        The link opens the device's page on the Device Sentinel
        dashboard, which says why the device is listed (0.23.5, in
        place of Home Assistant's device page), on the address the
        Links in Reports setting names and never another: None prints
        the name plain, Internal never reaches for the external
        address, and an address later removed from Home Assistant
        prints the name plain. The area sits outside the link, so what
        is clickable is the name itself.

        Two things are left plain. A row that belongs to the house
        rather than to a device, which has no id to link to. And a
        name that already ends in a bracket, "Soil Moisture
        (Monstera)", where the name is doing the same work the area
        would and two brackets in a row read as afterthoughts.
        """
        text = escape(name or "")
        cell = text
        url = (
            self._report_link(f"/{PANEL_URL_PATH}/device/{device_id}")
            if device_id
            else None
        )
        if url:
            cell = f'<a href="{escape(url, True)}">{text}</a>'
        if not device_id:
            return cell
        if not area:
            # The name grids list devices that are behaving. A room is
            # worth a column's width when something is wrong, not when
            # a list is there to be skimmed past.
            return cell
        if (name or "").rstrip().endswith(")"):
            # The name is already doing the work the area would, and
            # two brackets in a row read as afterthoughts.
            return cell
        room = self._device_area(device_id)
        # A device in no area says so, briefly: a reader who sees an
        # area beside every other name should not be left wondering
        # whether this one was looked up at all.
        return f"{cell} [{escape(room) if room else 'None'}]"

    def _device_status(self, device_id: str) -> str:
        """Return a device's muting status for the report column.

        Two states, one grammar: "Reported" when nothing mutes it,
        or "Muted (...)" naming why. GLB is the global mute,
        shown alone because it covers everything and a globally
        muted device is never offered to the section lists. BAT,
        SIG, and FRZ are the section muting, listed in column order
        when more than one applies.

        A todo icon lived here for one release and moved to the
        Reporting Devices section: the same state shown twice was
        redundant and confusing, and that section is where a fault's
        whole story reads, list state included.
        """
        if device_id in self._muted_devices:
            return "Muted (GLB)"
        tags = []
        if self._battery_muted(device_id):
            tags.append("BAT")
        if self._signal_muted(device_id):
            tags.append("SIG")
        if self._freeze_muted(device_id):
            tags.append("FRZ")
        if tags:
            return f"Muted ({', '.join(tags)})"
        return "Reported"


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
        # The maintainer files came back up out of the diagnostics
        # subfolder when the Markdown brief retired (rulings #178 and
        # #179); since 0.23.5 the HTML brief lives here beside them,
        # the www folder being gone. The old
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
        # The signal and battery reports retired with the www folder
        # (0.23.5): the dashboard's Signal Trends and Battery Trends
        # tabs carry what they did, behind Home Assistant's sign-in.
        # The brief's window runs from the last brief time to now, so
        # a regenerate mid-day writes the in-progress one. The
        # scheduled write closes the day instead, covering the window
        # that just ended rather than the one just beginning (#116).
        closing = trigger == BRIEF_TRIGGER
        if closing:
            window_start, window_end = self._brief_close_bounds()
        else:
            # The live copy carries a rolling day rather than the
            # hours since the brief time (ruling #187): for most of
            # the day the brief-to-brief window held almost nothing,
            # so the file read "nothing happened" while a full day of
            # events had passed. Now stays live either way, since it
            # is read from the problem list rather than from the
            # window.
            window_end = dt_util.utcnow().timestamp()
            window_start = window_end - BRIEF_LIVE_WINDOW_SECONDS
        brief_text = self._write_brief(
            report_directory,
            trigger,
            window_start,
            window_end,
            complete=closing,
        )
        # A scheduled write closes the day that just ended and hands
        # it to the email; the file then carries the day just
        # beginning at once, rather than the closed day until the
        # next startup or regenerate (ruling #116).
        if closing:
            now = dt_util.utcnow().timestamp()
            self._write_brief(
                report_directory,
                trigger,
                now - BRIEF_LIVE_WINDOW_SECONDS,
                now,
                complete=False,
            )
        return brief_text
