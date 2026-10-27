# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: problem_list.py, Version: 0.27.10 (2026-10-27)

"""The problem list: the single memory every channel renders.

One line per device however many problems it carries, worst first,
so a device that is both frozen and low on battery is one row rather
than two. Above the devices sit the upstream rows: a coordinator,
broker, Wi-Fi network or integration that has gone down takes one
row naming the cause with its casualties counted, and the devices
behind it never reach the list at all. The two exceptions are the
device already broken before the outage and the one still down after
it clears.

Checking a row is an acknowledgment and never a recovery. Recovery
is detected, and the row leaves on its own when the device speaks
again, whether or not anybody checked it.

One of the subject modules split out of coordinator.py. The seam is
the subject, chosen by measuring which methods call which (rule
CODE-11).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

import math

import uuid
from collections.abc import Callable
from typing import Any
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_call_later,
)
from homeassistant.util import dt as dt_util

from .battery_level import level_text
from .events import sort_kinds
from .narrative import BRIEF_EVENT_WORDS, BRIEF_STATE_WORDS
from .normalise import row_damage
from .const import (
    INCIDENT_SETTLE_SECONDS,
    TODO_KIND_FLAPPING,
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_MUTED,
    ACTION_REMOVED,
    ACTION_SET_ASIDE,
    ACTION_UNACKNOWLEDGED,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_WATCHED_FROM,
    FREEZE_CATEGORY_FROZEN,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    SETTLE_SHARE_PCT,
    DEV_DAILY_MAX,
    FREEZE_CATEGORY_NEVER_REPORTED,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    LOGGER,
    NOTIFY_KIND_FAMILY,
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
    WIFI_KEY,
    UPSTREAM_SETTLE_SECONDS,
    WITHDRAWN_REASON_MUTED,
    WITHDRAWN_REASON_REMOVED,
    WITHDRAWN_REASON_SET_ASIDE,
)


# Keyed by problem kind, so every key is a TODO_KIND_ and nothing
# else; a railed signal row carries TODO_KIND_RAILED_SIGNAL, so the
# two vocabularies are one (rule LIST-02).
_EVENT_WORD = {
    TODO_KIND_LOW_BATTERY: "low",
}
# A device problem's push line says what the device did in the Daily
# Brief's words, "At 3:04 pm, Kitchen Motion stopped reporting.", where
# it read "was detected frozen" (rules NOTE-01, UNAV-08).

# The kinds whose push line is written rather than assembled from
# _EVENT_WORD. A battery forecast cannot use the shared shape: "was
# detected running down" is not English, and nothing was detected
# about the device at all, since what changed is what its readings
# say about where it is heading (rule LIST-02). A recovery names the
# kind that lifted rather than reading "recovered", because a cell
# can carry a level and a forecast and "recovered" would not say
# which of them ended (rule NOTE-10).
_FAULT_LINE = {
    TODO_KIND_FLAPPING: (
        "{name} keeps dropping out",
        "{name} keeps dropping out",
    ),
    TODO_KIND_FALLING_BATTERY: (
        "{name} battery is running down, {left}",
        "{name} battery is running down",
    ),
}
_RECOVERY_LINE = {
    TODO_KIND_FLAPPING: "{name} has stopped dropping out",
    TODO_KIND_LOW_BATTERY: "{name} battery is no longer low",
    TODO_KIND_FALLING_BATTERY: "{name} battery is no longer running down",
}

class ProblemListMixin:
    """The problem list: the single memory every channel renders."""

    # Set in the coordinator's constructor (rule LIST-06).
    _parked: dict[str, float]
    _park_timer: Callable[[], None] | None
    _matured_in_park: dict[tuple[str, str], tuple[str, str]]


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

        Only rows a consumer can use. A damaged row is repaired out of
        the store at the boundary, so this filter is the readers' own
        safety for a row made some other way; the to-do entity, the
        sensors and the brief all read through here, the way every
        record surface reads through watched_records (rules STOR-09,
        WATCH-03).
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
            # nothing, rather than raising and taking the sync down.
            # The boundary repairs such a row; this is the sorter's own
            # safety (rule STOR-09). Every key is a string so no two
            # rows can be incomparable.
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
        the list, marked done, and nothing is sent about a device
        while its item sits acknowledged. The check time is
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
                # What the Problem List shows has changed, from
                # whichever surface the tick came.
                mark = getattr(self, "_mark_changed", None)
                if mark is not None:
                    mark()
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
                # (rule NOTE-12).
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
                    level, value = self._event_figures(record[TODO_DEVICE_ID])
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
                        level=level,
                        signal_value=value,
                    )
            break
        self._sort_todo_items()
        await self._save_now()
        self._notify()

    async def async_todo_delete(self, uids: list[str]) -> None:
        """Delete items the user removed by hand.

        Deleting an item whose device is still detected is the hard
        un-acknowledge: the next sync re-adds it fresh, and that
        re-add lands in the journal like any other, so it is
        announced again.

        Both halves reach the timeline now. Without the deletion on
        the record, a reader saw the same device detected twice with
        nothing between, which reads as a flapping fault rather than
        as somebody clearing a row that came straight back.
        """
        for record in self.data[DATA_TODO_ITEMS]:
            if record[TODO_UID] not in uids:
                continue
            device_id = record[TODO_DEVICE_ID]
            if self._parked.pop(device_id, None) is None:
                self._hand_deleted.add(device_id)
            else:
                # Its problems had already cleared and it waited its
                # minute (rule LIST-06): nothing stands to come back, so
                # its next fault is a new one.
                for key in [k for k in self._matured_in_park if k[0] == device_id]:
                    self._matured_in_park.pop(key, None)
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

        Reads the same properties the family sensors publish
        (frozen_devices_list, battery_low_list, battery_falling_list,
        signal_problem_list), with the upstream rows and the flapping_list
        beside them, so the list can never disagree with the sensors: one
        source, two readers. The freeze category string is the kind itself; a
        device carries at most one freeze kind but may stack battery and signal
        on top. since is normalized to epoch seconds where the detection has
        one; a rail has none, so the sync stamps the moment the kind first
        appears on the item instead.
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

        down_rows = self.reportable_down_rows
        # The run of drops is folded in before the list is built, so a
        # flap that starts on this pass is listed on it.
        self._track_flaps(down_rows, dt_util.utcnow().timestamp())
        for row in down_rows:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][row["category"]] = row.get("since")
        for row in self.flapping_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_FLAPPING] = row["since"]

        # One row for the fault itself. The devices it masks are
        # counted in the summary rather than listed, so the person is
        # told what to fix (rule UP-05).
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

        # A falling cell, from the battery rows Battery Trends shows, so
        # the list, that page, the brief and the sensor cannot disagree
        # about which cells are near the end (rule BAT-14). Cells
        # already low are absent from that source, so a device never
        # carries both kinds at once from here; where one follows the
        # other the item gains a kind and keeps its acknowledgment
        # (rule LIST-03). Acknowledging silences the phone and not the
        # record: the item stays on the list and updates to say the
        # level as well as the projection, so a person who ticked off a
        # forecast still watches it come true.
        for row in self.battery_falling_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_FALLING_BATTERY] = None
            # The whole clause, "reaches 15% in about 2 weeks" (rule BAT-13).
            entry["left"] = row.get("until") or row.get("left")
            if entry["level"] is None:
                entry["level"] = row.get("level")

        for row in self.signal_problem_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_RAILED_SIGNAL] = None
            # The railed value, for the fault event (rule NOTE-12).
            entry["signal_value"] = row.get("value")

        return problems

    def _event_figures(self, device_id: str) -> tuple[Any, Any]:
        """The battery level and railed signal value a renewed fault
        carries, read from the same rows the list is built from (rule
        NOTE-12). Without the flap tracking _current_problems does, so
        an untick changes nothing but the item."""
        level = None
        for row in self.battery_low_list:
            if row["device_id"] == device_id:
                level = row.get("level")
        if level is None:
            for row in self.battery_falling_list:
                if row["device_id"] == device_id:
                    level = row.get("level")
        value = None
        for row in self.signal_problem_list:
            if row["device_id"] == device_id:
                value = row.get("value")
        return level, value

    @staticmethod
    def _kind_word(
        kind: str, level: Any, left: str | None = None
    ) -> str:
        """Return one kind as the person reads it in the item text.

        The falling kind reads as a warning rather than a fault,
        because the cell is working: what is wrong is where it is
        heading. It says the time in the same words the report and the
        brief use, which are words rather than a count of days because
        the projection moves (rules BAT-13, BAT-14).
        """
        if kind == TODO_KIND_LOW_BATTERY:
            if level is None:
                return "battery low"
            return f"battery {level_text(level)}"
        if kind == TODO_KIND_FALLING_BATTERY:
            # The noun is carried, because the item may say this and
            # nothing else: "Door 2nd Bedroom: empty in about 2 weeks"
            # sitting beside "Soil Irrigation: battery 0%" leaves a
            # reader to guess what is empty (rule BAT-14). It reads
            # once when both kinds are present, because the level
            # clause ahead of it has already said the word.
            if left:
                return left if left.startswith(("reaches ", "empty in ")) else f"empty in {left}"
            return "battery running down"
        # The rest in the Daily Brief's words, as its Right Now table
        # says them: "stopped reporting", "signal railed" (rule LIST-02).
        if kind in BRIEF_STATE_WORDS:
            return BRIEF_STATE_WORDS[kind]
        return kind.replace("_", " ")

    def _upstream_item_text(
        self, name: str, kinds: dict[str, float | None], count: Any
    ) -> tuple[str, str]:
        """Return the summary and description for a downed upstream.

        The per-device grammar would give "z2m: upstream", which tells
        a person nothing: not what z2m is, not what it means for their
        house, not what to do. This row is the only one on the list
        that names a cause rather than a casualty, so it says so in
        words (rule UP-05).

        The count is in the summary and moves as devices fall, which
        is safe: the sync keeps an existing kind's stamp unless the
        detection carries its own, and this one carries the moment
        the upstream went down, which does not move while it stays
        down. So the text can be rewritten every pass and the SINCE
        column and the duration beside it stay pinned to the outage.
        """
        display = STACK_DISPLAY_NAMES.get(name, name)
        devices = int(count or 0)
        # Membership cannot honestly read below the casualties it is
        # measured against; where it does, the resolver has no
        # answer for this name and the count stands alone.
        behind = max(self.upstream_membership(name), devices)
        # Casualties against membership. The count climbs as devices
        # are judged and drains as they return, and printed alone it
        # reads as one number wandering; beside the membership the
        # drain reads as the recovery it is (rule UP-11).
        since = kinds.get(UPSTREAM_KIND)
        when = (
            self._format_report_time(
                dt_util.as_local(dt_util.utc_from_timestamp(since))
            )
            if since is not None
            else None
        )
        if name == WIFI_KEY:
            return self._wifi_item_text(devices, behind, when)
        if self.upstream_recovering_at(name) is not None:
            return self._bridge_recovering_text(name, display, behind)
        # The total named as the total, so it cannot be read as the
        # size of the recovery that follows (rule UP-11).
        summary = (
            f"{display} down: {devices} of {behind} total devices "
            f"unavailable"
        )
        opening = (
            f"{display} stopped reporting at {when}."
            if when
            else f"{display} is not reporting."
        )
        return summary, (
            f"{opening} {self._took_words(devices, behind)}, because of "
            f"it rather than on their own, so they are counted here "
            f"instead of listed. Each device keeps its own state while "
            f"it is down. Anything still down afterwards is listed on "
            f"its own."
        )

    @staticmethod
    def _took_words(devices: int, behind: int) -> str:
        """What the outage took, in the number the count deserves.

        The verb agrees with the count, and the sentence leads with
        what went down, which is what a person wants to know, rather
        than how many sit behind the upstream (rule UP-11).
        """
        if devices <= 0:
            noun = "device" if behind == 1 else "devices"
            has = "has" if behind == 1 else "have"
            return f"None of its {behind} {noun} {has} gone down yet"
        if behind <= 1:
            return "Its one device went down with it"
        if devices >= behind:
            return f"All {behind} devices behind it went down with it"
        return (
            f"{devices} of the {behind} devices behind it went down "
            f"with it"
        )

    @staticmethod
    def _recovering_words(
        subject: str, came_back: str, left: int, fell: int
    ) -> tuple[str, str]:
        """The row while an upstream's recovery is watched.

        Two totals exist during an outage, and each row names the one
        it counts against: a down row counts against every device
        behind the upstream, a recovering row against the devices that
        went down. And a recovery with nothing back yet says what it is
        waiting for, rather than saying "none remain recovered" beside
        "all remain unavailable", which reads as a contradiction (rule
        UP-11).

        `subject` names the upstream in the summary, and `came_back`
        is the opening of the description up to its time.
        """
        back = max(fell - left, 0)
        closing = (
            "Any device that does not recover will be reported as its "
            "own problem."
        )
        if back == 0:
            noun = "device" if left == 1 else "devices"
            return (
                f"{subject} is back: waiting for {left} {noun} to "
                f"reconnect",
                f"{came_back}. Device Sentinel is waiting for the "
                f"{left} {noun} that went down to reconnect. {closing}",
            )
        verb = "remains" if left == 1 else "remain"
        return (
            f"{subject} recovering: {left} of the {fell} devices that "
            f"went down {verb} unavailable",
            f"{came_back}. {back} of the {fell} devices that went down "
            f"have already recovered. Device Sentinel is monitoring the "
            f"recovery. {closing}",
        )

    def _bridge_recovering_text(
        self, stack: str, display: str, behind: int
    ) -> tuple[str, str]:
        """The row while a bridge's recovery is watched (rules UP-08, UP-11).

        The same shape the network gets, for the same reason: a
        bridge coming back is not the devices behind it being back,
        and a Zigbee device can take longer to rejoin a mesh than a
        Wi-Fi device takes to reassociate. The count here is simply
        how many of its devices are still down, which needs no fallen
        set to track and falls on its own as they return.
        """
        left, fell = self.upstream_recovery_counts(stack)
        when = self._format_report_time(
            dt_util.as_local(
                dt_util.utc_from_timestamp(self.upstream_recovering_at(stack))
            )
        )
        return self._recovering_words(
            display, f"{display} came back at {when}", left, fell
        )

    def _wifi_recovering_text(self, devices: int) -> tuple[str, str]:
        """The row while a recovery is being watched (rule UP-11).

        Three states rather than two, so a person can tell recovering
        from still down while the settle runs.

        The count is what has not come back, because that is the
        number falling toward zero and the one a person watches.
        """
        back = self.wifi_returned_count
        fell = max(devices, back)
        left = max(fell - back, 0)
        names = list(self.wifi_networks)
        if not names:
            subject = "Home Assistant's WiFi network"
        elif len(names) == 1:
            subject = f"The '{names[0]}' WiFi network"
        else:
            quoted = [f"'{one}'" for one in names]
            subject = (
                f"The {', '.join(quoted[:-1])} and {quoted[-1]} "
                f"WiFi networks"
            )
        when = self._format_report_time(
            dt_util.as_local(
                dt_util.utc_from_timestamp(self.wifi_recovering_at)
            )
        )
        verb = "networks came" if len(names) > 1 else "network came"
        opening = f"{subject.rsplit(' WiFi network', 1)[0]} WiFi {verb} back"
        return self._recovering_words(
            "WiFi network", f"{opening} at {when}", left, fell
        )

    def _wifi_item_text(
        self, devices: int, behind: int, when: str | None
    ) -> tuple[str, str]:
        """Return the row a Wi-Fi outage writes (rule UP-15).

        The stack grammar above belongs to a bridge, which is a
        component that stopped reporting. A network is not a
        component and does not report, so it gets its own wording:
        the network became unavailable, and it is named, because the
        person reads the row rather than the tie table.

        A house with no network configured is named for the house,
        and a house with several names them all. The plural form is
        untested on a real house.
        """
        if self.wifi_recovering_at is not None:
            return self._wifi_recovering_text(devices)
        names = list(self.wifi_networks)
        if not names:
            subject = "Home Assistant's WiFi network"
        elif len(names) == 1:
            subject = f"The '{names[0]}' WiFi network"
        else:
            quoted = [f"'{one}'" for one in names]
            subject = (
                f"The {', '.join(quoted[:-1])} and {quoted[-1]} "
                f"WiFi networks"
            )
        many = len(names) > 1
        verb = "networks" if many else "network"
        # "its" has no referent once two networks are named, so the
        # plural wording changes and the singular stays as it is.
        whose = "their" if many else "its"
        opening = (
            f"{subject} became unavailable at {when}."
            if when
            else f"{subject} is unavailable."
        )
        return (
            f"WiFi {verb} unavailable: {devices} of {behind} total "
            f"devices down",
            f"{opening} Currently, {devices} of {whose} {behind} total "
            f"devices became unavailable. Device Sentinel is tracking "
            f"these devices independently and this total will change "
            f"as this outage develops."
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

        The summary leads with the human readable device name, then the
        kinds in a fixed order: the freeze verdict first because it
        says whether the device is alive, then battery, then signal.
        The description expands each kind with its readable local start
        time, so the list line stays short and the tap-open carries the
        story.

        A device that is both low and falling reads as one line, the
        level then where it is heading: "battery 16%, empty in about
        2 weeks" rather than two phrases stacked (rule BAT-14).
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
        # A hub that is down says so, and how many devices it controls,
        # whether or not it has dropped out before: the count of what it
        # controls is what a person needs while it is down, and its
        # earlier drops stay on its page (rule STACK-10).
        hub_words = (
            self.hub_problem_words(device_id)  # type: ignore[attr-defined]
            if device_id is not None and TODO_KIND_UNAVAILABLE in order
            else None
        )
        if hub_words:
            order = [kind for kind in order if kind != TODO_KIND_FLAPPING]
        if TODO_KIND_FLAPPING in order:
            # The flap is the problem; a drop inside it is not listed
            # beside it, whether or not the device is down this minute.
            order = [kind for kind in order if kind != TODO_KIND_UNAVAILABLE]
        words = [
            self.flap_words(device_id)
            if kind == TODO_KIND_FLAPPING and device_id is not None
            else hub_words
            if kind == TODO_KIND_UNAVAILABLE and hub_words
            else self._kind_word(kind, level, left)
            for kind in order
        ]
        # The falling clause names the battery unless the level
        # clause already did, so one item says the noun once and an
        # item carrying only the forecast still says what is empty
        # (rule BAT-14).
        if TODO_KIND_FALLING_BATTERY in order and (
            TODO_KIND_LOW_BATTERY not in order
        ):
            index = order.index(TODO_KIND_FALLING_BATTERY)
            if words[index].startswith(("empty in ", "reaches ")):
                words[index] = f"battery {words[index]}"
        summary = f"{name}: " + ", ".join(words)
        lines = []
        for kind, word in zip(order, words, strict=True):
            since = kinds.get(kind)
            if kind == TODO_KIND_FLAPPING:
                # The first letter only, because str.capitalize() lowers
                # the rest and gives "since september 25, 2026 at 2:04 pm".
                lines.append(f"{word[:1].upper()}{word[1:]}.")
                continue
            when = self._plausible_time(since)
            if kind == TODO_KIND_UNAVAILABLE and hub_words:
                lines.append(self.hub_problem_line(device_id, when))  # type: ignore[attr-defined]
                continue
            # A never-reported device's time is when watching began,
            # and the brief says "discovered" (rule LIST-10); a stopped
            # device stopped at a moment, as the brief tells it (rule
            # LIST-02).
            if kind == TODO_KIND_NEVER_REPORTED and when is not None:
                lines.append(f"{word.capitalize()}, discovered {when}.")
                continue
            if kind == TODO_KIND_FROZEN and when is not None:
                lines.append(f"{word.capitalize()} at {when}.")
                continue
            if when is not None:
                lines.append(f"{word.capitalize()} since {when}.")
            else:
                lines.append(f"{word.capitalize()}.")
        # What the stack says about the same device, where it can say
        # anything. It goes in the description rather than the
        # summary, because the summary is a list line read at a
        # glance and this is a second opinion rather than the verdict
        # (rule STACK-03). It confirms or it doubts; it never changes
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
        # The item no longer adds that a battery device needs a person
        # at it, as the push no longer does (rule NOTE-10).
        return summary, " ".join(lines)

    def _journal_addition(
        self, device_id: str, name: str, kind: str
    ) -> None:
        """Record one addition to the list in the journal.

        The journal is the record of what was added and when (rule
        LIST-05).
        """
        when = dt_util.utcnow().isoformat()
        self._append_row(
            DATA_TODO_JOURNAL,
            {
                "device_id": device_id,
                "name": name,
                "kind": kind,
                "when": when,
            },
        )
        journal = self.data.setdefault(DATA_TODO_JOURNAL, [])
        del journal[:-TODO_JOURNAL_KEEP]

    def _kind_muted(self, device_id: str, kind: str) -> bool:
        """Whether a person's mute is what silenced this kind.

        A mute is a person's act, not a recovery: an item or a kind
        that leaves the list because its device, its freeze or its
        battery was muted, by device, integration or label, has
        nothing to announce (rule MUTE-07). Read per kind, because a
        freeze mute takes only frozen and never reported, the
        unavailable mute every down kind, and a battery mute only the
        battery kinds, and the other family on the same item may still
        be a genuine recovery. A whole-device mute takes every kind.
        """
        if device_id in getattr(self, "_muted_devices", {}):
            return True
        family = TODO_KIND_FAMILIES.get(kind)
        if family == "down":
            # A freeze mute takes what is judged from silence; the
            # unavailable mute takes every down kind, dropping out
            # included (rule MUTE-06).
            if self._kind_muted_plain(device_id, kind):
                return True
            # A kind held from before while a mute took the device's
            # verdict away: the device is still down and the mute is
            # why it leaves.
            return self._down_but_muted(device_id)
        if family == "battery":
            return bool(self._battery_muted(device_id))  # type: ignore[attr-defined]
        if family == "signal":
            return bool(self._signal_muted(device_id))  # type: ignore[attr-defined]
        return False

    def _kind_muted_plain(self, device_id: str, kind: str) -> bool:
        """Whether a person's mute covers this down kind on the device."""
        if kind in (TODO_KIND_FROZEN, TODO_KIND_NEVER_REPORTED):
            return bool(self._freeze_muted(device_id))  # type: ignore[attr-defined]
        if TODO_KIND_FAMILIES.get(kind) == "down":
            return bool(self._unavailable_muted(device_id))  # type: ignore[attr-defined]
        return False

    def _down_but_muted(self, device_id: str) -> bool:
        """Whether a mute took the device's verdict away while it was
        still down (detect_freeze._apply_freeze_verdict), or covers the
        verdict that still stands, which the down list leaves out at once
        (frozen_devices_list), before any sweep has run."""
        if device_id in getattr(self, "_muted_down", set()):
            return True
        record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
        category = record.get(DEV_FROZEN_CATEGORY)
        return category is not None and self._muted_away(  # type: ignore[attr-defined]
            category,
            self._freeze_muted(device_id),  # type: ignore[attr-defined]
            self._unavailable_muted(device_id),  # type: ignore[attr-defined]
        ) is None

    def _still_judged_down(self, device_id: str | None) -> bool:
        """Whether a device's own verdict still says it is not reporting.

        A recovery goes one way: an item leaves the list as recovered
        only when its device reports (rule LIST-08). Its problem can be
        missing from the source for a moment while the verdict stands,
        and that absence is not a return: after a restart the grace
        keeps never-reported devices off the source until it closes
        (rule WATCH-10), and without this hold such devices were told
        recovered at every reload. Such an item is held, as a held
        upstream's devices are. A device that is unwatched or muted is
        not, since those do leave the list (rule LIST-09).
        """
        if device_id is None or device_id not in self._watched:
            return False
        if device_id in getattr(self, "_muted_devices", set()):
            return False
        record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
        category = record.get(DEV_FROZEN_CATEGORY)
        if category is None:
            return False
        # Muted for the kind its verdict is: not held (rule MUTE-06).
        return self._muted_away(  # type: ignore[attr-defined]
            category,
            self._freeze_muted(device_id),  # type: ignore[attr-defined]
            self._unavailable_muted(device_id),  # type: ignore[attr-defined]
        ) is not None

    def _plausible_time(self, since: Any) -> str | None:
        """A start time as a person reads it, or None when it cannot be one.

        A stamp outside what a date can hold would crash the minute
        tick here, and with it the freeze judgment, the list and the
        save, for as long as the stamp stood. The item then says what
        is wrong without a time (rule STOR-07).
        """
        if isinstance(since, bool) or not isinstance(since, (int, float)) or since <= 0:
            return None
        try:
            return self._format_report_time(
                dt_util.as_local(dt_util.utc_from_timestamp(since))
            )
        except (OverflowError, OSError, ValueError):
            return None

    # The down family's plain verdicts, which one silence moves between
    # as its entities change. Flapping is the family's own problem with
    # its own ending, and never held (rules UNAV-06, LIST-08).
    _HELD_DOWN = (TODO_KIND_UNAVAILABLE, TODO_KIND_FROZEN, TODO_KIND_UNKNOWN)

    def _hold_the_worst(
        self,
        stored_kinds: dict[str, float | None],
        incoming: dict[str, float | None],
        device_id: str | None = None,
    ) -> dict[str, float | None]:
        """Keep a silent device's worst verdict until it reports (rule LIST-08).

        A recovery goes one way. Frozen to unavailable is the device
        getting worse and is told so; the step back, unavailable to
        frozen or unknown, happens only while a boot or a coordinator
        restart hides the entities for a moment, and it is false data.
        So within the down family the list never steps down: the worse
        kind stays, with its own start, until the device reports and
        the family clears. Otherwise the step back closes the
        unavailable record, the bus hears a recovery, and a new frozen
        record opens, though the device never spoke.
        """
        order = self._KIND_SEVERITY
        # A kind the person has muted is never held.
        standing = [
            k for k in stored_kinds
            if k in self._HELD_DOWN
            and not (device_id is not None and self._kind_muted_plain(device_id, k))
        ]
        arriving = [k for k in incoming if k in self._HELD_DOWN]
        if not standing:
            return incoming
        if not arriving:
            # The down problem left while another kept the item, and
            # the device's own verdict still says it is down: an
            # upstream outage dated from the start of the run claims
            # everything behind it and hides the row, which is not the
            # device reporting (rules UP-05, LIST-08). Without this the
            # bus hears a recovery and the upstream's return announces
            # the problem again. The worst kind stays.
            if not self._still_judged_down(device_id):
                return incoming
            held = dict(incoming)
            worst = min(standing, key=order.index)
            held[worst] = stored_kinds[worst]
            return held
        worst = min(standing, key=order.index)
        if any(order.index(k) <= order.index(worst) for k in arriving):
            return incoming
        held = {k: v for k, v in incoming.items() if k not in self._HELD_DOWN}
        held[worst] = stored_kinds[worst]
        return held

    @staticmethod
    def _still_down(kind: str, new_kinds: dict[str, float | None]) -> bool:
        """Whether a down kind leaves while the device is still down."""
        if TODO_KIND_FAMILIES.get(kind) != "down":
            return False
        return any(
            TODO_KIND_FAMILIES.get(other) == "down" for other in new_kinds
        )

    def _overtaken(self, kind: str, gained: set[str]) -> bool:
        """Return whether a kind ended because a worse one replaced it.

        A cell already below the threshold is absent from the falling
        source (rule BAT-14), so the moment a cell drops through the
        threshold the item loses the forecast and gains the level in
        one pass. Both are collected, both are battery, and one push
        per family survives, so without this the phone would read
        "battery is no longer running down" at the exact moment the
        battery went low (rules LIST-07, NOTE-10).

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
        kind: str,
        name: str,
        when: str,
        recovery: bool,
        left: str | None,
        said: str | None = None,
    ) -> str:
        """Return the one sentence a push carries.

        Four shapes. A fault in words the caller worked out for the
        device (`said`: a hub that went down, a count of drop-outs), a
        fault in the Daily Brief's word for its kind, a fault with a
        written line of its own, and a recovery. Every one of them is a
        sentence a person reads on a phone, so the kind never appears
        raw: an underscore reaching a person is the tell that a table
        was missed (rules LIST-02, NOTE-01, UNAV-08).
        """
        if not recovery and said:
            return f"At {when}, {name} {said}."
        if not recovery and kind in BRIEF_EVENT_WORDS:
            return f"At {when}, {name} {BRIEF_EVENT_WORDS[kind]}."
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
        final: bool = False,
        at: float | None = None,
    ) -> None:
        """Buffer a family event to fire after the sync settles.

        A ticked item is silent on the phone until the device's last
        problem clears (rules LIST-03, NOTE-08): a kind arriving on it,
        or leaving it while another stays, sends nothing, and `final`,
        the recovery as the item leaves the list, is pushed. The bus is
        not this method's, so automations still hear every change.

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
        (rule NOTE-10).
        """
        # A drop inside a flap is recorded, never announced: the flap
        # was, once, and will be again when it ends. Otherwise a
        # flapping device pushes every drop and every return.
        if kind == TODO_KIND_UNAVAILABLE and self.is_flapping(device_id):
            return
        key = (device_id, kind)
        if not final and self._todo_status_of(device_id) == "completed":
            # Ticked: nothing reaches the phone until the item leaves
            # (rule LIST-03). A fault held from before the tick is
            # dropped by its release, which reads the list; a recovery
            # here still cancels its own fault's hold.
            if recovery:
                cancel = self._held_events.pop(key, None)
                if cancel is not None:
                    cancel()
            return
        family = NOTIFY_KIND_FAMILY.get(kind, "freeze")
        moment = dt_util.now() if at is None else dt_util.as_local(dt_util.utc_from_timestamp(at))
        when = moment.strftime("%-I:%M %p").lower()
        # The brief's words where they depend on the device: a hub
        # "went down", and a device dropping out says how often, as the
        # brief does (rules NOTE-01, UNAV-08). The push no longer adds
        # that a battery device needs a person at it (rule NOTE-10).
        said = None
        if not recovery and kind == TODO_KIND_UNAVAILABLE:
            words = self.unavailable_words(device_id)  # type: ignore[attr-defined]
            said = words[0] if words else None
        elif not recovery and kind == TODO_KIND_FLAPPING:
            said = self.flap_words(device_id)  # type: ignore[attr-defined]
        elif not recovery and kind == TODO_KIND_LOW_BATTERY:
            # A low battery reads as the brief says it, "battery fell
            # to 12%", not "was detected low" (rule NOTE-10).
            said = self._battery_phrase(device_id, False)  # type: ignore[attr-defined]
        line = self._event_line(kind, name, when, recovery, left, said)
        if recovery:
            cancel = self._held_events.pop(key, None)
            if cancel is not None:
                cancel()
                return
            if self._matured_in_park.pop(key, None) is not None:
                # Its fault matured while it waited its minute and was
                # never sent, so its recovery is no news (rule LIST-06).
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

    def _upstream_phases(self) -> dict[str, str]:
        """What phase each downed upstream is in (rule UP-09).

        Phases rather than a number: "down", "recovering" and, by
        absence, over. Keyed on the casualty count, the push would
        move on every device that returns once the recovering row
        counts down live, and a recovery would announce itself once
        per device. Keyed on the phase, a tracker flapping inside the
        settle cannot announce at all, because the phase has not
        changed.

        A Wi-Fi outage stays open while it recovers, so its phase is
        down until it is over: recovering sends no push, the row says
        it, and a recovery withdrawn by losses pushes nothing again
        either. Read as recovering it would push a third time, unlike
        every other upstream (rule UP-09).
        """
        phases: dict[str, str] = {}
        for name in self.suppressed_down_counts:
            recovering = (
                name != WIFI_KEY
                and self.upstream_recovering_at(name) is not None
            )
            phases[name] = "recovering" if recovering else "down"
        return phases

    def _upstream_messages(self) -> list[tuple[str, int, bool]]:
        """Return the upstream pushes this sync owes, if any.

        An outage settles before it is announced, because the devices
        arrive over tens of seconds and a count taken at the first one
        is wrong. After the settle it is pushed once for each phase:
        when it is down, and once it is over; the recovering phase
        sends nothing. Every upstream that is down has a row from the
        start, so a healthy house losing one is told too (rules UP-05,
        UP-09).

        Nothing is owed inside the startup grace (rule WATCH-10). The
        phase is not recorded either, so an outage still standing when
        the window shuts is announced then, once.
        """
        if self._in_startup_grace():
            return []
        now = dt_util.utcnow().timestamp()
        counts = self.suppressed_down_counts
        phases = self._upstream_phases()
        messages: list[tuple[str, int, bool]] = []
        for name, count in counts.items():
            since = self.upstream_down_since_for(name)
            if since is None or now - since < UPSTREAM_SETTLE_SECONDS:
                continue
            # Keyed on the phase, not the count (rule UP-09).
            if self._upstream_phase.get(name) == phases.get(name):
                continue
            self._upstream_phase[name] = phases.get(name)
            messages.append((name, count, False))
            # Kept with a bridge or broker outage, so a restart does not
            # push its down a second time (rule UP-09).
            self._note_upstream_pushed(name)
        for name, count in list(self._upstream_announced.items()):
            if name not in counts and self.upstream_down_since_for(name) is None:
                self._upstream_phase.pop(name, None)
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
        muted: set[str] | None = None,
    ) -> None:
        """Close every kind on an item that is going away.

        `muted` names the kinds a person's mute silenced (rule MUTE-07).
        Each leaves as that person's action, with no recovery fired
        and no resolution written, the way an unwatched device's kinds
        leave; the kinds not in it, if any, resolve as before.

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
        when it had never gone (rule LIST-09).
        """
        name = record.get(TODO_SORT_NAME) or device_id
        kinds = record.get(TODO_KINDS, {})
        if not announce:
            # Removed from Home Assistant rather than set aside: the
            # timeline and the event say which (rule WATCH-07).
            removed = self.is_held(device_id)  # type: ignore[attr-defined]
            withdrawn = sort_kinds([k for k in kinds if k != UPSTREAM_KIND])
            for kind in withdrawn:
                # A fault still held for its debounce is withdrawn
                # with the item. The release checks the list before
                # sending and would find nothing, so this changes no
                # outcome; it stops a timer outliving what it was
                # timing.
                cancel = self._held_events.pop((device_id, kind), None)
                if cancel is not None:
                    cancel()
                # A hand deletion is forgotten with the item, as the
                # verdict is: the incident it belonged to is closed here
                # as set aside, so the device returning later is a fresh
                # problem, not the deleted row coming back (rule
                # LIST-09).
                self._hand_deleted.discard(device_id)
                self._record_incident(
                    device_id,
                    name,
                    kind,
                    INCIDENT_ACTION,
                    cause=ACTION_REMOVED if removed else ACTION_SET_ASIDE,
                )
            if withdrawn:
                # The answer the untick event promises, without the
                # word "recovered" (rule NOTE-12).
                self.fire_withdrawn(
                    device_id, name, withdrawn,
                    WITHDRAWN_REASON_REMOVED if removed else WITHDRAWN_REASON_SET_ASIDE,
                )
            return
        # Worst first, and every kind fires as it becomes the top,
        # so a line carrying two faults answers both rather than
        # leaving one unanswered. A device leaving the list can
        # therefore fire more than one recovery in the same instant,
        # the lesser evil, because an automation pairing faults to
        # recoveries stays balanced (rule NOTE-12).
        silenced = sort_kinds(
            [k for k in kinds if k != UPSTREAM_KIND and k in (muted or ())]
        )
        for kind in silenced:
            cancel = self._held_events.pop((device_id, kind), None)
            if cancel is not None:
                cancel()
            self._record_incident(
                device_id, name, kind, INCIDENT_ACTION, cause=ACTION_MUTED
            )
        if silenced:
            self.fire_withdrawn(
                device_id, name, silenced, WITHDRAWN_REASON_MUTED
            )
        for kind in sort_kinds(
            [k for k in kinds if k != UPSTREAM_KIND and k not in silenced]
        ):
            # The incident being closed is what this recovery is
            # about, so its opening is what the duration measures.
            # The item's own stamp is a fallback and no longer the
            # first choice: a device set aside with a problem
            # standing keeps its verdict and its stamp, so the stamp
            # can predate this absence by any amount, and the event
            # would then contradict the timeline the brief reads from
            # (rule LIST-09).
            opened = self._incident_opened_at(device_id, kind)
            if opened is None:
                opened = kinds.get(kind)
            if isinstance(opened, bool) or not isinstance(
                opened, (int, float)
            ):
                # A stamp that is not a moment times nothing: the
                # recovery still fires, with no duration rather than
                # with a crash. The boundary repairs such a row; this
                # is the reader's own safety (rule STOR-09).
                opened = None
            # This path is the device leaving the list altogether, so
            # nothing replaced anything: every kind here really did
            # clear.
            down = self._down_for(device_id, kind, opened, now)
            self._resolve_incident(
                device_id, name, kind, now, opened_at=opened, down_for=down,
                at=now,
            )
            self._collect_event(
                kind, name, recovery=True, device_id=device_id, final=True,
                at=now,
            )
            self.fire_recovered(
                device_id,
                name,
                kind,
                down,
                # Bounded to this incident, using the opening read
                # before the resolve. Asking again here returns None,
                # because the row just written closes it, and an
                # `or 0.0` fallback would let every episode on the
                # device pass the bound (rule BRIEF-05).
                self._recovery_cause(device_id, opened or 0.0),
            )

    def _down_for(
        self, device_id: str, kind: str, opened: float | None, now: float
    ) -> float | None:
        """How long a recovered device was down, for the recovered event.

        For a frozen, unavailable or unknown kind (rule UNAV-07):
        trouble that began as a freeze counts from the device's last
        report, so a device frozen at 2h21 and unavailable at 2h41 that
        returns at 2h50 was down 2h50; trouble that began as
        unavailable or unknown counts from when it went, so a
        five-minute drop on a device that reports twice a day reads five
        minutes. A freeze that cleared with no report (the wait grew, a
        setting changed) counts from the last report. A device taken
        back counts from when it was watched again (rule WATCH-08), or
        from the opening when it came back already past its window.
        Other kinds count from the opening.
        """
        began: Any = None
        if TODO_KIND_FAMILIES.get(kind) == "down":
            ended = self._report_ends_down.pop(device_id, None)  # type: ignore[attr-defined]
            if isinstance(ended, tuple):
                began_as, chain_since = ended
                if began_as == FREEZE_CATEGORY_FROZEN:
                    # A freeze: down since the device last spoke.
                    began = self._silence_began.get(device_id)  # type: ignore[attr-defined]
                elif isinstance(chain_since, (int, float)) and not isinstance(chain_since, bool):
                    # Straight to unavailable or unknown: down since it went.
                    began = chain_since
                else:
                    began = self._silence_began.get(device_id)  # type: ignore[attr-defined]
            elif kind == TODO_KIND_FROZEN:
                # A freeze that cleared with no report: the wait grew.
                # Not across a stretch the device was set aside, which
                # keeps the opening, as the report path does (round
                # thirteen).
                devices = self.data.get(DATA_DEVICES) if isinstance(self.data, dict) else None  # type: ignore[attr-defined]
                record = devices.get(device_id) if isinstance(devices, dict) else None
                if isinstance(record, dict) and record.get(DEV_SET_ASIDE_SINCE) is None:
                    began = record.get(DEV_LAST_ACTIVITY)
                elif isinstance(record, dict):
                    # Taken back: from when it was watched again (rule WATCH-08).
                    began = record.get(DEV_WATCHED_FROM)
        # Across a clock step both count from the step (rule FRZ-21).
        if isinstance(began, (int, float)) and not isinstance(began, bool):
            began = self._counted_from(float(began))  # type: ignore[attr-defined]
        opened = self._counted_from(opened)  # type: ignore[attr-defined]
        if (
            isinstance(began, (int, float))
            and not isinstance(began, bool)
            and math.isfinite(began)
            and began > 0.0
            and began <= now
            and (opened is None or began <= opened)
        ):
            return now - began
        return None if opened is None else max(0.0, now - opened)

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
        incoming = self._hold_the_worst(
            stored_kinds, problem["kinds"], device_id
        )
        for kind, since in incoming.items():
            if kind in stored_kinds:
                new_kinds[kind] = (
                    since if since is not None else stored_kinds[kind]
                )
                continue
            new_kinds[kind] = since if since is not None else now
            if kind == UPSTREAM_KIND:
                # No incident, no event, no journal line: those are a
                # device's story and this row is a bridge. The outage
                # has its own system event and its own push already
                # (rule UP-05).
                continue
            self._journal_addition(device_id, problem["name"], kind)
            self._record_incident(
                device_id, problem["name"], kind, INCIDENT_OPENED,
                since=since,
            )
            if self._said_in_family(device_id, kind, stored_kinds):
                # A worsening inside the family, such as frozen becoming
                # unavailable, is the same problem said differently: no
                # push, as no new fault (rule LIST-06).
                continue
            self._collect_event(
                kind, problem["name"], recovery=False,
                device_id=device_id, left=problem.get("left"),
            )
        gained = set(new_kinds) - set(stored_kinds)
        # Clearing worst first, so each kind is judged against what
        # is still on the line above it. A kind that is the highest
        # when it goes fires a recovery; a lesser one under a worse
        # one is silent, and becomes the highest itself once that
        # worse one has gone (rule NOTE-12).
        standing = dict(stored_kinds)
        for kind in sort_kinds(
            [k for k in stored_kinds if k not in new_kinds]
        ):
            top = sort_kinds(standing)[0] if standing else None
            # The same fallback the site above uses: the stored start
            # time for this kind, where the log no longer has the
            # opening (rule LIST-11).
            opened = standing.pop(kind, None)
            if isinstance(opened, bool) or not isinstance(
                opened, (int, float)
            ):
                opened = None
            if self._kind_muted(device_id, kind):
                # A person muted it; nothing recovered (rule MUTE-07).
                cancel = self._held_events.pop((device_id, kind), None)
                if cancel is not None:
                    cancel()
                self._record_incident(
                    device_id, problem["name"], kind, INCIDENT_ACTION,
                    cause=ACTION_MUTED,
                )
                self.fire_withdrawn(
                    device_id, problem["name"], [kind], WITHDRAWN_REASON_MUTED
                )
                continue
            # A recovery goes one way (rule LIST-08): a kind leaving
            # while another of the down family still stands is the
            # device still not reporting, said differently, and no
            # surface tells it as a recovery.
            replaced = self._overtaken(kind, gained) or self._still_down(
                kind, new_kinds
            )
            down = (
                self._down_for(device_id, kind, opened, now)
                if kind == top and not replaced
                else None
            )
            self._resolve_incident(
                device_id, problem["name"], kind, now, opened_at=opened,
                superseded=replaced, down_for=down,
            )
            self._collect_event(
                kind, problem["name"], recovery=True,
                device_id=device_id,
                superseded=replaced,
            )
            if kind == top and not replaced:
                self.fire_recovered(
                    device_id,
                    problem["name"],
                    kind,
                    down,
                    # The same bound as the retire path: read before
                    # the resolve, because asking after it returns
                    # None and the fallback let any episode on the
                    # device answer (rule BRIEF-05).
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
                device_id, problem["name"], kind, INCIDENT_OPENED,
                since=problem["kinds"].get(kind),
            )
            self._collect_event(
                kind, problem["name"], recovery=False,
                device_id=device_id, left=problem.get("left"),
            )
        # One event for the device, now that every kind is known.
        # Not inside the loop above: _journal_addition runs once per
        # kind, and firing there would give a device landing with two
        # faults two events, undoing the one-line collapse on the bus
        # while it holds on the screen (rules LIST-01, NOTE-12).
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

    def _said_in_family(
        self, device_id: str, kind: str, standing: dict[str, float | None]
    ) -> bool:
        """Whether a kind of the same family already stands on the item
        and has been told, or was never to be told (rule LIST-06).

        One still held for its debounce has told nobody yet, so the
        worse kind takes its place in the hold rather than the person
        hearing nothing at all.
        """
        family = TODO_KIND_FAMILIES.get(kind, kind)
        if family != "down":
            # A battery crossing from running down to low is pushed
            # (rule NOTE-10): only the not-reporting family is said once.
            return False
        same = [
            k for k in standing
            if k != UPSTREAM_KIND and TODO_KIND_FAMILIES.get(k, k) == family
        ]
        return bool(same) and not any(
            (device_id, k) in self._held_events for k in same
        )

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
        states for a minute walks it from one to another and back. A
        coordinator unplugged for days would otherwise be pushed at
        every restart, because the correction registers as an arrival
        (rule LIST-06).
        """
        families = {
            TODO_KIND_FAMILIES.get(kind, kind) for kind in standing
        }
        # A battery running down that crosses into low is news, on the
        # bus as on the phone, because the forecast has come true and a
        # low battery is what a person acts on.
        if TODO_KIND_LOW_BATTERY in arriving:
            return True
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
        # A device held (its integration still loading after a restart,
        # or a Wi-Fi burst waiting for the router) has its row taken out
        # of the source until the hold ends (rules UP-04, UP-15). Held
        # means undecided, not recovered: its standing freeze problem
        # stays as it was, so a never-reported device is not retired as
        # recovered at a restart and raised again minutes later.
        held = self.wifi_burst_held() | self.loading_held()
        items = self.data.get(DATA_TODO_ITEMS, [])
        now = dt_util.utcnow().timestamp()
        # A start time no clock could give is taken as now, here where
        # every stamp enters the list, so nothing downstream is handed
        # a date it cannot write. One such stamp would crash the minute
        # tick, and with it the freeze judgment, the list and the save
        # (rule STOR-07).
        for problem in problems.values():
            kinds = problem.get("kinds") or {}
            for kind, since in list(kinds.items()):
                if since is not None and (
                    isinstance(since, bool)
                    or not isinstance(since, (int, float))
                    or not 0 < since <= now + 86400
                ):
                    kinds[kind] = now
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
                # Verify changes nothing (rule STOR-05), and a reader
                # that raises on it takes the whole list down with
                # it. Kept as the reader's safety behind the repair at
                # the storage boundary (rule STOR-09).
                kept.append(record)
                continue
            device_id = record.get(TODO_DEVICE_ID)
            problem = problems.pop(device_id, None)
            if problem is not None or self._still_judged_down(device_id):
                # Back inside the minute, or never gone: the item carries
                # on, and nothing is announced (rule LIST-06). A fault
                # that matured while it waited is true again, and sent.
                if isinstance(device_id, str) and self._parked.pop(device_id, None) is not None:
                    self._send_matured(device_id)
            if problem is None and self._still_judged_down(device_id):
                # Absent from the source for a moment while its own
                # verdict still says down: held, never retired as
                # recovered (rule LIST-08).
                kept.append(record)
                continue
            if device_id in held:
                # A kind a mute now covers is not kept: the hold keeps a
                # verdict, not one the person has muted.
                standing = {
                    kind: since
                    for kind, since in (record.get(TODO_KINDS) or {}).items()
                    if TODO_KIND_FAMILIES.get(kind) == "down"
                    and device_id not in getattr(self, "_muted_devices", set())
                    and not (
                        isinstance(device_id, str)
                        and self._kind_muted_plain(device_id, kind)
                    )
                }
                if standing:
                    if problem is None:
                        kept.append(record)
                        continue
                    for kind, since in standing.items():
                        problem["kinds"].setdefault(kind, since)
            if problem is None:
                # Two different things arrive here as the same
                # silence: a problem that ended, and a device nobody
                # is watching any more. Only the first is a recovery.
                # Announcing the second tells a house that a device
                # has come back when it never went: a coordinator
                # watched for the length of the startup grace and set
                # aside when it closes would be announced back up at
                # every restart (rule LIST-09).
                watched = device_id in self._watched
                muted = (
                    {
                        kind
                        for kind in record.get(TODO_KINDS, {})
                        if self._kind_muted(device_id, kind)
                    }
                    if watched
                    else None
                )
                cleared = now
                if watched and self._parks(device_id, record, muted):
                    cleared = self._parked.setdefault(device_id, now)
                    if now - cleared < INCIDENT_SETTLE_SECONDS:
                        # Its last problem cleared: it stays a minute,
                        # and its recovery is told only if it does not
                        # come back in that minute (rule LIST-06).
                        self._schedule_park_release()
                        kept.append(record)
                        continue
                self._parked.pop(device_id, None)
                if not watched or muted:
                    # Leaving silently: no recovery will read a fault
                    # kept from its minute, so none is kept for a later
                    # one to misread.
                    for key in [k for k in self._matured_in_park if k[0] == device_id]:
                        self._matured_in_park.pop(key, None)
                self._retire_item(
                    record, device_id, cleared, announce=watched, muted=muted
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
                # it (rule WATCH-10).
                remaining = {
                    kind: since
                    for kind, since in problem["kinds"].items()
                    if kind != FREEZE_CATEGORY_NEVER_REPORTED
                }
                if not remaining:
                    continue
                if len(remaining) != len(problem["kinds"]):
                    problem = dict(problem, kinds=remaining)
            item = self._new_item(device_id, problem, now)
            why = row_damage(DATA_TODO_ITEMS, item)
            if why is not None:
                # The sync rebuilds the list wholesale, so this is
                # its write seam: an item the shape refuses is
                # dropped at the instant it is made and never listed
                # (rule STOR-06).
                LOGGER.error(
                    "Storage write: to-do item refused by the shape "
                    "check and dropped (%s); this is a fault in the "
                    "writer",
                    why,
                )
                self._note_writer_fault(DATA_TODO_ITEMS, why)
                continue
            kept.append(item)
            changed = True

        if changed:
            self.data[DATA_TODO_ITEMS] = kept
            self._sort_todo_items()
            self._dirty = True
            self._critical = True
            self._notify()
            # A problem opened, closed or changed: the dashboard's
            # Refresh has something new to show.
            mark = getattr(self, "_mark_changed", None)
            if mark is not None:
                mark()
        # Now that the list and its summaries are settled, fire the
        # collected family events and refresh the persistent card. The
        # card always updates; the events respect quiet hours and the
        # high-priority targets. Scheduled as a task because the sync
        # runs in a sync context and the sends are async.
        self._dispatch_notifications()

    def _parks(
        self, device_id: str, record: dict[str, Any], muted: set[str] | None
    ) -> bool:
        """Whether an item whose problems cleared waits its minute
        (rule LIST-06): a device's own item with a kind a recovery would
        be told for. An upstream's row, and kinds a mute took, leave at
        once, as they announce nothing."""
        if device_id.startswith("upstream:"):
            return False
        if self._in_startup_grace():
            # Inside the startup window the line goes at once and its
            # recovery is held until the window shuts (rule WATCH-10),
            # which already waits longer than a minute.
            return False
        return any(
            kind != UPSTREAM_KIND and kind not in (muted or ())
            for kind in (record.get(TODO_KINDS) or {})
        )

    def _send_matured(self, device_id: str) -> None:
        """Send the faults that matured while the device waited its
        minute and came back down before it ended (rule LIST-06)."""
        ticked = self._todo_status_of(device_id) == "completed"
        for key in [k for k in self._matured_in_park if k[0] == device_id]:
            family, line = self._matured_in_park.pop(key)
            if not ticked:
                self._pending_events.append((family, line, False))

    def _schedule_park_release(self) -> None:
        """Come back when the oldest parked item's minute is up."""
        # An item deleted by hand, or otherwise gone, waits for nothing.
        listed = {
            record.get(TODO_DEVICE_ID)
            for record in self.data.get(DATA_TODO_ITEMS, [])
            if isinstance(record, dict)
        }
        for device_id in [d for d in self._parked if d not in listed]:
            self._parked.pop(device_id, None)
            for key in [k for k in self._matured_in_park if k[0] == device_id]:
                self._matured_in_park.pop(key, None)
        if self._park_timer is not None or not self._parked:
            return
        now = dt_util.utcnow().timestamp()
        due = min(self._parked.values()) + INCIDENT_SETTLE_SECONDS - now

        @callback
        def _release(_now: Any) -> None:
            self._park_timer = None
            if getattr(self, "_stopped", False):
                return
            self._sync_problem_list()
            self._schedule_park_release()

        self._park_timer = async_call_later(self.hass, max(1.0, due + 0.5), _release)

    def _problem_device_ids(self) -> set[str]:
        """Return the device_ids that currently have any fault.

        The union of the problem lists, the same sets the todo
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
        # A falling cell's forecast is an item too (rule BAT-14): left
        # out here, a house with one would count a device short and
        # hold an item with nothing behind it.
        for row in self.battery_falling_list:
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
        if device_id in self._parked:
            # Its problems cleared and it waits its minute: nothing it
            # held has anything left to say (rule LIST-06).
            return False
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
        if device_id in self._parked:
            if self._todo_status_of(device_id) == "completed":
                # Ticked: silent until its last problem clears (rule
                # LIST-03).
                return
            # Its problems cleared and it waits its minute: the fault is
            # kept until the minute decides (rule LIST-06). Back down,
            # it is sent; gone for good, it was never news, and its
            # recovery is not sent either.
            self._matured_in_park[key] = (family, line)
            return
        if not self._still_on_the_list(device_id, kind):
            return
        self.hass.async_create_task(
            self.async_fire_events([(family, line, False)])
        )

    @property
    def notification_debounce(self) -> float:
        """Return the configured notification debounce, as a fraction.

        Live from options: a fault waits this much of the device's own
        learned reporting gap before it reaches a phone, so a problem
        that heals inside the delay is never announced at all (rule
        NOTE-06). Clamped to the band the screen offers, so a
        hand-edited entry cannot hold an alert for a week.
        """
        return SETTLE_SHARE_PCT / 100.0

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
