# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: notifier.py, Version: 0.27.6 (2026-10-26)

"""The event notification engine: per-family pushes and the card.

Three self-overwriting surfaces, each keyed by a fixed id so it
replaces its own last message rather than stacking, always showing
the most recent picture rather than a pile of stale ones
(ruling #147):

The persistent card. One card, always the current trouble state of the
home, re-sent on every change. It is silent by nature and so is never
gated by quiet hours, the same reason the problem list is not.

The per-family pushes. One push per family (battery, signal, freeze),
each carrying the triggering event line and then the current state of
that family, so an admin reading the latest push for a family sees both
what just happened and what is true now. A fault plays the device's own
system sound; a recovery is sent silently.

The upstream push. A coordinator, the broker, the Wi-Fi network or a
whole integration going down silences everything behind it at once,
and those devices deliberately raise no faults of their own. One
message, in the words of its Problem List row, names the thing a
person can actually fix and counts the devices behind it rather than
listing them; the return is announced once and silently, in the Daily
Brief's words, with how long it was down.

High-priority targets get every push at any hour. Normal-priority
targets get every push except during Quiet Hours; what Quiet Hours
drop, the persistent card and the Daily Brief carry. The Daily Brief
goes only to Send the Full Brief To (rules NOTE-02, NOTE-07, BRIEF-11).

Everything here is a listener on state the sync already settled, so a
failure to notify never touches detection, the list, or the card's own
truth. A target that will not take a message is logged and skipped.
"""

from __future__ import annotations

import re

from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.util import dt as dt_util

from .battery_level import level_text
from .narrative import BRIEF_STATE_WORDS
from .const import (
    BROKER_LABEL,
    BROKER_SCOPE,
    DATA_SYSTEM_EVENTS,
    SYS_BRIDGE_UP,
    SYS_BROKER_UP,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WIFI_UP,
    UPSTREAM_KIND,
    WIFI_KEY,
    TODO_KIND_FLAPPING,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_SEVERITY,
    SUMMARY_NAMES,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    DEFAULT_PERSISTENT_ENABLED,
    DEFAULT_QUIET_ENABLED,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    LOGGER,
    NOTIFY_CARD_ID,
    PROBLEM_LIST_PATH,
    NOTIFY_FAMILY_BATTERY,
    NOTIFY_FAMILY_FREEZE,
    NOTIFY_FAMILY_IDS,
    NOTIFY_FAMILY_SIGNAL,
    NOTIFY_FAMILY_TITLES,
    SIGNAL_ROW_LOW,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    STACK_DISPLAY_NAMES,
)

# A message with this flag set is delivered without a sound. Recoveries
# use it; faults leave it unset so the device's own system sound plays.
_ANDROID_SILENT = {"channel": "Device Sentinel", "importance": "low"}
_APPLE_SILENT = {"push": {"interruption-level": "passive"}}

# The word the card and pushes use for each internal kind, matching the
# briefs and the problem list so a device reads the same everywhere. A
# rail is not a low; a not_reported device reads as never reported.
# Keyed by the kind a row carries. The signal rows tag a railed link
# and leave a merely low one untagged, so SIGNAL_ROW_LOW is the
# default rather than a kind anything writes. Until 0.15.8 the railed
# rows said "rail" here while the problem list called the same thing
# "signal", which is why the family map had to list both; the rows
# carry TODO_KIND_RAILED_SIGNAL now (ruling #299). The device problems
# read the Daily Brief's words, as its Right Now table says them:
# "stopped reporting", "signal railed" (rules NOTE-01, LIST-02).
_SUMMARY_WORD = {
    TODO_KIND_FLAPPING: "keeps dropping out",
    SIGNAL_ROW_LOW: "low signal",
    **BRIEF_STATE_WORDS,
}


def _in_quiet_hours(options: dict[str, Any], now_hms: str) -> bool:
    """Return whether the wall clock is inside the quiet-hours window.

    The window is compared as zero-padded HH:MM:SS strings, and a
    window that wraps past midnight (start later than end) is handled
    by the OR of the two half-open ranges. Quiet hours off means never
    quiet.
    """
    if not options.get(CONF_QUIET_ENABLED, DEFAULT_QUIET_ENABLED):
        return False
    start = options.get(CONF_QUIET_START, DEFAULT_QUIET_START)
    end = options.get(CONF_QUIET_END, DEFAULT_QUIET_END)
    if start == end:
        return False
    if start < end:
        return start <= now_hms < end
    # Wraps midnight: quiet if after start or before end.
    return now_hms >= start or now_hms < end


_CARD_MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")


def _card_text(text: str) -> str:
    """Text as the card shows it, never as Markdown (0.24.9).

    A name holding "![x](https://...)" made Home Assistant load an
    outside picture into the card, and "[x](https://...)" made a link
    beside the card's own. Each Markdown character is escaped with a
    backslash, which Home Assistant's renderer takes back off, and a line
    break inside a name becomes a space.
    """
    return _CARD_MARKDOWN.sub(r"\\\1", " ".join(str(text).splitlines()))


class NotifierMixin:
    """The event push engine, mixed into the coordinator.

    It reads the family changes the sync collected and the family
    summaries the list properties expose, and it sends. It owns no
    detection and no list state; it is a reader that speaks.
    """

    def _high_priority_targets(self) -> list[str]:
        """Return the configured high-priority targets, cleaned."""
        return [
            target
            for target in (
                self.entry.options.get(CONF_HIGH_PRIORITY_TARGETS) or []
            )
            if target
        ]

    def _normal_priority_targets(self) -> list[str]:
        """Return the configured normal-priority targets, cleaned."""
        return [
            target
            for target in (
                self.entry.options.get(CONF_NORMAL_PRIORITY_TARGETS) or []
            )
            if target
        ]

    def _push_targets(self) -> list[str]:
        """The targets a push goes to now, each once.

        High-priority targets get every push, Quiet Hours included;
        normal-priority targets get every push except during Quiet
        Hours. Quiet Hours once stopped every push, high priority
        included, and normal-priority targets were sent nothing at all
        (rules NOTE-02, NOTE-07).
        """
        targets = self._high_priority_targets()
        if not _in_quiet_hours(
            self.entry.options, dt_util.now().strftime("%H:%M:%S")
        ):
            targets = [*targets, *self._normal_priority_targets()]
        return list(dict.fromkeys(targets))

    @staticmethod
    def _capped(
        entries: list[tuple[int, float, str]], always: list[str]
    ) -> str:
        """Name the worst few and count the rest (0.22.26).

        Fifty devices down made a push of 2,160 characters, which a
        phone truncates and a fleet of a hundred could push past the
        4 kB a push may carry. Worst first, then most recent, so the
        first name is the one the headline belongs to and a line read
        aloud leads with what matters. The list, the card and the
        brief's tables keep every name.
        """
        entries.sort(key=lambda row: (row[0], -row[1]))
        named = [row[2] for row in entries[:SUMMARY_NAMES]]
        rest = len(entries) - len(named)
        parts = [*always, *named]
        if rest > 0:
            parts.append(f"and {rest} more device{'s' if rest != 1 else ''}")
        return ", ".join(parts) + "." if parts else "All clear."

    def _family_summary(self, family: str) -> str:
        """Return a one-line current-state summary for a family.

        Reads the same list properties the family sensors publish, so
        the summary can never disagree with what is detected, then drops
        the devices a person has acknowledged: an acknowledged problem
        is invisible to humans everywhere, the card and pushes
        included, exactly as the brief already hides it, because the
        phone is a live status board rather than a log and shows what
        is wrong and unacknowledged right now (ruling #109). Each
        remaining
        entry is worded the way the briefs and the list word it: a
        battery's level, a signal marked railed, a device that is
        unavailable or never reported.
        """
        acknowledged = self._acknowledged_devices()
        # (severity, when it began, what to say). The upstream lines
        # are counts rather than devices, so they are never capped.
        entries: list[tuple[int, float, str]] = []
        always: list[str] = []
        order = {kind: index for index, kind in enumerate(TODO_KIND_SEVERITY)}

        def _rank(kind: str) -> int:
            return order.get(kind, len(order))

        def _since(row: dict[str, Any]) -> float:
            value = row.get("since")
            return float(value) if isinstance(value, (int, float)) else 0.0

        if family == NOTIFY_FAMILY_FREEZE:
            # The card is a human surface and follows the same rule as
            # the list and the pushes (ruling #266): while an upstream
            # is down its casualties are counted, not named. The
            # sensors and the telemetry audit keep the full list,
            # because they say what is true rather than what is worth
            # reading.
            for name, count in self.suppressed_down_counts.items():
                display = STACK_DISPLAY_NAMES.get(name, name)
                behind = max(self.upstream_membership(name), count)
                # Casualties against membership (ruling #401): the
                # count drains as devices return, and printed alone
                # it read as one figure that would not hold still.
                always.append(
                    f"{display} down, {count} of {behind} devices "
                    "unavailable"
                )
        if family == NOTIFY_FAMILY_BATTERY:
            # Two sources, because low and falling are two questions
            # and the card was reading only the first: a cell heading
            # for empty never reached it at all, so a card could read
            # "All devices reporting" while an unacknowledged forecast
            # stood on the list and in the brief (ruling #220). A cell
            # already low is absent from the falling source, so the
            # two rarely name one device, but where they do the level
            # leads and the direction follows in one clause rather
            # than two entries (ruling #216).
            rows: dict[str, tuple[int, float, str]] = {}

            def _key(row: dict[str, Any], count: int) -> str:
                # The device id joins the two sources, so a cell that
                # is both reads as one entry. It falls back to the
                # name and then to position, because a row with no id
                # must still be its own entry rather than overwriting
                # the row before it.
                return row.get("device_id") or row.get("name") or f"#{count}"

            for row in self.battery_low_list:
                if row.get("device_id") in acknowledged:
                    continue
                level = row.get("level")
                name = row.get("name") or row.get("device_id")
                if level is not None:
                    rows[_key(row, len(rows))] = (
                        _rank(TODO_KIND_LOW_BATTERY), _since(row),
                        # As reported, the same on every surface (0.27.1): this
                        # cut 15.5 to "15%", a level the threshold did not call low.
                        f"{name} {level_text(level)}",
                    )
                else:
                    rows[_key(row, len(rows))] = (
                        _rank(TODO_KIND_LOW_BATTERY), _since(row), f"{name} low",
                    )
            for row in self.battery_falling_list:
                if row.get("device_id") in acknowledged:
                    continue
                name = row.get("name") or row.get("device_id")
                left = row.get("until") or (f"empty in {row['left']}" if row.get("left") else None)
                clause = left or "running down"
                key = _key(row, len(rows))
                if key in rows:
                    rank, since, said = rows[key]
                    rows[key] = (rank, since, f"{said}, {clause}")
                else:
                    rows[key] = (
                        _rank(TODO_KIND_FALLING_BATTERY), _since(row),
                        f"{name} {clause}",
                    )
            entries.extend(rows.values())
        elif family == NOTIFY_FAMILY_SIGNAL:
            # The signal list tags each row by kind, not category, and
            # a rail is not a low: a railed device shows a stale
            # perfect reading held at the protocol's fill value, which
            # is a dead reading rather than a strong link, so the card
            # must say railed, not low (ruling #78).
            for row in self.signal_problem_list:
                if row.get("device_id") in acknowledged:
                    continue
                name = row.get("name") or row.get("device_id")
                kind = row.get("kind") or SIGNAL_ROW_LOW
                entries.append((
                    _rank(TODO_KIND_RAILED_SIGNAL), _since(row),
                    f"{name} {_SUMMARY_WORD.get(kind, kind)}",
                ))
        elif family == NOTIFY_FAMILY_FREEZE:
            # A device in a flap is named for the flap, down this
            # minute or not, and its drop is not named again (0.23.2).
            flapping = set()
            down_rows = self.reportable_down_rows
            down_ids = {row.get("device_id") for row in down_rows}
            for row in self.flapping_list:
                # A hub that is down is named for that, as on the
                # Problem List (#665): its drops stay on its page. Only
                # once its down row is here to name it.
                if row.get("device_id") in down_ids and self.hub_problem_words(row.get("device_id")):  # type: ignore[attr-defined]
                    continue
                flapping.add(row.get("device_id"))
                if row.get("device_id") in acknowledged:
                    continue
                name = row.get("name") or row.get("device_id")
                # How often, as the brief says it (rule NOTE-01).
                entries.append((
                    _rank(TODO_KIND_FLAPPING), _since(row),
                    f"{name} {self.flap_words(row['device_id']) if row.get('device_id') else _SUMMARY_WORD[TODO_KIND_FLAPPING]}",  # type: ignore[attr-defined]
                ))
            for row in down_rows:
                if row.get("device_id") in acknowledged:
                    continue
                if row.get("device_id") in flapping:
                    continue
                name = row.get("name") or row.get("device_id")
                kind = row.get("category") or "down"
                # A hub says what the Problem List says (James, 14
                # October 2026): "hub down, 2 devices that it controls".
                hub_words = (
                    self.hub_problem_words(row.get("device_id"))  # type: ignore[attr-defined]
                    if kind == TODO_KIND_UNAVAILABLE
                    else None
                )
                word = (
                    f"{hub_words[:1].lower()}{hub_words[1:]}"
                    if hub_words
                    else _SUMMARY_WORD.get(kind, kind)
                )
                entries.append((_rank(kind), _since(row), f"{name} {word}"))
        if not entries and not always:
            return "All clear."
        return self._capped(entries, always)

    def _family_payload(
        self, family: str, event_line: str, recovery: bool
    ) -> dict[str, Any]:
        """Return the notify payload for a family push.

        The message is the event line then the family summary. The id
        is fixed per family so the push overwrites its own last one. A
        recovery carries the silent flags for both mobile platforms; a
        fault leaves them off so the phone's own sound plays.
        """
        title = f"Device Sentinel: {NOTIFY_FAMILY_TITLES.get(family, family)}"
        message = f"{event_line} Summary: {self._family_summary(family)}"
        data: dict[str, Any] = {"tag": NOTIFY_FAMILY_IDS[family]}
        if recovery:
            data.update(_ANDROID_SILENT)
            data.update(_APPLE_SILENT)
        return {"title": title, "message": message, "data": data}

    def _upstream_down_words(self, name: str, count: int) -> str:
        """The down push, in the Problem List row's own words.

        The push built its own text and named the upstream by its key,
        "z2m is down", where the row says "Zigbee2MQTT down: 3 of 77
        total devices unavailable". Reading the row's summary names it
        as a person would and states the total behind it, devices
        muted for unavailable included (rules UP-09, UP-11).
        """
        since = self.upstream_down_since_for(name)  # type: ignore[attr-defined]
        summary, _ = self._upstream_item_text(  # type: ignore[attr-defined]
            name, {UPSTREAM_KIND: since}, count
        )
        return f"{summary}."

    def _upstream_return_words(self, name: str) -> str:
        """The recovery push, in the Daily Brief's words for the return.

        The brief's sentence for the stored return says how long the
        upstream was down and what went down out of the total behind
        it, so the push claims no count already back (rule UP-09).
        Where no return is stored, the upstream is named and nothing
        is counted.
        """
        if name == BROKER_LABEL:
            wanted = (SYS_BROKER_UP, BROKER_SCOPE)
        elif name == WIFI_KEY:
            wanted = (SYS_WIFI_UP, WIFI_KEY)
        elif name in self._stacks or name in self._bridge_readers:  # type: ignore[attr-defined]
            wanted = (SYS_BRIDGE_UP, name)
        else:
            # An integration's own outage, which can span several of its
            # entries, told from its stored records rather than the log.
            # Only a file whose records keep no start, written before
            # 0.27.6, falls through to its latest return below (rules
            # UP-09, UP-11).
            ended = self._integration_over_row(name)  # type: ignore[attr-defined]
            if ended is not None:
                return self._system_event_sentence(ended)  # type: ignore[attr-defined]
            wanted = (SYS_INTEGRATION_UP, name)
        for row in reversed(self.data.get(DATA_SYSTEM_EVENTS) or []):  # type: ignore[attr-defined]
            if (row.get(SYS_KIND), row.get(SYS_SCOPE)) == wanted:
                return self._system_event_sentence(row)  # type: ignore[attr-defined]
        return f"{self._integration_title(name)} is back."  # type: ignore[attr-defined]

    async def async_push_upstream(
        self, name: str, count: int, recovered: bool = False
    ) -> None:
        """Push the message an upstream outage's phase deserves.

        Once when it is down, in its Problem List row's words, and
        once when it is over, in the Daily Brief's words for its
        return; the recovering phase sends nothing (#435). The first
        message about an upstream sounds and the return is silent, as
        every recovery is (#265). Sent to the targets `_push_targets`
        names (rules UP-09, NOTE-02).
        """
        heard = name in self._upstream_announced
        if recovered:
            self._upstream_announced.pop(name, None)
            message = self._upstream_return_words(name)
        else:
            self._upstream_announced[name] = count
            message = self._upstream_down_words(name, count)
        payload: dict[str, Any] = {
            "title": "Device Sentinel: upstream",
            "message": message,
            "data": {"tag": f"device_sentinel_upstream_{name}"},
        }
        if heard or recovered:
            payload["data"].update(_ANDROID_SILENT)
            payload["data"].update(_APPLE_SILENT)
        for target in self._push_targets():
            domain, _, service = target.partition(".")
            if not service:
                continue
            try:
                await self.hass.services.async_call(
                    domain, service, payload, blocking=True
                )
            except Exception as err:  # noqa: BLE001 - one bad target
                LOGGER.warning(
                    "Device Sentinel could not push to %s: %s", target, err
                )

    async def _push_family_event(
        self, family: str, event_line: str, recovery: bool
    ) -> None:
        """Send one family push to every target `_push_targets` names.

        Quiet Hours are applied there, to normal-priority targets only
        (rule NOTE-07). Each target is tried on its own and a failure
        is logged rather than raised, so one bad target never blocks
        the rest.
        """
        payload = self._family_payload(family, event_line, recovery)
        for target in self._push_targets():
            domain, _, service = target.partition(".")
            if not service:
                LOGGER.warning(
                    "Push target %s is not a service, skipped",
                    target,
                )
                continue
            try:
                await self.hass.services.async_call(
                    domain, service, payload, blocking=True
                )
            except Exception as err:  # noqa: BLE001 - any notify platform error
                LOGGER.warning(
                    "Device Sentinel event to %s was not delivered: %s",
                    target,
                    err,
                )

    async def async_fire_events(
        self, events: list[tuple[str, str, bool]]
    ) -> None:
        """Fire the family events the sync collected, if allowed.

        events is a list of (family, event_line, recovery). Quiet Hours
        keep the events from normal-priority targets only, and what
        they drop is not queued: the card and the brief carry the
        state. High-priority targets get them at any hour (rules
        NOTE-02, NOTE-07). With no target to send to now, nothing is
        sent. The persistent card is updated separately and always, so
        it is not gated here.
        """
        if not events:
            return
        if not self._push_targets():
            return
        if self._in_startup_grace():
            # Nothing is pushed inside the startup grace, for any
            # reason (ruling #291). A change to a device already on
            # the list pushed straight through it: the reference rig's
            # phone read "At 3:50 pm" one minute into a start
            # (0.22.28). The list and the card carry what is true when
            # the window shuts.
            LOGGER.debug(
                "Device Sentinel: %d event(s) fell inside the startup "
                "grace and were not pushed",
                len(events),
            )
            return
        # One push per family, so several devices in one family that
        # change together become one message, not a burst. The last
        # event line for a family is the headline; the summary carries
        # the rest.
        latest: dict[str, tuple[str, bool]] = {}
        for family, line, recovery in events:
            latest[family] = (line, recovery)
        for family, (line, recovery) in latest.items():
            await self._push_family_event(family, line, recovery)

    def _card_show(self, message: str) -> None:
        """Raise or replace the state card, under its one fixed id.

        Through Home Assistant's own helpers for an integration's own
        card (0.23.19), rather than a call through the service layer,
        which fails with "Action not found" wherever the service has
        not been registered. A card chosen as a push target still goes
        through the service, as every target does.
        """
        persistent_notification.async_create(
            self.hass,
            message,
            title="Device Sentinel",
            notification_id=NOTIFY_CARD_ID,
        )

    def _card_dismiss(self) -> None:
        """Take the state card down."""
        persistent_notification.async_dismiss(self.hass, NOTIFY_CARD_ID)

    async def async_update_card(self) -> None:
        """Rewrite the persistent card to the current home state.

        One fixed id, so it overwrites rather than stacks. Always the
        current state, sent on every change, never gated by quiet hours.
        A home with no trouble clears the card by writing an all-clear,
        so a stale problem never lingers on it.

        The card is optional. When the Create a persistent notification
        toggle is off, no card is written, and any card already showing
        is dismissed so turning the setting off removes it rather than
        leaving a stale one behind.

        Written only when its message changes. Home Assistant shows
        every write as a fresh notification, so repeating the same
        words every thirty seconds was noise two testers reported. The
        last message written is held in memory and nowhere else: it
        starts empty at every setup, so the first call after a restart
        always writes, and it is forgotten by a dismiss or a failed
        write, since neither leaves those words on screen (ruling
        #454).
        """
        if not self.entry.options.get(
            CONF_PERSISTENT_ENABLED, DEFAULT_PERSISTENT_ENABLED
        ):
            try:
                self._card_dismiss()
            except Exception as err:  # noqa: BLE001 - dismiss must never raise
                LOGGER.warning(
                    "Device Sentinel could not dismiss the state card: %s",
                    err,
                )
            self._card_written = None
            return
        lines: list[str] = []
        for family in ("freeze", "battery", "signal"):
            summary = self._family_summary(family)
            if summary != "All clear.":
                title = NOTIFY_FAMILY_TITLES[family]
                # The card is drawn as Markdown and the summary names
                # devices, whose names may come from the device itself
                # (0.24.9): escaped here, and only here, since the same
                # summary goes to phones as plain text.
                lines.append(f"{title}: {_card_text(summary)}")
        # A card that lists anything ends with a link to the Problem
        # List, which names every device the card counts (0.23.10).
        # Home Assistant draws the card as Markdown and leaves a link
        # inside Home Assistant as a plain link, so it opens in place.
        message = (
            "\n".join(lines) + f"\n\n[Open the Problem List]({PROBLEM_LIST_PATH})"
            if lines
            else "All devices reporting."
        )
        if message == getattr(self, "_card_written", None):
            return
        try:
            self._card_show(message)
        except Exception as err:  # noqa: BLE001 - card write must never raise
            self._card_written = None
            LOGGER.warning(
                "Device Sentinel could not update the state card: %s", err
            )
            return
        self._card_written = message
