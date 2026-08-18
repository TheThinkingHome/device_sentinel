# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: notifier.py, Version: 0.15.8 (2026-08-18)

"""The event notification engine: per-family pushes and the card.

Three self-overwriting surfaces, each keyed by a fixed id so it
replaces its own last message rather than stacking, always showing
the most recent picture rather than a pile of stale ones
(ruling #147):

The persistent card. One card, always the current trouble state of the
home, re-sent on every change. It is silent by nature and so is never
gated by quiet hours, the same reason the problem list is not.

The per-family high-priority pushes. One push per family (battery,
signal, freeze), each carrying the triggering event line and then the
current state of that family, so an admin reading the latest push for a
family sees both what just happened and what is true now. A fault plays
the device's own system sound; a recovery is sent silently. Events fire
only outside quiet hours; what quiet hours drops, the persistent card
and the daily brief carry.

Normal-priority targets receive none of this. They get the daily brief
and nothing else, which is the whole difference between the tiers: not
urgency, but whether live events arrive at all.

Everything here is a listener on state the sync already settled, so a
failure to notify never touches detection, the list, or the card's own
truth. A target that will not take a message is logged and skipped.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_HIGH_PRIORITY_TARGETS,
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
    NOTIFY_FAMILY_BATTERY,
    NOTIFY_FAMILY_FREEZE,
    NOTIFY_FAMILY_IDS,
    NOTIFY_FAMILY_SIGNAL,
    NOTIFY_FAMILY_TITLES,
    SIGNAL_ROW_LOW,
    TODO_KIND_FROZEN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    PERSISTENT_CREATE,
    PERSISTENT_DISMISS,
    PERSISTENT_TARGET,
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
# carry TODO_KIND_RAILED_SIGNAL now (ruling #299).
_SUMMARY_WORD = {
    TODO_KIND_RAILED_SIGNAL: "railed",
    SIGNAL_ROW_LOW: "low signal",
    TODO_KIND_FROZEN: "frozen",
    TODO_KIND_UNAVAILABLE: "unavailable",
    TODO_KIND_UNKNOWN: "unknown",
    TODO_KIND_NEVER_REPORTED: "never reported",
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

    def _family_summary(self, family: str) -> str:
        """Return a one-line current-state summary for a family.

        Reads the same list properties the Problems sensors publish, so
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
        parts: list[str] = []
        if family == NOTIFY_FAMILY_FREEZE:
            # The card is a human surface and follows the same rule as
            # the list and the pushes (ruling #266): while an upstream
            # is down its casualties are counted, not named. The
            # sensors and the telemetry audit keep the full list,
            # because they say what is true rather than what is worth
            # reading.
            for name, count in self.suppressed_down_counts.items():
                display = STACK_DISPLAY_NAMES.get(name, name)
                plural = "" if count == 1 else "s"
                parts.append(
                    f"{display} down, {count} device{plural} unavailable"
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
            rows: dict[str, str] = {}

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
                    rows[_key(row, len(rows))] = f"{name} {int(level)}%"
                else:
                    rows[_key(row, len(rows))] = f"{name} low"
            for row in self.battery_falling_list:
                if row.get("device_id") in acknowledged:
                    continue
                name = row.get("name") or row.get("device_id")
                left = row.get("left")
                clause = f"empty in {left}" if left else "running down"
                key = _key(row, len(rows))
                if key in rows:
                    rows[key] = f"{rows[key]}, {clause}"
                else:
                    rows[key] = f"{name} {clause}"
            parts.extend(rows.values())
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
                parts.append(f"{name} {_SUMMARY_WORD.get(kind, kind)}")
        elif family == NOTIFY_FAMILY_FREEZE:
            for row in self.reportable_down_rows:
                if row.get("device_id") in acknowledged:
                    continue
                name = row.get("name") or row.get("device_id")
                kind = row.get("category") or "down"
                parts.append(f"{name} {_SUMMARY_WORD.get(kind, kind)}")
        if not parts:
            return "All clear."
        return ", ".join(parts) + "."

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

    async def async_push_upstream(
        self, name: str, count: int, recovered: bool = False
    ) -> None:
        """Push the one message an upstream outage deserves.

        Ruling #265. The devices do not fall in one tick: Home
        Assistant marks each entity unavailable as it notices, so the
        reference system produced a push per tick until the add-on
        came back. The first message about an upstream sounds; every
        later one about the same upstream is silent and carries the
        current tally, so a person always sees the true count without
        being told about it again. Recovery is silent too, as every
        recovery is.
        """
        heard = name in self._upstream_announced
        if recovered:
            self._upstream_announced.pop(name, None)
            message = (
                f"{name} is back. {count} device(s) had gone quiet."
                if count
                else f"{name} is back."
            )
        else:
            self._upstream_announced[name] = count
            message = (
                f"{name} is down. {count} device(s) unavailable, "
                f"and they are symptoms rather than faults."
            )
        payload: dict[str, Any] = {
            "title": "Device Sentinel: upstream",
            "message": message,
            "data": {"tag": f"device_sentinel_upstream_{name}"},
        }
        if heard or recovered:
            payload["data"].update(_ANDROID_SILENT)
            payload["data"].update(_APPLE_SILENT)
        for target in self._high_priority_targets():
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
        """Send one family push to every high-priority target.

        Called only outside quiet hours by the caller; the engine does
        not re-check the clock here. Each target is tried on its own and
        a failure is logged rather than raised, so one bad target never
        blocks the rest.
        """
        payload = self._family_payload(family, event_line, recovery)
        for target in self._high_priority_targets():
            domain, _, service = target.partition(".")
            if not service:
                LOGGER.warning(
                    "High-priority target %s is not a service, skipped",
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

        events is a list of (family, event_line, recovery). Quiet hours
        drops live events entirely: the card and the brief carry the
        state, so nothing is queued. With no high-priority targets,
        nothing is sent. The persistent card is updated separately and
        always, so it is not gated here.
        """
        if not events:
            return
        if not self._high_priority_targets():
            return
        now_hms = dt_util.now().strftime("%H:%M:%S")
        if _in_quiet_hours(self.entry.options, now_hms):
            LOGGER.debug(
                "Device Sentinel: %d event(s) fell inside quiet hours "
                "and were not pushed; the card and brief carry them",
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
        """
        if not self.entry.options.get(
            CONF_PERSISTENT_ENABLED, DEFAULT_PERSISTENT_ENABLED
        ):
            try:
                await self.hass.services.async_call(
                    PERSISTENT_TARGET,
                    PERSISTENT_DISMISS,
                    {"notification_id": NOTIFY_CARD_ID},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - dismiss must never raise
                LOGGER.warning(
                    "Device Sentinel could not dismiss the state card: %s",
                    err,
                )
            return
        lines: list[str] = []
        for family in ("freeze", "battery", "signal"):
            summary = self._family_summary(family)
            if summary != "All clear.":
                title = NOTIFY_FAMILY_TITLES[family]
                lines.append(f"{title}: {summary}")
        message = "\n".join(lines) if lines else "All devices reporting."
        try:
            await self.hass.services.async_call(
                PERSISTENT_TARGET,
                PERSISTENT_CREATE,
                {
                    "notification_id": NOTIFY_CARD_ID,
                    "title": "Device Sentinel",
                    "message": message,
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - card write must never raise
            LOGGER.warning(
                "Device Sentinel could not update the state card: %s", err
            )
