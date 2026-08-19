# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_brief.py, Version: 0.16.2 (2026-08-19)

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
from datetime import timedelta
from html import escape
from typing import Any

from homeassistant.util import dt as dt_util

from . import attribution
from .const import (
    CONF_REPEAT_FLOOR,
    DEFAULT_REPEAT_FLOOR,
    REPEAT_FLOOR_MAX,
    REPEAT_FLOOR_MIN,
    REPEAT_WINDOW_DAYS,
    BRIEF_NOTEWORTHY_SECONDS,
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_UNACKNOWLEDGED,
    CONF_REMINDER_TIME,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEFAULT_REMINDER_TIME,
    DEV_BATTERY_VALUE,
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
    REPORT_SIGNAL_DWELL_URL,
    REPORT_WWW_DIR,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_BROKER_DOWN,
    SYS_DEVICES,
    SYS_STORM_CLOSED,
    SYS_STORM_OPEN,
    SYS_BROKER_UP,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_EPOCH_RESET,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_STORAGE_SHAPE,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_PAIRING_CLOSED,
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


def _plural(count: int) -> str:
    """Return a count of devices as a person would write it.

    The count is known when the sentence is written, so "device(s)"
    is an evasion rather than a shorthand (ruling #233).
    """
    return f"{count} device" if count == 1 else f"{count} devices"


# What a repeat-offender line calls one occurrence of each kind.
# "Interruption" covers the freeze family; the battery kinds get
# their own noun because "unexplained interruption" misdescribes a
# threshold crossing (ruling #305).
_REPEAT_NOUNS = {
    TODO_KIND_LOW_BATTERY: "low-battery alarm",
    TODO_KIND_FALLING_BATTERY: "falling-battery alarm",
}


class BriefMixin:
    """The daily brief: the one report written for a person."""

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
        if kind == TODO_KIND_LOW_BATTERY:
            # Borrowed from the composer so the table and the prose
            # cannot disagree about the same event: one composer
            # serves every channel, so nothing is described two ways
            # (ruling #120). The level belongs in both or neither.
            return self._battery_phrase(row[INC_DEVICE_ID], False)
        wording = {
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
        if kind == SYS_BROKER_DOWN:
            return f"The MQTT broker went down at {when}."
        if kind == SYS_BROKER_UP:
            if held:
                return (
                    f"The MQTT broker came back at {when} after {held}."
                )
            return f"The MQTT broker came back at {when}."
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
        if kind == SYS_BROKER_DOWN:
            return "MQTT broker went down"
        if kind == SYS_BROKER_UP:
            return (
                f"MQTT broker came back after {held}"
                if held
                else "MQTT broker came back"
            )
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
        if kind == SYS_EPOCH_RESET:
            return f"learned statistics reset ({detail})" if detail else "learned statistics reset"
        if kind == SYS_OPTIONS_CHANGED:
            return f"settings changed ({detail})" if detail else "settings changed"
        if kind == SYS_STORAGE_SHAPE:
            return (
                f"storage check: {detail}"
                if detail
                else "storage check found a record that does not fit"
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
        worst = self._longest(rows, SYS_RESTART)
        if worst is not None:
            said.append(
                "The system was unwatched for "
                f"{self._human_span(worst[SYS_DURATION])} at "
                f"{self._brief_moment(worst[SYS_WHEN])}."
            )
        scopes: list[str] = []
        for row in rows:
            scope = row.get(SYS_SCOPE)
            if row[SYS_KIND] == SYS_BRIDGE_UP and scope not in scopes:
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
        listed = ", ".join(names)
        if len(changes) == 1:
            when = self._brief_moment(changes[0][SYS_WHEN])
            return [f"Settings changed at {when}: {listed}."]
        return [f"Settings changed {len(changes)} times: {listed}."]

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
            window = (
                attribution.attribute(
                    spans,
                    self._watched.get(device_id),
                    self._device_stack(device_id),
                    opened[INC_WHEN],
                    resolved[INC_WHEN] if resolved is not None else None,
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
            key = (window.key, opened[INC_KIND], resolved is not None)
            if key not in placed:
                placed[key] = len(told)
                told.append("")
                owners.append(set())
            owners[placed[key]].add(device_id)
            groups.setdefault(key, []).append((opened, resolved))
        for key, members in groups.items():
            told[placed[key]] = self._compose_flood(key, members, spans)
        kept = [
            (line, who) for line, who in zip(told, owners) if line
        ]
        return self._collapse_flapping(kept, pairs)

    def _collapse_flapping(
        self,
        told: list[tuple[str, set[str]]],
        pairs: list[tuple[dict[str, Any], dict[str, Any] | None]],
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
        by_device: dict[str, list[tuple[dict, dict | None]]] = {}
        for opened, resolved in pairs:
            by_device.setdefault(opened[INC_DEVICE_ID], []).append(
                (opened, resolved)
            )
        # A device that has never reported is one standing condition,
        # not a device going and returning, so it keeps the sentence
        # that says so. Pairing sees two rows and would otherwise
        # read them as two silences.
        flapping = {
            device_id: members
            for device_id, members in by_device.items()
            if len(members) > 1
            and not any(
                opened.get(INC_KIND) == TODO_KIND_NEVER_REPORTED
                for opened, _resolved in members
            )
        }
        # Remembered for the repeat-offender section (ruling #305,
        # amended): a device the day's flapping sentence already
        # carries is not named again below unless its pattern spans
        # more than this one brief, because the same device in two
        # sentences of one paragraph is the duplication #276 and
        # #304 both exist to prevent.
        self._flapping_told = set(flapping)
        if not flapping:
            return [line for line, _who in told]
        kept = [
            line
            for line, who in told
            if not (who and who <= set(flapping))
        ]
        for members in flapping.values():
            kept.append(self._compose_flapping(members))
        return kept

    def _compose_flapping(
        self, members: list[tuple[dict[str, Any], dict[str, Any] | None]]
    ) -> str:
        """Return one sentence for a device that went and came back
        more than once: how often, and how long it was gone in all."""
        name = members[0][0][INC_NAME]
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
        """
        if opened.get(INC_KIND) == TODO_KIND_UNAVAILABLE:
            return "went unavailable", "unavailable"
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
        window_key, kind, resolved = key
        window = next(
            (span for span in spans if span.key == window_key), None
        )
        clause = attribution.phrase(window) if window else "an intervention"
        if len(members) == 1:
            opened, closed = members[0]
            if closed is not None:
                return self._compose_episode(opened, closed, clause)
            return self._compose_event(opened)
        word = self._EVENT_WORDING.get(kind, kind)
        when = self._clock(min(row[INC_WHEN] for row, _ in members))
        if resolved:
            return (
                f"{len(members)} devices {word} at {when} and "
                f"recovered, revived by {clause}."
            )
        return f"{len(members)} devices {word} at {when}, with {clause}."

    def _repeat_offender_lines(self, now: float) -> list[str]:
        """Return one line per device that keeps failing on its own.

        The brief's answer to the device nobody can detect (ruling
        #305): a TV that reads unavailable whenever a person turns it
        off, a sensor whose dying cell crosses the battery threshold
        hundreds of times a day. The integration cannot tell either
        from a real fault at the moment it judges, so instead of a
        verdict it shows the pattern and the person decides, which is
        how the reference LG TV and the first external fleet's
        propane sensor both end: ignored or excluded by their owner,
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
        so the view grows with the record rather than waiting for a
        week to exist. The line carries the count, the days it
        spread over, and the worst day, because "18 over 6 days" is
        a failing device and "15, all on one day" was one bad
        afternoon, and the reader should not need arithmetic to
        tell them apart (ruling #305).
        """
        rows = self.data.get(DATA_INCIDENTS) or []
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
            )
            if window is not None:
                continue
            key = (device_id, row.get(INC_KIND))
            entry = found.setdefault(
                key,
                {"name": row.get(INC_NAME), "n": 0, "days": {}},
            )
            entry["n"] += 1
            day = dt_util.as_local(
                dt_util.utc_from_timestamp(when)
            ).strftime("%Y-%m-%d")
            entry["days"][day] = entry["days"].get(day, 0) + 1
        lines: list[str] = []
        already_told = getattr(self, "_flapping_told", set())
        for (device_id, kind), entry in sorted(
            found.items(), key=lambda item: -item[1]["n"]
        ):
            if entry["n"] < floor:
                continue
            if len(entry["days"]) == 1 and device_id in already_told:
                # The whole pattern is today, and today's flapping
                # sentence already says it (ruling #305, amended by
                # the collision test): this line's job is the
                # pattern the day's sentences cannot show, and a
                # one-day pattern is not one of those.
                continue
            noun = _REPEAT_NOUNS.get(kind, "interruption")
            day_count = len(entry["days"])
            worst = max(entry["days"].values())
            if day_count == 1:
                spread = "all on one day"
            elif worst > 1:
                spread = (
                    f"over {day_count} days, "
                    f"worst day {worst}"
                )
            else:
                spread = f"over {day_count} days"
            lines.append(
                f"{entry['name']}: {entry['n']} unexplained "
                f"{noun}{'s' if entry['n'] != 1 else ''} "
                f"{spread}, nothing intervened."
            )
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
        if house:
            lines += [" ".join(house), ""]
        if told:
            lines += [f"Since {since_text}: " + " ".join(told), ""]
        else:
            lines += [f"Nothing has happened since {since_text}.", ""]
        if standing:
            lines += ["Right now: " + " ".join(standing), ""]
        repeats = self._repeat_offender_lines(
            dt_util.utcnow().timestamp()
        )
        if repeats:
            lines += [
                "Keeps failing on its own: " + " ".join(repeats),
                "",
            ]
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
                    if kind == TODO_KIND_NEVER_REPORTED
                    else self._brief_moment(since)
                )
                lines.append(
                    f"| {self._report_cell(name)} | {problem} "
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
                for url, words in (
                    (REPORT_SIGNAL_DWELL_URL, "the signal dwell chart"),
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
