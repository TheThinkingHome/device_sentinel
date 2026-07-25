# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: notifier.py, Version: 0.9.6 (2026-07-25)

"""The event notification engine: per-family pushes and the card.

Three self-overwriting surfaces, each keyed by a fixed id so it
replaces its own last message rather than stacking (#479, #487 as
reimagined 2026-07-25):

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
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    DEFAULT_QUIET_ENABLED,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    LOGGER,
    NOTIFY_CARD_ID,
    NOTIFY_FAMILY_IDS,
    NOTIFY_FAMILY_TITLES,
    PERSISTENT_CREATE,
    PERSISTENT_TARGET,
)

# A message with this flag set is delivered without a sound. Recoveries
# use it; faults leave it unset so the device's own system sound plays.
_ANDROID_SILENT = {"channel": "Device Sentinel", "importance": "low"}
_APPLE_SILENT = {"push": {"interruption-level": "passive"}}


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
        the summary can never disagree with what is detected. Each entry
        is the device name and its current trouble, for example a
        battery's level or a signal marked railed.
        """
        parts: list[str] = []
        if family == "battery":
            for row in self.battery_low_list:
                level = row.get("level")
                name = row.get("name") or row.get("device_id")
                if level is not None:
                    parts.append(f"{name} {int(level)}%")
                else:
                    parts.append(f"{name} low")
        elif family == "signal":
            for row in self.signal_problem_list:
                name = row.get("name") or row.get("device_id")
                kind = row.get("category") or "low"
                parts.append(f"{name} {kind}")
        elif family == "freeze":
            for row in self.frozen_devices_list:
                name = row.get("name") or row.get("device_id")
                kind = row.get("category") or "down"
                parts.append(f"{name} {kind}")
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
            LOGGER.info(
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
        """
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
