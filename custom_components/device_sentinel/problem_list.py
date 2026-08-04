# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: problem_list.py, Version: 0.11.13 (2026-08-04)

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

from .const import (
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_UNACKNOWLEDGED,
    CONF_SETTLE_SHARE,
    DATA_DEVICES,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    DEFAULT_SETTLE_SHARE_PCT,
    DEV_DAILY_MAX,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    NOTIFY_KIND_FAMILY,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    SIGNAL_PROBLEM_ADDITION,
    TODO_ACKED_AT,
    TODO_DESCRIPTION,
    TODO_DEVICE_ID,
    TODO_JOURNAL_KEEP,
    TODO_KINDS,
    TODO_KIND_BATTERY,
    TODO_KIND_BATTERY_FALLING,
    TODO_KIND_SIGNAL,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
)


_EVENT_WORD = {
    "battery": "low",
    "signal": "low signal",
    "rail": "railed",
    "frozen": "frozen",
    "unavailable": "unavailable",
    "unknown": "unknown",
    "not_reported": "never reporting",
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
        """Return the stored problem items in display order."""
        return self.data.get(DATA_TODO_ITEMS, [])

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
        self.data[DATA_TODO_ITEMS].sort(
            key=lambda record: (
                record.get(TODO_STATUS) == "completed",
                (
                    record.get(TODO_ACKED_AT) or ""
                    if record.get(TODO_STATUS) == "completed"
                    else (
                        record.get(TODO_SORT_NAME)
                        or record.get(TODO_SUMMARY)
                        or ""
                    ).lower()
                ),
            )
        )

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

        for row in self.frozen_devices_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][row["category"]] = row.get("since")

        for row in self.battery_low_list:
            entry = _entry(row["device_id"], row.get("name"))
            since = row.get("since")
            since_dt = dt_util.parse_datetime(since) if since else None
            entry["kinds"][TODO_KIND_BATTERY] = (
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
            entry["kinds"][TODO_KIND_BATTERY_FALLING] = None
            entry["left"] = row.get("left")
            if entry["level"] is None:
                entry["level"] = row.get("level")

        for row in self.signal_problem_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_SIGNAL] = None

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
        if kind == TODO_KIND_BATTERY:
            if level is None:
                return "battery low"
            shown = int(level) if float(level).is_integer() else level
            return f"battery {shown}%"
        if kind == TODO_KIND_BATTERY_FALLING:
            # The noun is carried, because the item may say this and
            # nothing else: "Door 2nd Bedroom: empty in about 2 weeks"
            # sitting beside "Soil Irrigation: battery 0%" leaves a
            # reader to guess what is empty (ruling #216). It reads
            # once when both kinds are present, because the level
            # clause ahead of it has already said the word.
            if left:
                return f"empty in {left}"
            return "battery running down"
        if kind == TODO_KIND_SIGNAL:
            return "signal (rail)"
        return kind.replace("_", " ")

    def _problem_item_text(
        self,
        name: str,
        kinds: dict[str, float | None],
        level: Any,
        left: str | None = None,
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
            TODO_KIND_BATTERY,
            TODO_KIND_BATTERY_FALLING,
            TODO_KIND_SIGNAL,
        )
        order = [kind for kind in kinds if kind not in tail]
        order += [kind for kind in tail if kind in kinds]

        words = [self._kind_word(kind, level, left) for kind in order]
        # The falling clause names the battery unless the level
        # clause already did, so one item says the noun once and an
        # item carrying only the forecast still says what is empty
        # (ruling #216).
        if TODO_KIND_BATTERY_FALLING in order and (
            TODO_KIND_BATTERY not in order
        ):
            index = order.index(TODO_KIND_BATTERY_FALLING)
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

    @callback
    def _collect_event(
        self, kind: str, name: str, recovery: bool, device_id: str
    ) -> None:
        """Buffer a family event to fire after the sync settles.

        The kind maps to its family (battery, signal, freeze), and the
        event line names the device and what happened, timestamped in
        local wall time so the push reads like a person would write it.
        A recovery reads recovered; a fault reads the kind. The buffer
        is fired and cleared by the dispatch after the sync.

        A fault is held for its device's notification debounce first,
        so a problem that heals inside the delay is never announced.
        Its recovery cancels the hold and goes no further either: a
        recovery for a fault nobody was told about would be news about
        nothing. The card, the list and the brief are untouched by any
        of this, since they carry state rather than announcements.
        """
        family = NOTIFY_KIND_FAMILY.get(kind, "freeze")
        when = dt_util.now().strftime("%-I:%M %p").lower()
        if recovery:
            line = f"At {when}, {name} recovered."
        else:
            line = f"At {when}, {name} was detected {_EVENT_WORD.get(kind, kind)}."
        key = (device_id, kind)
        if recovery:
            cancel = self._held_events.pop(key, None)
            if cancel is not None:
                cancel()
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
        self.hass.async_create_task(self._run_dispatch(events))

    async def _run_dispatch(
        self, events: list[tuple[str, str, bool]]
    ) -> None:
        """Await the card refresh and the event pushes."""
        await self.async_update_card()
        await self.async_fire_events(events)

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
            device_id = record.get(TODO_DEVICE_ID)
            problem = problems.pop(device_id, None)
            if problem is None:
                # Every kind cleared: the recovery deletes the item,
                # acknowledged or not. Each kind resolves on the
                # incident timeline first, so the brief can tell the
                # end of the story as well as its beginning.
                for kind in record.get(TODO_KINDS, {}):
                    self._resolve_incident(
                        device_id,
                        record.get(TODO_SORT_NAME) or device_id,
                        kind,
                        now,
                    )
                    self._collect_event(
                        kind,
                        record.get(TODO_SORT_NAME) or device_id,
                        recovery=True,
                        device_id=device_id,
                    )
                changed = True
                continue
            stored_kinds: dict[str, float | None] = record.get(
                TODO_KINDS, {}
            )
            new_kinds: dict[str, float | None] = {}
            for kind, since in problem["kinds"].items():
                if kind in stored_kinds:
                    # Keep the item's own stamp when the detection
                    # carries none, so a rail's first-seen time is
                    # not rewritten on every pass.
                    new_kinds[kind] = (
                        since
                        if since is not None
                        else stored_kinds[kind]
                    )
                else:
                    new_kinds[kind] = since if since is not None else now
                    self._journal_addition(
                        device_id, problem["name"], kind
                    )
                    self._record_incident(
                        device_id, problem["name"], kind, INCIDENT_OPENED
                    )
                    self._collect_event(
                        kind, problem["name"], recovery=False,
                        device_id=device_id,
                    )
            for kind in stored_kinds:
                if kind not in new_kinds:
                    self._resolve_incident(
                        device_id, problem["name"], kind, now
                    )
                    self._collect_event(
                        kind, problem["name"], recovery=True,
                        device_id=device_id,
                    )
            summary, description = self._problem_item_text(
                problem["name"],
                new_kinds,
                problem["level"],
                problem.get("left"),
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
            kinds = {
                kind: (since if since is not None else now)
                for kind, since in problem["kinds"].items()
            }
            summary, description = self._problem_item_text(
                problem["name"], kinds, problem["level"],
                problem.get("left"),
            )
            kept.append(
                {
                    TODO_UID: uuid.uuid4().hex,
                    TODO_DEVICE_ID: device_id,
                    TODO_SUMMARY: summary,
                    TODO_DESCRIPTION: description,
                    TODO_STATUS: "needs_action",
                    TODO_ACKED_AT: None,
                    TODO_SORT_NAME: problem["name"],
                    TODO_KINDS: kinds,
                }
            )
            # A row a person deleted while the fault still stood
            # comes back, and that return is the list re-adding an
            # item, not the house producing a new fault. Calling it
            # opened put a second opening on a key that already had
            # one pending, which orphaned the first and left a real
            # episode rendering as never resolved.
            readded = device_id in self._hand_deleted
            self._hand_deleted.discard(device_id)
            for kind in kinds:
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
                    device_id=device_id,
                )
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
