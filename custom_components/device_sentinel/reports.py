# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: reports.py, Version: 0.27.10 (2026-10-27)

"""The report writers, split out of the coordinator for legibility.

This is a file split rather than a boundary: the methods here read a
great deal of coordinator state and are mixed in rather than composed,
so `self` is the coordinator and nothing in this file can be
instantiated or tested on its own.

What lives here is the shared half: the formatters every report uses,
the link helper, and the orchestrator that calls the writers. Each
report is its own module beside this one (rule CODE-11).

The seam is the report rather than the audience, because one
orchestrator writes both maintainer and person-facing files, the
address resolver and the cell escaper serve both, and the telemetry's
signal columns come from the same bad-day judgment the dashboard
draws.

The composition is inheritance rather than delegation. These are
mixins on the coordinator, so moving a method between them changes
nothing about how it runs.
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
    LOGGER,
    CLASSIFICATION_SETTLED_TRIGGER,
    UNASSIGNED_AREA,
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
from .durations import compact_span, LONG_SPAN_SECONDS, long_span


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
        """Return a local time a person reads at a glance, the month
        spelled out, the day, the year and "at 7:19 AM". Built without
        strftime's platform specific %-d and %-I so it is the same on
        every host: the month name and AM/PM come from strftime, the
        day and hour are integers so they carry no leading zero.
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
        device is called (rule CODE-10).

        Angle brackets are escaped the same way, with a backslash, so a
        name holding markup does not draw when a report is pasted into
        a page that renders Markdown. The backslash is Markdown's own
        escape, reads plainly in the raw file, and is taken back off by
        the brief's page, which escapes for HTML itself.

        Square brackets are escaped too, because a name holding
        "![x](https://...)" or "[x](https://...)" would draw an outside
        picture or a link wherever the text is shown as Markdown: the
        brief delivered as a Home Assistant notification, or a report
        pasted into a page. Both need brackets, so escaping them is
        enough, and names like "Soil Irrigation (Monstera)" stay plain.
        """
        return (
            text.replace("\n", " ")
            .replace("\r", " ")
            .replace("|", "\\|")
            .replace("<", "\\<")
            .replace(">", "\\>")
            .replace("[", "\\[")
            .replace("]", "\\]")
        )

    def _fmt_gap(self, seconds: Any) -> str:
        """Format a gap for the report.

        A gap held at the retention reads "more than" it: the silence
        was at least that long, and how much longer is no longer kept
        (rule FRZ-13).
        """
        if seconds is None:
            return "-"
        value = float(seconds)
        cap = self.gap_cap()  # type: ignore[attr-defined]
        # Words from two days up, as the Daily Brief (rule GEN-09).
        if value >= LONG_SPAN_SECONDS and (cap is None or value < cap):
            return long_span(value)
        return compact_span(value, cap=cap)

    @staticmethod
    def _human_span(seconds: float | None) -> str:
        """Return a duration in the units a person thinks in."""
        if seconds is None:
            return "?"
        seconds = max(0.0, seconds)
        if seconds >= LONG_SPAN_SECONDS:
            return long_span(seconds)
        return compact_span(seconds)


    def _device_area(self, device_id: str) -> str:
        """Return the device's area name, or an empty string.

        Shown in brackets beside a device's name in the brief's and the
        reports' tables, so a reader sees where to go (rule BRIEF-13).
        """
        from homeassistant.helpers import area_registry as ar

        device = dr.async_get(self.hass).async_get(device_id)
        if not device or not device.area_id:
            return ""
        area = ar.async_get(self.hass).async_get_area(device.area_id)
        return area.name if area else ""


    def _report_link(self, path: str) -> str | None:
        """The address a report links to, or None for no link.

        The brief is a file that gets shared and forwarded, so the
        house's address goes into it only when its owner says which
        address to use, and only that address: the setting is off until
        then, off means the name prints as text, and Internal never
        reaches for the external address (rule BRIEF-13).
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

    def _write_classification_settled(self) -> None:
        """Write classification.md again once the startup grace closes.

        The setup report is written before every integration has
        loaded, so a device waiting on one reads as watched in it and
        is set aside only when the grace closes, such as a ZHA
        coordinator minutes after its radio restarted (rule WATCH-10).
        So the file ends on the settled answer.
        """
        report_directory = self.hass.config.path(REPORT_DIR)
        os.makedirs(report_directory, exist_ok=True)
        self._write_classification(report_directory, CLASSIFICATION_SETTLED_TRIGGER)

    async def _rewrite_classification(self) -> None:
        """Rewrite the classification report off the event loop, in its
        turn with the other report writes (rule CODE-06)."""
        try:
            async with self._report_lock:  # type: ignore[attr-defined]
                await self.hass.async_add_executor_job(
                    self._write_classification_settled
                )
        except OSError as err:
            LOGGER.warning(
                "Device Sentinel could not rewrite its classification report: %s",
                err,
            )

    def _device_cell(
        self, device_id: str | None, name: str, *, area: bool = True
    ) -> str:
        """A device's name for an HTML report: linked, with its area.

        On a large house a name alone means nothing: every temperature
        sensor can be called "Temperature & Humidity", and the person
        reading the report has to go and find out which one it is. The
        name links to its device page and carries its area in square
        brackets.

        The link opens the device's page on the Device Sentinel
        dashboard, which says why the device is listed, on the address
        the Links in Reports setting names and never another: None
        prints the name plain, Internal never reaches for the external
        address, and an address later removed from Home Assistant
        prints the name plain (rule BRIEF-13). The area sits outside
        the link, so what is clickable is the name itself.

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
        # whether this one was looked up at all. In the word the bus
        # events use, Unassigned, so the reports and the events agree.
        return f"{cell} [{escape(room) if room else UNASSIGNED_AREA}]"

    def _device_status(self, device_id: str) -> str:
        """Return a device's muting status for the report column.

        Two states, one grammar: "Reported" when nothing mutes it,
        or "Muted (...)" naming why. GLB is the global mute,
        shown alone because it covers everything and a globally
        muted device is never offered to the section lists. BAT,
        SIG, FRZ and UNAV are the section muting, listed in column
        order when more than one applies.

        A todo icon lived here for one release and moved to the
        Devices With a Fault section: the same state shown twice was
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
        # Each mute that is set is named, each its own kind
        # (rule MUTE-10).
        if self._freeze_muted_own(device_id):
            tags.append("FRZ")
        if self._unavailable_muted(device_id):
            tags.append("UNAV")
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
        would see half a page (rule BRIEF-14).

        Nothing is lost either way, because every report regenerates
        at the next write. What this buys is that the file on disk is
        always a whole report, the old one or the new one and never a
        piece of both. The temporary name sits beside the target so
        the move stays within one filesystem; a temp directory
        elsewhere would make os.replace a copy and lose the property.

        Failure is left to the caller, which catches it. An executor
        job handles nothing on its own: an OSError raised in one
        escapes into Home Assistant's task machinery and lands in a
        person's log as an unretrieved task exception. A report that
        cannot be written is a worse report rather than a broken
        integration (rule CODE-06).
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

    def _write_one_report(
        self, name: str, writer: Any, report_directory: str, trigger: str
    ) -> None:
        """Write one report, and if it fails, log it and carry on.

        A file error is logged as a warning, as before. Anything else
        is a fault in the report or in what it read, and is logged with
        its traceback once per report per start, so the person can
        report it, without stopping the reports after it.
        """
        try:
            writer(report_directory, trigger)
        except OSError as err:
            LOGGER.warning("Device Sentinel could not write %s: %s", name, err)
        except Exception:  # noqa: BLE001 - one report never stops the rest
            failed: set[str] | None = getattr(self, "_report_failed", None)
            if failed is None:
                failed = set()
                self._report_failed = failed
            if name in failed:
                LOGGER.debug("Device Sentinel could not write %s again", name)
                return
            failed.add(name)
            LOGGER.exception(
                "Device Sentinel could not write %s; the other reports "
                "and the brief are written without it. Said once per "
                "start (ruling #544)",
                name,
            )

    def _write_reports(self, trigger: str = "manual") -> str | None:
        """Write the report files, and return a closed brief if one.

        They live under /config because custom_components is code and
        is overwritten on every update (rule BRIEF-14). Written at
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
        # The maintainer files live beside the brief, not in the old
        # diagnostics subfolder (rule BRIEF-14). The old subfolder's
        # three files are removed once; anything else in it, the rig
        # log included, is not this integration's to touch.
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
        # Each report on its own: one that fails is logged and skipped,
        # and the rest are written, the brief among them, so a single
        # impossible value in one report's input cannot stop every
        # report after it and the brief's send (rule STOR-07).
        self._write_one_report(REPORT_TELEMETRY, self._write_telemetry, report_directory, trigger)
        self._write_one_report(REPORT_CLASSIFICATION, self._write_classification, report_directory, trigger)
        self._write_one_report(REPORT_EPISODES, self._write_episodes, report_directory, trigger)
        # The dashboard's Signal Trends and Battery Trends tabs carry
        # the signal and battery reports, behind Home Assistant's
        # sign-in. The brief's window runs from the last brief time to
        # now, so a regenerate mid-day writes the in-progress one. The
        # scheduled write closes the day instead, covering the window
        # that just ended rather than the one just beginning
        # (rule BRIEF-10).
        closing = trigger == BRIEF_TRIGGER
        if closing:
            window_start, window_end = self._brief_close_bounds()
        else:
            # The live copy carries a rolling day rather than the
            # hours since the brief time, because for most of the day
            # the brief-to-brief window holds almost nothing and the
            # file would read "nothing happened" after a full day of
            # events. Now stays live either way, since it is read from
            # the problem list rather than from the window
            # (rule BRIEF-10).
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
        # next startup or regenerate (rule BRIEF-10).
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
