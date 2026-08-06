# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: journal.py, Version: 0.12.5 (2026-08-06)

"""The forensic record: silence episodes, incidents, system events.

The recording half of what was narrative.py, split out because the
two halves never called each other once (ruling #202). This half
writes what happened; narrative.py reads it back and turns it into
sentences. Nothing here composes prose and nothing there records.

What is written here is the single memory every channel renders
over: the push, the brief, the email and the card all read these
rows and none derives its own truth (ruling #107). An episode is a
silence that passed the device's own learned basis and it records
whether it ended because the device spoke or because something
made it speak (ruling #103).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the coordinator
throughout.
"""

from __future__ import annotations

from typing import Any
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    CAUSE_EPISODE_SLACK_SECONDS,
    EPISODE_ENDED_RESUMED,
    EPISODE_KEEP_DAYS,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_TAINT_SECONDS,
    EP_WINDOW,
    FREEZE_ARMING_DAYS,
    FREEZE_KINDS_FOR_CAUSE,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    LOGGER,
    RECOVERY_CAUSE_UNOBSERVED,
    SYS_DETAIL,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_SCOPE,
    SYS_SCOPE_SYSTEM,
    SYS_WHEN,
    TAINT_PROMOTIONS,
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TODO_DEVICE_ID,
    TODO_STATUS,
)


# The taint labels a promotion may replace. A taint carries the
# reason learning skipped a gap rather than a bare flag, so a row can
# name the cause instead of always saying unavailable (ruling #164).
# Built from the
# reasons rather than written out, so a reason added later is covered
# without a second place to remember. Pairing is deliberately absent:
# it is a hand intervention and more specific than any cause above it.
_TAINT_LABELS = frozenset(
    f"no ({reason})" for reason in (TAINT_UNAVAILABLE, TAINT_UNKNOWN)
)


def _promoted_learned(ended: str | None, learned: str | None) -> str | None:
    """Return the widest cause that fits a tainted gap.

    Where more than one reason fits, the widest wins, so a device
    felled by its bridge reads as the bridge rather than as its own
    unavailability (ruling #164).

    A device felled by its bridge showed unavailable, which is true
    and shallow: the row worth reading names the bridge. The episode
    already knows what ended it, stamped when the intervention
    happened, so the promotion is resolved here rather than where the
    label is built, where the storm behind a reconnect has long since
    released. Anything that is not a taint label passes through, so
    "yes" and a pairing discard are returned unchanged.
    """
    if learned not in _TAINT_LABELS:
        return learned
    reason = TAINT_PROMOTIONS.get(ended or "")
    return f"no ({reason})" if reason else learned


class JournalMixin:
    """The forensic record: episodes, incidents, system events."""

    def _open_episode_for(self, device_id: str) -> dict[str, Any] | None:
        """Return a device's episode still awaiting its lag, if any.

        Awaiting means either fully open (no end recorded) or ended by
        an intervention whose lag cannot be known until the device
        speaks again. Both are completed by the same next report. A
        resumed episode is finished and carries no lag by design (it
        had no lever to measure from), so it never blocks the next
        episode for that device.
        """
        for episode in reversed(self.data.get(DATA_EPISODES) or []):
            if episode[EP_DEVICE_ID] != device_id:
                continue
            if episode[EP_ENDED] is None:
                return episode
            if (
                episode[EP_ENDED] != EPISODE_ENDED_RESUMED
                and episode[EP_LAG] is None
            ):
                return episode
            return None
        return None

    def _note_silences(self, now: float) -> None:
        """Open an episode for any device well into its own patience.

        The threshold is basis plus a share of that device's grace:
        the silence has spent that share of the distance from the
        rhythm to the freeze line (ruling #105, and a person may set
        the share since ruling #117). Basis alone, which is what the
        first version shipped, was too sensitive at the fast end,
        where a
        rhythm of seconds is exceeded constantly and trivial silences
        filled the file, while the same rule was properly selective
        for a device measured in hours. A share of grace scales with
        the patience each device has earned, so a 36-second device
        opens at minutes and an hours-long device opens at hours,
        both a clear distance short of judgment.

        Devices whose freeze judgment is suppressed are skipped
        (ruling #106). Exclusion suppresses judgment and reporting
        while
        observation continues, and this file exists to explain
        verdicts: a device that can never be judged frozen has no
        verdict to explain, so its silences are noise here. A device
        excluded only for battery or signal is still judged for
        freeze and still belongs.
        """
        if now < self._grace_until:
            # Startup grace: every stored clock is stale by however
            # long the system was down, so opening episodes here
            # would manufacture a batch of rows that the startup
            # storm closes seconds later, all of them describing the
            # restart rather than any device. Silences that matter
            # are still open in the record from before the restart,
            # and new ones open once grace closes.
            return
        for device_id in self._watched:
            if device_id in self._excluded_devices or self._freeze_excluded(
                device_id
            ):
                continue
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            last = record.get(DEV_LAST_ACTIVITY)
            if last is None:
                continue
            daily = record.get(DEV_DAILY_MAX) or []
            if len(daily) < FREEZE_ARMING_DAYS:
                continue
            basis, _ = self._trimmed_maximum(daily)
            if basis is None or basis <= 0:
                continue
            window = self._freeze_window(record)
            grace = (window - basis) if window is not None else 0.0
            if now - last <= basis + self.episode_share * grace:
                continue
            if self._open_episode_for(device_id) is not None:
                continue
            self.data.setdefault(DATA_EPISODES, []).append(
                {
                    EP_DEVICE_ID: device_id,
                    EP_NAME: self._device_name(device_id),
                    EP_SINCE: last,
                    EP_BASIS: basis,
                    EP_WINDOW: window,
                    EP_ENDED: None,
                    EP_AT: None,
                    EP_LAG: None,
                    EP_LEARNED: None,
                    EP_TAINT_SECONDS: None,
                }
            )
            # The main file, not the routine flag. An episode lives
            # only in the cold file, so _dirty alone schedules a write
            # of the clocks file that cannot carry it, and then clears
            # itself, leaving nothing to remember the row is unwritten
            # at all. _mark_cold_dirty raises _dirty too, so nothing
            # the routine tier did is lost by asking for both.
            self._mark_cold_dirty()

    def _close_episode(
        self,
        device_id: str,
        now: float,
        learned: str | None,
        taint_seconds: float | None = None,
    ) -> None:
        """Complete a device's episode when it genuinely reports.

        Two shapes complete here. A still-open episode closes as
        resumed: the device chose to speak, and the learned column
        says whether its gap reached the statistics. An episode
        already stamped by an intervention gains only its lag, the
        time from the lever to the first genuine report, which is the
        column that separates a wedge (seconds) from a device that
        was merely quiet (hours).
        """
        episode = self._open_episode_for(device_id)
        if episode is None:
            return
        if episode[EP_ENDED] is None:
            episode[EP_ENDED] = EPISODE_ENDED_RESUMED
            episode[EP_AT] = now
            episode[EP_LEARNED] = learned
        else:
            episode[EP_LAG] = max(0.0, now - (episode[EP_AT] or now))
            if episode[EP_LEARNED] is None:
                episode[EP_LEARNED] = _promoted_learned(
                    episode[EP_ENDED], learned
                )
        if taint_seconds is not None:
            episode[EP_TAINT_SECONDS] = taint_seconds
        # The ending, the lag and the learned verdict are all cold
        # fields, so the close schedules the main file for the same
        # reason the open does.
        self._mark_cold_dirty()

    def _stamp_intervention(
        self, cause: str, now: float, entry_id: str | None = None
    ) -> None:
        """Mark open episodes as ended by an intervention.

        A reboot or a bridge reconnect truncates a silence: we know
        the device had been quiet at least this long, never how much
        longer it would have stayed quiet. The row keeps that honesty
        by recording the cause and waiting for the lag.

        Scoped by entry_id where the intervention belongs to one
        integration. A Zigbee bridge reconnecting cannot revive a
        HomeKit accessory, and crediting it with one puts a false
        cause in the brief, which is what happened on 2026-07-23.
        A restart carries no entry_id, because it touches everything.
        """
        stamped = 0
        for episode in self.data.get(DATA_EPISODES) or []:
            if episode[EP_ENDED] is not None:
                continue
            if entry_id is not None and entry_id not in (
                self._device_entries.get(episode[EP_DEVICE_ID]) or set()
            ):
                continue
            episode[EP_ENDED] = cause
            episode[EP_AT] = now
            stamped += 1
        if stamped:
            self._mark_cold_dirty()
            LOGGER.debug(
                "Stamped %d open silence episode(s) as %s", stamped, cause
            )

    def _trim_episodes(self, now: float) -> None:
        """Drop episodes older than the statistics window.

        Fourteen days by timestamp, matching the daily-maxima series
        the file exists to explain. An episode still awaiting its lag
        survives the boundary: an unfinished story is not old news.
        """
        cutoff = now - EPISODE_KEEP_DAYS * 86400.0
        episodes = self.data.get(DATA_EPISODES) or []
        kept = [
            episode
            for episode in episodes
            if episode[EP_SINCE] >= cutoff
            or episode[EP_ENDED] is None
            or (
                episode[EP_ENDED] != EPISODE_ENDED_RESUMED
                and episode[EP_LAG] is None
            )
        ]
        if len(kept) != len(episodes):
            self.data[DATA_EPISODES] = kept
            self._mark_cold_dirty()

    def _record_incident(
        self,
        device_id: str,
        name: str,
        kind: str,
        event: str,
        cause: str | None = None,
        duration: float | None = None,
    ) -> None:
        """Append one event to the incident log.

        The whole life of a problem on one timeline: opened when a
        detection first names it, resolved when it clears (with the
        cause and the duration where we know them), acknowledged when
        a person checks the box. Renderers read this and nothing
        else, so what the phone says, what the brief says, and what
        a future voice answer says can never disagree.
        """
        entry = {
            INC_DEVICE_ID: device_id,
            INC_NAME: name,
            INC_KIND: kind,
            INC_EVENT: event,
            INC_WHEN: dt_util.utcnow().timestamp(),
            INC_CAUSE: cause,
            INC_DURATION: duration,
        }
        incidents = self.data.setdefault(DATA_INCIDENTS, [])
        incidents.append(entry)
        cutoff = (
            dt_util.utcnow().timestamp() - INCIDENT_KEEP_DAYS * 86400.0
        )
        self.data[DATA_INCIDENTS] = [
            row for row in incidents if row[INC_WHEN] >= cutoff
        ]
        self._mark_cold_dirty()

    def _record_system_event(
        self,
        kind: str,
        scope: str = SYS_SCOPE_SYSTEM,
        detail: str | None = None,
        duration: float | None = None,
        when: float | None = None,
        devices: int | None = None,
    ) -> None:
        """Append one thing that happened to the house, not a device.

        Its own list rather than a fourth kind of incident. A system
        event has a scope and never a device, so put in the incident
        log it would leave the device column empty on every row and
        overload the kind column to carry what happened, and the
        pairing machinery that matches an opening to its recovery
        would have rows it could never pair. It also wants a longer
        memory: an incident is spent after a fortnight, while how
        often this house loses power is a question worth years.

        Retention follows the person's history setting, so the events
        that explain the statistics live exactly as long as the
        statistics they explain.
        """
        events = self.data.setdefault(DATA_SYSTEM_EVENTS, [])
        events.append(
            {
                # When it happened, which is not always when the row
                # is written. A restart is recorded once setup has
                # succeeded, so a start that failed halfway leaves no
                # claim the system came back, but it happened before
                # the first sweep judged anything. Stamped at the
                # write it would sort below the very devices it
                # explains.
                SYS_WHEN: (
                    when
                    if when is not None
                    else dt_util.utcnow().timestamp()
                ),
                SYS_KIND: kind,
                SYS_SCOPE: scope,
                SYS_DETAIL: detail,
                SYS_DURATION: duration,
                # Only a storm carries a count: it is the one event
                # whose size a person wants in the sentence.
                **({SYS_DEVICES: devices} if devices is not None else {}),
            }
        )
        cutoff = (
            dt_util.utcnow().timestamp()
            - self.retention_days * 86400.0
        )
        self.data[DATA_SYSTEM_EVENTS] = [
            row for row in events if row[SYS_WHEN] >= cutoff
        ]
        self._mark_cold_dirty()

    def _incident_opened_at(
        self, device_id: str, kind: str
    ) -> float | None:
        """Return when this device's current problem of a kind began.

        The most recent opening with no resolution after it. Used to
        compute a resolution's duration, so the brief can say how
        long a problem lasted without the renderer doing arithmetic
        on a raw log.
        """
        opened: float | None = None
        for row in self.data.get(DATA_INCIDENTS) or []:
            if row[INC_DEVICE_ID] != device_id or row[INC_KIND] != kind:
                continue
            if row[INC_EVENT] == INCIDENT_OPENED:
                opened = row[INC_WHEN]
            elif row[INC_EVENT] == INCIDENT_RESOLVED:
                opened = None
        return opened

    def _recovery_cause(
        self, device_id: str, opened: float = 0.0
    ) -> str | None:
        """Return how a device's silence ended, if the record says.

        Borrowed from the episode record rather than guessed: an
        episode closed by an intervention names the lever, and one
        the device closed itself says so. Only silences carry a
        cause; a battery or a rail recovering has no lever to name.
        """
        for episode in reversed(self.data.get(DATA_EPISODES) or []):
            if episode[EP_DEVICE_ID] != device_id:
                continue
            # Bounded to the incident. Without this the newest
            # episode for the device answered whatever the question
            # was, so an incident that opened no episode of its own
            # took its cause from one days old, and 74 devices
            # recovering from one broker outage were given four
            # different explanations (ruling #228).
            at = episode.get(EP_AT)
            if at is None or at < opened - CAUSE_EPISODE_SLACK_SECONDS:
                return None
            ended = episode[EP_ENDED]
            if ended is None:
                return None
            if ended == EPISODE_ENDED_RESUMED:
                return RECOVERY_CAUSE_UNOBSERVED
            return ended.replace("intervention (", "").rstrip(")")
        return None

    def _resolve_incident(
        self, device_id: str, name: str, kind: str, now: float
    ) -> None:
        """Close one problem on the incident timeline.

        Carries the duration, computed from the matching opening, and
        the cause where the episode record knows it. A resolution
        with no opening behind it (a problem that predates the log)
        is still recorded, simply without a duration.
        """
        opened = self._incident_opened_at(device_id, kind)
        duration = (now - opened) if opened is not None else None
        cause = (
            self._recovery_cause(device_id, opened or now)
            if kind in FREEZE_KINDS_FOR_CAUSE
            else None
        )
        self._record_incident(
            device_id,
            name,
            kind,
            INCIDENT_RESOLVED,
            cause=cause,
            duration=duration,
        )

    def _acknowledged_devices(self) -> set[str]:
        """Return the devices a person has checked off.

        Acknowledgment ends at recovery, because the item is deleted
        when its last problem clears. Acknowledgment silences every
        human-facing channel while it lasts (ruling #123), and a
        recovery is still news because it ends the acknowledgment
        rather than happening under it (ruling #114). So a device is
        in this set only while it is both broken and acknowledged,
        and its eventual recovery is reported as the news it is.
        """
        return {
            record[TODO_DEVICE_ID]
            for record in self.todo_items
            if record.get(TODO_STATUS) == "completed"
            and record.get(TODO_DEVICE_ID)
        }
