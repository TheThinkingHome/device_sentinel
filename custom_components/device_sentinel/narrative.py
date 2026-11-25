# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: narrative.py, Version: 0.30.11 (2026-11-25)

"""How to say what happened: the composer.

A mixin, so `self` is the coordinator and nothing here can be
instantiated alone; the split is for legibility rather than a
boundary.

The recording half lives in journal.py, apart because the two halves
never call each other (rule CODE-11): the silence episodes, the
incident log, and the system events. This half only reads those rows
back and turns them into sentences.

Two shapes, because a reader needs two: history that carries its
time, and a device line that carries its state. Every channel calls
this composer, so one event cannot be described three different
ways.
"""

from __future__ import annotations

import math
from typing import Any

from datetime import datetime

from homeassistant.util import dt as dt_util

from .restart_values import confirmed_by, is_confirmed_cause
from .battery_level import level_text
from . import clock
from .phrases import say
from .const import (
    RECOVERY_CAUSE_PAIRING,
    RECOVERY_CAUSES_INTERVENTION,
    RECOVERY_CAUSES_RESTART,
    TODO_KIND_FLAPPING,
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_MUTED,
    ACTION_REMOVED,
    ACTION_SET_ASIDE,
    ACTION_UNACKNOWLEDGED,
    DATA_DEVICES,
    DEV_BATTERY_VALUE,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_SINCE,
    INC_SINCE_MAX_LEAD,
    INC_WHEN,
    RECOVERY_CAUSE_UNOBSERVED,
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
    BATTERY_CLEAR_MARGIN,
    DEV_BATTERY_SINCE,
    BATTERY_REPLACED_LANDS,
)
from .escalation import ESCALATED_FROM, state_word


# The Daily Brief's words for each problem, read by the push, the card
# and the Problem List too: the brief is the surface checked most, so
# the others say what it says, each in its own sentence shape. The
# event words are what the device did, for a push line ("At 3:04 pm,
# Kitchen Motion became unavailable."); the state words are what it is,
# for a list line, as the brief's Right Now table says it. A hub that
# goes down, and a dropping-out device's count, are worded where the
# device is known (rules NOTE-01, LIST-02, UNAV-08). Each table holds
# the phrase's key; say() gives the words in the house's language
# (rule GEN-12).
BRIEF_EVENT_WORDS = {
    TODO_KIND_FROZEN: "push.kind.event.frozen",
    TODO_KIND_NEVER_REPORTED: "push.kind.event.never_reported",
    TODO_KIND_UNAVAILABLE: "push.kind.event.unavailable",
    TODO_KIND_UNKNOWN: "push.kind.event.unknown",
    TODO_KIND_RAILED_SIGNAL: "push.kind.event.railed_signal",
}
BRIEF_STATE_WORDS = {
    TODO_KIND_FROZEN: "push.kind.state.frozen",
    TODO_KIND_NEVER_REPORTED: "push.kind.state.never_reported",
    TODO_KIND_UNAVAILABLE: "push.kind.state.unavailable",
    TODO_KIND_UNKNOWN: "push.kind.state.unknown",
    TODO_KIND_RAILED_SIGNAL: "push.kind.state.railed_signal",
}


def kind_text(kind: str) -> str:
    """A kind no phrase covers, as words rather than its code name."""
    return str(kind).replace("_", " ")


def event_words(kind: str) -> str:
    """A kind as what a device did, "stopped reporting", in the house's
    language; a kind with no phrase reads as itself, in words."""
    key = BRIEF_EVENT_WORDS.get(kind) or NarrativeMixin._EVENT_WORDING.get(kind)
    return say(key) if key else kind_text(kind)


def state_words(kind: str) -> str:
    """A kind as what a device is, "unavailable", in the house's language."""
    key = BRIEF_STATE_WORDS.get(kind)
    return say(key) if key else kind_text(kind)


class NarrativeMixin:
    """The words for the coordinator: rows read back as sentences.

    Mixed into DeviceSentinelCoordinator; every attribute reached for
    here belongs to that class.
    """

    def _told_name(self, row: dict[str, Any]) -> str:
        """Return the name a device has now, never the stored one.

        An incident row stores the name a device had when the row was
        written, and a device renamed since would name hardware the
        reader does not own (rule DEV-02). Every place that shows a
        stored name to a person resolves it against the device as it
        is at the moment of writing. The stored name is the fallback,
        kept for a device the registry and the maps no longer know,
        because what was true then still beats a hex id.
        """
        device_id = row.get(INC_DEVICE_ID)
        stored = row.get(INC_NAME)
        if not device_id:
            return stored or "unknown device"
        # An outage's own row names an integration or a coordinator by
        # its short id ("matter", "z2m"), which a person reads by the
        # name Home Assistant shows: "Matter acknowledged at 9:30 AM"
        # (rule GEN-07).
        if str(device_id).startswith("upstream:"):
            short = stored or str(device_id).split(":", 1)[1]
            return str(self._integration_title(short))  # type: ignore[attr-defined]
        current = self._trim_name(device_id)
        if current != device_id:
            return current
        if stored:
            return stored
        # Nothing knows it and nothing recorded it, so the ladder
        # answers rather than the raw id (rule DEV-01).
        return self._device_name(device_id)

    # How bad a problem is, worst first. A device with several
    # problems is described by its worst one, because a phone line
    # has room for one fact and the reader needs the one that
    # matters. Silence outranks battery and signal: a device that
    # cannot be heard from cannot be trusted to report either.
    _KIND_SEVERITY = (
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_FROZEN,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NEVER_REPORTED,
        TODO_KIND_LOW_BATTERY,
        # A forecast ranks below the level it forecasts: a cell that
        # has crossed the threshold is more urgent than one heading
        # for it (rule LIST-02).
        TODO_KIND_FALLING_BATTERY,
        # A signal problem (rule SIG-17).
        TODO_KIND_FLAPPING,
        TODO_KIND_RAILED_SIGNAL,
    )

    # A never-reported device has no moment of failure, so its
    # opening reads "since it was discovered" and cannot be joined
    # to a recovery without producing nonsense. It is told as two
    # sentences instead. An acknowledgment is not an opening at all.
    _PAIRABLE_KINDS = (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_RAILED_SIGNAL,
        TODO_KIND_LOW_BATTERY,
    )

    _EVENT_WORDING = {
        TODO_KIND_FLAPPING: "push.kind.event.short_drop_outs",
        TODO_KIND_FROZEN: "push.kind.event.frozen",
        # The brief's own word for the kind (rule UNAV-08).
        TODO_KIND_UNAVAILABLE: "push.kind.event.unavailable",
        TODO_KIND_UNKNOWN: "push.kind.event.unknown",
        TODO_KIND_RAILED_SIGNAL: "push.kind.event.railed_signal",
        # Present tense, because nothing happened to the device: what
        # changed is what the readings now say about where it is
        # heading (rule LIST-02).
        TODO_KIND_FALLING_BATTERY: "push.kind.event.falling_battery",
    }

    # Each kind carries its own duration template rather than sharing
    # a suffix. The wordings differ in tense (one past, the others present
    # or present perfect) and only the past-tense one joins correctly with "ago";
    # a shared suffix would read "has been unavailable 4.0h ago". The
    # second form is used when no duration is known.
    _STATE_TEMPLATE = {
        TODO_KIND_FLAPPING: (
            "push.line.short_drop_outs_for",
            "push.line.short_drop_outs",
        ),
        TODO_KIND_FROZEN: (
            "push.line.frozen_for",
            "push.line.frozen",
        ),
        TODO_KIND_UNAVAILABLE: (
            "push.line.unavailable_for",
            "push.line.unavailable",
        ),
        TODO_KIND_UNKNOWN: ("push.line.unknown_for", "push.line.unknown"),
        TODO_KIND_RAILED_SIGNAL: (
            "push.line.railed_signal_for",
            "push.line.railed_signal",
        ),
        # No duration, because how long the projection has stood is
        # not the interesting number; how long the cell has is, and
        # the brief's own falling line carries that.
        TODO_KIND_FALLING_BATTERY: (
            "push.line.falling_battery",
            "push.line.falling_battery",
        ),
    }


    # Each form of the change clause: any kind, a battery, and a battery
    # with its level.
    _CHANGE_KEYS = {
        "sentence": ("push.change.sentence", "push.change.battery_sentence", "push.change.battery_sentence_level"),
        "table": ("push.change.table", "push.change.battery_table", "push.change.battery_table_level"),
        "flood": ("push.change.flood", "push.change.battery_flood", "push.change.battery_flood_level"),
    }

    @staticmethod
    def _clock(epoch: float) -> str:
        """Return a bare local time, as a person would say it."""
        return clock.time_text(dt_util.as_local(dt_util.utc_from_timestamp(epoch)))

    def _battery_phrase(
        self, device_id: str, state: bool, crossed_at: float | None = None, at: str | None = None
    ) -> str:
        """Return the battery clause with its level where known.

        The level here is the record's level at composition time, not
        at the alarm's moment, because an incident row carries no
        reading. So the falling wording is only used while the level
        still reads low; otherwise a row composed after the cell
        recovered would say "battery fell to 100%", a rise described
        as a fall. When the level has recovered, the sentence says what
        is actually known: it read low then, and what it reads now
        (rule BAT-03).
        """
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        if isinstance(level, (int, float)):
            shown = level_text(level)
            if state:
                return say("push.battery.is_at", level=shown)
            if self._battery_still_low(device_id):
                # When it crossed, and where it stands, because "fell"
                # reads as a fall at a level it may have risen to since
                # (rule BAT-03). A row of history is told by its own
                # moment: `at`, its clock time, where the sentence
                # carries no other, or `crossed_at` for its day; the
                # device's own crossing is the latest one.
                if at is not None:
                    return say("push.battery.crossed_at", time=at, level=shown)
                crossed = self._crossed_day(record, crossed_at)
                if crossed:
                    return say("push.battery.crossed_on", day=crossed, level=shown)
                return say("push.battery.crossed", level=shown)
            # Back above the line. The level it fell to is not stored,
            # so no number is given: "now 55%" would read as if 55 were
            # the low reading. A cell back at the level the replacement
            # rule calls full may be new or recharged, and the brief
            # does not claim which (rule BAT-06).
            if level >= BATTERY_REPLACED_LANDS:
                return say("push.battery.read_low_replaced")
            return say("push.battery.read_low_recovered")
        return say("push.battery.is_low") if state else say("push.battery.read_low")

    def _battery_still_low(self, device_id: str) -> bool:
        """Whether the device's level still reads low, so a battery
        sentence carries its level and the time it crossed (rule BAT-03)."""
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        return (
            isinstance(level, (int, float))
            and not isinstance(level, bool)
            and level <= self.threshold_for(device_id) + BATTERY_CLEAR_MARGIN  # type: ignore[attr-defined]
        )

    @staticmethod
    def _crossed_day(record: dict[str, Any], crossed_at: float | None = None) -> str | None:
        """The local day a low battery crossed its threshold, "Oct 24",
        from the moment given, else the record's, or None."""
        moment: datetime | None
        if crossed_at is not None:
            moment = dt_util.utc_from_timestamp(crossed_at)
        else:
            moment = dt_util.parse_datetime(str(record.get(DEV_BATTERY_SINCE) or ""))
        if moment is None:
            return None
        return clock.day_text(dt_util.as_local(moment))

    def _change_clause(
        self, row: dict[str, Any], form: str = "sentence", name: str = "", time: str = ""
    ) -> str | None:
        """Return how a worse problem replaced a lesser one, else None.

        In these words: "Soil Irrigation (Monstera) was marked
        unavailable from frozen at 3:43 AM", and "Door 2nd Bedroom's
        battery was marked low (18%) from running down" (rule LIST-07).
        The form follows where the clause lands: a whole sentence with
        the name and the time given, alone in a table cell whose row
        already names the device, or after "N devices" in a flood.

        The level follows the low battery rule: shown only while the
        cell still reads low, because a row carries no reading of its
        own (rule BAT-03).
        """
        lesser = row.get(ESCALATED_FROM)
        if lesser is None:
            return None
        worse = row[INC_KIND]
        if worse == TODO_KIND_LOW_BATTERY:
            device_id = row[INC_DEVICE_ID]
            level = self.data[DATA_DEVICES].get(device_id, {}).get(DEV_BATTERY_VALUE)
            shown = level_text(level) if self._battery_still_low(device_id) else ""
            key = self._CHANGE_KEYS[form][2 if shown else 1]
            return say(key, name=name, time=time, level=shown, lesser=state_word(lesser))
        return say(
            self._CHANGE_KEYS[form][0], name=name, time=time, worse=state_word(worse), lesser=state_word(lesser)
        )

    def _recovery_tail(self, row: dict[str, Any]) -> str:
        """Return what ended a silence, as a trailing clause.

        Shared by the lone recovery sentence and the paired episode
        so one recovery cannot be attributed two ways. The
        unobserved wording stands alone because it is a statement
        about what was not seen rather than a named lever. The brief
        is a report for a person rather than a diagnostic dump, so it
        says plainly that nobody saw the recovery (rule BRIEF-01).
        """
        cause = row.get(INC_CAUSE)
        if cause == RECOVERY_CAUSE_UNOBSERVED:
            return say("push.tail.clause", clause=say("push.cause.unobserved"))
        if is_confirmed_cause(cause):
            return say("push.tail.clause", clause=self._confirmed_words(cause))
        if cause in RECOVERY_CAUSES_RESTART:
            # Stored by an older release: a restart or an outage
            # revived nothing, so the recovery is told plainly
            # (rule BRIEF-05).
            return ""
        if cause == RECOVERY_CAUSE_PAIRING:
            return say("push.tail.revived_by_pairing")
        if cause in RECOVERY_CAUSES_INTERVENTION:
            # A person's own act, already a phrase: "handled at the
            # device". Glued to "revived by a" it would read "revived
            # by a handled at the device".
            return say("push.tail.clause", clause=say("push.cause.handled_at_device"))
        if cause:
            return say("push.tail.revived_by_a", cause=cause)
        return ""

    def _cause_words(self, cause: str) -> str:
        """A recovery's stored cause, as a table cell names it, in the
        house's language: the causes Device Sentinel writes by name, and
        any other as it was stored."""
        if cause == RECOVERY_CAUSE_UNOBSERVED:
            return say("push.cause.unobserved")
        if is_confirmed_cause(cause):
            return self._confirmed_words(cause)
        if cause == RECOVERY_CAUSE_PAIRING:
            return say("brief.stored.pairing_window")
        if cause in RECOVERY_CAUSES_INTERVENTION:
            return say("push.cause.handled_at_device")
        return cause

    @staticmethod
    def _confirmed_words(cause: str) -> str:
        """A confirmed recovery's stored cause, "confirmed working by"
        and the person's name, in the house's language (rule WATCH-12)."""
        who = confirmed_by(cause)
        if who:
            return say("push.cause.confirmed_by", who=who)
        return say("push.cause.confirmed_on_dashboard")

    @staticmethod
    def _began_at(row: dict[str, Any]) -> float:
        """When a problem began, as the table and the sentence say it.

        An unavailable or unknown opening is written when the device is
        listed, minutes after it went; the row keeps when it went,
        which its recovery counts from, so "became unavailable" and
        "recovered after" agree (rule UNAV-07). Any other row, and one
        written by an older release, is dated when it was written.
        """
        since = row.get(INC_SINCE)
        if (
            row.get(INC_EVENT) == INCIDENT_OPENED
            and row.get(ESCALATED_FROM) is None
            and isinstance(since, (int, float))
            and not isinstance(since, bool)
            and math.isfinite(since)
            and 0.0 < since <= row[INC_WHEN]
            and row[INC_WHEN] - since <= INC_SINCE_MAX_LEAD
        ):
            return float(since)
        return float(row[INC_WHEN])

    def _opening_clause(self, row: dict[str, Any]) -> str:
        """Return how a problem began, without its full stop.

        Split out of the event composer so the paired episode can
        reuse the exact wording rather than growing a second copy
        that could drift from it.
        """
        name = self._told_name(row)
        kind = row[INC_KIND]
        # A worse problem replacing a lesser one is one change, told
        # as that change (rule LIST-07).
        change = self._change_clause(row, name=name, time=self._clock(row[INC_WHEN]))
        if change is not None:
            return change
        when = self._clock(self._began_at(row))
        if kind == TODO_KIND_LOW_BATTERY:
            # Its time inside the first sentence, not after the level
            # (rule BAT-03).
            phrase = self._battery_phrase(row[INC_DEVICE_ID], False, at=when)
            if self._battery_still_low(row[INC_DEVICE_ID]):
                return say("push.opening.timed", name=name, words=phrase)
            return say("push.opening.at", name=name, words=phrase, time=when)
        key = self._EVENT_WORDING.get(kind)
        wording = say(key) if key else kind_text(kind)
        hub = self.unavailable_words(row.get(INC_DEVICE_ID))  # type: ignore[attr-defined]
        if kind == TODO_KIND_UNAVAILABLE and hub:
            # A hub went down (rule STACK-10); a Z-Wave device became
            # unavailable (rule UNAV-08).
            wording = hub[0]
        return say("push.opening.at", name=name, words=wording, time=when)

    def _compose_event(self, row: dict[str, Any]) -> str:
        """Return one incident as a sentence of history.

        Used by the log and the brief, and meant for a spoken answer
        later: one composer, so the same event can never be described
        three different ways by three different renderers.
        """
        name = self._told_name(row)
        kind = row[INC_KIND]
        when = self._clock(row[INC_WHEN])
        event = row[INC_EVENT]
        if event == INCIDENT_ACTION:
            return self._action_sentence(name, row.get(INC_CAUSE), when)
        if event == INCIDENT_RESOLVED and is_confirmed_cause(row.get(INC_CAUSE)):
            return self._confirmed_sentence(row)
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            tail = self._recovery_tail(row)
            # A closed signal problem says so: the device never stopped
            # reporting, and "recovered" alone reads as if it had.
            at, after = (
                ("push.event.signal_recovered_at", "push.event.signal_recovered_after")
                if kind == TODO_KIND_RAILED_SIGNAL
                else ("push.event.recovered_at", "push.event.recovered_after")
            )
            if row.get(INC_DURATION) is None:
                return say(at, name=name, time=when, tail=tail)
            return say(after, name=name, time=when, span=span, tail=tail)
        if kind == TODO_KIND_NEVER_REPORTED:
            return say("push.event.never_reported", name=name)
        return say("push.sentence", clause=self._opening_clause(row))

    def _confirmed_sentence(self, row: dict[str, Any]) -> str:
        """A recovery a person confirmed with It's Back, as its own
        sentence: who said the device was working, when, and how long
        it had been listed (rule WATCH-12)."""
        name = self._told_name(row)
        when = self._clock(row[INC_WHEN])
        who = confirmed_by(row[INC_CAUSE])
        listed = row.get(INC_DURATION) is not None
        span = self._human_span(row.get(INC_DURATION)) if listed else ""
        if who:
            key = "push.confirmed.by_after" if listed else "push.confirmed.by"
            return say(key, time=when, who=who, name=name, span=span)
        key = "push.confirmed.dashboard_after" if listed else "push.confirmed.dashboard"
        return say(key, time=when, name=name, span=span)

    def _action_sentence(
        self, name: str, cause: str | None, when: str
    ) -> str:
        """Return one thing a person did to the list, as a sentence.

        The re-add says why it came back, because the moment a
        reader meets it is the moment they want to know that
        deleting a row does not silence anything.
        """
        if cause == ACTION_UNACKNOWLEDGED:
            return say("push.action.unacknowledged", name=name, time=when)
        if cause == ACTION_DELETED:
            return say("push.action.deleted", name=name, time=when)
        if cause == ACTION_READDED:
            return say("push.action.readded", name=name, time=when)
        if cause == ACTION_ACKNOWLEDGED:
            return say("push.action.acknowledged", name=name, time=when)
        if cause == ACTION_MUTED:
            # A person's mute, not a recovery (rule LIST-09).
            return say("push.action.muted", name=name, time=when)
        if cause == ACTION_REMOVED:
            # Removed from Home Assistant, its record held (rule WATCH-07).
            return say("push.action.removed", name=name, time=when)
        if cause == ACTION_SET_ASIDE:
            # Not a recovery and not an acknowledgment. The device
            # left the watched set with its problem standing, which
            # the reader deserves to hear in those words rather than
            # as an action nobody took (rule LIST-09).
            return say("push.action.set_aside", name=name, time=when)
        # A cause this renderer has not learned yet. The check is by
        # far the common case, so it is the safest thing to say, and
        # a legacy row carries no cause at all.
        return say("push.action.acknowledged", name=name, time=when)

    def _compose_episode(
        self,
        opened: dict[str, Any],
        resolved: dict[str, Any],
        clause: str | None = None,
    ) -> str:
        """Return a whole silence as one sentence.

        A stop and its recovery are one thing that happened, so the
        prose tells them together and leaves strict chronology to the
        table, where a reader is looking a time up; in strict time
        order, two unrelated sentences can fall between them
        (rule BRIEF-02). The recovery's clock time is dropped because
        the opening time plus the span already gives it.

        clause overrides the cause the row carries. The stored cause
        is written when the incident closes, before the intervention
        that explains it has necessarily been recorded, and older
        rows carry a cause borrowed from an unrelated episode. The
        reader works it out afresh and passes it here, so the sentence
        says the true thing and one composer still writes every
        wording (rule BRIEF-05).
        """
        if opened[INC_EVENT] == INCIDENT_ACTION:
            # A deletion and the re-add that undid it are one thing
            # that happened, told the way an opening and its
            # recovery are (rule BRIEF-02).
            when = self._clock(opened[INC_WHEN])
            return say("push.episode.deleted_readded", name=self._told_name(opened), time=when)
        if is_confirmed_cause(resolved.get(INC_CAUSE)):
            # A person said it was working: told as that, in its own
            # sentence, whatever else was open at the time (rule WATCH-12).
            return say(
                "push.episode.confirmed",
                clause=self._opening_clause(opened),
                confirmed=self._confirmed_sentence(resolved),
            )
        tail = (
            say("push.tail.revived_by", cause=clause)
            if clause
            else self._recovery_tail(resolved)
        )
        opening = self._opening_clause(opened)
        if resolved.get(INC_DURATION) is None:
            when = self._clock(resolved[INC_WHEN])
            return say("push.episode.recovered_at", clause=opening, time=when, tail=tail)
        frozen = self._frozen_span_sentence(opened, resolved, tail)
        if frozen is not None:
            return frozen
        span = self._human_span(resolved.get(INC_DURATION))
        return say("push.episode.recovered_later", clause=opening, span=span, tail=tail)

    def _frozen_span_sentence(
        self, opened: dict[str, Any], resolved: dict[str, Any], tail: str
    ) -> str | None:
        """A frozen device's silence, told from when it went quiet.

        A freeze is called once a device has been silent past its wait,
        so the verdict's time is hours after the device went quiet, and
        the recovery's duration is the whole silence. Added to the
        verdict's time, it would put the recovery hours after it really
        came. So the sentence says when it went quiet and when it
        recovered. None for any other kind, a change of kind, or a
        duration that does not fit.
        """
        if opened.get(INC_KIND) != TODO_KIND_FROZEN or self._change_clause(opened) is not None:
            return None
        duration = resolved.get(INC_DURATION)
        end = resolved.get(INC_WHEN)
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or not math.isfinite(duration)
            or not math.isfinite(end)
            or duration <= 0
        ):
            return None
        start = end - duration
        if start > opened[INC_WHEN]:
            # A silence that began after the verdict cannot be this one.
            return None
        local_start = dt_util.as_local(dt_util.utc_from_timestamp(start))
        local_end = dt_util.as_local(dt_util.utc_from_timestamp(end))
        quiet = self._clock(start)
        back = self._clock(end)
        if local_start.utcoffset() != local_end.utcoffset():
            # The clock changed inside the silence: the zone names keep
            # the two times true.
            quiet = say("push.time_zone", time=quiet, zone=local_start.strftime("%Z"))
            back = say("push.time_zone", time=back, zone=local_end.strftime("%Z"))
        if local_start.date() != local_end.date():
            # Across midnight both times carry their day, or a stop at
            # 1:04 AM and a return at 1:48 AM the next night read as 44
            # minutes (rule BRIEF-02).
            quiet = say("push.day_time", day=clock.day_text(local_start), time=quiet)
            back = say("push.day_time", day=clock.day_text(local_end), time=back)
        name = self._told_name(opened)
        # "Recovered", not "reported again": a freeze can also clear
        # because its wait grew, with no report, and the row cannot
        # tell the two apart.
        return say("push.episode.frozen_span", name=name, quiet=quiet, back=back, tail=tail)

    def _pair_incidents(
        self, rows: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        """Group a window's incidents into episodes, in order.

        One episode is one sentence in the prose, so the pairing has
        to happen before the wording does (rule BRIEF-02).

        Each resolution is matched to the most recent unmatched
        opening for the same device and kind, so a device that
        breaks twice inside one window yields two episodes rather
        than a crossed pair. Everything unmatched stands alone: a
        recovery whose opening predates the window, an opening still
        unresolved when the window closed, an acknowledgment.

        Order is by each episode's first event, which keeps the
        paragraph moving forward while holding a pair together.
        """
        units: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        pending: dict[tuple[str, str], int] = {}
        deleted: dict[tuple[str, str], int] = {}
        for row in sorted(rows, key=lambda item: item[INC_WHEN]):
            key = (row[INC_DEVICE_ID], row[INC_KIND])
            event = row[INC_EVENT]
            cause = row.get(INC_CAUSE)
            if event == INCIDENT_RESOLVED and key in pending:
                index = pending.pop(key)
                units[index] = (units[index][0], row)
                continue
            if (
                event == INCIDENT_ACTION
                and cause == ACTION_READDED
                and key in deleted
            ):
                index = deleted.pop(key)
                units[index] = (units[index][0], row)
                continue
            units.append((row, None))
            if event == INCIDENT_OPENED and row[INC_KIND] in (
                self._PAIRABLE_KINDS
            ):
                pending[key] = len(units) - 1
            elif event == INCIDENT_ACTION and cause == ACTION_DELETED:
                deleted[key] = len(units) - 1
        return units

    def _compose_device_line(self, device_id: str) -> str | None:
        """Return what is wrong with one device, right now.

        One line per device, saying where that device is now rather
        than piling up a history, so it describes a state rather than
        an event and carries no timestamp (rule NOTE-01). Several problems at once are
        named by the worst with the rest counted, because the line has
        room for one fact.
        """
        record = next(
            (
                item
                for item in self.todo_items
                if item.get(TODO_DEVICE_ID) == device_id
            ),
            None,
        )
        if record is None:
            return None
        kinds = record.get(TODO_KINDS) or {}
        if not kinds:
            return None
        ordered = sorted(
            kinds,
            key=lambda kind: (
                self._KIND_SEVERITY.index(kind)
                if kind in self._KIND_SEVERITY
                else len(self._KIND_SEVERITY)
            ),
        )
        worst = ordered[0]
        name = record.get(TODO_SORT_NAME) or device_id
        since = kinds.get(worst)
        ago = (
            self._human_span(dt_util.utcnow().timestamp() - since)
            if since
            else None
        )
        if worst == TODO_KIND_NEVER_REPORTED:
            clause = (
                say("push.line.never_reported_in", ago=ago)
                if ago
                else say("push.line.never_reported")
            )
        elif worst == TODO_KIND_LOW_BATTERY:
            clause = self._battery_phrase(device_id, True)
        elif worst not in self._STATE_TEMPLATE:
            # A kind with no words of its own, an outage's row: its age
            # where known, as it has always read.
            clause = ago or kind_text(worst)
        else:
            with_age, without_age = self._STATE_TEMPLATE[worst]
            if worst == TODO_KIND_UNAVAILABLE and self.is_hub(device_id):  # type: ignore[attr-defined]
                # A hub is down, not unavailable (rule STACK-10).
                with_age, without_age = "push.line.hub_down_for", "push.line.hub_down"
            clause = say(with_age, ago=ago) if ago else say(without_age)
        extra = len(ordered) - 1
        # The same device, so say so: "and 1 more problem" alone would
        # read as a second device.
        if extra:
            return say("push.line.more_problems", count=extra, name=name, clause=clause)
        return say("push.line.one_problem", name=name, clause=clause)


