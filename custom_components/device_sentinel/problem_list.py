# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: problem_list.py, Version: 0.15.9 (2026-08-18)

"""The problem list: the single memory every channel renders.

One of six subject modules split out of coordinator.py, which
had reached four thousand lines. The seam is the subject, chosen
by measuring which methods call which: storage and interventions
call nothing outside themselves at all, and the three detectors
reach out fewer than ten times each (ruling #201).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

import uuid
from typing import Any
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
)
from homeassistant.util import dt as dt_util

from .events import sort_kinds
from .const import (
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_SET_ASIDE,
    ACTION_UNACKNOWLEDGED,
    CONF_SETTLE_SHARE,
    DATA_DEVICES,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    DEFAULT_SETTLE_SHARE_PCT,
    DEV_DAILY_MAX,
    FREEZE_CATEGORY_NEVER_REPORTED,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    NOTIFY_FAMILY_FREEZE,
    NOTIFY_KIND_FAMILY,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    SIGNAL_PROBLEM_ADDITION,
    STACK_DISPLAY_NAMES,
    TODO_ACKED_AT,
    TODO_DESCRIPTION,
    TODO_DEVICE_ID,
    TODO_JOURNAL_KEEP,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FAMILIES,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_KINDS,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
    UPSTREAM_KIND,
    UPSTREAM_SETTLE_SECONDS,
)


# Keyed by problem kind, so every key is a TODO_KIND_ and nothing
# else. The "rail" entry that sat here until 0.15.8 was a signal row
# kind rather than a problem kind and could never be reached; the
# rows carry TODO_KIND_RAILED_SIGNAL now and the two vocabularies
# have become one (ruling #299).
_EVENT_WORD = {
    TODO_KIND_LOW_BATTERY: "low",
    TODO_KIND_RAILED_SIGNAL: "railed",
    TODO_KIND_FROZEN: "frozen",
    TODO_KIND_UNAVAILABLE: "unavailable",
    TODO_KIND_UNKNOWN: "unknown",
    TODO_KIND_NEVER_REPORTED: "never reporting",
}

# The kinds whose push line is written rather than assembled from
# _EVENT_WORD. A battery forecast cannot use the shared shape: "was
# detected running down" is not English, and nothing was detected
# about the device at all, since what changed is what its readings
# say about where it is heading (ruling #215). A recovery names the
# kind that lifted rather than reading "recovered", because a cell
# can carry a level and a forecast and "recovered" would not say
# which of them ended (ruling #220).
_FAULT_LINE = {
    TODO_KIND_FALLING_BATTERY: (
        "{name} battery is running down, empty in {left}",
        "{name} battery is running down",
    ),
}
_RECOVERY_LINE = {
    TODO_KIND_LOW_BATTERY: "{name} battery is no longer low",
    TODO_KIND_FALLING_BATTERY: "{name} battery is no longer running down",
}

class ProblemListMixin:
    """The problem list: the single memory every channel renders."""


    def _todo_tag_of(self, device_id: str) -> str:
        """Return the todo-state tag for a device with a fault.

        The same three states the sync produces, worded for a
        diagnostics reader: open, acknowledged, or removed from the
        list by hand while the fault persists. A device has one todo
        item covering all its faults, so both lines of a two-fault
        device carry the same tag.
        """
        status = self._todo_status_of(device_id)
        if status == "needs_action":
            return "[\u25cb open]"
        if status == "completed":
            return "[\u2713 acknowledged]"
        return "[\u2717 removed from list]"

    @property
    def todo_items(self) -> list[dict[str, Any]]:
        """Return the stored problem items in display order.

        Only rows a consumer can use. The store may hold a row the
        shape check has named and Verify left untouched (ruling
        #278); the to-do entity, the sensors and the brief all read
        through here, so this is the one line that keeps such a row
        off every surface, the way watched_records does for a
        device record (rulings #257, #357). The row stays in the
        store, still named on the card, until a restore or a trim
        (ruling #369).
        """
        return [
            record
            for record in self.data.get(DATA_TODO_ITEMS, [])
            if isinstance(record, dict)
            and isinstance(record.get(TODO_UID), str)
            and isinstance(record.get(TODO_SUMMARY), str)
            and isinstance(record.get(TODO_DEVICE_ID), str)
            and isinstance(record.get(TODO_KINDS), dict)
        ]

    def _sort_todo_items(self) -> None:
        """Enforce the display order: open alphabetical, then
        acknowledged in the order they were checked.

        Order is owned by the integration and re-imposed on every
        write, because a readable list beats one ordered by age; user
        reordering does not stick, by design. The open block sorts
        alphabetically by the device's common name. The acknowledged
        block follows, oldest acknowledgment first, so the checked
        section reads as a stable history rather than reshuffling as
        problems come and go around it.
        """
        def order(record: Any) -> tuple[int, str]:
            # A row the sorter cannot read sorts last and sorts by
            # nothing, rather than raising and taking the sync down:
            # the shape check has named it, and it is carried through
            # untouched (ruling #369). Every key is a string so no
            # two rows can be incomparable.
            if not isinstance(record, dict):
                return 2, ""
            acknowledged = record.get(TODO_STATUS) == "completed"
            if acknowledged:
                return 1, str(record.get(TODO_ACKED_AT) or "")
            name = (
                record.get(TODO_SORT_NAME)
                or record.get(TODO_SUMMARY)
                or ""
            )
            return 0, str(name).lower()

        self.data[DATA_TODO_ITEMS].sort(key=order)

    async def async_todo_update(
        self,
        uid: str | None,
        summary: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Apply a user edit to one item.

        A status of completed is the acknowledgment: the item stays on
        the list, marked done, and Step 8 will send nothing about a
        device while its item sits acknowledged. The check time is
        stamped because it orders the acknowledged block. Only a full
        recovery deletes the item; unchecking simply reopens it. Text
        edits do not stick: the sync owns the wording and rewrites it
        from the detections.
        """
        for record in self.data[DATA_TODO_ITEMS]:
            if record[TODO_UID] != uid:
                continue
            if summary is not None:
                record[TODO_SUMMARY] = summary
            if description is not None:
                record[TODO_DESCRIPTION] = description
            if status is not None and status != record.get(TODO_STATUS):
                record[TODO_STATUS] = status
                record[TODO_ACKED_AT] = (
                    dt_util.utcnow().isoformat()
                    if status == "completed"
                    else None
                )
                # The checkbox lands on the timeline in both
                # directions. Recording only the check left a brief
                # saying a device was acknowledged and never saying
                # the acknowledgment had been taken back, so the
                # record told half the story and read as though the
                # silence still held.
                cause = (
                    ACTION_ACKNOWLEDGED
                    if status == "completed"
                    else ACTION_UNACKNOWLEDGED
                )
                for kind in record.get(TODO_KINDS, {}):
                    self._record_incident(
                        device_id=record[TODO_DEVICE_ID],
                        name=record.get(TODO_SORT_NAME)
                        or record[TODO_DEVICE_ID],
                        kind=kind,
                        event=INCIDENT_ACTION,
                        cause=cause,
                    )
                # Ticking has an event of its own. Unticking does
                # not: it is the soft un-acknowledge, so the fault
                # fires again carrying renewed, and an automation
                # needs no knowledge of acknowledgment at all
                # (ruling #289).
                name = (
                    record.get(TODO_SORT_NAME) or record[TODO_DEVICE_ID]
                )
                kinds = [
                    kind
                    for kind in record.get(TODO_KINDS, {})
                    if kind != UPSTREAM_KIND
                ]
                if status == "completed":
                    self.fire_acknowledged(
                        record[TODO_DEVICE_ID], name, kinds
                    )
                else:
                    stamps = record.get(TODO_KINDS, {})
                    since = min(
                        (
                            stamps[k]
                            for k in kinds
                            if stamps.get(k) is not None
                        ),
                        default=dt_util.utcnow().timestamp(),
                    )
                    self.fire_fault(
                        record[TODO_DEVICE_ID],
                        name,
                        kinds,
                        dt_util.utc_from_timestamp(since)
                        .astimezone(dt_util.DEFAULT_TIME_ZONE)
                        .isoformat(),
                        renewed=True,
                    )
            break
        self._sort_todo_items()
        await self._save_now()
        self._notify()

    async def async_todo_delete(self, uids: list[str]) -> None:
        """Delete items the user removed by hand.

        Deleting an item whose device is still detected is the hard
        un-acknowledge: the next sync re-adds it fresh, and that
        re-add lands in the journal like any other, so Step 8 will
        announce it again.

        Both halves reach the timeline now. Without the deletion on
        the record, a reader saw the same device detected twice with
        nothing between, which reads as a flapping fault rather than
        as somebody clearing a row that came straight back.
        """
        for record in self.data[DATA_TODO_ITEMS]:
            if record[TODO_UID] not in uids:
                continue
            device_id = record[TODO_DEVICE_ID]
            self._hand_deleted.add(device_id)
            for kind in record.get(TODO_KINDS, {}):
                self._record_incident(
                    device_id=device_id,
                    name=record.get(TODO_SORT_NAME) or device_id,
                    kind=kind,
                    event=INCIDENT_ACTION,
                    cause=ACTION_DELETED,
                )
        self.data[DATA_TODO_ITEMS] = [
            record
            for record in self.data[DATA_TODO_ITEMS]
            if record[TODO_UID] not in uids
        ]
        await self._save_now()
        self._notify()

    def _current_problems(self) -> dict[str, dict[str, Any]]:
        """Return every detected problem, one entry per device.

        Reads the same three properties the Problems sensors publish
        (frozen_devices_list, battery_low_list, signal_problem_list),
        so the todo can never disagree with the sensors: one source,
        two readers. The freeze category string is the kind itself; a
        device carries at most one freeze kind but may stack battery
        and signal on top. since is normalized to epoch seconds where
        the detection has one; a rail has none, so the sync stamps the
        moment the kind first appears on the item instead.
        """
        problems: dict[str, dict[str, Any]] = {}

        def _entry(device_id: str, name: str | None) -> dict[str, Any]:
            return problems.setdefault(
                device_id,
                {
                    "name": name or device_id,
                    "kinds": {},
                    "level": None,
                    "left": None,
                },
            )

        for row in self.reportable_down_rows:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][row["category"]] = row.get("since")

        # One row for the fault itself (ruling #264). The devices it
        # masks are counted in the summary rather than listed, so the
        # person is told what to fix.
        for name, count in self.suppressed_down_counts.items():
            problems[f"upstream:{name}"] = {
                "name": name,
                "kinds": {
                    UPSTREAM_KIND: self.upstream_down_since_for(
                        name
                    )
                },
                "level": count,
                "left": None,
            }

        for row in self.battery_low_list:
            entry = _entry(row["device_id"], row.get("name"))
            since = row.get("since")
            since_dt = dt_util.parse_datetime(since) if since else None
            entry["kinds"][TODO_KIND_LOW_BATTERY] = (
                since_dt.timestamp() if since_dt else None
            )
            entry["level"] = row.get("level")

        # A falling cell, from the battery report's own rows so the
        # list, the report, the brief and the sensor cannot disagree
        # about which cells are near the end (ruling #213). Cells
        # already low are absent from that source, so a device never
        # carries both kinds at once from here; where one follows the
        # other the item gains a kind and keeps its acknowledgment
        # (rulings #123 and #133). Acknowledging silences the phone
        # and not the record: the item stays on the list and updates
        # to say the level as well as the projection, so a person who
        # ticked off a forecast still watches it come true.
        for row in self.battery_falling_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_FALLING_BATTERY] = None
            entry["left"] = row.get("left")
            if entry["level"] is None:
                entry["level"] = row.get("level")

        for row in self.signal_problem_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_RAILED_SIGNAL] = None

        return problems

    @staticmethod
    def _kind_word(
        kind: str, level: Any, left: str | None = None
    ) -> str:
        """Return one kind as the person reads it in the item text.

        The falling kind reads as a warning rather than a fault,
        because the cell is working: what is wrong is where it is
        heading (ruling #213). It says the time in the same words the
        report and the brief use, which are words rather than a count
        of days because the projection moves (ruling #197).
        """
        if kind == TODO_KIND_LOW_BATTERY:
            if level is None:
                return "battery low"
            shown = int(level) if float(level).is_integer() else level
            return f"battery {shown}%"
        if kind == TODO_KIND_FALLING_BATTERY:
            # The noun is carried, because the item may say this and
            # nothing else: "Door 2nd Bedroom: empty in about 2 weeks"
            # sitting beside "Soil Irrigation: battery 0%" leaves a
            # reader to guess what is empty (ruling #216). It reads
            # once when both kinds are present, because the level
            # clause ahead of it has already said the word.
            if left:
                return f"empty in {left}"
            return "battery running down"
        if kind == TODO_KIND_RAILED_SIGNAL:
            return "signal (rail)"
        return kind.replace("_", " ")

    def _upstream_item_text(
        self, name: str, kinds: dict[str, float | None], count: Any
    ) -> tuple[str, str]:
        """Return the summary and description for a downed upstream.

        Ruling #266. The per-device grammar produced "z2m: upstream",
        which is accurate and tells a person nothing: not what z2m
        is, not what it means for their house, not what to do. This
        row is the only one on the list that names a cause rather
        than a casualty, so it says so in words.

        The count is in the summary and moves as devices fall, which
        is safe: the sync keeps an existing kind's stamp unless the
        detection carries its own, and this one carries the moment
        the upstream went down, which does not move while it stays
        down. So the text can be rewritten every pass and the SINCE
        column and the duration beside it stay pinned to the outage.
        """
        display = STACK_DISPLAY_NAMES.get(name, name)
        devices = int(count or 0)
        plural = "" if devices == 1 else "s"
        summary = f"{display} down: {devices} device{plural} unavailable"
        since = kinds.get(UPSTREAM_KIND)
        when = (
            self._format_report_time(
                dt_util.as_local(dt_util.utc_from_timestamp(since))
            )
            if since is not None
            else None
        )
        opening = (
            f"{display} stopped reporting at {when}."
            if when
            else f"{display} is not reporting."
        )
        return summary, (
            f"{opening} The {devices} device{plural} behind it are "
            f"unavailable because of it rather than on their own, so "
            f"they are counted here instead of listed. Their verdicts "
            f"are recorded and clear when it returns; anything still "
            f"down afterward is listed on its own."
        )

    def _problem_item_text(
        self,
        name: str,
        kinds: dict[str, float | None],
        level: Any,
        left: str | None = None,
        device_id: str | None = None,
    ) -> tuple[str, str]:
        """Return the summary and description for one item.

        The summary leads with the human readable device name, the
        one thing ruled front and center, then the kinds in a fixed
        order: the freeze verdict first because it says whether the
        device is alive, then battery, then signal. The description
        expands each kind with its readable local start time, so the
        list line stays short and the tap-open carries the story.

        A device that is both low and falling reads as one line, the
        level then where it is heading: "battery 16%, empty in about
        2 weeks" rather than two phrases stacked (ruling #213).
        """
        tail = (
            TODO_KIND_LOW_BATTERY,
            TODO_KIND_FALLING_BATTERY,
            TODO_KIND_RAILED_SIGNAL,
        )
        order = [kind for kind in kinds if kind not in tail]
        order += [kind for kind in tail if kind in kinds]

        if UPSTREAM_KIND in kinds:
            return self._upstream_item_text(name, kinds, level)
        words = [self._kind_word(kind, level, left) for kind in order]
        # The falling clause names the battery unless the level
        # clause already did, so one item says the noun once and an
        # item carrying only the forecast still says what is empty
        # (ruling #216).
        if TODO_KIND_FALLING_BATTERY in order and (
            TODO_KIND_LOW_BATTERY not in order
        ):
            index = order.index(TODO_KIND_FALLING_BATTERY)
            if words[index].startswith("empty in "):
                words[index] = f"battery {words[index]}"
        summary = f"{name}: " + ", ".join(words)
        lines = []
        for kind, word in zip(order, words, strict=True):
            since = kinds.get(kind)
            if since is not None:
                when = self._format_report_time(
                    dt_util.as_local(dt_util.utc_from_timestamp(since))
                )
                lines.append(f"{word.capitalize()} since {when}.")
            else:
                lines.append(f"{word.capitalize()}.")
        # What the stack says about the same device, where it can say
        # anything. It goes in the description rather than the
        # summary, because the summary is a list line read at a
        # glance and this is a second opinion rather than the verdict
        # (ruling #221). It confirms or it doubts; it never changes
        # what the kinds above say.
        if device_id is not None and any(
            kind not in (
                TODO_KIND_LOW_BATTERY,
                TODO_KIND_FALLING_BATTERY,
                TODO_KIND_RAILED_SIGNAL,
            )
            for kind in order
        ):
            phrase = self.reachability_phrase(device_id)
            if phrase:
                lines.append(phrase)
            # The same plain sentence the push carries (ruling #235): a
            # convicted battery device is unreachable by radio, so
            # the tap-open says what fixes it, a person at the
            # device, rather than leaving the reader to try remedies
            # that cannot work.
            if device_id in self._battery_entity:
                lines.append(
                    "This is a battery device. It cannot be reached "
                    "remotely; bringing it back needs a person at "
                    "the device."
                )
        return summary, " ".join(lines)

    def _journal_addition(
        self, device_id: str, name: str, kind: str
    ) -> None:
        """Record one addition and announce it on the dispatcher.

        The journal plus the signal is the whole Step 8 contract: an
        addition to the list is the notification trigger, so the
        engine to come subscribes here and never re-derives newness
        from raw detections.
        """
        when = dt_util.utcnow().isoformat()
        journal = self.data.setdefault(DATA_TODO_JOURNAL, [])
        journal.append(
            {
                "device_id": device_id,
                "name": name,
                "kind": kind,
                "when": when,
            }
        )
        del journal[:-TODO_JOURNAL_KEEP]
        async_dispatcher_send(
            self.hass,
            SIGNAL_PROBLEM_ADDITION,
            {
                "device_id": device_id,
                "name": name,
                "kind": kind,
                "when": when,
            },
        )

    def _overtaken(self, kind: str, gained: set[str]) -> bool:
        """Return whether a kind ended because a worse one replaced it.

        A cell already below the threshold is absent from the falling
        source (ruling #213), so the moment Door 2nd Bedroom drops
        through 18 percent the item loses the forecast and gains the
        level in one pass. Both are collected, both are battery, and
        one push per family survives, so without this the phone would
        read "battery is no longer running down" at the exact moment
        the battery went low (ruling #220).

        Read from the severity order rather than by naming the pair,
        so a future kind that supersedes another needs nothing here.
        A kind absent from the order ranks last, which makes it
        supersede nothing and be superseded by anything named.
        """
        if not gained:
            return False
        order = self._KIND_SEVERITY
        limit = len(order)
        rank = order.index(kind) if kind in order else limit
        return any(
            (order.index(other) if other in order else limit) < rank
            for other in gained
        )

    @staticmethod
    def _event_line(
        kind: str, name: str, when: str, recovery: bool, left: str | None
    ) -> str:
        """Return the one sentence a push carries.

        Three shapes. A fault with a written line of its own, a fault
        assembled from the shared word, and a recovery. Every one of
        them is a sentence a person reads on a phone, so the kind
        never appears raw: an underscore reaching a person is the
        tell that a table was missed (ruling #215).
        """
        if recovery:
            written = _RECOVERY_LINE.get(kind)
            if written is not None:
                return f"At {when}, {written.format(name=name)}."
            return f"At {when}, {name} recovered."
        pair = _FAULT_LINE.get(kind)
        if pair is not None:
            with_left, without = pair
            if left:
                return f"At {when}, {with_left.format(name=name, left=left)}."
            return f"At {when}, {without.format(name=name)}."
        word = _EVENT_WORD.get(kind, kind)
        return f"At {when}, {name} was detected {word}."

    @callback
    def _collect_event(
        self,
        kind: str,
        name: str,
        recovery: bool,
        device_id: str,
        left: str | None = None,
        superseded: bool = False,
    ) -> None:
        """Buffer a family event to fire after the sync settles.

        The kind maps to its family (battery, signal, freeze), and the
        event line names the device and what happened, timestamped in
        local wall time so the push reads like a person would write it.
        The buffer is fired and cleared by the dispatch after the sync.

        A fault is held for its device's notification debounce first,
        so a problem that heals inside the delay is never announced.
        Its recovery cancels the hold and goes no further either: a
        recovery for a fault nobody was told about would be news about
        nothing. The card, the list and the brief are untouched by any
        of this, since they carry state rather than announcements.

        superseded is the crossing: a kind that ends because a worse
        one replaced it in the same pass. The hold is still cancelled,
        because the fault it guards has been overtaken, but nothing is
        announced, since a cell that dropped through the threshold has
        not stopped running down in any sense a person would accept
        (ruling #220).
        """
        family = NOTIFY_KIND_FAMILY.get(kind, "freeze")
        when = dt_util.now().strftime("%-I:%M %p").lower()
        line = self._event_line(kind, name, when, recovery, left)
        if (
            not recovery
            and family == NOTIFY_FAMILY_FREEZE
            and device_id in self._battery_entity
        ):
            # A convicted battery device cannot be reached by radio;
            # the recovery research established that plainly, so the
            # push says it rather than leaving the reader to try
            # (ruling #235). The elected battery entity is the
            # classification the battery detector already maintains,
            # so a device with one runs on battery.
            line = (
                f"{line} This is a battery device. It cannot be "
                "reached remotely; bringing it back needs a "
                "person at the device."
            )
        key = (device_id, kind)
        if recovery:
            cancel = self._held_events.pop(key, None)
            if cancel is not None:
                cancel()
                return
            if superseded:
                return
            self._pending_events.append((family, line, recovery))
            return
        delay = self._notification_delay(device_id)
        if delay <= 0:
            self._pending_events.append((family, line, recovery))
            return
        # A second fault of the same kind on the same device replaces
        # the hold rather than stacking a second timer on it.
        previous = self._held_events.pop(key, None)
        if previous is not None:
            previous()

        @callback
        def _release(_now: Any) -> None:
            self._release_held_event(key, family, line)

        self._held_events[key] = async_call_later(
            self.hass, delay, _release
        )

    def _dispatch_notifications(self) -> None:
        """Fire the buffered family events and refresh the card.

        Scheduled as a task because the sync is synchronous and the
        sends are async. The buffer is copied and cleared first, so a
        sync triggered while a dispatch is in flight does not double-
        send. The card always refreshes; the events are gated inside
        async_fire_events by quiet hours and the target list.
        """
        events = list(self._pending_events)
        self._pending_events.clear()
        self.hass.async_create_task(
            self._run_dispatch(events, self._upstream_messages())
        )

    def _upstream_messages(self) -> list[tuple[str, int, bool]]:
        """Return the upstream pushes this sync owes, if any.

        Ruling #265: an outage settles before it is announced, because
        the devices arrive over tens of seconds and a count taken at
        the first one is wrong. After the settle the count is pushed
        whenever it changes, silently after the first, so the tally on
        the phone is always current and only the first makes a sound.
        A recovery is announced once the upstream is back, carrying
        how many had gone quiet.
        """
        now = dt_util.utcnow().timestamp()
        counts = self.suppressed_down_counts
        messages: list[tuple[str, int, bool]] = []
        for name, count in counts.items():
            since = self.upstream_down_since_for(name)
            if since is None or now - since < UPSTREAM_SETTLE_SECONDS:
                continue
            if self._upstream_announced.get(name) == count:
                continue
            messages.append((name, count, False))
        for name, count in list(self._upstream_announced.items()):
            if name not in counts and self.upstream_down_since_for(name) is None:
                messages.append((name, count, True))
        return messages

    async def _run_dispatch(
        self,
        events: list[tuple[str, str, bool]],
        upstream: list[tuple[str, int, bool]] | None = None,
    ) -> None:
        """Await the card refresh and the pushes."""
        await self.async_update_card()
        await self.async_fire_events(events)
        for name, count, recovered in upstream or ():
            await self.async_push_upstream(name, count, recovered)

    def _retire_item(
        self,
        record: dict[str, Any],
        device_id: str,
        now: float,
        *,
        announce: bool = True,
    ) -> None:
        """Close every kind on an item that is going away.

        The item itself is dropped by the caller; this closes the
        incident timeline first, so the brief can tell the end of the
        story as well as its beginning. Acknowledged or not makes no
        difference: recovery is the automatic re-arm.

        `announce` is False when the item is going because its device
        left the watched set rather than because anything about the
        device changed. Nothing recovered, so no recovery is fired
        and the timeline records the device being set aside rather
        than the problem resolving: a resolution that never happened
        would leave the brief telling a house its device came back
        when it had never gone (ruling #368).
        """
        name = record.get(TODO_SORT_NAME) or device_id
        kinds = record.get(TODO_KINDS, {})
        if not announce:
            for kind in sort_kinds(
                [k for k in kinds if k != UPSTREAM_KIND]
            ):
                # A fault still held for its debounce is withdrawn
                # with the item. The release checks the list before
                # sending and would find nothing, so this changes no
                # outcome; it stops a timer outliving what it was
                # timing.
                cancel = self._held_events.pop((device_id, kind), None)
                if cancel is not None:
                    cancel()
                self._record_incident(
                    device_id,
                    name,
                    kind,
                    INCIDENT_ACTION,
                    cause=ACTION_SET_ASIDE,
                )
            return
        # Worst first, and every kind fires as it becomes the top,
        # so a line carrying two faults answers both rather than
        # leaving one unanswered. A device leaving the list can
        # therefore fire more than one recovery in the same instant,
        # which was ruled the lesser evil: an automation pairing
        # faults to recoveries stays balanced (ruling #289).
        for kind in sort_kinds([k for k in kinds if k != UPSTREAM_KIND]):
            # The incident being closed is what this recovery is
            # about, so its opening is what the duration measures.
            # The item's own stamp is a fallback and no longer the
            # first choice: a device set aside with a problem
            # standing keeps its verdict and its stamp, so the stamp
            # can predate this absence by any amount, and the event
            # then contradicts the timeline the brief reads from. On
            # 30 August a five minute absence was announced as
            # twenty-seven minutes for exactly that reason
            # (ruling #367).
            opened = self._incident_opened_at(device_id, kind)
            if opened is None:
                opened = kinds.get(kind)
            if isinstance(opened, bool) or not isinstance(
                opened, (int, float)
            ):
                # A stamp that is not a moment times nothing. The
                # row it came from is named on the card and carried
                # through; the recovery still fires, with no duration
                # rather than with a crash (ruling #369).
                opened = None
            self._resolve_incident(device_id, name, kind, now)
            self._collect_event(
                kind, name, recovery=True, device_id=device_id
            )
            self.fire_recovered(
                device_id,
                name,
                kind,
                None if opened is None else now - opened,
                # Bounded to this incident, using the opening read
                # before the resolve. Asking again here returns None,
                # because the row just written closes it, and the
                # `or 0.0` that caught it made the bound meaningless:
                # every episode on the device passed it, which is the
                # unbounded reading #228 was written to end
                # (ruling #367).
                self._recovery_cause(device_id, opened or 0.0),
            )

    def _diff_kinds(
        self,
        device_id: str,
        problem: dict[str, Any],
        stored_kinds: dict[str, float | None],
        now: float,
    ) -> dict[str, float | None]:
        """Return the item's new kind map, journalling what moved.

        A kind that was already there keeps the item's own stamp when
        the detection carries none, so a rail's first-seen time is not
        rewritten on every pass. A kind that has arrived opens an
        incident; a kind that has gone resolves one, marked superseded
        where another kind overtook it in the same pass.
        """
        new_kinds: dict[str, float | None] = {}
        for kind, since in problem["kinds"].items():
            if kind in stored_kinds:
                new_kinds[kind] = (
                    since if since is not None else stored_kinds[kind]
                )
                continue
            new_kinds[kind] = since if since is not None else now
            if kind == UPSTREAM_KIND:
                # No incident, no event, no journal line (ruling
                # #266): those are a device's story and this row is a
                # bridge. The outage has its own system event and its
                # own push already.
                continue
            self._journal_addition(device_id, problem["name"], kind)
            self._record_incident(
                device_id, problem["name"], kind, INCIDENT_OPENED
            )
            self._collect_event(
                kind, problem["name"], recovery=False,
                device_id=device_id, left=problem.get("left"),
            )
        gained = set(new_kinds) - set(stored_kinds)
        # Clearing worst first, so each kind is judged against what
        # is still on the line above it. A kind that is the highest
        # when it goes fires a recovery; a lesser one under a worse
        # one is silent, and becomes the highest itself once that
        # worse one has gone (ruling #289).
        standing = dict(stored_kinds)
        for kind in sort_kinds(
            [k for k in stored_kinds if k not in new_kinds]
        ):
            top = sort_kinds(standing)[0] if standing else None
            opened = standing.pop(kind, None)
            self._resolve_incident(device_id, problem["name"], kind, now)
            self._collect_event(
                kind, problem["name"], recovery=True,
                device_id=device_id,
                superseded=self._overtaken(kind, gained),
            )
            if kind == top:
                self.fire_recovered(
                    device_id,
                    problem["name"],
                    kind,
                    None if opened is None else now - opened,
                    # The same bound as the retire path: read before
                    # the resolve, because asking after it returns
                    # None and the fallback let any episode on the
                    # device answer (ruling #367).
                    self._recovery_cause(device_id, opened or 0.0),
                )
        return new_kinds

    def _new_item(
        self, device_id: str, problem: dict[str, Any], now: float
    ) -> dict[str, Any]:
        """Build the todo row for a device detected for the first time.

        A row a person deleted while the fault still stood comes back,
        and that return is the list re-adding an item, not the house
        producing a new fault. Calling it opened put a second opening
        on a key that already had one pending, which orphaned the
        first and left a real episode rendering as never resolved.
        """
        kinds = {
            kind: (since if since is not None else now)
            for kind, since in problem["kinds"].items()
        }
        summary, description = self._problem_item_text(
            problem["name"], kinds, problem["level"],
            problem.get("left"), device_id,
        )
        readded = device_id in self._hand_deleted
        self._hand_deleted.discard(device_id)
        for kind in kinds:
            if kind == UPSTREAM_KIND:
                continue
            self._journal_addition(device_id, problem["name"], kind)
            if readded:
                self._record_incident(
                    device_id,
                    problem["name"],
                    kind,
                    INCIDENT_ACTION,
                    cause=ACTION_READDED,
                )
                continue
            self._record_incident(
                device_id, problem["name"], kind, INCIDENT_OPENED
            )
            self._collect_event(
                kind, problem["name"], recovery=False,
                device_id=device_id, left=problem.get("left"),
            )
        # One event for the device, now that every kind is known.
        # Not inside the loop above: _journal_addition runs once per
        # kind, and firing there would give a device landing with two
        # faults two events, undoing #213's collapse on the bus while
        # it holds on the screen (ruling #289).
        self._fire_fault_for(device_id, problem, kinds, now)
        return {
            TODO_UID: uuid.uuid4().hex,
            TODO_DEVICE_ID: device_id,
            TODO_SUMMARY: summary,
            TODO_DESCRIPTION: description,
            TODO_STATUS: "needs_action",
            TODO_ACKED_AT: None,
            TODO_SORT_NAME: problem["name"],
            TODO_KINDS: kinds,
        }

    def _worth_announcing(
        self, arriving: set[str], standing: dict[str, float | None]
    ) -> bool:
        """Return whether an arriving kind is worth a person's phone.

        A device already on the list has been announced. What can
        still be new is a different family of problem: a cell dying on
        a device that is already silent is a second thing to know
        about, and the person hears it.

        What is not new is the same problem said differently. A
        device that is not reporting is called frozen, unavailable,
        unknown or never reported depending on what its entities read
        at the moment of judgment, and a restart that hides those
        states for a minute walks it from one to another and back. The
        reference fleet pushed a coordinator that had been unplugged
        for four days at every restart, thirty-one times, because the
        correction registered as an arrival (ruling #318).
        """
        families = {
            TODO_KIND_FAMILIES.get(kind, kind) for kind in standing
        }
        return any(
            TODO_KIND_FAMILIES.get(kind, kind) not in families
            for kind in arriving
        )

    def _fire_fault_for(
        self,
        device_id: str,
        problem: dict[str, Any],
        kinds: dict[str, float | None],
        now: float,
        *,
        renewed: bool = False,
    ) -> None:
        """Announce one device's faults, carrying what they need.

        The battery and signal figures ride along only when a kind
        that needs them is on the line, so an automation can read
        them without first checking whether they mean anything.
        """
        announced = [k for k in kinds if k != UPSTREAM_KIND]
        if not announced:
            return
        stamps = [
            stamp
            for k in announced
            if (stamp := kinds[k]) is not None
        ]
        since = min(stamps, default=now)
        self.fire_fault(
            device_id,
            problem["name"],
            announced,
            dt_util.utc_from_timestamp(since)
            .astimezone(dt_util.DEFAULT_TIME_ZONE)
            .isoformat(),
            renewed=renewed,
            level=problem.get("level"),
            signal_value=problem.get("signal_value"),
        )

    def _sync_problem_list(self) -> None:
        """Reconcile the todo against the detections, immediately.

        A full diff rather than incremental patches: idempotent, so a
        missed call self-heals on the next, and cheap at fleet scale.
        One item per device, keyed by device_id, whatever mix of
        problems it carries. An item appears the moment its device is
        first detected, its text follows the kinds as they come and
        go, and it is deleted the moment the last kind clears, open
        or acknowledged alike: recovery is the automatic re-arm, so
        the next failure is a new incident and a fresh item. The
        acknowledged status and its check time are never touched by
        the sync; silencing is exactly what the checkbox is for.

        Persistence rides the dirty flag: the render tick, the report
        paths, and shutdown all flush it, so a sync is safe to call
        from any detection path without its own await.
        """
        problems = self._current_problems()
        items = self.data.get(DATA_TODO_ITEMS, [])
        now = dt_util.utcnow().timestamp()
        changed = False
        kept: list[dict[str, Any]] = []

        for record in items:
            if (
                not isinstance(record, dict)
                or not isinstance(record.get(TODO_DEVICE_ID), str)
                or not isinstance(record.get(TODO_KINDS), dict)
            ):
                # A row the sync cannot use is carried through
                # untouched and skipped, never judged and never
                # dropped: the shape check has named it on the card,
                # Verify changes nothing (ruling #278), and a reader
                # that raises on it takes the whole list down with
                # it. The same rule #363 set for system events
                # (ruling #369).
                kept.append(record)
                continue
            device_id = record.get(TODO_DEVICE_ID)
            problem = problems.pop(device_id, None)
            if problem is None:
                # Two different things arrive here as the same
                # silence: a problem that ended, and a device nobody
                # is watching any more. Only the first is a recovery.
                # Announcing the second told a house that a device
                # had come back when it had never gone: the ZHA
                # coordinator is watched for the length of the
                # startup grace and set aside when it closes, and a
                # voice assistant said it was back up, out loud, at
                # every restart. Eight devices do it on the tester's
                # fleet (ruling #368).
                watched = device_id in self._watched
                self._retire_item(
                    record, device_id, now, announce=watched
                )
                changed = True
                continue
            stored_kinds: dict[str, float | None] = record.get(
                TODO_KINDS, {}
            )
            new_kinds = self._diff_kinds(
                device_id, problem, stored_kinds, now
            )
            arriving = set(new_kinds) - set(stored_kinds)
            if arriving and self._worth_announcing(arriving, stored_kinds):
                self._fire_fault_for(device_id, problem, new_kinds, now)
            summary, description = self._problem_item_text(
                problem["name"],
                new_kinds,
                problem["level"],
                problem.get("left"),
                device_id,
            )
            if (
                new_kinds != stored_kinds
                or record.get(TODO_SUMMARY) != summary
                or record.get(TODO_DESCRIPTION) != description
                or record.get(TODO_SORT_NAME) != problem["name"]
            ):
                record[TODO_KINDS] = new_kinds
                record[TODO_SUMMARY] = summary
                record[TODO_DESCRIPTION] = description
                record[TODO_SORT_NAME] = problem["name"]
                changed = True
            kept.append(record)

        for device_id, problem in problems.items():
            if now < self._grace_until:
                # A device first detected as never reported inside the
                # startup window stays off the list until the window
                # shuts. The window exists because things are still
                # arriving: integrations still loading, entities still
                # registering, a device with none yet that will have
                # some in a moment. A verdict of never reported taken
                # then is taken on a house that has not finished
                # waking up, and an item raised on it pushes a fault
                # to a phone at once, because a device with no learned
                # rhythm has no debounce. When the window shuts the
                # rebuild sets aside what has nothing to say, and what
                # is genuinely silent is listed then. A device already
                # on the list before the restart is untouched: its
                # item survived the restart and this loop never sees
                # it (ruling #369).
                remaining = {
                    kind: since
                    for kind, since in problem["kinds"].items()
                    if kind != FREEZE_CATEGORY_NEVER_REPORTED
                }
                if not remaining:
                    continue
                if len(remaining) != len(problem["kinds"]):
                    problem = dict(problem, kinds=remaining)
            kept.append(self._new_item(device_id, problem, now))
            changed = True

        if changed:
            self.data[DATA_TODO_ITEMS] = kept
            self._sort_todo_items()
            self._dirty = True
            self._critical = True
            self._notify()
        # Now that the list and its summaries are settled, fire the
        # collected family events and refresh the persistent card. The
        # card always updates; the events respect quiet hours and the
        # high-priority targets. Scheduled as a task because the sync
        # runs in a sync context and the sends are async.
        self._dispatch_notifications()

    def _problem_device_ids(self) -> set[str]:
        """Return the device_ids that currently have any fault.

        The union of the three problem lists, the same sets the todo
        sync reads. A device here is one the todo is expected to hold
        an item for; the report's status icon is judged against this
        set, not against the todo alone, so a healthy Reported device
        wears no icon.
        """
        ids: set[str] = set()
        for row in self.frozen_devices_list:
            ids.add(row["device_id"])
        for row in self.battery_low_list:
            ids.add(row["device_id"])
        for row in self.signal_problem_list:
            ids.add(row["device_id"])
        return ids

    def _todo_status_of(self, device_id: str) -> str | None:
        """Return a device's todo item status, or None when absent.

        "needs_action" or "completed" for an item the sync holds,
        None when no item exists for the device.
        """
        for record in self.todo_items:
            if record.get(TODO_DEVICE_ID) == device_id:
                return record.get(TODO_STATUS)
        return None

    def _still_on_the_list(self, device_id: str, kind: str) -> bool:
        """Return whether a held fault still describes reality.

        The list is the single source of truth, so it is what a
        matured hold is checked against: a device gone from the list,
        checked off by hand, or no longer carrying this kind has
        nothing left to announce.
        """
        for record in self.data.get(DATA_TODO_ITEMS, []):
            if record.get(TODO_DEVICE_ID) != device_id:
                continue
            if record.get(TODO_STATUS) == "completed":
                return False
            return kind in (record.get(TODO_KINDS) or {})
        return False

    @callback
    def _release_held_event(
        self, key: tuple[str, str], family: str, line: str
    ) -> None:
        """Send a held fault whose debounce has elapsed.

        The hold is cancelled by its own recovery, so one that
        survives to here is still true unless a hand silenced it in
        the meantime, which the list check catches. The line keeps the
        timestamp it was written with, so a delayed alert still says
        when the problem started rather than when it was sent.
        """
        self._held_events.pop(key, None)
        device_id, kind = key
        if not self._still_on_the_list(device_id, kind):
            return
        self.hass.async_create_task(
            self.async_fire_events([(family, line, False)])
        )

    @property
    def notification_debounce(self) -> float:
        """Return the configured notification debounce, as a fraction.

        Live from options (ruling #117): a fault waits this much of the
        device's own learned reporting gap before it reaches a phone,
        so a problem that heals inside the delay is never announced at
        all. Clamped to the band the screen offers, so a hand-edited
        entry cannot hold an alert for a week.
        """
        raw = int(
            self.entry.options.get(
                CONF_SETTLE_SHARE, DEFAULT_SETTLE_SHARE_PCT
            )
        )
        return min(SHARE_PCT_MAX, max(SHARE_PCT_MIN, raw)) / 100.0

    def _notification_delay(self, device_id: str) -> float:
        """Return the seconds a fault on this device waits to be sent.

        The share is of the device's own learned reporting gap, so a
        chatty device holds for seconds while a twice-a-day one holds
        for far longer, which is the same per-device reasoning the
        freeze windows use. A device with nothing learned yet has no
        gap to take a share of, so its fault goes out at once rather
        than waiting on a number that does not exist.
        """
        record = self.data[DATA_DEVICES].get(device_id)
        if record is None:
            return 0.0
        basis, _ = self._trimmed_maximum(record[DEV_DAILY_MAX])
        if basis is None or basis <= 0:
            return 0.0
        return basis * self.notification_debounce
