# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: narrative.py, Version: 0.27.10 (2026-10-27)

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

from .battery_level import level_text
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
# device is known (rules NOTE-01, LIST-02, UNAV-08).
BRIEF_EVENT_WORDS = {
    TODO_KIND_FROZEN: "stopped reporting",
    TODO_KIND_NEVER_REPORTED: "never reported",
    TODO_KIND_UNAVAILABLE: "became unavailable",
    TODO_KIND_UNKNOWN: "went unknown",
    TODO_KIND_RAILED_SIGNAL: "signal railed",
}
BRIEF_STATE_WORDS = {
    TODO_KIND_FROZEN: "stopped reporting",
    TODO_KIND_NEVER_REPORTED: "never reported",
    TODO_KIND_UNAVAILABLE: "unavailable",
    TODO_KIND_UNKNOWN: "unknown",
    TODO_KIND_RAILED_SIGNAL: "signal railed",
}


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
        TODO_KIND_FLAPPING,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_FROZEN,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NEVER_REPORTED,
        TODO_KIND_LOW_BATTERY,
        # A forecast ranks below the level it forecasts: a cell that
        # has crossed the threshold is more urgent than one heading
        # for it (rule LIST-02).
        TODO_KIND_FALLING_BATTERY,
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
        TODO_KIND_FLAPPING: "started dropping out again and again",
        TODO_KIND_FROZEN: "stopped reporting",
        # The brief's own word for the kind (rule UNAV-08).
        TODO_KIND_UNAVAILABLE: "became unavailable",
        TODO_KIND_UNKNOWN: "went unknown",
        TODO_KIND_RAILED_SIGNAL: "signal railed",
        # Present tense, because nothing happened to the device: what
        # changed is what the readings now say about where it is
        # heading (rule LIST-02).
        TODO_KIND_FALLING_BATTERY: "battery is running down",
    }

    # Each kind carries its own duration template rather than sharing
    # a suffix. The wordings differ in tense (one past, the others present
    # or present perfect) and only the past-tense one joins correctly with "ago";
    # a shared suffix would read "has been unavailable 4.0h ago". The
    # second form is used when no duration is known.
    _STATE_TEMPLATE = {
        TODO_KIND_FLAPPING: (
            "has been dropping out for {ago}",
            "keeps dropping out",
        ),
        TODO_KIND_FROZEN: (
            "stopped reporting {ago} ago",
            "stopped reporting",
        ),
        TODO_KIND_UNAVAILABLE: (
            "has been unavailable for {ago}",
            "is unavailable",
        ),
        TODO_KIND_UNKNOWN: ("has been unknown for {ago}", "is unknown"),
        TODO_KIND_RAILED_SIGNAL: (
            "signal has been railed for {ago}",
            "signal is railed",
        ),
        # No duration, because how long the projection has stood is
        # not the interesting number; how long the cell has is, and
        # the brief's own falling line carries that.
        TODO_KIND_FALLING_BATTERY: (
            "battery is running down",
            "battery is running down",
        ),
    }


    @staticmethod
    def _clock(epoch: float) -> str:
        """Return a bare local time, as a person would say it."""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%-I:%M %p")

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
                return f"battery is at {shown}"
            if level <= self.low_threshold + BATTERY_CLEAR_MARGIN:
                # When it crossed, and where it stands, because "fell"
                # reads as a fall at a level it may have risen to since
                # (rule BAT-03). A row of history is told by its own
                # moment: `at`, its clock time, where the sentence
                # carries no other, or `crossed_at` for its day; the
                # device's own crossing is the latest one.
                if at is not None:
                    on = f" at {at}"
                else:
                    crossed = self._crossed_day(record, crossed_at)
                    on = f" on {crossed}" if crossed else ""
                return f"battery crossed the threshold{on}. Its current level is {shown}"
            # Back above the line. The level it fell to is not stored,
            # so no number is given: "now 55%" would read as if 55 were
            # the low reading. A cell back at the level the replacement
            # rule calls full may be new or recharged, and the brief
            # does not claim which (rule BAT-06).
            if level >= BATTERY_REPLACED_LANDS:
                return "battery read low, since replaced or recharged"
            return "battery read low, since recovered"
        return "battery is low" if state else "battery read low"

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
        local = dt_util.as_local(moment)
        return f"{local.strftime('%b')} {local.day}"

    def _change_clause(
        self, row: dict[str, Any], form: str = "sentence"
    ) -> str | None:
        """Return how a worse problem replaced a lesser one, else None.

        In these words: "Soil Irrigation (Monstera) was marked
        unavailable from frozen at 3:43 AM", and "Door 2nd Bedroom's
        battery was marked low (18%) from running down" (rule LIST-07).
        The form follows where the clause lands: after the name in a
        sentence, alone in a table cell whose row already names the
        device, or after "N devices" in a flood.

        The level follows the low battery rule: shown only while the
        cell still reads low, because a row carries no reading of its
        own (rule BAT-03).
        """
        lesser = row.get(ESCALATED_FROM)
        if lesser is None:
            return None
        worse = row[INC_KIND]
        if worse == TODO_KIND_LOW_BATTERY:
            level = self.data[DATA_DEVICES].get(row[INC_DEVICE_ID], {}).get(
                DEV_BATTERY_VALUE
            )
            shown = (
                f" ({level_text(level)})"
                if isinstance(level, (int, float))
                and level <= self.low_threshold + BATTERY_CLEAR_MARGIN
                else ""
            )
            core = f"marked low{shown} from {state_word(lesser)}"
            return {
                "sentence": f"'s battery was {core}",
                "table": f"battery {core}",
                "flood": f"had their battery {core}",
            }[form]
        core = f"marked {state_word(worse)} from {state_word(lesser)}"
        return {
            "sentence": f" was {core}",
            "table": core,
            "flood": f"were {core}",
        }[form]

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
            return f", {cause}"
        if cause in RECOVERY_CAUSES_RESTART:
            # Stored by an older release: a restart or an outage
            # revived nothing, so the recovery is told plainly
            # (rule BRIEF-05).
            return ""
        if cause == RECOVERY_CAUSE_PAIRING:
            return f", revived by a {cause}"
        if cause in RECOVERY_CAUSES_INTERVENTION:
            # A person's own act, already a phrase: "handled at the
            # device". Glued to "revived by a" it would read "revived
            # by a handled at the device".
            return f", {cause}"
        if cause:
            return f", revived by a {cause}"
        return ""

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
        change = self._change_clause(row)
        if change is not None:
            return f"{name}{change} at {self._clock(row[INC_WHEN])}"
        when = self._clock(self._began_at(row))
        if kind == TODO_KIND_LOW_BATTERY:
            # Its time inside the first sentence, not after the level
            # (rule BAT-03).
            phrase = self._battery_phrase(row[INC_DEVICE_ID], False, at=when)
            if " at " in phrase:
                return f"{name} {phrase}"
            return f"{name} {phrase} at {when}"
        wording = self._EVENT_WORDING.get(kind, kind)
        hub = self.unavailable_words(row.get(INC_DEVICE_ID))  # type: ignore[attr-defined]
        if kind == TODO_KIND_UNAVAILABLE and hub:
            # A hub went down (rule STACK-10); a Z-Wave device became
            # unavailable (rule UNAV-08).
            wording = hub[0]
        return f"{name} {wording} at {when}"

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
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            tail = self._recovery_tail(row)
            # A closed signal problem says so: the device never stopped
            # reporting, and "recovered" alone reads as if it had.
            what = "signal recovered" if kind == TODO_KIND_RAILED_SIGNAL else "recovered"
            if row.get(INC_DURATION) is None:
                return f"{name} {what} at {when}{tail}."
            return f"{name} {what} at {when} after {span}{tail}."
        if kind == TODO_KIND_NEVER_REPORTED:
            return f"{name} has never reported since it was discovered."
        return f"{self._opening_clause(row)}."

    def _action_sentence(
        self, name: str, cause: str | None, when: str
    ) -> str:
        """Return one thing a person did to the list, as a sentence.

        The re-add says why it came back, because the moment a
        reader meets it is the moment they want to know that
        deleting a row does not silence anything.
        """
        if cause == ACTION_UNACKNOWLEDGED:
            return f"{name} acknowledgment removed at {when}."
        if cause == ACTION_DELETED:
            return f"{name} deleted from the list at {when}."
        if cause == ACTION_READDED:
            return (
                f"{name} re-added to the list at {when} because the "
                "problem is still there."
            )
        if cause == ACTION_ACKNOWLEDGED:
            return f"{name} acknowledged at {when}."
        if cause == ACTION_MUTED:
            # A person's mute, not a recovery (rule LIST-09).
            return f"{name} was muted at {when}."
        if cause == ACTION_REMOVED:
            # Removed from Home Assistant, its record held (rule WATCH-07).
            return f"{name} was removed from Home Assistant at {when}."
        if cause == ACTION_SET_ASIDE:
            # Not a recovery and not an acknowledgment. The device
            # left the watched set with its problem standing, which
            # the reader deserves to hear in those words rather than
            # as an action nobody took (rule LIST-09).
            return f"{name} was set aside at {when} and is no longer watched."
        # A cause this renderer has not learned yet. The check is by
        # far the common case, so it is the safest thing to say, and
        # a legacy row carries no cause at all.
        return f"{name} acknowledged at {when}."

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
            return (
                f"{self._told_name(opened)} deleted from the list at {when}, "
                "and re-added because the problem is still there."
            )
        tail = (
            f", revived by {clause}"
            if clause
            else self._recovery_tail(resolved)
        )
        opening = self._opening_clause(opened)
        if resolved.get(INC_DURATION) is None:
            when = self._clock(resolved[INC_WHEN])
            return f"{opening} and recovered at {when}{tail}."
        frozen = self._frozen_span_sentence(opened, resolved, tail)
        if frozen is not None:
            return frozen
        span = self._human_span(resolved.get(INC_DURATION))
        return f"{opening} and recovered {span} later{tail}."

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
            quiet = f"{quiet} {local_start.strftime('%Z')}"
            back = f"{back} {local_end.strftime('%Z')}"
        if local_start.date() != local_end.date():
            quiet = local_start.strftime("%b %-d, ") + quiet
        name = self._told_name(opened)
        # "Recovered", not "reported again": a freeze can also clear
        # because its wait grew, with no report, and the row cannot
        # tell the two apart.
        return f"{name} stopped reporting at {quiet} and recovered at {back}{tail}."

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
                f"has never reported in {ago}"
                if ago
                else "has never reported"
            )
        elif worst == TODO_KIND_LOW_BATTERY:
            clause = self._battery_phrase(device_id, True)
        else:
            with_age, without_age = self._STATE_TEMPLATE.get(
                worst, ("{ago}", worst)
            )
            if worst == TODO_KIND_UNAVAILABLE and self.is_hub(device_id):  # type: ignore[attr-defined]
                # A hub is down, not unavailable (rule STACK-10).
                with_age, without_age = "has been down for {ago}", "is down"
            clause = with_age.format(ago=ago) if ago else without_age
        extra = len(ordered) - 1
        # The same device, so say so: "and 1 more problem" alone would
        # read as a second device.
        tail = (
            f", and {extra} more problem{'s' if extra != 1 else ''} "
            "on the same device"
            if extra
            else ""
        )
        return f"{name} {clause}{tail}."


