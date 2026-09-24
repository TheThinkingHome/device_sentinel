# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_brief.py, Version: 0.23.2 (2026-09-24)

"""The daily brief: the one report written for a person.

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

import json
import os
import re
from datetime import timedelta
from html import escape
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from . import attribution, escalation
from .repairs import (
    _english_list,
    delivery_is_configured,
    missing_targets,
)
from .const import (
    TODO_KIND_FLAPPING,
    STACK_DISPLAY_NAMES,
    DEV_SIGNAL_VALUE,
    FLOOD_MIN_DAYS,
    FLOOD_MIN_STORMS,
    FLOOD_WINDOW_DAYS,
    RECOMMENDATION_LIBRARY,
    LIBRARY_FALSE_ALERTS,
    LIBRARY_NO_DEVICES,
    CONF_REPORT_LINKS,
    DEFAULT_REPORT_LINKS,
    REPORT_LINKS_EXTERNAL,
    REPORT_LINKS_INTERNAL,
    CONF_MUTED_INTEGRATIONS,
    CONF_REPEAT_FLOOR,
    DEFAULT_REPEAT_FLOOR,
    REPEAT_FLOOR_MAX,
    REPEAT_FLOOR_MIN,
    REPEAT_WINDOW_DAYS,
    BRIEF_NOTEWORTHY_SECONDS,
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_SET_ASIDE,
    ACTION_UNACKNOWLEDGED,
    CONF_REMINDER_TIME,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEFAULT_REMINDER_TIME,
    DEV_BATTERY_VALUE,
    DEV_FROZEN_SINCE,
    FREEZE_KINDS_FOR_CAUSE,
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
    REPORT_BATTERY_URL,
    REPORT_BRIEF_HTML,
    REPORT_BRIEF_PREFIX,
    REPORT_SIGNAL_URL,
    REPORT_WWW_DIR,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_WIFI_DOWN,
    SYS_WIFI_UP,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_RECOVERY_WITHDRAWN,
    SYS_BROKER_DOWN,
    SYS_DEVICES,
    SYS_WORST,
    SYS_STORM_CLOSED,
    SYS_STORM_OPEN,
    SYS_BROKER_UP,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_EPOCH_RESET,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_TRIMMED,
    DATA_STORM_DAYS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_INTERVAL,
    SYS_STORAGE_SHAPE,
    SYS_STORAGE_REPAIR,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_PAIRING_CLOSED,
    SYS_BATTERY_REPLACED,
    SYS_DEVICE_HANDLED,
    SYS_PAIRING_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_SCOPE_SYSTEM,
    SYS_UNCLEAN_RESTART,
    SYS_WHEN,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_SORT_NAME,
    TODO_STATUS,
)
from .outage_detail import FAILED, parse_detail


def _plural(count: int) -> str:
    """Return a count of devices as a person would write it.

    The count is known when the sentence is written, so "device(s)"
    is an evasion rather than a shorthand (ruling #233).
    """
    return f"{count} device" if count == 1 else f"{count} devices"


# What `_report_cell` escapes with a backslash, and the pipe that
# divides table cells as distinct from the one a name carries. The
# page escapes for HTML itself, so the backslashes come off first.
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_MARKDOWN_ESCAPED = re.compile(r"\\([|<>])")


def _markdown_unescaped(text: str) -> str:
    """Return report text with the report cell's escapes taken off."""
    return _MARKDOWN_ESCAPED.sub(r"\1", text)


# What a repeat-offender line calls one occurrence of each kind.
# "Interruption" covers the freeze family; the battery kinds get
# their own noun because "unexplained interruption" misdescribes a
# threshold crossing (ruling #305).
_REPEAT_NOUNS = {
    TODO_KIND_LOW_BATTERY: "low-battery alarm",
    TODO_KIND_FALLING_BATTERY: "falling-battery alarm",
}

# The author's own wording, printed verbatim beneath the Repeat
# Offenders table (ruling #374).
REPEAT_PARAGRAPH = (
    "This table lists repeat offenders. Every row represents a "
    "device that failed more than once in the last seven days "
    "for no obvious reason. We ruled out the usual causes. These "
    "failures did not happen during a system restart, a "
    "coordinator outage, a network or integration outage, or work "
    "you did yourself in Maintenance Mode. To help you track down "
    "the real problem, the table "
    "attempts to correlate a cause by grouping devices that failed "
    "at the same moment. If multiple devices fail together, it "
    "usually means the cause is shared. A device on this list is a "
    "candidate for muting or excluding if you recognize the cause, "
    "like a smart TV whose state goes unavailable when it is "
    "switched off."
)




# The words under the recommendations, the owner's of 18 September.
# One constant, because the brief and the dashboard's tab both print it.
RECOMMENDATIONS_CLOSING = (
    "These are suggestions based on observations that the integration "
    "has made. Device Sentinel is meant to monitor physical devices. Not "
    "all integrations own physical devices and therefore should not be "
    "monitored. When a setting that the integration depends on is not "
    "properly configured, Device Sentinel will notify you here. Making "
    "these changes will make the integration more efficient, and record "
    "and interpret data that is meaningful."
)

class BriefMixin:
    """The daily brief: the one report written for a person."""

    @staticmethod
    def _brief_moment(epoch: float) -> str:
        """Return a readable local time for the brief."""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %-d, %-I:%M %p")

    @staticmethod
    def _brief_log_moment(epoch: float) -> str:
        """A time to the second, for the Last 24 Hours table.

        The table is the record a tester reads back after a staged
        outage (ruling #444), where a minute is too coarse to order
        what happened. The summary above it keeps minutes, because a
        person reading it wants the story, not the stopwatch.
        """
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %-d, %-I:%M:%S %p")

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
        phrase, which over two weeks is the column that says
        whether a device recovers on its own or only when levered.
        """
        kind = row[INC_KIND]
        event = row[INC_EVENT]
        # A worse problem replacing a lesser one: one change, never a
        # recovery (0.22.27).
        change = self._change_clause(row, "table")
        if change is not None:
            return change
        if event == INCIDENT_RESOLVED:
            # No duration means the opening is gone and nothing could
            # measure the gap, which the retention rule makes rare and
            # a storage repair can still cause (ruling #438). Say what
            # is known rather than printing the question mark that
            # `_human_span` gives a table column where every other row
            # carries a number.
            seconds = row.get(INC_DURATION)
            cause = row.get(INC_CAUSE)
            # A closed signal problem says so, as the sentence does.
            what = "signal recovered" if kind == TODO_KIND_RAILED_SIGNAL else "recovered"
            base = (
                f"{what} after {self._human_span(seconds)}"
                if seconds is not None
                else what
            )
            return f"{base}, {cause}" if cause else base
        if event == INCIDENT_ACTION:
            return {
                ACTION_ACKNOWLEDGED: "acknowledged",
                ACTION_UNACKNOWLEDGED: "acknowledgment removed",
                ACTION_DELETED: "deleted from the list",
                ACTION_READDED: "re-added, the problem is still there",
                # Nothing recovered and nobody acted: the watching
                # stopped. Saying so keeps the table from claiming an
                # acknowledgment nobody made (ruling #369).
                ACTION_SET_ASIDE: "set aside, no longer watched",
            }.get(row.get(INC_CAUSE) or "", "acknowledged")
        if event == INCIDENT_ACKNOWLEDGED:
            # Legacy rows only, removable after 2026-08-11.
            return "acknowledged"
        if kind == TODO_KIND_LOW_BATTERY:
            # Borrowed from the composer so the table and the prose
            # cannot disagree about the same event: one composer
            # serves every channel, so nothing is described two ways
            # (ruling #120). The level belongs in both or neither.
            return self._battery_phrase(row[INC_DEVICE_ID], False)
        wording = {
            TODO_KIND_FLAPPING: "started dropping out again and again",
            TODO_KIND_FROZEN: "stopped reporting",
            TODO_KIND_NEVER_REPORTED: "has never reported",
            TODO_KIND_UNAVAILABLE: "went unavailable",
            TODO_KIND_UNKNOWN: "went unknown",
            TODO_KIND_RAILED_SIGNAL: "signal railed",
            TODO_KIND_FALLING_BATTERY: "battery is running down",
        }
        return wording.get(kind, kind)

    def _brief_falling_text(self, device_id: str) -> str:
        """Return the falling clause with its time left where known.

        Read from the same rows the report and the sensor use, so a
        person cannot be told two different times for one cell
        (ruling #215).
        """
        for row in self.battery_falling_list:
            if row.get("device_id") == device_id:
                return f"battery empty in {row['left']}"
        return "battery running down"

    def _brief_now_rows(
        self,
    ) -> list[tuple[str, str, float, str, str]]:
        """Return the standing state: what is wrong right now.

        Read from the problem list rather than recomputed, so the
        brief and the list can never disagree. Muted devices are
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
        # Name, problem, since, kind and device id: the id joined
        # the tuple and the annotation did not follow (ruling #331).
        rows: list[tuple[str, str, float, str, str]] = []
        for record in self.todo_items:
            device_id = record.get(TODO_DEVICE_ID)
            if not device_id or device_id in self._muted_devices:
                continue
            if record.get(TODO_STATUS) == "completed":
                continue
            name = record.get(TODO_SORT_NAME) or device_id
            kinds = record.get(TODO_KINDS) or {}
            for kind, since in kinds.items():
                if kind == TODO_KIND_UNAVAILABLE and TODO_KIND_FLAPPING in kinds:
                    # The flap is the row; its drops are not (0.23.2).
                    continue
                problem = {
                    TODO_KIND_FLAPPING: self.flap_words(device_id),
                    TODO_KIND_FROZEN: "stopped reporting",
                    TODO_KIND_NEVER_REPORTED: "never reported",
                    TODO_KIND_UNAVAILABLE: "unavailable",
                    TODO_KIND_UNKNOWN: "unknown",
                    TODO_KIND_RAILED_SIGNAL: "signal railed",
                    TODO_KIND_LOW_BATTERY: self._brief_battery_text(device_id),
                    TODO_KIND_FALLING_BATTERY: (
                        self._brief_falling_text(device_id)
                    ),
                }.get(kind, kind)
                rows.append((name, problem, since or now, kind, device_id))
        rows.sort(key=lambda row: row[2])
        return rows

    @staticmethod
    def _worst_words(row: dict[str, Any], sentence: bool) -> str | None:
        """How many devices an ended outage took, or None.

        The worst moment beside the total (ruling #442), never a count
        taken partway through. A row written before 0.21.12 carries no
        worst figure and keeps its old wording.
        """
        if SYS_WORST not in row:
            return None
        # The storage check vouches for both as whole numbers, and for
        # the total as present or absent (ruling #370).
        worst = row[SYS_WORST]
        total = row.get(SYS_DEVICES)
        noun = "device" if total == 1 else "devices"
        if total is None:
            count = "No" if worst == 0 else str(worst)
            plain = "device" if worst == 1 else "devices"
            text = f"{count} {plain} went down"
            return f"{text}." if sentence else text.lower()
        if total == 1 and worst == 1:
            # "1 of its 1 device went down" reads as arithmetic where
            # a sentence would do (ruling #452), and matches the row's
            # own wording.
            return "Its one device went down." if sentence else (
                "its one device went down"
            )
        if sentence:
            count = "None" if worst == 0 else str(worst)
            return f"{count} of its {total} {noun} went down."
        count = "none" if worst == 0 else str(worst)
        return f"{count} of {total} {noun} went down"

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
        # One device's own entry (0.22.23): the device is offline and
        # its connection is the reason, rather than the whole
        # integration being down.
        device = self.outage_device_name(detail)
        if device is not None and kind in (SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP):
            title = self._integration_title(str(scope))
            if kind == SYS_INTEGRATION_DOWN:
                how = (
                    "failed to start"
                    if parse_detail(detail)[2] == FAILED
                    else "went down"
                )
                return f"{device} is offline: its {title} connection {how} at {when}."
            worst = self._worst_words(row, sentence=True)
            said = (
                f"{device} is back: its {title} connection came back at {when} after {held}."
                if held
                else f"{device} is back: its {title} connection came back at {when}."
            )
            return f"{said} {worst}" if worst else said
        if kind == SYS_INTEGRATION_DOWN:
            return f"The {scope} integration went down at {when}."
        worst = self._worst_words(row, sentence=True)
        if kind == SYS_INTEGRATION_UP:
            said = (
                f"The {scope} integration came back at {when} after "
                f"{held}."
                if held
                else f"The {scope} integration came back at {when}."
            )
            return f"{said} {worst}" if worst else said
        if kind == SYS_BRIDGE_DOWN:
            return f"The {scope} bridge went down at {when}."
        if kind == SYS_BRIDGE_UP:
            said = (
                f"The {scope} bridge came back at {when} after {held}."
                if held
                else f"The {scope} bridge came back at {when}."
            )
            return f"{said} {worst}" if worst else said
        # The broker names itself rather than its scope, because a
        # house has one and "the mqtt broker" reads as a stack name
        # to somebody who does not know the difference.
        if kind == SYS_STORM_OPEN:
            return f"The {scope} integration reloaded at {when}."
        if kind == SYS_STORM_CLOSED:
            count = row.get(SYS_DEVICES)
            if count:
                return (
                    f"It settled after {held or 'a moment'}, "
                    f"{_plural(count)} affected."
                )
            return f"It settled after {held or 'a moment'}."
        if kind == SYS_WIFI_DOWN:
            count = row.get(SYS_DEVICES)
            if count:
                return (
                    f"The WiFi network went down at {when}, "
                    f"{_plural(count)} behind it."
                )
            return f"The WiFi network went down at {when}."
        if kind == SYS_WIFI_RECOVERING:
            return (
                f"The WiFi network came back at {when}, and its devices "
                f"began reconnecting."
            )
        if kind == SYS_WIFI_RECOVERY_WITHDRAWN:
            return (
                f"The WiFi recovery stalled at {when} as devices dropped "
                f"again, so the outage continues."
            )
        if kind == SYS_WIFI_UP and worst:
            # The network came back when the recovery began, which has
            # its own line now; this one is the outage ending.
            said = (
                f"The WiFi outage ended at {when} after {held}."
                if held
                else f"The WiFi outage ended at {when}."
            )
            return f"{said} {worst}"
        if kind == SYS_WIFI_UP:
            count = row.get(SYS_DEVICES)
            tail = f", {_plural(count)} behind it" if count else ""
            if held:
                return (
                    f"The WiFi network came back at {when} after "
                    f"{held}{tail}."
                )
            return f"The WiFi network came back at {when}{tail}."
        if kind == SYS_BROKER_DOWN:
            return f"The MQTT broker went down at {when}."
        if kind == SYS_BROKER_UP:
            said = (
                f"The MQTT broker came back at {when} after {held}."
                if held
                else f"The MQTT broker came back at {when}."
            )
            return f"{said} {worst}" if worst else said
        if kind == SYS_DEVICE_HANDLED:
            # The device's own name rather than its id, and the plain
            # fact rather than the mechanism: somebody was at it
            # (ruling #362). The detail holds "<registry id> <kind>",
            # and the id is no use to a person.
            named = str(detail or "").split(" ", 1)[0]
            who = self._device_name(named) if named else "A device"
            return (
                f"{who} was handled at {when}: somebody re-paired, "
                f"reconfigured or removed it."
            )
        if kind == SYS_BATTERY_REPLACED:
            # "<registry id> <from> <to>": the name, and the two levels
            # that made it a new cell rather than a recovery (ruling
            # #397). One reading a day cannot tell a new cell from a
            # charge, so the sentence names both and claims neither
            # (ruling #455, issue #11).
            parts = str(detail or "").split(" ")
            who = self._device_name(parts[0]) if parts and parts[0] else "A device"
            levels = (
                f", {parts[1]}% to {parts[2]}%" if len(parts) >= 3 else ""
            )
            return (
                f"{who} had its battery replaced or recharged at "
                f"{when}{levels}. Its history starts again from that day."
            )
        if kind == SYS_PAIRING_OPEN:
            return f"A {scope} pairing window opened at {when}."
        if kind == SYS_PAIRING_CLOSED:
            if held:
                return (
                    f"The {scope} pairing window closed at {when} "
                    f"after {held}."
                )
            return f"The {scope} pairing window closed at {when}."
        if kind == SYS_MAINTENANCE_OPEN:
            return f"Maintenance mode was opened at {when}."
        if kind == SYS_MAINTENANCE_CLOSED:
            tail = f" ({detail})" if detail else ""
            if held:
                return (
                    f"Maintenance mode ended at {when} after "
                    f"{held}{tail}."
                )
            return f"Maintenance mode ended at {when}{tail}."
        if kind == SYS_UNCLEAN_RESTART:
            # The restart row above already carried the plain fact
            # that the system came back, so this one carries what was
            # different about it. Both are written deliberately
            # (ruling #163)
            # and read as a pair: what happened, then why the clocks
            # moved. On the morning after a real one this is the first
            # sentence read, so it says the count rather than leaving
            # the reader to find it in a diagnostics download.
            # The line says what it cost and stops (ruling #376):
            # the gap length and the timers restarted. What that
            # means for detection is the wiki's job. The moment named
            # is the shutdown itself, worked back from the resume the
            # row was written at, because "did not shut down cleanly
            # at" must point at the stop rather than the start.
            gap = row.get(SYS_DURATION) or 0.0
            stopped = self._brief_moment(
                (row.get(SYS_WHEN) or 0.0) - gap
            )
            count = str(detail or "").split(" ", 1)[0]
            costs: list[str] = []
            if held:
                costs.append(f"{held} went unwatched")
            if count.isdigit():
                costs.append(
                    f"{count} devices had their silence timers "
                    f"restarted"
                )
            if costs:
                return (
                    f"Home Assistant did not shut down cleanly at "
                    f"{stopped}: {' and '.join(costs)}."
                )
            return (
                f"Home Assistant did not shut down cleanly at "
                f"{stopped}."
            )
        if kind == SYS_EPOCH_RESET:
            extra = f" for {detail}" if detail else ""
            return f"Learned statistics were reset at {when}{extra}."
        if kind == SYS_OPTIONS_CHANGED:
            extra = f": {detail}" if detail else ""
            return f"Settings changed at {when}{extra}."
        if kind == SYS_TRIMMED:
            # The one destructive act performed on a person's
            # instruction, so the brief carries it even though the
            # person did it themselves (ruling #307). A week later
            # the question is why a device's history begins on a
            # Tuesday, and this is the sentence that answers it.
            extra = f" ({detail})" if detail else ""
            return (
                f"Learned history was erased at {when}{extra}. A copy "
                f"of storage was written first."
            )
        if kind == SYS_STORAGE_REPAIR:
            # A repair nobody can see afterwards did not happen as
            # far as the person is concerned (ruling #342), so the
            # sentence names the action and its source. A detail that
            # carries its own full stop keeps it (ruling #352): the
            # unconditional stop produced the double full stop the
            # reference brief showed twice on 27 August, and the
            # guard also repairs the rows already sitting in the
            # permanent event log with the old detail inside them.
            extra = f": {detail}" if detail else ""
            line = f"Storage repaired itself at {when}{extra}"
            return line if line.endswith(".") else f"{line}."
        if kind == SYS_STORAGE_SHAPE:
            # The check writes what it found rather than a count on
            # its own, because a person reading this cannot act on a
            # number and can act on a field name. It touches nothing
            # (ruling #278), so the sentence says so: this is a
            # report, not damage, and the reader should not go
            # looking for what was changed.
            extra = f" ({detail})" if detail else ""
            return (
                f"The storage check found a record that does not fit "
                f"at {when}{extra}. Nothing was changed."
            )
        return f"{kind} at {when}."

    def _system_event_phrase(self, row: dict[str, Any]) -> str:
        """The same event as a table cell rather than a sentence."""
        scope = row.get(SYS_SCOPE) or SYS_SCOPE_SYSTEM
        detail = row.get(SYS_DETAIL)
        span = row.get(SYS_DURATION)
        held = self._human_span(span) if span else None
        kind = row.get(SYS_KIND)
        worst = self._worst_words(row, sentence=False)
        tail = f", {worst}" if worst else ""
        device = self.outage_device_name(detail)
        if device is not None and kind in (SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP):
            title = self._integration_title(str(scope))
            if kind == SYS_INTEGRATION_DOWN:
                how = (
                    "failed to start"
                    if parse_detail(detail)[2] == FAILED
                    else "went down"
                )
                return f"{device} offline, its {title} connection {how}"
            return (
                f"{device} back, its {title} connection came back after {held}"
                if held
                else f"{device} back, its {title} connection came back"
            ) + tail
        if kind == SYS_RESTART:
            return (
                f"system restarted, {held} unwatched"
                if held
                else "system restarted"
            )
        if kind == SYS_INTEGRATION_DOWN:
            return f"{scope} integration went down"
        if kind == SYS_INTEGRATION_UP:
            return (
                f"{scope} integration came back after {held}"
                if held
                else f"{scope} integration came back"
            ) + tail
        if kind == SYS_BRIDGE_DOWN:
            return f"{scope} bridge went down"
        if kind == SYS_BRIDGE_UP:
            return (
                f"{scope} bridge came back after {held}"
                if held
                else f"{scope} bridge came back"
            ) + tail
        if kind == SYS_STORM_OPEN:
            return f"{scope} integration reloaded"
        if kind == SYS_STORM_CLOSED:
            count = row.get(SYS_DEVICES)
            return (
                f"{scope} integration settled after {held}, "
                f"{_plural(count)}"
                if held and count
                else f"{scope} integration settled"
            )
        if kind == SYS_WIFI_DOWN:
            return "WiFi network went down"
        if kind == SYS_WIFI_RECOVERING:
            return "WiFi network came back, devices reconnecting"
        if kind == SYS_WIFI_RECOVERY_WITHDRAWN:
            return "WiFi recovery stalled, outage continues"
        if kind == SYS_WIFI_UP and worst:
            return (
                f"WiFi outage ended after {held}"
                if held
                else "WiFi outage ended"
            ) + tail
        if kind == SYS_WIFI_UP:
            return (
                f"WiFi network came back after {held}"
                if held
                else "WiFi network came back"
            )
        if kind == SYS_BROKER_DOWN:
            return "MQTT broker went down"
        if kind == SYS_BROKER_UP:
            return (
                f"MQTT broker came back after {held}"
                if held
                else "MQTT broker came back"
            ) + tail
        if kind == SYS_PAIRING_OPEN:
            return f"{scope} pairing window opened"
        if kind == SYS_PAIRING_CLOSED:
            return (
                f"{scope} pairing window closed after {held}"
                if held
                else f"{scope} pairing window closed"
            )
        if kind == SYS_MAINTENANCE_OPEN:
            return "maintenance mode opened"
        if kind == SYS_MAINTENANCE_CLOSED:
            tail = f" ({detail})" if detail else ""
            return (
                f"maintenance mode ended after {held}{tail}"
                if held
                else f"maintenance mode ended{tail}"
            )
        if kind == SYS_UNCLEAN_RESTART:
            return (
                f"unclean shutdown ({detail})"
                if detail
                else "unclean shutdown"
            )
        if kind == SYS_DEVICE_HANDLED:
            # The table row is per event and already sits beside the
            # device's own rows, so it says what happened without
            # repeating the id, which is no use to a person.
            action = str(detail or "").split(" ", 1)
            what = action[1] if len(action) > 1 else ""
            plain = {
                "device_joined": "re-paired",
                "raw_device_initialized": "reconfigured",
                "device_fully_initialized": "re-paired or reconfigured",
                "device_removed": "removed",
            }.get(what, "handled")
            return f"a device was {plain} by hand"
        if kind == SYS_BATTERY_REPLACED:
            parts = str(detail or "").split(" ")
            levels = (
                f" ({parts[1]}% to {parts[2]}%)" if len(parts) >= 3 else ""
            )
            return f"battery replaced or recharged{levels}"
        if kind == SYS_EPOCH_RESET:
            return f"learned statistics reset ({detail})" if detail else "learned statistics reset"
        if kind == SYS_OPTIONS_CHANGED:
            return f"settings changed ({detail})" if detail else "settings changed"
        if kind == SYS_TRIMMED:
            return (
                f"learned history erased ({detail})"
                if detail
                else "learned history erased"
            )
        if kind == SYS_STORAGE_SHAPE:
            return (
                f"storage check: {detail}"
                if detail
                else "storage check found a record that does not fit"
            )
        if kind == SYS_STORAGE_REPAIR:
            return (
                f"storage repaired: {detail}"
                if detail
                else "storage repaired itself"
            )
        return str(kind)

    def _option_label(self, key: str) -> str:
        """Return the label a person saw on the screen for an option.

        Read from strings.json rather than a table kept beside it. A
        table would say what somebody once believed the screen said,
        and the two would part on the first label anybody improved.
        The file is the screen, so this cannot drift and a new option
        arrives already named. The raw key is the fallback, which is
        wrong but visible.
        """
        labels = self._option_labels()
        return labels.get(key.strip(), key.strip())

    def _option_labels(self) -> dict[str, str]:
        """Return every option key's screen label, read once."""
        cached = getattr(self, "_option_label_cache", None)
        if cached is not None:
            return cached
        labels: dict[str, str] = {}
        try:
            path = os.path.join(os.path.dirname(__file__), "strings.json")
            with open(path, encoding="utf-8") as handle:
                steps = json.load(handle)["options"]["step"]
            for body in steps.values():
                for key, label in (body.get("data") or {}).items():
                    labels[key] = label
                # A field inside a section is still a field, and the
                # brief names a changed setting by what the person
                # read on the screen. Ruling #314 moved every mute
                # picker into a section, and reading only the loose
                # fields printed raw option keys in the morning
                # brief; the gate caught it, and it is the sort of
                # fault that would have reached a person's inbox.
                for block in (body.get("sections") or {}).values():
                    for key, label in (block.get("data") or {}).items():
                        labels[key] = label
        except (OSError, ValueError, KeyError):
            labels = {}
        self._option_label_cache = labels
        return labels

    def _house_sentences(
        self, sys_events: list[dict[str, Any]]
    ) -> list[str]:
        """Return what happened to the house, abnormal only.

        In Short is read rather than scanned, and a paragraph that
        reports normal behaviour is a paragraph nobody finishes
        (ruling #275). So an interruption earns a sentence only by
        lasting longer than BRIEF_NOTEWORTHY_SECONDS, and then only
        the longest one is told: seven restarts of thirty seconds are
        not seven events, they are a quiet night, and the Last 24
        Hours table below carries every one for anyone who wants
        them.

        This overturns ruling #230, which held that a second restart
        is a second event a person wants to see. It is not. That was
        decided when restarts were rare on the reference system, and
        a day with sixteen house sentences reading almost identically
        to the table beneath them showed it was wrong.

        Two things are always said, because neither is ever noise. A
        storm is somebody's integration misbehaving, already grouped
        per integration (ruling #230). A settings change is a person
        acting on their own system, and it is the reason tomorrow's
        data will differ from today's, so it is named with what
        changed.
        """
        rows = sorted(sys_events, key=lambda row: row[SYS_WHEN])
        said: list[str] = []
        said += self._quiet_run_sentences(rows)
        said += self._storm_sentences(rows)
        said += self._options_sentence(rows)
        said += self._other_house_sentences(rows)
        return said

    @staticmethod
    def _plain_interval(seconds: float | None) -> str:
        """Return an interval in whole words, for the advice lines."""
        if not seconds:
            return ""
        if seconds < 90:
            count, unit = round(seconds), "second"
        elif seconds < 5400:
            count, unit = round(seconds / 60), "minute"
        else:
            count, unit = round(seconds / 3600), "hour"
        return f"{count} {unit}{'' if count == 1 else 's'}"

    def _integration_title(self, domain: str) -> str:
        """The integration's name as Home Assistant shows it.

        Except where the dashboard's own status boxes already name it
        otherwise: Home Assistant calls ZHA "Zigbee Home Automation",
        the boxes and the outage lines call it ZHA, and one name for
        one thing is the rule (0.23.0, from Tim Plas's review).
        """
        if domain in STACK_DISPLAY_NAMES:
            return STACK_DISPLAY_NAMES[domain]
        try:
            return async_get_loaded_integration(self.hass, domain).name
        except Exception:  # noqa: BLE001 - a name is never worth a failure
            return domain

    def _noisy_integration_advice(self) -> list[str]:
        """Return one line per integration worth excluding for noise.

        Read from the storm tally, which since ruling #457 holds only
        storms nothing explains. An integration qualifies with at
        least FLOOD_MIN_STORMS such storms in a day on at least
        FLOOD_MIN_DAYS days of the last FLOOD_WINDOW_DAYS: a person
        testing hardware has a bad day, a poller has a bad week. The
        line recommends and never instructs (ruling #321), and it is
        gone the day the person excludes it or the noise stops.
        """
        rows = self.data.get(DATA_STORM_DAYS) or []
        today = dt_util.now().date()
        earliest = (today - timedelta(days=FLOOD_WINDOW_DAYS)).isoformat()
        excluded = self.excluded_integrations
        bad_days: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            domain = row.get(STORM_DAY_DOMAIN)
            day = str(row.get(STORM_DAY_DATE) or "")
            # An integration with no hardware of its own cannot be
            # excluded to any effect: it owns no device, and since
            # 0.22.21 its entities feed no burst. Bursts it logged
            # before then would otherwise keep the advice alive for
            # the whole window (0.22.21).
            if (
                not domain
                or domain in excluded
                or domain in self._no_hardware_integrations
                or day < earliest
            ):
                continue
            if int(row.get(STORM_DAY_COUNT) or 0) >= FLOOD_MIN_STORMS:
                bad_days.setdefault(domain, []).append(row)
        said: list[str] = []
        for domain, days in sorted(bad_days.items()):
            if len(days) < FLOOD_MIN_DAYS:
                continue
            worst = max(days, key=lambda row: int(row.get(STORM_DAY_COUNT) or 0))
            every = self._plain_interval(worst.get(STORM_DAY_INTERVAL))
            cadence = f"every {every}" if every else "over and over"
            said.append(
                f"One of the integrations being monitored by Device "
                f"Sentinel is a polling integration and consuming "
                f"resources: the {domain} integration is a poller and is "
                f"publishing its fleet data {cadence}. Device Sentinel "
                f"can learn nothing useful from a poller integration and "
                f"it should be excluded from the Exclusions and Muting "
                f"settings screen."
            )
        return said

    def _recommendation_items(self) -> list[str]:
        """Return every recommendation line, worst first.

        The order is what failing to act costs. A message that goes
        nowhere is lost the day it matters; a family muted for every
        device is switched off without saying so; a disabled entity
        blinds one reading; a router integration and a noisy one only
        make the rest harder to read (ruling #458). The words are the
        project owner's, approved 18 September.
        """
        items: list[str] = []
        screen = "the Notifications and Daily Brief settings screen"
        for target in missing_targets(self.hass, self.entry):
            items.append(
                f"Notifications Recipient Not Valid: {target} no longer "
                f"exists. Anything sent there is lost. Choose another "
                f"notification target from {screen}."
            )
        if not delivery_is_configured(self.entry):
            items.append(
                f"Notifications Recipient Not Set: no phone or brief "
                f"notification target is set. A problem reaches only the "
                f"persistent card and this page. Targets are set from "
                f"{screen}."
            )
        choice = self.entry.options.get(CONF_REPORT_LINKS, DEFAULT_REPORT_LINKS)
        if (
            choice in (REPORT_LINKS_EXTERNAL, REPORT_LINKS_INTERNAL)
            and self._configured_url(choice) is None
        ):
            which = "external" if choice == REPORT_LINKS_EXTERNAL else "internal"
            items.append(
                f"Your Home Assistant {which.title()} URL, which you have "
                f"chosen, is missing or invalid: Device names in reports "
                f"are set to be links with your {which} URL, and that URL "
                f"is misconfigured or not set. Set that address in Home "
                f"Assistant's network settings, or choose another under "
                f"Links in Reports on {screen}."
            )
        items += self._family_muted_items()
        adapter = getattr(self, "_wifi_adapter_unused", None)
        if adapter and not self.wifi_capable:
            items.append(
                f"Wi-Fi network not set in Device Sentinel's WiFi "
                f"settings: this machine is equipped with a wireless "
                f"adapter ({adapter}) and no network is chosen for it to "
                f"listen for. Naming your network on the WiFi screen "
                f"enables Device Sentinel to detect a wireless network "
                f"outage."
            )
        counts = self.awaiting_enable_counts()
        total = sum(counts.values())
        if total:
            kinds = [
                label for key, label in (
                    ("battery", "battery"),
                    ("signal", "signal"),
                    ("last_seen", "last seen"),
                )
                if counts.get(key)
            ]
            one = total == 1
            items.append(
                f"{'One' if one else 'Several'} of your devices' "
                f"{_english_list(kinds, limit=len(kinds))} entities "
                f"{'is' if one else 'are'} disabled: Device Sentinel "
                f"requires {'this entity' if one else 'these entities'} "
                f"to be enabled when {'it is' if one else 'they are'} "
                f"available. Press Fix on the Repairs card to turn "
                f"{'it on' if one else 'them all on'}, or use the Enable "
                f"buttons at the top of the Device Sentinel dashboard to "
                f"turn {'it' if one else 'them'} on by kind."
            )
        for reader in list(getattr(self, "_bridge_readers", {}).values()):
            # Off, not unknown: a reader that has not heard yet says
            # nothing rather than guessing (ruling #236 surfaces this
            # setting and never writes it).
            if getattr(reader, "availability_enabled", None) is False:
                items.append(
                    "Zigbee2MQTT availability is disabled: Device Sentinel "
                    "uses Z2M availability as a confirmation for outage "
                    "detection. Turning on Availability in Zigbee2MQTT's "
                    "settings gives Device Sentinel that second opinion."
                )
                break
        items += self._router_watched_items()
        items += self._noisy_integration_advice()
        items += self._library_items()
        return items

    def _library_items(self) -> list[str]:
        """Name watched integrations the library knows to be noise.

        Known rather than measured, so last in the order. An
        integration the person muted is left alone, since muting is
        already a view expressed about it (ruling #459).
        """
        excluded = self.excluded_integrations
        muted = set(self.entry.options.get(CONF_MUTED_INTEGRATIONS, []))
        per_domain: dict[str, int] = {}
        for domain in self._watched.values():
            per_domain[domain] = per_domain.get(domain, 0) + 1

        def present(domains: tuple[str, ...]) -> list[str]:
            return sorted(
                domain for domain in domains
                if per_domain.get(domain)
                and domain not in excluded
                and domain not in muted
            )

        said: list[str] = []
        false_alerts = present(RECOMMENDATION_LIBRARY[LIBRARY_FALSE_ALERTS])
        if false_alerts:
            names = sorted(
                (self._integration_title(domain) for domain in false_alerts),
                key=str.casefold,
            )
            plural = "s" if len(names) > 1 else ""
            said.append(
                f"Some integrations create false alerts: Exclude the "
                f"{_english_list(names, limit=len(names))} "
                f"integration{plural} to stop false alarms. Some "
                f"integrations are not beneficial to monitor because they "
                f"contain entities that become unavailable when the device "
                f"is turned off, leave the house WiFi, or contain "
                f"batteries that are recharged daily. Exclude these in "
                f"the Exclusions and Muting settings screen."
            )
        no_devices = present(RECOMMENDATION_LIBRARY[LIBRARY_NO_DEVICES])
        if no_devices:
            named = [
                f"{domain} ({per_domain[domain]} device"
                f"{'' if per_domain[domain] == 1 else 's'})"
                for domain in no_devices
            ]
            one = len(no_devices) == 1
            said.append(
                f"Some integrations own no devices and are not worth "
                f"monitoring: {_english_list(named, limit=len(named))} "
                f"{'is' if one else 'are'} watched. Integrations of this "
                f"kind add tools to Home Assistant rather than hardware, "
                f"so their devices go quiet for reasons that are not "
                f"faults. Exclude {'it' if one else 'them'} in the "
                f"Exclusions and Muting settings screen."
            )
        return said

    def _family_muted_items(self) -> list[str]:
        """Name a detection family muted for every device it judges.

        Muting every battery device is switching battery warnings off
        without the word off appearing anywhere, and a person who did
        it one device at a time may never have noticed the total.
        """
        records = self.data.get(DATA_DEVICES) or {}
        watched = [device_id for device_id in self._watched if device_id in records]
        families = (
            (
                "All devices are muted or excluded for freeze reporting",
                "frozen-device warnings", "devices", "device",
                "freeze", "Freeze Detection",
                watched, self._freeze_muted,
            ),
            (
                "All battery devices are muted or excluded for battery "
                "reporting",
                "low-battery warnings", "battery devices", "battery device",
                "battery", "Low Battery",
                [
                    device_id for device_id in watched
                    if records[device_id].get(DEV_BATTERY_VALUE) is not None
                ],
                self._battery_muted,
            ),
            (
                "All signal devices are muted or excluded for signal "
                "reporting",
                "weak-signal warnings", "signal devices", "signal device",
                "signal", "Signal Strength",
                [
                    device_id for device_id in watched
                    if records[device_id].get(DEV_SIGNAL_VALUE) is not None
                ],
                self._signal_muted,
            ),
        )
        said: list[str] = []
        for title, warnings, nouns, noun, family, screen, judged, muted in families:
            if not judged:
                continue
            if all(
                device_id in self._muted_devices or muted(device_id)
                for device_id in judged
            ):
                why = (
                    f"your only {noun} is muted"
                    if len(judged) == 1
                    else f"all {len(judged)} of your {nouns} are muted"
                )
                said.append(
                    f"{title}: You will not get any {warnings} because "
                    f"{why}. To receive {family} reports on the devices "
                    f"you wish to monitor, unmute or unexclude "
                    f"{'it' if len(judged) == 1 else 'them'} on the "
                    f"Exclusions and Muting, and the {screen} settings "
                    f"screen."
                )
        return said

    def _router_watched_items(self) -> list[str]:
        """Name a router integration the person has chosen to watch.

        Excluded once, when first seen (ruling #420); from then on the
        list is the person's, so this advises and never acts. The line
        carries how many devices the integration has registered.
        """
        excluded = self.excluded_integrations
        registry = er.async_get(self.hass)
        clients: dict[str, set[str]] = {}
        for entity in registry.entities.values():
            if (
                entity.domain == "device_tracker"
                and entity.platform in self._router_integrations_present()
                and entity.platform not in excluded
                and entity.device_id
            ):
                clients.setdefault(entity.platform, set()).add(entity.device_id)
        return [
            f"Eliminate noise from integrations that own no actual "
            f"devices: Device Sentinel is monitoring the {domain} "
            f"integration, and it has registered {len(devices)} virtual "
            f"device{'' if len(devices) == 1 else 's'} that duplicate "
            f"hardware other integrations own and that are already being "
            f"watched. It is recommended that the {domain} integration be "
            f"excluded from the Exclusions and Muting settings screen."
            for domain, devices in sorted(clients.items())
        ]

    def _recommendations_section(self) -> list[str]:
        """Return the Recommendations section, or nothing.

        What the person could change about their own setup, as
        opposed to what is wrong with a device, which is why it is not
        the problem list. Each line stands until its condition is gone
        and nothing is stored or dismissed. Worst first, and every
        line shown: with nothing to dismiss, a cap would hide the lines
        below it for as long as the ones above it stood (ruling #461,
        amending #458).
        """
        items = self._recommendation_items()
        if not items:
            return []
        lines = ["## Recommendations", ""]
        for item in items:
            lines += [item, ""]
        lines += [RECOMMENDATIONS_CLOSING, ""]
        return lines

    def _longest(
        self, rows: list[dict[str, Any]], kind: str, scope: str | None = None
    ) -> dict[str, Any] | None:
        """Return the longest run of one kind, when it is noteworthy."""
        candidates = [
            row
            for row in rows
            if row[SYS_KIND] == kind
            and (scope is None or row.get(SYS_SCOPE) == scope)
            and (row.get(SYS_DURATION) or 0) >= BRIEF_NOTEWORTHY_SECONDS
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: row.get(SYS_DURATION) or 0)

    def _quiet_run_sentences(
        self, rows: list[dict[str, Any]]
    ) -> list[str]:
        """Return sentences for the interruptions worth telling.

        A restart, a bridge outage and a broker outage are the same
        shape of thing: the house stopped listening for a while. Each
        is silent unless one instance ran long, and then it is told
        on its own, with its length and its time, because that is the
        only part a reader can act on.
        """
        said: list[str] = []
        # The gap ends at the time given, and a clean stop is named
        # as one (ruling #376): a clean stop wrote the file on the
        # way down and lost nothing. An unclean restart is excluded
        # here because its own sentence tells it, with what it cost,
        # and claiming "shut down cleanly" of it would be false.
        unclean = {
            row.get(SYS_WHEN)
            for row in rows
            if row.get(SYS_KIND) == SYS_UNCLEAN_RESTART
        }
        worst = self._longest(
            [
                row
                for row in rows
                if not (
                    row.get(SYS_KIND) == SYS_RESTART
                    and row.get(SYS_WHEN) in unclean
                )
            ],
            SYS_RESTART,
        )
        if worst is not None:
            said.append(
                "The system was shut down cleanly and was unwatched "
                f"for {self._human_span(worst[SYS_DURATION])}, "
                f"ending {self._brief_moment(worst[SYS_WHEN])}."
            )
        scopes: list[str] = []
        for row in rows:
            scope = row.get(SYS_SCOPE)
            if (
                row[SYS_KIND] == SYS_BRIDGE_UP
                and scope is not None
                and scope not in scopes
            ):
                scopes.append(scope)
        for scope in scopes:
            worst = self._longest(rows, SYS_BRIDGE_UP, scope)
            if worst is not None:
                said.append(
                    f"The {scope} bridge was down for "
                    f"{self._human_span(worst[SYS_DURATION])} at "
                    f"{self._brief_moment(worst[SYS_WHEN])}."
                )
        worst = self._longest(rows, SYS_BROKER_UP)
        if worst is not None:
            said.append(
                "The MQTT broker was down for "
                f"{self._human_span(worst[SYS_DURATION])} at "
                f"{self._brief_moment(worst[SYS_WHEN])}."
            )
        return said

    def _options_sentence(self, rows: list[dict[str, Any]]) -> list[str]:
        """Return one sentence naming what a person changed.

        Never suppressed however often it happens, because this is
        the sentence that explains why tomorrow's numbers moved. The
        settings are named by their screen labels, deduplicated and
        in the order first touched, since a person who changed the
        same one five times changed one setting.

        The separator is a semicolon because the labels themselves
        carry commas: Bad Day Drop, LQI and Bad Day Drop, RSSI are
        two settings, and a comma-separated list turned three
        changed settings into what read as five. One separator in
        every case rather than one shape for lists with commas and
        another for lists without.
        """
        changes = [row for row in rows if row[SYS_KIND] == SYS_OPTIONS_CHANGED]
        if not changes:
            return []
        names: list[str] = []
        for row in changes:
            for key in (row.get(SYS_DETAIL) or "").split(","):
                label = self._option_label(key)
                if label and label not in names:
                    names.append(label)
        listed = "; ".join(names)
        if len(changes) == 1:
            when = self._brief_moment(changes[0][SYS_WHEN])
            return [f"Settings changed at {when}: {listed}."]
        return [f"Settings changed {len(changes)} times: {listed}."]

    def _storms_inside_restart(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return the storm rows that are the restart, told twice.

        A storm inside a restart is the restart, and is not reported
        (ruling #375): the storm the reference brief called "the mqtt
        integration reloaded" was the last seconds before Home
        Assistant went down, and the restart row on the next line
        said the same thing more accurately. No new threshold: the
        test is the same restart window the incident attribution
        uses, which reaches a measured 90 seconds backward.

        A pair is the restart's only when both its moments fall
        inside a restart window. A storm that began before the
        window, or that is still open, is its own event and keeps
        its rows. Windows are built from the whole event log rather
        than the brief's slice, because a restart just outside the
        window still explains a storm just inside it.
        """
        events = self.data.get(DATA_SYSTEM_EVENTS) or []
        restarts = [
            window
            for window in attribution.windows(events)
            if window.kind in (SYS_RESTART, SYS_UNCLEAN_RESTART)
        ]
        if not restarts:
            return []

        def inside(moment: float) -> bool:
            return any(
                window.in_effect_at(moment) for window in restarts
            )

        suppressed: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        storms = sorted(
            (
                row
                for row in rows
                if row.get(SYS_KIND)
                in (SYS_STORM_OPEN, SYS_STORM_CLOSED)
            ),
            key=lambda row: row.get(SYS_WHEN) or 0.0,
        )
        for row in storms:
            scope = row.get(SYS_SCOPE) or ""
            if row.get(SYS_KIND) == SYS_STORM_OPEN:
                pending[scope] = row
                continue
            opened = pending.pop(scope, None)
            if opened is None:
                continue
            if inside(opened.get(SYS_WHEN) or 0.0) and inside(
                row.get(SYS_WHEN) or 0.0
            ):
                suppressed.append(opened)
                suppressed.append(row)
        return suppressed

    def _storm_sentences(self, rows: list[dict[str, Any]]) -> list[str]:
        """Return the storm sentences, grouped per integration.

        A storm is an integration republishing its whole fleet, which
        is never normal and never suppressed. Grouping is ruling
        #230's, unchanged: a polling integration trips the detector
        every cycle and the reference fleet produced twenty in an
        hour.
        """
        storms: dict[str, list[dict[str, Any]]] = {}
        pending: dict[str, int] = {}
        orphans: set[int] = set()
        for row in rows:
            kind, scope = row[SYS_KIND], row[SYS_SCOPE]
            if kind == SYS_STORM_OPEN:
                storms.setdefault(scope, []).append(row)
                pending[scope] = pending.get(scope, 0) + 1
            elif kind == SYS_STORM_CLOSED:
                if pending.get(scope, 0) <= 0:
                    orphans.add(id(row))
                else:
                    pending[scope] -= 1
        said: list[str] = []
        grouped: set[str] = set()
        for row in rows:
            kind, scope = row[SYS_KIND], row[SYS_SCOPE]
            if kind not in (SYS_STORM_OPEN, SYS_STORM_CLOSED):
                continue
            if id(row) in orphans:
                continue
            opens = storms.get(scope) or []
            if len(opens) < 2:
                said.append(self._system_event_sentence(row))
                continue
            if scope in grouped:
                continue
            grouped.add(scope)
            said.append(self._compose_storm_run(scope, opens, rows))
        return said

    def _compose_storm_run(
        self,
        scope: str,
        opens: list[dict[str, Any]],
        rows: list[dict[str, Any]],
    ) -> str:
        """Return one sentence for an integration that keeps storming.

        The size is the largest seen rather than the mean, because
        what a person wants from a repeated event is how big it gets.
        """
        first = self._clock(opens[0][SYS_WHEN])
        last = self._clock(opens[-1][SYS_WHEN])
        sizes = [
            row.get(SYS_DEVICES) or 0
            for row in rows
            if row[SYS_KIND] == SYS_STORM_CLOSED and row[SYS_SCOPE] == scope
        ]
        most = max(sizes) if sizes else 0
        # The largest of the group rather than a limit. "Up to 5
        # devices at a time" read as a cap on something, when it is
        # the biggest burst seen: a five-device poller and a
        # fifty-device hub reconnect wear the same word otherwise
        # (ruling #233).
        tail = f", the largest affecting {_plural(most)}" if most else ""
        return (
            f"The {scope} integration reloaded {len(opens)} times "
            f"between {first} and {last}{tail}."
        )

    def _other_house_sentences(
        self, rows: list[dict[str, Any]]
    ) -> list[str]:
        """Return the house events that are neither runs nor storms.

        Pairing windows, maintenance mode and an unclean restart keep
        one sentence each. Every one of them is either rare or the
        person's own doing, so none of them can flood the paragraph
        the way a restart can.
        """
        handled = {
            SYS_RESTART,
            SYS_BRIDGE_DOWN,
            SYS_BRIDGE_UP,
            SYS_BROKER_DOWN,
            SYS_BROKER_UP,
            SYS_WIFI_DOWN,
            SYS_WIFI_UP,
            # The recovery's own moments belong to the table, which is
            # the log (ruling #444); the summary tells the outage once.
            SYS_WIFI_RECOVERING,
            SYS_WIFI_RECOVERY_WITHDRAWN,
            SYS_STORM_OPEN,
            SYS_STORM_CLOSED,
            SYS_OPTIONS_CHANGED,
        }
        return [
            self._system_event_sentence(row)
            for row in rows
            if row[SYS_KIND] not in handled
        ]

    def _tell_episodes(
        self,
        pairs: list[tuple[dict[str, Any], dict[str, Any] | None]],
        sys_events: list[dict[str, Any]] | None,
    ) -> list[str]:
        """Return one sentence per episode, floods collapsed to one.

        A flood is not a count inside a time bucket. It is every
        episode the same recorded intervention explains, which is
        both narrower and wider than counting: two devices are a
        flood if one broker outage took them both, and a hundred
        unrelated ones in the same minute are not (ruling #228).
        Without this the reference fleet's brief carried a single
        paragraph of 7,375 characters and 74 sentences, one per
        device, for one broker outage.

        Grouping runs on both directions, since the same event puts
        every device on the list going in as well as coming out.
        """
        spans = attribution.windows(sys_events or [])
        told: list[str] = []
        # Which devices each sentence is about, kept beside it rather
        # than read back out of its words (ruling #304).
        owners: list[set[str]] = []
        groups: dict[Any, list[tuple[dict, dict | None]]] = {}
        placed: dict[Any, int] = {}
        for opened, resolved in pairs:
            device_id = opened[INC_DEVICE_ID]
            # An action row is a person's act, told on its own. It is
            # never a member of a flood: three acknowledgments inside
            # a restart's window are not "3 devices signal railed",
            # which is what grouping them produced the moment the
            # flapping collapse stopped hiding it.
            if opened.get(INC_EVENT) != INCIDENT_OPENED:
                told.append(
                    self._compose_episode(opened, resolved)
                    if resolved is not None
                    else self._compose_event(opened)
                )
                owners.append({device_id})
                continue
            window = (
                attribution.attribute(
                    spans,
                    self._watched.get(device_id),
                    self._device_stack(device_id),
                    opened[INC_WHEN],
                    resolved[INC_WHEN] if resolved is not None else None,
                    device_id,
                )
                if spans
                else None
            )
            if window is None:
                told.append(
                    self._compose_episode(opened, resolved)
                    if resolved is not None
                    else self._compose_event(opened)
                )
                owners.append({device_id})
                continue
            # An escalation groups only with escalations from the same
            # kind, so a flood sentence never loses the "from" (0.22.27).
            key = (
                window.key,
                opened[INC_KIND],
                opened.get(escalation.ESCALATED_FROM),
                resolved is not None,
            )
            if key not in placed:
                placed[key] = len(told)
                told.append("")
                owners.append(set())
            owners[placed[key]].add(device_id)
            groups.setdefault(key, []).append((opened, resolved))
        for key, members in groups.items():
            told[placed[key]] = self._compose_flood(key, members, spans)
        # Strict (ruling #328): told and owners are built together
        # one entry per device, so a length mismatch is a bug in this
        # method rather than a shape a stored file can produce.
        kept = [
            (line, who)
            for line, who in zip(told, owners, strict=True)
            if line
        ]
        return self._collapse_flapping(kept, pairs, sys_events or [])

    def _collapse_flapping(
        self,
        told: list[tuple[str, set[str]]],
        pairs: list[tuple[dict[str, Any], dict[str, Any] | None]],
        sys_events: list[dict[str, Any]],
    ) -> list[str]:
        """Return the told episodes with a flapping device said once.

        Ruling #228 collapsed a flood across devices: one broker
        outage taking seventy-four of them is one sentence. This
        collapses the other axis, one device across time. A device
        that stopped and recovered five times produced five sentences
        that differed only in their clock times, and five of those
        say less than one sentence with a count and a total does.

        Unlike the house events, a count is the information here. An
        interruption that repeats is not normal behaviour the way a
        nightly reboot is: it is the shape of a dying device, and the
        number of times is the symptom (ruling #276).

        Which sentences to drop is decided from the devices behind
        each one rather than from its opening words (ruling #304).
        The first version compared the line against the device's
        name, which cannot see a sentence that names no device: two
        flapping devices collapsed into "2 devices went unavailable
        at 3:35 PM" survived the filter, so 19 August's brief carried
        nine of those beside the two flapping sentences that already
        said it. A sentence goes only when every device in it is
        flapping. A real outage of seventy-four devices that happens
        to include one keeps its line, because the outage is news the
        flapping sentence does not carry.
        """
        # An acknowledgment is not an opening at all. The pairing
        # states that rule and this consumer now honours it: an
        # action row rode into these buckets as an unresolved going,
        # so a device that was acknowledged and fully recovered read
        # as "still silent" with an inflated count on the 25 August
        # brief. Only openings are goings.
        #
        # Buckets carry the kind beside the device, so a rail and a
        # 22 second unavailability on the same device no longer share
        # one sentence and one verb.
        by_bucket: dict[
            tuple[str, str], list[tuple[dict, dict | None]]
        ] = {}
        for opened, resolved in pairs:
            if opened.get(INC_EVENT) != INCIDENT_OPENED:
                continue
            by_bucket.setdefault(
                (opened[INC_DEVICE_ID], opened.get(INC_KIND)), []
            ).append((opened, resolved))
        # A silence the restarts only interrupted is not flapping and
        # is not recoveries: it is one outage the bookkeeping
        # segmented (ruling #308). Decided from the protocol clock
        # rather than the rows, because the rows are the thing that
        # lies here: the device's last true speech predates every
        # interruption in the window, so nothing in these pairs was a
        # recovery. A device that spoke anywhere in the window fails
        # the test and keeps the flapping sentence, which is what
        # keeps Presence Guest's real reconnects told as such.
        # Stitching's witness is the standing freeze verdict, so only
        # a freeze-family bucket can be claimed by it: a railed or a
        # battery bucket beside a standing freeze is its own news,
        # not a fragment of the silence.
        stitched = {
            key: members
            for key, members in by_bucket.items()
            if key[1] in FREEZE_KINDS_FOR_CAUSE
            and self._silence_never_broken(key[0], members)
        }
        # A device that has never reported is one standing condition,
        # not a device going and returning, so it keeps the sentence
        # that says so. Pairing sees two rows and would otherwise
        # read them as two silences.
        flapping = {
            key: members
            for key, members in by_bucket.items()
            if key not in stitched
            and len(members) > 1
            and key[1] != TODO_KIND_NEVER_REPORTED
        }
        # Remembered for the repeat-offender section (ruling #305,
        # amended): a device the day's flapping sentence already
        # carries is not named again below unless its pattern spans
        # more than this one brief, because the same device in two
        # sentences of one paragraph is the duplication #276 and
        # #304 both exist to prevent. A stitched device counts the
        # same way: its one sentence is its mention.
        self._flapping_told = {key[0] for key in flapping} | {
            key[0] for key in stitched
        }
        # Remembered for the Last 24 Hours table (ruling #308): the
        # rows behind a stitched sentence are bookkeeping, and a
        # table that keeps them beside the sentence that corrects
        # them says the wrong thing twice as often as the right one.
        self._stitched_told = {key[0] for key in stitched}
        if not flapping and not stitched:
            return [line for line, _who in told]
        gone = self._flapping_told
        kept = [
            line
            for line, who in told
            if not (who and who <= gone)
        ]
        for members in flapping.values():
            kept.append(self._compose_flapping(members))
        # One stitched sentence per device however many of its kinds
        # were claimed: unavailable and frozen fragments of one
        # unbroken outage are the same outage, and two identical
        # sentences say it worse than one.
        stitched_by_device: dict[str, list] = {}
        for (device_id, _kind), members in stitched.items():
            stitched_by_device.setdefault(device_id, []).extend(members)
        for device_id, members in stitched_by_device.items():
            kept.append(
                self._compose_stitched(device_id, members, sys_events or [])
            )
        return kept

    def _silence_never_broken(
        self,
        device_id: str,
        members: list[tuple[dict[str, Any], dict[str, Any] | None]],
    ) -> bool:
        """Return whether this window's interruptions were bookkeeping.

        The witness is the standing verdict, not the incident rows,
        because the rows are the thing that lies here. When a device
        genuinely recovers, its verdict clears and the next failure
        starts a new one; when a restart only truncates the counting,
        the verdict never clears. So a verdict still standing today
        whose start predates every opening in the window is a
        condition that never once lifted, however many recoveries the
        rows claim (ruling #308).

        Three conditions, all required. Something in the window
        claimed a recovery, or there is nothing to correct. The
        device holds a standing verdict now. And that verdict began
        before the earliest opening here, which is what separates an
        unbroken outage from a device that really came back and
        failed again, since the second case carries a verdict younger
        than its own fragments.

        A never-reported device is muted, having its own standing
        sentence already. The reference case is an unplugged SLZB-06
        told as twenty-one recoveries across seven restarts while its
        verdict stood untouched from the moment of the unplug.
        """
        if any(
            opened.get(INC_KIND) == TODO_KIND_NEVER_REPORTED
            for opened, _resolved in members
        ):
            return False
        if not any(resolved is not None for _opened, resolved in members):
            return False
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id)
        if not isinstance(record, dict):
            return False
        since = record.get(DEV_FROZEN_SINCE)
        if since is None:
            return False
        earliest = min(opened[INC_WHEN] for opened, _resolved in members)
        return float(since) < float(earliest)

    def _compose_stitched(
        self,
        device_id: str,
        members: list[tuple[dict[str, Any], dict[str, Any] | None]],
        sys_events: list[dict[str, Any]],
    ) -> str:
        """Return one sentence for a silence the restarts segmented.

        The anchor is the standing verdict's own start, because the
        outage predates the window the fragments sit in. The restart
        count comes from the recorded restarts themselves, counted
        between the anchor and now: the resolution rows cannot supply
        it, since on a live system they carry no cause at all
        (ruling #308).
        """
        name = self._told_name(members[0][0])
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id) or {}
        anchor = float(record[DEV_FROZEN_SINCE])
        now = dt_util.utcnow().timestamp()
        span = self._human_span(now - anchor)
        restarts = sum(
            1
            for row in sys_events
            if row.get(SYS_KIND) == SYS_RESTART
            and anchor <= float(row.get(SYS_WHEN, 0.0)) <= now
        )
        base = (
            f"{name} has been silent since "
            f"{self._brief_moment(anchor)}, {span} so far"
        )
        if restarts:
            plural = "s" if restarts != 1 else ""
            return f"{base}, across {restarts} restart{plural}."
        return f"{base}."

    def _compose_flapping(
        self, members: list[tuple[dict[str, Any], dict[str, Any] | None]]
    ) -> str:
        """Return one sentence for a device that went and came back
        more than once: how often, and how long it was gone in all."""
        name = self._told_name(members[0][0])
        went, state = self._flap_verbs(members[0][0])
        total = sum(
            (resolved.get(INC_DURATION) or 0.0)
            for _opened, resolved in members
            if resolved is not None
        )
        recovered = sum(1 for _o, r in members if r is not None)
        count = "twice" if len(members) == 2 else f"{len(members)} times"
        span = self._human_span(total) if total else None
        tail = f", {state} for {span} in total" if span else ""
        if recovered == len(members):
            return f"{name} {went} {count} and recovered each time{tail}."
        return f"{name} {went} {count} and is still {state}{tail}."

    def _flap_verbs(self, opened: dict[str, Any]) -> tuple[str, str]:
        """Return the going and the being for a kind of interruption.

        A repeated interruption needs both: what the device did, and
        what it was while it did it. One word cannot carry "went
        unavailable" and "unavailable for 8m in total" at once.

        A rail is not a silence: a railed device reports the whole
        time, and the freeze verbs said the opposite of what
        happened on the 25 August brief.
        """
        kind = opened.get(INC_KIND)
        if kind == TODO_KIND_UNAVAILABLE:
            return "went unavailable", "unavailable"
        if kind == TODO_KIND_RAILED_SIGNAL:
            return "signal railed", "railed"
        # A battery crossing its line is not a silence: the device
        # reported the whole time. The fourth fleet's brief told a
        # phone's two overnight low readings as "went silent twice".
        if kind == TODO_KIND_LOW_BATTERY:
            return "battery read low", "low"
        if kind == TODO_KIND_FALLING_BATTERY:
            return "battery fell", "falling"
        return "went silent", "silent"

    def _compose_flood(
        self,
        key: Any,
        members: list[tuple[dict[str, Any], dict[str, Any] | None]],
        spans: list[Any],
    ) -> str:
        """Return the one sentence a group of episodes becomes.

        One device is not a flood. It keeps its own sentence, with
        its time and its duration, and gains only the corrected
        cause, because collapsing a single device would throw away
        detail to solve a problem it does not have.

        Beyond one, the count leads: a person reading a brief wants
        the size of the thing before a roll of seventy-four names.
        """
        window_key, kind, _lesser, resolved = key
        window = next(
            (span for span in spans if span.key == window_key), None
        )
        clause = attribution.phrase(window) if window else "an intervention"
        if len(members) == 1:
            opened, closed = members[0]
            if closed is not None:
                return self._compose_episode(opened, closed, clause)
            return self._compose_event(opened)
        word = self._change_clause(
            members[0][0], "flood"
        ) or self._EVENT_WORDING.get(kind, kind)
        when = self._clock(min(row[INC_WHEN] for row, _ in members))
        if resolved:
            return (
                f"{len(members)} devices {word} at {when} and "
                f"recovered, revived by {clause}."
            )
        return f"{len(members)} devices {word} at {when}, with {clause}."

    def _repeat_offender_rows(
        self, now: float
    ) -> list[dict[str, Any]]:
        """Return one row per device that keeps failing on its own.

        The brief's answer to the device nobody can detect (ruling
        #305): a TV that reads unavailable whenever a person turns it
        off, a sensor whose dying cell crosses the battery threshold
        hundreds of times a day. The integration cannot tell either
        from a real fault at the moment it judges, so instead of a
        verdict it shows the pattern and the person decides, which is
        how the reference LG TV and the first external fleet's
        propane sensor both end: excluded or muted by their owner,
        on evidence.

        Only unexplained interruptions count. An opening that a
        restart, an outage, a reload or a pairing window covers is
        already explained, and counting it made the nightly reboot
        the loudest thing on the reference fleet: 71 devices at
        exactly two openings each, and the one device everybody
        already knew about at the top. The attribution is the same
        module the episode sentences use, so one opening can never
        be explained in one paragraph and counted as a mystery in
        the next.

        Reads up to REPEAT_WINDOW_DAYS of incidents, from day one,
        so the view grows with the record rather than waiting for
        the window to exist. Each row is evidence a person can act
        on (ruling #374): what the device did, how often, when, how
        long a typical episode ran, and which device failed in the
        same second, because devices failing together usually share
        a cause.
        """
        rows = self.incident_rows()
        events = self.data.get(DATA_SYSTEM_EVENTS) or []
        cutoff = now - REPEAT_WINDOW_DAYS * 86400.0
        floor_raw = self.entry.options.get(
            CONF_REPEAT_FLOOR, DEFAULT_REPEAT_FLOOR
        )
        try:
            floor = int(floor_raw)
        except (TypeError, ValueError):
            floor = DEFAULT_REPEAT_FLOOR
        floor = max(REPEAT_FLOOR_MIN, min(REPEAT_FLOOR_MAX, floor))
        wins = attribution.windows(events)
        resolved: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            if row.get(INC_EVENT) == INCIDENT_RESOLVED:
                resolved.setdefault(
                    (row.get(INC_DEVICE_ID), row.get(INC_KIND)), []
                ).append(row.get(INC_WHEN) or 0.0)
        found: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if row.get(INC_EVENT) != INCIDENT_OPENED:
                continue
            when = row.get(INC_WHEN) or 0.0
            if when < cutoff:
                continue
            device_id = row.get(INC_DEVICE_ID)
            ends = [
                t
                for t in resolved.get(
                    (device_id, row.get(INC_KIND)), []
                )
                if t >= when
            ]
            closed = min(ends) if ends else None
            window = attribution.attribute(
                wins,
                self._watched.get(device_id),
                self._device_stack(device_id),
                when,
                closed,
                device_id,
            )
            if window is not None:
                continue
            key = (device_id, row.get(INC_KIND))
            entry = found.setdefault(
                key,
                {
                    "device_id": device_id,
                    "kind": row.get(INC_KIND),
                    "stored": row.get(INC_NAME),
                    "n": 0,
                    "days": {},
                    "whens": [],
                    "durations": [],
                },
            )
            entry["n"] += 1
            entry["whens"].append(when)
            if closed is not None:
                entry["durations"].append(closed - when)
            day = dt_util.as_local(
                dt_util.utc_from_timestamp(when)
            ).strftime("%Y-%m-%d")
            entry["days"][day] = entry["days"].get(day, 0) + 1
        table: list[dict[str, Any]] = []
        already_told: set[Any] = getattr(self, "_flapping_told", set())
        for (device_id, kind), entry in sorted(
            found.items(), key=lambda item: -item[1]["n"]
        ):
            if entry["n"] < floor:
                continue
            if len(entry["days"]) == 1 and device_id in already_told:
                # The whole pattern is today, and today's flapping
                # sentence already says it (ruling #305, amended by
                # the collision test): this row's job is the
                # pattern the day's sentences cannot show, and a
                # one-day pattern is not one of those.
                continue
            entry["name"] = self._repeat_name(entry)
            entry["what"] = self._repeat_verb(kind)
            entry["when"] = self._repeat_when(entry["whens"])
            entry["typical"] = (
                self._human_span(
                    sorted(entry["durations"])[
                        len(entry["durations"]) // 2
                    ]
                )
                if entry["durations"]
                else "unknown"
            )
            entry["with"] = self._repeat_with(entry, found)
            table.append(entry)
        return table

    def _repeat_name(self, entry: dict[str, Any]) -> str:
        """Return the name the device has now (ruling #373)."""
        device_id = entry.get("device_id")
        stored = entry.get("stored")
        if not device_id:
            return stored or "unknown device"
        current = self._trim_name(device_id)
        if current != device_id:
            return current
        if stored:
            return stored
        return self._device_name(device_id)

    @staticmethod
    def _repeat_verb(kind: str) -> str:
        """Return what the device did, as the table's second column."""
        if kind == TODO_KIND_UNAVAILABLE:
            return "went unavailable"
        if kind == TODO_KIND_RAILED_SIGNAL:
            return "signal railed"
        noun = _REPEAT_NOUNS.get(kind)
        if noun:
            return noun
        return "went silent"

    def _repeat_when(self, whens: list[float]) -> str:
        """Return the WHEN cell: the days, or one day's span.

        One day carries its first and last time, because "Aug 28,
        08:02 to 16:22" is a shape a person can chase through their
        own memory of the day. Two days are named; more become a
        range, since a roll of dates is a column nobody reads.
        """

        def day(moment: float) -> str:
            return dt_util.as_local(
                dt_util.utc_from_timestamp(moment)
            ).strftime("%b %-d")

        def clock(moment: float) -> str:
            return dt_util.as_local(
                dt_util.utc_from_timestamp(moment)
            ).strftime("%H:%M")

        ordered = sorted(whens)
        days: list[str] = []
        for moment in ordered:
            named = day(moment)
            if named not in days:
                days.append(named)
        if len(days) == 1:
            if len(ordered) == 1:
                return f"{days[0]}, {clock(ordered[0])}"
            return (
                f"{days[0]}, {clock(ordered[0])} to "
                f"{clock(ordered[-1])}"
            )
        if len(days) == 2:
            return f"{days[0]} and {days[1]}"
        return f"{days[0]} to {days[-1]}"

    def _repeat_with(
        self,
        entry: dict[str, Any],
        found: dict[tuple[str, str], dict[str, Any]],
    ) -> str:
        """Return which device failed in the same second, or alone.

        The column that earns its place (ruling #374): devices that
        fail in the same second usually share a cause, and the prose
        form read two halves of one problem as two mysteries. "Every
        time" is said only when it matched every time; anything less
        is counted rather than overstated.

        One shared second is not a pattern, so a partner is named
        only when it matched more than once, unless one match is the
        whole record. Measured on the reference fleet: the two ZHA
        devices matched six of six, and the coordinator matched one
        of six, which is a coincidence wearing the same column as a
        cause.
        """
        mine = [int(moment) for moment in entry["whens"]]
        partners: list[str] = []
        for key, other in found.items():
            if other is entry or key[0] == entry.get("device_id"):
                continue
            theirs = {int(moment) for moment in other["whens"]}
            matched = sum(1 for second in mine if second in theirs)
            if matched < 2 and len(mine) > 1:
                continue
            if not matched:
                continue
            name = self._repeat_name(other)
            if matched == len(mine):
                partners.append(f"{name}, every time")
            else:
                partners.append(
                    f"{name}, {matched} of {len(mine)} times"
                )
        if not partners:
            return "alone"
        return "; ".join(partners)

    def _repeat_offenders_section(self, now: float) -> list[str]:
        """Return the Repeat Offenders section, or nothing.

        Its own heading below Now (ruling #374), because In Short is
        read in ten seconds and a table does not belong in it. The
        paragraph beneath the table is the author's own wording,
        verbatim.
        """
        table = self._repeat_offender_rows(now)
        if not table:
            return []
        lines = [
            "## Repeat Offenders",
            "",
            "| DEVICE | WHAT HAPPENED | TIMES | WHEN "
            "| TYPICAL | WITH |",
            "|---|---|---|---|---|---|",
        ]
        for row in table:
            lines.append(
                f"| {self._note_brief_device(row.get('device_id'), row['name'])} "
                f"| {row['what']} | {row['n']} | {row['when']} "
                f"| {row['typical']} | {row['with']} |"
            )
        lines += ["", REPEAT_PARAGRAPH, ""]
        return lines

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
        # Every event, not only the window's. An outage that began
        # before the window still explains an incident inside it, and
        # filtering first left those devices with no cause at all
        # (ruling #229). The printed house sentences below stay
        # filtered, because those are what happened today.
        told = self._tell_episodes(
            self._pair_incidents(incidents),
            self.data.get(DATA_SYSTEM_EVENTS) or [],
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
        house = self._house_sentences(sys_events or [])
        # The restore leads, above the house and above the devices
        # (ruling #345). Nothing else in this brief matters as much
        # as the fact that the file the rest of it came from had to
        # be replaced, and how much of it is missing.
        if self.restore_told:
            lines += [self.restore_told, ""]
        if house:
            lines += [" ".join(house), ""]
        if told:
            lines += [f"Since {since_text}: " + " ".join(told), ""]
        else:
            # Which nothing it means (ruling #377): the line counts
            # device incidents, and it sat beneath a paragraph of
            # system events it appeared to deny.
            lines += [
                "No device problems started or ended in this "
                "window.",
                "",
            ]
        if standing:
            lines += ["Right now: " + " ".join(standing), ""]
        else:
            # The repeat offenders left this paragraph for their own
            # section below Now (ruling #374), so the all-clear
            # answers the standing problems alone.
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
        lag or muting reasoning. Regenerating mid-day writes the
        in-progress brief with its scope stated and marked
        incomplete, replacing itself until the real brief publishes
        and starts a new day.
        """
        now_rows = self._brief_now_rows()
        silenced = self._acknowledged_devices()
        # Folded before the window cuts, so an escalation's two rows
        # are always read together (0.22.27).
        incidents = [
            row
            for row in escalation.fold(self.incident_rows())
            if window_start <= row[INC_WHEN] <= window_end
            and row[INC_DEVICE_ID] not in self._muted_devices
            and row[INC_DEVICE_ID] not in silenced
        ]
        incidents.sort(key=lambda row: row[INC_WHEN], reverse=True)
        # The house's own events, over the same window. Never
        # filtered by muting or acknowledgment: a person silencing
        # one device has not asked to stop hearing that the power
        # failed.
        sys_events = [
            row
            for row in (self.data.get(DATA_SYSTEM_EVENTS) or [])
            if window_start <= row[SYS_WHEN] <= window_end
        ]
        # Filtered once, here, so the summary and the Last 24 Hours
        # table cannot disagree about which storms exist (ruling
        # #375). The permanent log keeps every row.
        told_twice = {
            id(row) for row in self._storms_inside_restart(sys_events)
        }
        if told_twice:
            sys_events = [
                row for row in sys_events if id(row) not in told_twice
            ]
        sys_events.sort(key=lambda row: row[SYS_WHEN], reverse=True)
        # The span is counted rather than asserted. The window is
        # anchored to the wall clock so a person's seven o'clock brief
        # covers seven to seven, which across a daylight saving change
        # is 23 or 25 real hours, not 24. Reproduced on a New York
        # clock: the March window measures 23.0 and the November one
        # 25.0, and the page said 24 for both (ruling #206). Anchoring
        # to the epoch instead would hold the number and move the
        # brief hour, which is the thing a person notices.
        span = round((window_end - window_start) / 3600.0)
        scope = (
            f"{self._brief_moment(window_end)}. Covering the {span} "
            f"hours since {self._brief_moment(window_start)}."
            if complete
            else f"From {self._brief_moment(window_start)} to "
            f"{self._brief_moment(window_end)} (in progress)."
        )
        # One brief, one map: names pair with devices while this
        # brief is composed, and nothing carries over to the next one.
        self._brief_devices: dict[str, list[str | None]] = {}
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
            # The table lists problems, not devices, so a device with
            # two faults gave "1 device needs attention" above two
            # rows (0.22.24).
            if len(now_rows) != devices:
                summary += (
                    f", with {len(now_rows)} problem"
                    f"{'s' if len(now_rows) != 1 else ''} between them"
                    if devices != 1
                    else f", with {len(now_rows)} problems"
                )
            summary += "."
            now = dt_util.utcnow().timestamp()
            lines += [
                summary,
                "",
                "| DEVICE | PROBLEM | SINCE | FOR |",
                "|---|---|---|---|",
            ]
            for name, problem, since, kind, device_id in now_rows:
                # A device that has never reported has no last-seen
                # time; the stamp is when it was discovered in the
                # registry, and saying so stops a reader taking it
                # for the moment the device broke (ruling #118).
                when = (
                    f"discovered {self._brief_moment(since)}"
                    if kind == TODO_KIND_NEVER_REPORTED
                    else self._brief_moment(since)
                )
                lines.append(
                    f"| {self._note_brief_device(device_id, name)} "
                    f"| {problem} "
                    f"| {when} "
                    f"| {self._human_span(now - since)} |"
                )
            lines.append("")
            # What the stack says about the same devices. It follows
            # the table rather than joining it, because it applies to
            # some rows and not others and a mostly empty column
            # would read as a fault of its own. Only devices whose
            # problem is a freeze verdict are asked: a battery level
            # is nothing a bridge has an opinion about. It confirms
            # or it doubts, and it changes no verdict (ruling #221).
            seen: dict[str, str] = {}
            for name, _problem, _since, kind, device_id in now_rows:
                if kind in (
                    TODO_KIND_LOW_BATTERY,
                    TODO_KIND_FALLING_BATTERY,
                    TODO_KIND_RAILED_SIGNAL,
                ):
                    continue
                phrase = self.reachability_phrase(device_id)
                if phrase:
                    seen[name] = phrase
            if seen:
                lines += [
                    " ".join(
                        f"{name}: {phrase}" for name, phrase in seen.items()
                    ),
                    "",
                ]
        lines += self._repeat_offenders_section(
            dt_util.utcnow().timestamp()
        )
        # Dwell no longer reports (ruling #310). It measured distance
        # from a line derived from the floor, which descends to meet
        # a degraded device, so a permanently broken link reads its
        # way back to healthy over a week. Nothing is said here about
        # bad signal days yet either: the detector that replaces
        # dwell is on its own page first, and joins this brief only
        # once its thresholds have earned it.
        # The battery report answers what the threshold cannot: which
        # cells are going to be low rather than which are (ruling
        # #194). It shipped with nothing pointing at it, so a person
        # who did not know the file existed had no way to find it.
        # Named here on the same footing as the chart, and under the
        # same reasoning that lets signal appear in a brief while
        # never pushing (ruling #59): a document read at an hour a
        # person chose is not an alert.
        #
        # Only what is close. The report lists every cell measurably
        # falling, which is a third of a real fleet and most of them
        # a season out; naming those here would be sixteen devices
        # nobody can act on (ruling #195).
        fallers = self._battery_brief_rows()
        if fallers:
            named = ", ".join(
                f"{row['name']} ({self.battery_time_left(row['days'])})"
                for row in fallers[:5]
            )
            lines += [
                f"Batteries falling: {named}. Details and the full "
                f"report: {REPORT_BATTERY_URL}",
                "",
            ]
        lines += self._recommendations_section()
        lines += ["## Last 24 Hours", ""]
        # The rows behind a stitched sentence are dropped here
        # (ruling #308): each says a dead device recovered or broke
        # again when the restart only interrupted the counting, and
        # the In Short sentence above already tells the one outage
        # they fragment. What a person did (acknowledgments) and
        # everything the sentence does not cover stays. The counts
        # below count what the table shows, so the header cannot
        # claim rows the reader is not given.
        stitched_ids: set[Any] = getattr(self, "_stitched_told", set())
        shown = [
            row
            for row in incidents
            if not (
                row[INC_DEVICE_ID] in stitched_ids
                and row[INC_KIND] in FREEZE_KINDS_FOR_CAUSE
                and row[INC_EVENT]
                in (INCIDENT_OPENED, INCIDENT_RESOLVED)
            )
        ]
        opened = sum(
            1 for row in shown if row[INC_EVENT] == INCIDENT_OPENED
        )
        resolved = sum(
            1 for row in shown if row[INC_EVENT] == INCIDENT_RESOLVED
        )
        if not shown and not sys_events:
            lines += ["Nothing happened.", ""]
        else:
            lines += [
                f"{len(shown) + len(sys_events)} event"
                f"{'s' if len(shown) + len(sys_events) != 1 else ''}. "
                f"{opened} problem{'s' if opened != 1 else ''} "
                f"started, {resolved} ended.",
                "",
                "| TIME | DEVICE | WHAT HAPPENED |",
                "|---|---|---|",
            ]
            merged: list[tuple[float, str, str]] = [
                (row[INC_WHEN],
                 self._note_brief_device(
                     row.get(INC_DEVICE_ID), self._told_name(row)
                 ),
                 self._brief_phrase(row))
                for row in shown
            ] + [
                (row[SYS_WHEN], "The system",
                 self._system_event_phrase(row))
                for row in sys_events
            ]
            merged.sort(key=lambda item: item[0], reverse=True)
            for moment, who, what in merged:
                lines.append(
                    f"| {self._brief_log_moment(moment)} | {who} | "
                    f"{what} |"
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
        self._write_file(dated, page)
        self._write_file(
            os.path.join(directory, REPORT_BRIEF_HTML),
            page,
        )
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

    def _brief_cells(self, line: str) -> list[str]:
        """Return one pipe row's cells, stripped and escaped.

        A cell naming a device becomes that device's cell: linked
        where a person has chosen an address, and carrying its area
        (issue #13). The Markdown itself keeps plain names, because
        the same text is what a notification carries.
        """
        cells = []
        # Split on the pipes that divide cells, not on the one a
        # device's name carries escaped: "A|B Sensor" arrives as
        # "A\|B Sensor", and splitting on every pipe gave its row a
        # cell too many and cost the name its link and area (0.22.19).
        for cell in _UNESCAPED_PIPE.split(line.strip().strip("|")):
            text = cell.strip()
            seen = self._brief_devices.get(text)
            if not seen:
                cells.append(escape(_markdown_unescaped(text)))
                continue
            # In composition order, so two devices of one name each
            # link to themselves: the reference rig has two called
            # "Dining Shades", and a row naming one of them is where
            # a person finds out which it was.
            at = self._brief_cursor.get(text, 0)
            self._brief_cursor[text] = at + 1
            device_id = seen[at] if at < len(seen) else None
            if device_id is None:
                cells.append(escape(_markdown_unescaped(text)))
            else:
                cells.append(
                    self._device_cell(device_id, _markdown_unescaped(text))
                )
        return cells

    def _note_brief_device(self, device_id: str | None, name: str) -> str:
        """Remember which device a name in the brief belongs to.

        The tables are composed as Markdown, so the page is rendered
        from text that has lost the device by then. This keeps the
        pairing for the render, in the order the rows were composed,
        so a name two devices share still links each row to its own.
        """
        shown = self._report_cell(name)
        self._brief_devices.setdefault(shown, []).append(device_id)
        return shown

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
        # Each render walks the same composed text, so the pairing is
        # read rather than consumed: the page and the emailed body
        # must come out the same.
        self._brief_cursor: dict[str, int] = {}
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
                html_lines.append(f"<h1>{escape(_markdown_unescaped(line[2:]))}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{escape(_markdown_unescaped(line[3:]))}</h2>")
            elif line.strip():
                text_line = escape(_markdown_unescaped(line))
                for url, words in (
                    (REPORT_SIGNAL_URL, "the signal report"),
                    (REPORT_BATTERY_URL, "the battery report"),
                ):
                    if url in text_line:
                        href = self._absolute_url(url)
                        text_line = text_line.replace(
                            url, f"<a href='{href}'>{words}</a>"
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

    def _trim_briefs(self, directory: str) -> None:
        """Keep the most recent dated briefs, drop the rest."""
        self._trim_dated(directory, REPORT_BRIEF_PREFIX)
