# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: interventions.py, Version: 0.13.7 (2026-08-13)

"""Interventions: bridge state, pairing windows, and storms.

One of six subject modules split out of coordinator.py, which
had reached four thousand lines. The seam is the subject, chosen
by measuring which methods call which: storage and interventions
call nothing outside themselves at all, and the three detectors
reach out fewer than ten times each (ruling #201).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.

This file names no coordinator stack (ruling #218). It holds the
live readers and the accessors onto them; which stacks exist, how
each is recognised and which can be read are questions for the
stack registry and the stack files behind it. A test asserts the
silence rather than trusting it.
"""

from __future__ import annotations

from collections import deque
from typing import Any
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .stacks import make_reader
from .transport_mqtt import MQTTBrokerReader

from .const import (
    BROKER_DOWN,
    BROKER_RUNNING,
    BROKER_SCOPE,
    BROKER_TOPIC_UPTIME,
    BROKER_UNKNOWN,
    ATTR_BROKER_CADENCE,
    ATTR_BROKER_LAST_HEARD,
    ATTR_BROKER_STARTED,
    ATTR_BROKER_THRESHOLD,
    ATTR_BROKER_TOPIC,
    ATTR_BROKER_UPTIME,
    DATA_BROKER_SEEN,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    BRIDGE_DOWN,
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    BRIDGE_STATES,
    BRIDGE_UNKNOWN,
    DATA_BRIDGE_SEEN,
    EPISODE_ENDED_RECONNECT,
    EPISODE_ENDED_RESTART,
    LOGGER,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    DATA_STORMS,
    STORM_AT,
    STORM_DEVICES,
    STORM_DOMAIN,
    STORM_DURATION,
    STORM_ENTRY,
    STORM_EXEMPT_PER_HOUR,
    STORM_KEEP_SECONDS,
    SYS_STORM_CLOSED,
    SYS_STORM_OPEN,
    STORM_HISTORY_SECONDS,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
)


def _spell_minutes(minutes: int) -> str:
    """Return a count of minutes as a person would say it.

    Ten reads as ten minutes; fifteen hundred reads as twenty five
    hours rather than as fifteen hundred minutes, which nobody
    converts in their head while reading a brief.
    """
    if minutes < 90:
        return f"{minutes} minutes"
    hours = minutes / 60
    if hours < 48:
        shown = int(hours) if float(hours).is_integer() else round(hours, 1)
        return f"{shown} hours"
    days = hours / 24
    shown = int(days) if float(days).is_integer() else round(days, 1)
    return f"{shown} days"


class InterventionMixin:
    """Interventions: bridge state, pairing windows, and storms."""

    async def _start_broker_reader(self) -> None:
        """Start the one broker watch, where MQTT is present at all.

        Independent of which stacks are detected: a house running
        Tasmota or ESPHome over MQTT and no Zigbee at all still has a
        broker that can fail, and the failure is invisible to every
        other surface (ruling #224). A watch that cannot reach MQTT
        starts anyway and reports unknown, which every consumer reads
        as no opinion.
        """
        if self._broker_reader is not None:
            return
        reader = MQTTBrokerReader(self.hass)
        await reader.async_start()
        self._broker_reader = reader

    async def _start_bridge_readers(self) -> None:
        """Create and start a bridge reader for each capable stack.

        Which stacks can be read is the stack registry's question,
        not this file's (ruling #218): a stack with no reader returns
        None and gets nothing, so an unbuilt or absent stack costs no
        subscription and no timer. A reader that cannot reach its
        state (no MQTT, topics absent) starts anyway and reports
        unknown, so the sensor and the later detector always have
        something to read. The reader is kept regardless of whether it
        connected, because MQTT may come up after us.
        """
        for stack in sorted(self._stacks):
            if stack in self._bridge_readers:
                continue
            reader = make_reader(stack, self.hass)
            if reader is None:
                continue
            self._bridge_readers[stack] = reader
            await reader.async_start()

    def bridge_state(self, stack: str) -> str | None:
        """Return a stack's bridge state, or None if it has no reader."""
        reader = self._bridge_readers.get(stack)
        return reader.state if reader is not None else None

    def bridge_reader(self, stack: str) -> Any | None:
        """Return the reader for a stack, or None if there is none."""
        return self._bridge_readers.get(stack)

    @property
    def bridge_stacks(self) -> list[str]:
        """Return the stacks that have a bridge reader, sorted."""
        return sorted(self._bridge_readers)

    def reachability(self, device_id: str) -> dict[str, Any] | None:
        """Return the owning stack's view of one device, or None.

        None is the common answer and the safe one: no key for this
        device, no reader for its stack, a reader that cannot say, or
        a stack that has never claimed to know. Every caller treats
        None as no opinion and shows nothing (ruling #221).
        """
        owner = self._stack_keys.get(device_id)
        if owner is None:
            return None
        stack, key = owner
        reader = self._bridge_readers.get(stack)
        if reader is None:
            return None
        try:
            return reader.reachability(key)
        except Exception as err:  # noqa: BLE001 - a reader never raises up
            LOGGER.debug(
                "Device Sentinel: %s could not answer reachability "
                "for %s, reading as no opinion (%s)",
                stack,
                device_id,
                err,
            )
            return None

    def reachability_phrase(self, device_id: str) -> str | None:
        """Return the sentence a person reads beside a verdict.

        The state alone would mislead. Zigbee2MQTT allows a sleeping
        device a silence far longer than any window this integration
        learns, so on the reference fleet an online reading is true of
        a battery device that stopped reporting twenty hours ago, and
        a person shown a bare "reads online" would doubt a verdict
        that is correct. The timeout travels with the reading, in the
        units the bridge published it in (ruling #221).
        """
        seen = self.reachability(device_id)
        if seen is None:
            return None
        if seen.get("state") == "offline":
            return "Zigbee2MQTT confirms it is offline."
        minutes = seen.get("timeout_minutes")
        if not isinstance(minutes, int):
            return "Zigbee2MQTT reads it as online."
        if seen.get("class") == "passive":
            return (
                "Zigbee2MQTT reads it as online, though it allows a "
                f"battery device {_spell_minutes(minutes)} of silence "
                "before saying otherwise."
            )
        return (
            "Zigbee2MQTT reads it as online, and it pings a mains "
            f"device every {_spell_minutes(minutes)}."
        )

    def _sample_broker(self, now: float) -> str:
        """Record the broker going and returning. Returns its state.

        Two signals. A regression, where the computed start moves
        forward, means the broker restarted, and it is the only
        signal that survives Home Assistant restarting too, because
        it needs no continuity of its own. Silence past the learned
        threshold covers a broker that dies while this process stays
        alive, which is the case a bridge reader is blind to and the
        reason this watch exists (ruling #224).

        One attribution rule keeps a reboot from being reported
        twice: where the broker's computed start falls inside our own
        unwatched span, the restart event already accounts for it and
        no broker pair is written. Without it, a nightly reboot would
        produce both a restart and a broker outage describing the
        same two minutes.
        """
        reader = self._broker_reader
        if reader is None:
            return BROKER_UNKNOWN
        try:
            state = reader.state
            started = reader.started_at
        except Exception as err:  # noqa: BLE001 - never break the tick
            LOGGER.debug("Broker watch faulted, not sampled: %s", err)
            return BROKER_UNKNOWN
        if state == BROKER_UNKNOWN:
            return BROKER_UNKNOWN

        stored = self.data.setdefault(DATA_BROKER_SEEN, {})
        was = stored.get(BRIDGE_SEEN_STATE)
        known_start = stored.get("started")

        restarted = (
            state == BROKER_RUNNING
            and was == BROKER_RUNNING
            and reader.regressed_since(known_start)
        )
        if restarted and not self._inside_unwatched(started):
            since = known_start
            self._record_system_event(SYS_BROKER_DOWN, scope=BROKER_SCOPE)
            self._record_system_event(
                SYS_BROKER_UP,
                scope=BROKER_SCOPE,
                duration=(
                    started - since
                    if since is not None and started is not None
                    else None
                ),
            )
        elif was is not None and was != state:
            if state == BROKER_DOWN:
                stored[BRIDGE_SEEN_SINCE] = now
                self._record_system_event(
                    SYS_BROKER_DOWN, scope=BROKER_SCOPE
                )
            elif was == BROKER_DOWN:
                since = stored.pop(BRIDGE_SEEN_SINCE, None)
                self._record_system_event(
                    SYS_BROKER_UP,
                    scope=BROKER_SCOPE,
                    duration=(
                        now - since if since is not None else None
                    ),
                )

        if (
            stored.get(BRIDGE_SEEN_STATE) != state
            or stored.get("started") != started
        ):
            stored[BRIDGE_SEEN_STATE] = state
            if started is not None:
                stored["started"] = started
            self._dirty = True
        return state

    def _inside_unwatched(self, started: float | None) -> bool:
        """Return whether a broker start falls in our own dark window.

        A restart of the whole machine takes the broker with it, and
        the restart event already carries the span nothing was
        listening. Reporting a broker outage for the same two minutes
        would be two records of one event.
        """
        if started is None:
            return False
        last_alive = getattr(self, "_last_alive", None)
        if last_alive is None:
            return False
        session_start = getattr(self, "_started_at", None)
        if session_start is None:
            return False
        return last_alive <= started <= session_start + 1.0

    @property
    def broker_state(self) -> str:
        """Return the broker's state for the sensor and diagnostics."""
        reader = self._broker_reader
        if reader is None:
            return BROKER_UNKNOWN
        try:
            return reader.state
        except Exception:  # noqa: BLE001 - a reader never raises up
            return BROKER_UNKNOWN

    @property
    def broker_attributes(self) -> dict[str, Any]:
        """Return what the broker sensor publishes beside its state."""
        reader = self._broker_reader
        attributes: dict[str, Any] = {ATTR_BROKER_TOPIC: BROKER_TOPIC_UPTIME}
        if reader is None:
            return attributes
        try:
            started = reader.started_at
            attributes[ATTR_BROKER_STARTED] = (
                dt_util.utc_from_timestamp(started).isoformat()
                if started is not None
                else None
            )
            attributes[ATTR_BROKER_UPTIME] = reader.uptime
            attributes[ATTR_BROKER_LAST_HEARD] = reader.last_heard
            cadence = reader.cadence
            attributes[ATTR_BROKER_CADENCE] = (
                round(cadence, 3) if cadence is not None else None
            )
            threshold = reader.threshold
            attributes[ATTR_BROKER_THRESHOLD] = (
                round(threshold, 1) if threshold is not None else None
            )
        except Exception as err:  # noqa: BLE001 - a reader never raises up
            LOGGER.debug(
                "Device Sentinel: broker attributes unavailable, "
                "showing what was read (%s)",
                err,
            )
        return attributes

    def _remember_bridge_state(
        self, stack: str, state: str, since: float | None = None
    ) -> None:
        """Store a stack's bridge state so a restart does not lose it.

        Small and derived, but it has to outlive the process: the
        whole point is the comparison on the next boot. since is
        written only when the state becomes down, and it is what the
        recovery's duration is measured from, so an outage that
        spanned a reboot reports its real length rather than none.
        """
        seen = self.data.setdefault(DATA_BRIDGE_SEEN, {})
        entry = seen.setdefault(stack, {})
        if entry.get(BRIDGE_SEEN_STATE) != state or since is not None:
            entry[BRIDGE_SEEN_STATE] = state
            if since is not None:
                entry[BRIDGE_SEEN_SINCE] = since
            elif state != BRIDGE_DOWN:
                entry.pop(BRIDGE_SEEN_SINCE, None)
            self._dirty = True

    def _restore_bridge_state(self) -> None:
        """Load the last bridge state each stack was seen in.

        Called once, after the readers start and before the first
        sample. A stack with nothing stored stays absent, which is
        the fresh-start shape the sampler already handles by
        recording no transition (ruling #222).
        """
        for stack, entry in (self.data.get(DATA_BRIDGE_SEEN) or {}).items():
            if not isinstance(entry, dict):
                continue
            state = entry.get(BRIDGE_SEEN_STATE)
            if state not in BRIDGE_STATES or state == BRIDGE_UNKNOWN:
                continue
            self._bridge_seen[stack] = state
            since = entry.get(BRIDGE_SEEN_SINCE)
            if state == BRIDGE_DOWN and isinstance(since, (int, float)):
                self._bridge_down_at[stack] = since

    def _read_bridge(
        self, stack: str, reader: Any
    ) -> tuple[str, bool] | None:
        """Return a reader's state and pairing flag, or None if it
        faulted.

        A reader that cannot answer is not an event. Following ruling #147:
        any failure degrades to no reading and says so at debug,
        rather than being swallowed or allowed to stop the tick that
        every other judgment runs on.
        """
        try:
            return reader.state, reader.pairing_open
        except Exception as err:  # noqa: BLE001
            LOGGER.debug(
                "Bridge reader for %s faulted, not sampled: %s",
                stack,
                err,
            )
            return None

    @callback
    def _sample_bridges(self) -> None:
        """Record a bridge or a pairing window changing state.

        Nothing else polls the readers: their state is read on demand
        by the sensors and the pairing check, so a bridge could go
        down and come back with no trace anywhere. Sampling on the
        tick gives minute granularity, which is finer than any
        outage worth writing down.

        The unknown state is never recorded. It means nothing has
        been heard from the bridge yet, which is the shape of a fresh
        start rather than of anything happening, and recording it
        would put a bridge event under every restart.

        The last state seen is remembered across a restart, so an
        outage that spans one still closes. It used to live only in
        memory, so a bridge that went down at 03:40 and came back
        while the house rebooted at 03:42 wrote a bridge_down and
        never a bridge_up, and the log read as an outage that never
        ended. Twice on the reference fleet (ruling #222).
        """
        now = dt_util.utcnow().timestamp()
        # The broker first, because it is the outer scope. A bridge
        # that cannot be heard is not a bridge that is down: when the
        # broker dies nothing delivers the bridge's last will, since
        # the broker is the deliverer, so a bridge event written here
        # would name the wrong thing (ruling #224).
        broker = self._sample_broker(now)
        if broker == BROKER_DOWN:
            return
        for stack, reader in self._bridge_readers.items():
            sample = self._read_bridge(stack, reader)
            if sample is None:
                continue
            state, pairing = sample
            if state == BRIDGE_UNKNOWN:
                continue
            was = self._bridge_seen.get(stack)
            self._bridge_seen[stack] = state
            self._remember_bridge_state(stack, state)
            if was is not None and was != state:
                if state == BRIDGE_DOWN:
                    self._bridge_down_at[stack] = now
                    self._remember_bridge_state(stack, state, since=now)
                    self._record_system_event(
                        SYS_BRIDGE_DOWN, scope=stack
                    )
                elif was == BRIDGE_DOWN:
                    since = self._bridge_down_at.pop(stack, None)
                    self._record_system_event(
                        SYS_BRIDGE_UP,
                        scope=stack,
                        duration=(
                            now - since if since is not None else None
                        ),
                    )
            open_was = self._pairing_seen.get(stack)
            self._pairing_seen[stack] = pairing
            if open_was is not None and open_was != pairing:
                if pairing:
                    self._pairing_open_at[stack] = now
                    self._record_system_event(
                        SYS_PAIRING_OPEN, scope=stack
                    )
                else:
                    since = self._pairing_open_at.pop(stack, None)
                    self._record_system_event(
                        SYS_PAIRING_CLOSED,
                        scope=stack,
                        duration=(
                            now - since if since is not None else None
                        ),
                    )

    def _storm_feed(
        self, entry_id: str | None, device_id: str, now: float
    ) -> dict[str, Any] | None:
        """Feed the per-integration storm detector; return active storm."""
        if entry_id is None:
            return None
        # A poller is still watched and still counted. Only its
        # reporting stops. Returning here instead was the fault: an
        # integration read as a poller was never fed again, so its
        # history stopped accruing, its rows aged out of the hour,
        # the verdict lapsed, and it stormed ten more times. The
        # reference fleet ran exactly ten storms an hour for four
        # hours, which is the exemption threshold rather than
        # anything the router was doing. Being exempt cannot be
        # allowed to suppress the evidence for being exempt
        # (ruling #232). This is the rule the project already holds
        # for exclusion: every device is watched and recorded, and
        # exclusion suppresses judgment and reporting alone.
        polling = self._is_polling_integration(entry_id, now)
        if polling:
            self._announce_polling(entry_id)
        queue = self._storm_feed_q.setdefault(entry_id, deque())
        queue.append((now, device_id))
        cutoff = now - STORM_WINDOW_SECONDS
        while queue and queue[0][0] < cutoff:
            queue.popleft()
        distinct = len({dev for _, dev in queue})

        storm = self._storm_active.get(entry_id)
        if distinct >= STORM_DEVICE_THRESHOLD:
            if storm is None:
                # Inside startup grace the burst is the restart
                # itself, which is already recorded and already
                # explains these devices. Writing a storm here would
                # give the nightly reboot a second, narrower and
                # wrong explanation, and the episode stamp below has
                # said so since long before storms were recorded
                # (ruling #229).
                # The row is written whatever the verdict, because the
                # verdict is recomputed from these rows. What a
                # poller does not get is the system event and the
                # episode stamp (ruling #232).
                recorded = now >= self._grace_until
                if recorded:
                    self._record_storm(entry_id, now, announce=not polling)
                storm = {
                    "start": now,
                    "last_met": now,
                    "stamps": 0,
                    "devices": set(),
                    # Whether this storm's opening reached the record.
                    # A storm inside startup grace is the restart and
                    # is not recorded, so its closing must not be
                    # either: suppressing one half left an orphan
                    # sentence in the brief saying an integration
                    # settled when nothing had been said to start
                    # (ruling #230).
                    "recorded": recorded,
                    # A poller's storm is counted and never spoken
                    # of: no opening event, no closing event, and no
                    # episode stamp, so its devices go on learning
                    # their poll cadence as rhythm, which is the
                    # whole point of recognising it (ruling #232).
                    "announce": recorded and not polling,
                }
                self._storm_active[entry_id] = storm
                # A storm is a radio-level event, most often a bridge
                # or hub reconnecting: it can revive a wedged device,
                # so any silence running now is truncated, not
                # completed, exactly as a reboot truncates one. Inside
                # startup grace the storm is the restart itself, and
                # is named as such: the brief quotes this cause, and
                # crediting a reconnect for a restart's work would
                # name the wrong cause on every device it reached.
                if not polling:
                    self._stamp_intervention(
                        EPISODE_ENDED_RESTART
                        if now < self._grace_until
                        else EPISODE_ENDED_RECONNECT,
                        now,
                        entry_id=entry_id,
                    )
            else:
                storm["last_met"] = now
        elif storm is not None and now - storm["last_met"] > (
            STORM_RELEASE_SECONDS
        ):
            self._end_storm(entry_id, storm, now)
            return None
        return self._storm_active.get(entry_id)

    def _device_stack(self, device_id: str) -> str | None:
        """Return the coordinator stack a device belongs to, if known.

        Read from the map the registry walk already builds, so this
        file still names no stack (ruling #218).
        """
        owner = self._stack_keys.get(device_id)
        return owner[0] if owner else None

    def _entry_domain(self, entry_id: str) -> str:
        """Return an integration's domain, or its id if it is gone.

        The domain is what a person reads, and it is stable across a
        rename of the entry's title, which is why the stored series
        and the system event both carry it (ruling #227).
        """
        entry = self.hass.config_entries.async_get_entry(entry_id)
        return entry.domain if entry else entry_id

    def _record_storm(
        self, entry_id: str, now: float, announce: bool = True
    ) -> None:
        """Open a storm: one row, and an event where it is news.

        Both, because they answer different questions. The event puts
        an integration reload in the brief beside a bridge outage and
        a restart, which is where a person looks. The series is what
        the polling rule reads, and it has to outlive the process or
        the rule can only ever count the storms of one uptime.
        """
        domain = self._entry_domain(entry_id)
        if announce:
            self._record_system_event(SYS_STORM_OPEN, scope=domain)
        storms = self.data.setdefault(DATA_STORMS, [])
        storms.append(
            {
                STORM_AT: now,
                STORM_ENTRY: entry_id,
                STORM_DOMAIN: domain,
                STORM_DEVICES: 0,
                STORM_DURATION: None,
            }
        )
        self._trim_storms(now)
        self._dirty = True

    def _announce_polling(self, entry_id: str) -> None:
        """Say once a session that an integration reads as a poller.

        The verdict is recomputed from the series every time, which
        is the point, but saying so on every sample would fill a log
        with one sentence. Announced state is memory only and never
        a verdict: forgetting it costs one repeated line after a
        restart and nothing else (ruling #230).
        """
        if entry_id in self._storm_announced:
            return
        self._storm_announced.add(entry_id)
        LOGGER.debug(
            "Integration %s reclassified as synchronized "
            "polling (%d storms inside an hour); storm "
            "exclusion disabled for it, its devices learn "
            "their poll cadence as rhythm",
            self._entry_domain(entry_id),
            STORM_EXEMPT_PER_HOUR,
        )

    def _close_storm_row(
        self, entry_id: str, now: float, duration: float, devices: int
    ) -> bool:
        """Finish the open row for this entry. Returns whether one was.

        One storm is one row, opened when it begins and finished
        here, so the series carries a duration and a size rather than
        two rows to be paired later.
        """
        for row in reversed(self.data.get(DATA_STORMS) or []):
            if (
                isinstance(row, dict)
                and row.get(STORM_ENTRY) == entry_id
                and row.get(STORM_DURATION) is None
            ):
                row[STORM_DEVICES] = devices
                row[STORM_DURATION] = duration
                self._dirty = True
                return True
        return False

    def _is_polling_integration(self, entry_id: str, now: float) -> bool:
        """Return whether this integration's bursts are its own cadence.

        Some integrations poll every device on a timer, so all of them
        report inside the same second, again and again. That is
        indistinguishable from a hub reconnecting, and excluding it
        from learning would throw away the very rhythm the device has.
        Enough storms inside an hour and the integration is read as a
        poller instead.

        Counted from the stored series each time rather than written
        down once. A stored verdict cannot be revisited: an
        integration that misbehaved for a week and then settled would
        stay exempt for good, with nothing to notice. Reading the
        series means the answer changes when the evidence does, which
        is the same reason the storage split reads whether clocks are
        present rather than trusting a version number.
        """
        cutoff = now - STORM_HISTORY_SECONDS
        # Only finished storms count. A row left open by a crash
        # cannot be updated by anything, so counting it would let a
        # verdict rest on evidence that can never change, which is
        # the whole reason the exemption is recomputed rather than
        # remembered (ruling #230).
        # Every row is checked for shape before it is read. This
        # runs inside the event listener, so one malformed row would
        # break event processing for the device that triggered it,
        # and the restore path beside it has always guarded this way
        # (ruling #231).
        recent = [
            row
            for row in (self.data.get(DATA_STORMS) or [])
            if isinstance(row, dict)
            and row.get(STORM_ENTRY) == entry_id
            and isinstance(row.get(STORM_AT), (int, float))
            and row[STORM_AT] >= cutoff
            and row.get(STORM_DURATION) is not None
        ]
        return len(recent) >= STORM_EXEMPT_PER_HOUR

    def _trim_storms(self, now: float) -> None:
        """Drop storms past the person's retention.

        The series is kept on the retention setting rather than the
        judgment window, because nothing judges by it yet and its
        whole purpose is to be looked back over.
        """
        storms = self.data.get(DATA_STORMS) or []
        # Two days, not the retention setting. The only thing that
        # reads these rows looks back one hour, and a real reload is
        # already kept for the full retention in the system events
        # log, so a longer window here stores nothing anybody asks
        # for. On a fleet with one poller, the retention setting
        # would have reached 2.66 MB against a whole storage file of
        # about 880 KB (ruling #232).
        cutoff = now - STORM_KEEP_SECONDS
        # Shape-checked like every other read of this series: one
        # malformed row would otherwise break the storm path, which
        # runs inside the event listener (ruling #231). A row that
        # cannot be read is also a row that can never be trimmed by
        # date, so dropping it here is the only way it ever leaves.
        kept = [
            row
            for row in storms
            if isinstance(row, dict)
            and isinstance(row.get(STORM_AT), (int, float))
            and row[STORM_AT] >= cutoff
        ]
        if len(kept) != len(storms):
            self.data[DATA_STORMS] = kept

    def _end_storm(
        self, entry_id: str, storm: dict[str, Any], now: float
    ) -> None:
        """Close a storm, on the series and in the events log."""
        domain = self._entry_domain(entry_id)
        duration = (
            storm["last_met"] - storm["start"] + STORM_RELEASE_SECONDS
        )
        if storm.get("recorded", True):
            self._close_storm_row(
                entry_id, now, duration, len(storm["devices"])
            )
        if storm.get("announce", storm.get("recorded", True)):
            self._record_system_event(
                SYS_STORM_CLOSED,
                scope=domain,
                duration=duration,
                devices=len(storm["devices"]),
            )
        if storm["stamps"]:
            LOGGER.debug(
                "Storm on %s ended: %d devices, %d stamps excluded from "
                "learning, %.1f s duration",
                domain,
                len(storm["devices"]),
                storm["stamps"],
                duration,
            )
        self._storm_active.pop(entry_id, None)
        self._trim_storms(now)

    def _sweep_storms(self, now: float) -> None:
        """Close storms whose feed has gone quiet."""
        for entry_id, storm in list(self._storm_active.items()):
            if now - storm["last_met"] > STORM_RELEASE_SECONDS:
                self._end_storm(entry_id, storm, now)

    @callback
    def _on_grace_closed(self, _now: Any) -> None:
        """Log the startup grace summary and re-read the registry.

        The rebuild is the second half of ruling #260. Setting a
        device aside for having no entities is held during the
        startup window, because an integration that has not finished
        loading has none yet; without a rebuild when the window
        shuts, a device that genuinely has none stays watched until
        some unrelated registry change happens to trigger one, and
        reports as never having spoken in the meantime, which is the
        white noise the rule exists to end (ruling #261).
        """
        self._rebuild_registry_view()
        LOGGER.debug(
            "Startup grace closed after %d s: %d stamps across %d devices "
            "excluded from learning; %d boot-blip taints aggregated",
            STARTUP_GRACE_SECONDS,
            self._grace_stamps,
            len(self._grace_devices),
            len(self._grace_taints),
        )
