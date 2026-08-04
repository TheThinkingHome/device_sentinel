# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: narrative.py, Version: 0.11.12 (2026-08-04)

"""How to say what happened: the composer.

A mixin, so `self` is the coordinator and nothing here can be
instantiated alone; the split is for legibility rather than a
boundary.

This file used to hold the recording as well as the wording, and the
two were separated when a count of which method calls which found
they never called each other once, in either direction (ruling #202).
What records now lives in journal.py: the silence episodes, the
incident log, and the system events. This half only reads those rows
back and turns them into sentences.

Two shapes, because a reader needs two: history that carries its
time, and a device line that carries its state. Every channel calls
this composer, so one event cannot be described three different
ways.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_UNACKNOWLEDGED,
    DATA_DEVICES,
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
    RECOVERY_CAUSE_UNOBSERVED,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_KIND_BATTERY,
    TODO_KIND_BATTERY_FALLING,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
    TODO_KIND_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_SORT_NAME,
)



class NarrativeMixin:
    """The memory and the words for the coordinator.

    Mixed into DeviceSentinelCoordinator; every attribute reached for
    here belongs to that class.
    """

    # How bad a problem is, worst first. A device with several
    # problems is described by its worst one, because a phone line
    # has room for one fact and the reader needs the one that
    # matters. Silence outranks battery and signal: a device that
    # cannot be heard from cannot be trusted to report either.
    _KIND_SEVERITY = (
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_FROZEN,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NOT_REPORTED,
        TODO_KIND_BATTERY,
        # A forecast ranks below the level it forecasts: a cell that
        # has crossed the threshold is more urgent than one heading
        # for it (ruling #215).
        TODO_KIND_BATTERY_FALLING,
        TODO_KIND_SIGNAL,
    )

    # A never-reported device has no moment of failure, so its
    # opening reads "since it was discovered" and cannot be joined
    # to a recovery without producing nonsense. It is told as two
    # sentences instead. An acknowledgment is not an opening at all.
    _PAIRABLE_KINDS = (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_SIGNAL,
        TODO_KIND_BATTERY,
    )

    _EVENT_WORDING = {
        TODO_KIND_FROZEN: "stopped reporting",
        TODO_KIND_UNAVAILABLE: "went unavailable",
        TODO_KIND_UNKNOWN: "went unknown",
        TODO_KIND_SIGNAL: "signal railed",
        # Present tense, because nothing happened to the device: what
        # changed is what the readings now say about where it is
        # heading (ruling #215).
        TODO_KIND_BATTERY_FALLING: "battery is running down",
    }

    # Each kind carries its own duration template rather than sharing
    # a suffix. The wordings differ in tense (one past, three present
    # perfect) and only the past-tense one joins correctly with "ago",
    # which is how "has been unavailable 4.0h ago" reached a live
    # brief. The second form is used when no duration is known.
    _STATE_TEMPLATE = {
        TODO_KIND_FROZEN: (
            "stopped reporting {ago} ago",
            "stopped reporting",
        ),
        TODO_KIND_UNAVAILABLE: (
            "has been unavailable for {ago}",
            "is unavailable",
        ),
        TODO_KIND_UNKNOWN: ("has been unknown for {ago}", "is unknown"),
        TODO_KIND_SIGNAL: (
            "signal has been railed for {ago}",
            "signal is railed",
        ),
        # No duration, because how long the projection has stood is
        # not the interesting number; how long the cell has is, and
        # the brief's own falling line carries that.
        TODO_KIND_BATTERY_FALLING: (
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

    def _battery_phrase(self, device_id: str, state: bool) -> str:
        """Return the battery clause with its level where known."""
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        if isinstance(level, (int, float)):
            shown = f"{level:g}%"
            return (
                f"battery is at {shown}"
                if state
                else f"battery fell to {shown}"
            )
        return "battery is low" if state else "battery fell low"

    def _recovery_tail(self, row: dict[str, Any]) -> str:
        """Return what ended a silence, as a trailing clause.

        Shared by the lone recovery sentence and the paired episode
        so one recovery cannot be attributed two ways. The
        unobserved wording stands alone because it is a statement
        about what was not seen rather than a named lever. The brief
        is a report for a person rather than a diagnostic dump, so it
        says plainly that nobody saw the recovery (ruling #116).
        """
        cause = row.get(INC_CAUSE)
        if cause == RECOVERY_CAUSE_UNOBSERVED:
            return f", {cause}"
        if cause:
            return f", revived by a {cause}"
        return ""

    def _opening_clause(self, row: dict[str, Any]) -> str:
        """Return how a problem began, without its full stop.

        Split out of the event composer so the paired episode can
        reuse the exact wording rather than growing a second copy
        that could drift from it.
        """
        name = row[INC_NAME]
        kind = row[INC_KIND]
        when = self._clock(row[INC_WHEN])
        if kind == TODO_KIND_BATTERY:
            phrase = self._battery_phrase(row[INC_DEVICE_ID], False)
            return f"{name} {phrase} at {when}"
        wording = self._EVENT_WORDING.get(kind, kind)
        return f"{name} {wording} at {when}"

    def _compose_event(self, row: dict[str, Any]) -> str:
        """Return one incident as a sentence of history.

        Used by the log today, and by the brief and a future spoken
        answer later: one composer, so the same event can never be
        described three different ways by three different renderers.
        """
        name = row[INC_NAME]
        kind = row[INC_KIND]
        when = self._clock(row[INC_WHEN])
        event = row[INC_EVENT]
        if event == INCIDENT_ACTION:
            return self._action_sentence(name, row.get(INC_CAUSE), when)
        if event == INCIDENT_ACKNOWLEDGED:
            # Legacy rows only, removable after 2026-08-11.
            return f"{name} acknowledged at {when}."
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            tail = self._recovery_tail(row)
            if row.get(INC_DURATION) is None:
                return f"{name} recovered at {when}{tail}."
            return f"{name} recovered at {when} after {span}{tail}."
        if kind == TODO_KIND_NOT_REPORTED:
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
        # A cause this renderer has not learned yet. The check is by
        # far the common case, so it is the safest thing to say, and
        # a legacy row carries no cause at all.
        return f"{name} acknowledged at {when}."

    def _compose_episode(
        self, opened: dict[str, Any], resolved: dict[str, Any]
    ) -> str:
        """Return a whole silence as one sentence.

        A stop and its recovery are one thing that happened, so the
        prose tells them together and leaves strict chronology to the
        table, where a reader is looking a time up (ruling #134).

        A device stopping and the same device recovering are one
        thing that happened, and telling them in strict time order
        put two unrelated sentences between them in a live brief.
        The recovery's clock time is dropped because the opening
        time plus the span already gives it, and the table below
        carries exact times for anyone looking one up.
        """
        if opened[INC_EVENT] == INCIDENT_ACTION:
            # A deletion and the re-add that undid it are one thing
            # that happened, told the way an opening and its
            # recovery are (ruling #134).
            when = self._clock(opened[INC_WHEN])
            return (
                f"{opened[INC_NAME]} deleted from the list at {when}, "
                "and re-added because the problem is still there."
            )
        tail = self._recovery_tail(resolved)
        opening = self._opening_clause(opened)
        if resolved.get(INC_DURATION) is None:
            when = self._clock(resolved[INC_WHEN])
            return f"{opening} and recovered at {when}{tail}."
        span = self._human_span(resolved.get(INC_DURATION))
        return f"{opening} and recovered {span} later{tail}."

    def _pair_incidents(
        self, rows: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        """Group a window's incidents into episodes, in order.

        One episode is one sentence in the prose, so the pairing has
        to happen before the wording does (ruling #134).

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

        The shape a phone holds: one line per device, replaced in
        place as things change, tagged by device id so its line
        always says where that device is now rather than piling up a
        history (ruling #108), so it describes a state rather
        than an event and carries no timestamp. Several problems at
        once are named by the worst with the rest counted, because
        the line has room for one fact.
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
        if worst == TODO_KIND_NOT_REPORTED:
            clause = (
                f"has never reported in {ago}"
                if ago
                else "has never reported"
            )
        elif worst == TODO_KIND_BATTERY:
            clause = self._battery_phrase(device_id, True)
        else:
            with_age, without_age = self._STATE_TEMPLATE.get(
                worst, ("{ago}", worst)
            )
            clause = with_age.format(ago=ago) if ago else without_age
        extra = len(ordered) - 1
        tail = (
            f", and {extra} more problem{'s' if extra != 1 else ''}"
            if extra
            else ""
        )
        return f"{name} {clause}{tail}."


