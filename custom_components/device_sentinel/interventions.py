# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: interventions.py, Version: 0.23.1 (2026-09-24)

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
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .stacks import (
    make_join_observer,
    make_reader,
    reader_for_domain,
)
from .transport_mqtt import MQTTBrokerReader

from .const import (
    SYS_DETAIL,
    DATA_SYSTEM_EVENTS,
    STORM_EXPLAINED_SECONDS,
    SYS_KIND,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_DOWN,
    SYS_WIFI_UP,
    SYS_DEVICE_HANDLED,
    ZHA_HANDLED_TAIL_SECONDS,
    REPAIR_MOMENT_GRACE,
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
    INTEGRATION_DOWN_DWELL_SECONDS,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    UPSTREAM_INTEGRATION,
    WIFI_KEY,
    UPSTREAM_BRIDGE,
    UPSTREAM_BROKER,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    BRIDGE_DOWN,
    BRIDGE_HANDBACK_SECONDS,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    BROKER_LABEL,
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
    DATA_STORM_DAYS,
    DATA_STORMS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DEVICES,
    STORM_DAY_DOMAIN,
    STORM_DAY_DURATION,
    STORM_DAY_INTERVAL,
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
from .outage_detail import DOWN, FAILED, make_detail, pair_key, parse_detail


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



def _median(values: list[float]) -> float:
    """Return the median. Values are never empty at the call sites."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0

# The states in which Home Assistant says an entry tried to start and
# failed (ruling #445). An entry in any other unloaded state has not
# been started, and that is not an outage.
_FAILED_SETUP = frozenset(
    {
        ConfigEntryState.SETUP_ERROR,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.MIGRATION_ERROR,
    }
)


def _reader_loaded(reader: Any) -> bool:
    """Whether a reader says its upstream has loaded (ruling #445).

    A reader that cannot say is taken as established, which is what
    every reader was before 0.21.12. One that faults while saying is
    taken the same way, so the tick goes on for every other upstream.
    """
    try:
        return bool(getattr(reader, "loaded", True))
    except Exception as err:  # noqa: BLE001 - never break the tick
        LOGGER.debug("A reader could not say whether it loaded: %s", err)
        return True

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

        # The join observers (ruling #360). An instrument: it logs
        # what a stack says when a device joins and changes nothing.
        # It exists because a pairing window opened from the Home
        # Assistant UI is invisible outside the process, so the rig
        # could not answer whether the join itself is observable and
        # only code running here can. Which stacks have one is the
        # registry's question, not this file's (ruling #218), and a
        # stack without one costs nothing at all.
        for stack in sorted(self._stacks):
            if stack in self._join_observers:
                continue
            observer = make_join_observer(
                stack, self.hass, self._record_device_handled
            )
            if observer is None:
                continue
            if observer.async_start():
                self._join_observers[stack] = observer

    def bridge_state(self, stack: str) -> str | None:
        """Return a stack's bridge state, or None if it has no reader."""
        reader = self._bridge_readers.get(stack)
        return reader.state if reader is not None else None

    @callback
    def _record_device_handled(self, device_id: str, kind: str) -> None:
        """Write that a person handled one device (ruling #362).

        A stack's observer calls this when it hears that a device was
        re-paired, reconfigured or removed. The event is scoped to
        that one device, so the attribution reaches it and nothing
        else, and the window it opens closes after the measured tail
        rather than staying open: a handling that never produced a
        recovery must expire rather than explain the next one.

        Nothing is written for a device this integration does not
        watch. A device set aside is a device with no verdict to
        explain, and an event about it would be noise in the log a
        person reads.
        """
        if device_id not in self._watched:
            return
        now = dt_util.utcnow().timestamp()
        last = self._handled_at.get(device_id)
        self._handled_at[device_id] = now
        if last is not None and now - last <= ZHA_HANDLED_TAIL_SECONDS:
            # The same handling still running. A re-pair fires four
            # or five messages over half a minute, and each is the
            # same person at the same device: one event, refreshed,
            # rather than five in the brief.
            return
        # The registry id travels in `detail`, which is a string.
        # It cannot travel in `devices`: the shape check declares
        # that field an integer (a count), and writing a list there
        # would raise a storage fault on the next verify, which is
        # to say this feature would have raised the repair card
        # built for real corruption. Found before shipping, and the
        # shape is the authority.
        self._record_system_event(
            SYS_DEVICE_HANDLED,
            scope=self._device_stack(device_id) or "",
            detail=f"{device_id} {kind}",
        )
        LOGGER.info(
            "A person handled %s (%s); its next recovery will be "
            "attributed to that rather than learned",
            self._device_name(device_id),
            kind,
        )

    def _handled_recently(self, device_id: str, now: float) -> bool:
        """Return whether a person handled this device just now.

        The other half of ruling #362. The system event explains the
        recovery in the brief and the episode; this is what stops
        the gap teaching a rhythm, and without it the two disagree:
        the report says the silence was somebody's hands while the
        daily maximum quietly widens as though it were the device's
        own. Read from the same stamp the event was recorded
        against, so the two can never drift apart.

        Bounded by the measured tail rather than left open, because
        a person who touched a device and walked away must not
        explain its recovery an hour later.
        """
        when = self._handled_at.get(device_id)
        if when is None:
            return False
        return 0.0 <= now - when <= ZHA_HANDLED_TAIL_SECONDS

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
        failed = self._own_entry_failure(device_id)
        if failed is not None:
            return failed
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
                "Zigbee2MQTT reads it as online. Zigbee2MQTT waits "
                f"{_spell_minutes(minutes)} of silence from a battery "
                "device before it says otherwise."
            )
        return (
            "Zigbee2MQTT reads it as online. Zigbee2MQTT pings a mains "
            f"device every {_spell_minutes(minutes)}."
        )

    def _own_entry_failure(self, device_id: str) -> str | None:
        """Return why a device's own connection is down, or None.

        For a device that is its entry's only device, whose outage has
        been told (0.23.1). The words are the owner's from 0.22.23:
        "its SwitchBot connection failed to start".
        """
        entry_id = self._entry_of_device.get(device_id)
        if entry_id is None or self._entry_only_device.get(entry_id) != device_id:
            return None
        if entry_id not in self._integration_told:
            return None
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return None
        title = self._integration_title(entry.domain)
        detail = self._integration_detail.get(entry_id)
        if parse_detail(detail)[2] == FAILED:
            return f"Its {title} connection failed to start."
        return f"Its {title} connection is down."

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
        if state == BROKER_UNKNOWN and not self._broker_silent_run(now):
            return BROKER_UNKNOWN
        if state == BROKER_UNKNOWN:
            # Heard in an earlier run and silent through the whole of
            # this one, past the grace: this broker publishes, so the
            # silence is an outage rather than a broker that has
            # nothing to say (ruling #451). On the reference rig, 17
            # September, Home Assistant loaded the MQTT entry a
            # second after the restart while the broker itself was
            # stopped, so nothing else in the house would have said
            # so, and every device behind it would have been listed
            # on its own once the grace ended.
            state = BROKER_DOWN
        # The same rule as every bridge (ruling #445). The reader also
        # reads unknown until it first hears the broker, so a broker
        # this run has never heard cannot read down; the rule is kept
        # for a reader that can.
        loading, from_start = self._loading(
            BROKER_LABEL, _reader_loaded(reader), state == BROKER_DOWN, now
        )
        if loading:
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
            # Measured from the last arrival before the restart, not
            # from the previous start: the latter is how long the
            # broker had been up, which is the opposite of an outage
            # (ruling #396).
            since = reader.stopped_at
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
                began = from_start if from_start is not None else now
                if from_start is not None:
                    self._upstream_from_start.add(BROKER_LABEL)
                stored[BRIDGE_SEEN_SINCE] = began
                # The moment the reporting layer measures from
                # (ruling #264), kept beside the bridges' own stamps.
                self._broker_down_at = began
                self._begin_upstream_peak(BROKER_LABEL)
                self._record_system_event(
                    SYS_BROKER_DOWN, scope=BROKER_SCOPE
                )
                self._say_upstream_down(
                    UPSTREAM_BROKER, BROKER_LABEL, None, began
                )
            elif was == BROKER_DOWN:
                self._upstream_from_start.discard(BROKER_LABEL)
                # Read while the broker still claims its devices.
                ended = self._upstream_ended(BROKER_LABEL)
                self._broker_down_at = None
                since = stored.pop(BRIDGE_SEEN_SINCE, None)
                self._record_system_event(
                    SYS_BROKER_UP,
                    scope=BROKER_SCOPE,
                    duration=(
                        now - since if since is not None else None
                    ),
                    **ended,
                )
                self._say_upstream_restored(
                    UPSTREAM_BROKER, BROKER_LABEL, None, since, now
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

    def _upstream_devices(self, stack: str | None) -> int:
        """Count the watched devices behind an upstream.

        Membership, not casualties. `suppressed_down_counts` answers a
        different question, how many devices this upstream is masking
        right now, and at the moment an upstream fails that number is
        zero: no device has been judged silent yet, because judging
        one takes minutes. So the event carries how many devices sit
        behind the thing that stopped, which is stable, means the same
        on both halves of the pair, and is what an automation deciding
        whether to wake somebody actually wants.

        Watched and not freeze-muted. A muted device is never given an
        unavailable verdict, so it would never have been reported and
        must not swell a number a person acts on. Excluded and
        set-aside devices are not in `_watched` at all.

        A broker, with stack None, carries every watched device on
        every stack that has a reader, because that is what a stopped
        broker takes with it.
        """
        return sum(
            1
            for device_id in self._watched
            if (
                self._stack_for_device(device_id) is not None
                if stack is None
                else self._stack_for_device(device_id) == stack
            )
            and not self._freeze_muted(device_id)
        )

    def _say_upstream_down(
        self, kind: str, name: str, stack: str | None, since: float,
        devices: int | None = None,
        confirmed: int | None = None,
    ) -> None:
        """Put an upstream failure on the bus, or hold it for grace.

        Nothing is announced during the startup grace, because that is
        what the grace is for: every other integration is still coming
        up and none of what it reports is news (ruling #291). But an
        upstream that fails inside the grace and is still down when it
        ends is news, and without this it would produce a recovery
        with no failure before it, which is an automation pairing the
        two that never closes.

        So the announcement is held rather than dropped, and
        `_announce_held_upstreams` fires it on the first sample after
        the grace, carrying the moment it really happened.
        """
        if self._in_startup_grace():
            self._upstream_held[name] = (kind, stack, since, devices)
            return
        self._upstream_said[name] = (kind, stack, since, devices)
        self.fire_upstream_down(
            kind,
            name,
            dt_util.utc_from_timestamp(since)
            .astimezone(dt_util.DEFAULT_TIME_ZONE)
            .isoformat(),
            self._upstream_devices(stack)
            if devices is None
            else devices,
            confirmed=confirmed,
        )

    def _announce_held_upstreams(self) -> None:
        """Announce anything the grace swallowed, once, when it ends."""
        if not self._upstream_held or self._in_startup_grace():
            return
        held = dict(self._upstream_held)
        self._upstream_held.clear()
        for name, (kind, stack, since, devices) in held.items():
            self._say_upstream_down(kind, name, stack, since, devices)

    def _say_upstream_restored(
        self,
        kind: str,
        name: str,
        stack: str | None,
        since: float | None,
        now: float,
        devices: int | None = None,
    ) -> None:
        """Put an upstream recovery on the bus."""
        # An outage nobody was told about gets no recovery. The held
        # map covers the case where it was still down when the grace
        # ended; this covers the narrower one where it came and went
        # entirely inside it, which is a restart artifact and not an
        # event a person needs.
        self._upstream_held.pop(name, None)
        said = self._upstream_said.pop(name, None)
        if said is None:
            return
        # The pair must agree about what it was about, so the count
        # comes from the failure rather than from a fleet that may
        # have changed while the upstream was gone.
        if devices is None:
            devices = said[3]
        began = since if since is not None else now
        self.fire_upstream_restored(
            kind,
            name,
            dt_util.utc_from_timestamp(began)
            .astimezone(dt_util.DEFAULT_TIME_ZONE)
            .isoformat(),
            self._upstream_devices(stack)
            if devices is None
            else devices,
            max(0.0, now - began),
        )

    def _sample_integrations(self, now: float) -> None:
        """Watch the config entry behind every watched device.

        The third thing that can carry a house's devices, after the
        broker and a bridge. ZHA and Zigbee2MQTT report their own
        liveness and are skipped here; everything else has nothing
        watching it, and an integration that fell over takes every
        device behind it quiet with no cause on record (ruling #382).

        Down means any state other than loaded, held for the dwell.
        Home Assistant passes through setup_in_progress on the way
        back up and drops an entry for a few seconds on a reload, so
        the first sighting of an unloaded entry is evidence of
        nothing.

        An entry with no watched device behind it is not watched at
        all. An integration nobody is relying on has no story to tell,
        and a row for it would be noise.
        """
        behind: dict[str, int] = {}
        carried: dict[str, str] = {}
        for device_id in self._watched:
            if self._stack_for_device(device_id) is not None:
                continue
            entry_id = self._entry_of_device.get(device_id)
            if entry_id is None or self._freeze_muted(device_id):
                continue
            behind[entry_id] = behind.get(entry_id, 0) + 1
            carried[entry_id] = device_id
        # The one device an entry carries, where it carries one
        # (0.22.23): SwitchBot, TP-Link and Brother make an entry per
        # device, so that entry failing is that device offline.
        self._entry_only_device = {
            entry_id: carried[entry_id]
            for entry_id, count in behind.items()
            if count == 1
        }
        self._resume_integration_outages()

        for entry_id in list(self._entry_down_at):
            if entry_id not in behind:
                self._entry_down_at.pop(entry_id, None)

        for entry_id in behind:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            loaded = (
                entry is not None
                and entry.state is ConfigEntryState.LOADED
            )
            if loaded:
                self._entry_seen_loaded.add(entry_id)
                self._note_loaded(entry.domain, now)
                since = self._entry_down_at.pop(entry_id, None)
                if since is not None and now - since >= (
                    INTEGRATION_DOWN_DWELL_SECONDS
                ):
                    self._integration_back(entry, since, now)
                continue
            if entry_id not in self._entry_seen_loaded:
                # Not loaded since Home Assistant started. While the
                # grace lasts it is still starting (ruling #445). Once
                # the grace is over, one that Home Assistant says has
                # failed is down, dated from the start, because it
                # never came up in this run; until 0.21.12 it was
                # never judged, and the devices behind it were
                # reported one by one. One Home Assistant has simply
                # not set up says nothing either way and is still left
                # alone: reading it as down claimed every device of an
                # entry nobody had started and hid a real freeze.
                if self._in_startup_grace():
                    continue
                if entry is None or entry.state not in _FAILED_SETUP:
                    continue
                self._entry_down_at.setdefault(entry_id, self._run_start())
                self._upstream_from_start.add(entry.domain)
            first = self._entry_down_at.get(entry_id)
            if first is None:
                self._entry_down_at[entry_id] = now
                continue
            if now - first < INTEGRATION_DOWN_DWELL_SECONDS:
                continue
            if entry is not None and self._integration_new(entry_id):
                self._integration_gone(entry, first, behind[entry_id])

    def _resume_integration_outages(self) -> None:
        """Take back, once a run, the entry outages still open in the
        events log (0.22.23).

        Which outages had been announced was held in memory alone, so
        after every restart an entry that had never come back was
        dated from the new run's start and recorded down again: the
        second fleet's dead vacuum wrote a fresh outage after each
        restart. An entry whose outage is still open resumes it, from
        when it first went down; one that has come back is recorded
        back when it is next seen loaded. Events written before
        0.22.23 carry no entry and age out as they are.
        """
        if self._integration_resumed:
            return
        self._integration_resumed = True
        open_rows: dict[str, dict[str, Any]] = {}
        for row in self.data.get(DATA_SYSTEM_EVENTS) or []:
            if not isinstance(row, dict):
                continue
            entry_id = parse_detail(row.get(SYS_DETAIL))[0]
            if entry_id is None:
                continue
            if row.get(SYS_KIND) == SYS_INTEGRATION_DOWN:
                open_rows[entry_id] = row
            elif row.get(SYS_KIND) == SYS_INTEGRATION_UP:
                open_rows.pop(entry_id, None)
        for entry_id, row in open_rows.items():
            when = row.get(SYS_WHEN)
            if not isinstance(when, (int, float)):
                continue
            self._integration_told.add(entry_id)
            self._integration_detail[entry_id] = row[SYS_DETAIL]
            self._entry_down_at[entry_id] = float(when)

    def outage_device_name(self, detail: Any) -> str | None:
        """The device an entry outage was, by its name, or None."""
        device_id = parse_detail(detail)[1]
        if device_id is None:
            return None
        return self._device_names.get(device_id)

    def _integration_new(self, entry_id: str) -> bool:
        """True the first time an outage passes the dwell."""
        return entry_id not in self._integration_told

    def _integration_gone(self, entry, since: float, behind: int) -> None:
        """Record and announce an integration that has gone."""
        self._integration_told.add(entry.entry_id)
        self._begin_upstream_peak(entry.domain)
        detail = make_detail(
            entry.entry_id,
            self._entry_only_device.get(entry.entry_id),
            FAILED if entry.state in _FAILED_SETUP else DOWN,
        )
        self._integration_detail[entry.entry_id] = detail
        # Dated from when it went down rather than from when the dwell
        # confirmed it (0.22.23), so an outage resumed after a restart
        # keeps its own start.
        self._record_system_event(
            SYS_INTEGRATION_DOWN, scope=entry.domain, detail=detail, when=since
        )
        self._say_upstream_down(
            UPSTREAM_INTEGRATION, entry.domain, None, since, behind
        )

    def _integration_back(self, entry, since: float, now: float) -> None:
        """Record and announce an integration that has come back.

        What it was carrying keeps the claim for the same window a
        bridge gives (ruling #441), and the recovery is watched, so a
        Z-Wave or Matter device still rejoining is not reported the
        moment the entry loads.
        """
        if entry.entry_id not in self._integration_told:
            return
        domain = entry.domain
        self._upstream_from_start.discard(domain)
        # The window closes on the wall clock, for the reason the
        # Wi-Fi hand-back gives: the claim is asked without a clock,
        # so a sample's own time would be compared against another.
        self._integration_handback[entry.entry_id] = (
            since, dt_util.utcnow().timestamp()
        )
        self._integration_recovering_at[domain] = now
        self._integration_fell[domain] = self._integration_casualties(
            domain
        )
        # Read while the window holds the claim.
        ended = self._upstream_ended(domain)
        self._integration_told.discard(entry.entry_id)
        self._record_system_event(
            SYS_INTEGRATION_UP,
            scope=domain,
            detail=self._integration_detail.pop(entry.entry_id, None),
            duration=now - since,
            **ended,
        )
        self._say_upstream_restored(
            UPSTREAM_INTEGRATION, entry.domain, None, since, now
        )

    def integration_down_since(self, device_id: str) -> tuple[str, float] | None:
        """Return the integration that is down for this device.

        Never for a device that is its entry's only device (0.23.1). An
        entry per device, as SwitchBot, TP-Link and Brother make, failing
        is that device offline, not an outage behind it: claimed as a
        casualty, the second fleet's two dead freezer sensors were kept
        off the Problem List, counted instead under "switchbot down: 2
        of 14 total devices unavailable", and went on and off the list
        at each restart as the outage was taken back. They are judged
        on their own, and the reason travels with the verdict.
        """
        entry_id = self._entry_of_device.get(device_id)
        if entry_id is None:
            return None
        if self._entry_only_device.get(entry_id) == device_id:
            return None
        since = self._entry_down_at.get(entry_id)
        if since is None or entry_id not in self._integration_told:
            held = self._integration_handback.get(entry_id)
            if held is None:
                return None
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                return None
            if self._integration_window_open(held):
                return entry.domain, held[0]
            self._integration_handback.pop(entry_id, None)
            self._integration_recovery_over(entry.domain)
            return None
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return None
        return entry.domain, since

    @staticmethod
    def _integration_window_open(held: tuple[float, float]) -> bool:
        """Whether a returned integration still holds its devices."""
        return dt_util.utcnow().timestamp() - held[1] < (
            BRIDGE_HANDBACK_SECONDS
        )

    def _integration_recovery_over(self, domain: str) -> None:
        """Forget a domain's recovery once no entry of it holds one."""
        still = any(
            (self.hass.config_entries.async_get_entry(entry_id) or None)
            is not None
            and self.hass.config_entries.async_get_entry(entry_id).domain
            == domain
            and self._integration_window_open(held)
            for entry_id, held in self._integration_handback.items()
        )
        if not still:
            self._integration_recovering_at.pop(domain, None)
            self._integration_fell.pop(domain, None)

    def _integration_casualties(self, domain: str) -> int:
        """How many watched devices of this integration are down.

        Only devices no stack reader carries, which are the ones the
        integration rung speaks for.
        """
        count = 0
        for device_id in self._watched:
            if self._stack_for_device(device_id) is not None:
                continue
            record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
            if record.get(DEV_FROZEN_CATEGORY) is None:
                continue
            entry_id = self._entry_of_device.get(device_id)
            entry = (
                self.hass.config_entries.async_get_entry(entry_id)
                if entry_id is not None
                else None
            )
            if entry is not None and entry.domain == domain:
                count += 1
        return count

    def upstream_recovering_at(self, name: str) -> float | None:
        """When a bridge's or an integration's recovery began, or None.

        One question for the problem list, whichever rung carried the
        outage (ruling #441).
        """
        if name in self._bridge_recovering_at:
            return self._bridge_recovering_at[name]
        if name not in self._integration_recovering_at:
            return None
        self._integration_recovery_over(name)
        return self._integration_recovering_at.get(name)

    def upstream_recovery_counts(self, name: str) -> tuple[int, int]:
        """How many of a recovering upstream's devices are still down,
        and how many it took."""
        if name in self._bridge_recovering_at:
            return self.bridge_recovery_counts(name)
        fell = self._integration_fell.get(name, 0)
        left = self._integration_casualties(name)
        return left, max(fell, left)

    def upstream_down_since(self, device_id: str) -> tuple[str, float] | None:
        """Return the upstream that is down for this device, and when.

        Ruling #264. A stopped broker or bridge does not break
        seventy-six devices; it breaks one thing, and the devices are
        symptoms. The verdicts stay, because they are true, and the
        reporting layer asks this before it speaks so a person is
        told the cause rather than the casualty list.

        The broker outranks any bridge, because a broker that is down
        takes every bridge with it and two problems for one fault is
        the same noise in a smaller font. A device on a stack with no
        reader, or on no stack at all, has no upstream anyone can see
        and is always reported on its own.
        """
        broker_since = self._broker_down_at
        if broker_since is not None:
            return BROKER_LABEL, broker_since
        stack = self._stack_for_device(device_id)
        if stack is None:
            # No stack reader carries this device, so the ladder
            # continues: the network first, because during a Wi-Fi
            # outage the config entries mostly stay loaded and the
            # integration rung stays silent, and a device claimed by
            # its own tracker is claimed by the surest witness. Then
            # the integration itself (#382).
            wifi = self.wifi_down_since(device_id)
            if wifi is not None:
                return wifi
            return self.integration_down_since(device_id)
        since = self._bridge_down_at.get(stack)
        if since is None:
            # The bridge is back, and a device it was carrying is
            # given a window to rejoin before it becomes its own
            # problem (ruling #436). The claim is dated from the
            # outage, not from the end of the window.
            held = self._bridge_handback.get(stack)
            if held is not None:
                if dt_util.utcnow().timestamp() - held[1] < (
                    BRIDGE_HANDBACK_SECONDS
                ):
                    return stack, held[0]
                self._bridge_handback.pop(stack, None)
                self._bridge_recovering_at.pop(stack, None)
                self._bridge_fell.pop(stack, None)
            return None
        return stack, since

    def _stack_casualties(self, stack: str) -> int:
        """How many devices on this stack are currently down."""
        return sum(
            1 for device_id in self.data.get(DATA_DEVICES, {})
            if self._stack_for_device(device_id) == stack
            and (self.data[DATA_DEVICES][device_id] or {}).get(
                DEV_FROZEN_CATEGORY
            )
            is not None
        )

    def _note_loaded(self, name: str, now: float) -> None:
        """Record the first time an upstream is seen loaded this run."""
        if name in self.upstreams_loaded_after:
            return
        start = self._run_start()
        self.upstreams_loaded_after[name] = round(max(0.0, now - start), 1)

    def loading_held(self) -> set[str]:
        """Devices whose upstream is down and has not loaded (#449).

        Inside the startup grace an upstream that reads down and has
        not loaded in this run is still starting as far as anything
        here knows (ruling #445), so nothing is reported for it. Its
        devices wait with it, the way a Wi-Fi burst waits for the
        router (ruling #446): on the reference rig, 17 September, a
        restart taken with the broker stopped came up holding a row
        for each of 75 Zigbee devices, replaced by the single bridge
        row a tick later. Ruling #447 answered the case where the
        outage was remembered; this answers the case where it was not.

        Only an upstream that reads down or that Home Assistant says
        failed to set up holds anything. One that has simply not been
        sampled yet says nothing about its devices, and a device whose
        integration is running is nobody's business but its own.
        """
        if not self._in_startup_grace():
            return set()
        waiting = self._upstreams_still_starting()
        if not waiting:
            return set()
        held: set[str] = set()
        for device_id in self._watched:
            stack = self._stack_for_device(device_id)
            if stack is not None and stack in waiting:
                held.add(device_id)
                continue
            if stack is not None and BROKER_LABEL in waiting:
                held.add(device_id)
                continue
            entry_id = self._entry_of_device.get(device_id)
            if entry_id is not None and entry_id in waiting:
                held.add(device_id)
        return held

    def _broker_silent_run(self, now: float) -> bool:
        """Whether a broker known to publish has said nothing all run.

        Ruling #451. Evidence that it publishes is a state remembered
        from an earlier run: a broker that never published an uptime
        topic would have none, and is left alone.
        """
        if BROKER_LABEL in self.upstreams_loaded_after:
            return False
        if self._in_startup_grace():
            return False
        stored = self.data.get(DATA_BROKER_SEEN) or {}
        if stored.get(BRIDGE_SEEN_STATE) not in (
            BROKER_RUNNING, BROKER_DOWN
        ):
            return False
        return self._broker_reader is not None

    def _upstreams_still_starting(self) -> set[str]:
        """Upstreams reading down that have not loaded in this run."""
        waiting: set[str] = set()
        for stack, reader in self._bridge_readers.items():
            if stack in self.upstreams_loaded_after:
                continue
            sample = self._read_bridge(stack, reader)
            if sample is not None and sample[0] == BRIDGE_DOWN:
                waiting.add(stack)
        if BROKER_LABEL not in self.upstreams_loaded_after:
            reader = self._broker_reader
            stored = self.data.get(DATA_BROKER_SEEN) or {}
            heard_before = stored.get(BRIDGE_SEEN_STATE) in (
                BROKER_RUNNING, BROKER_DOWN
            )
            # Down, or silent all run while the house knows it
            # publishes: either way its devices wait with it
            # (rulings #449, #451).
            if reader is not None and (
                self.broker_state == BROKER_DOWN or heard_before
            ):
                waiting.add(BROKER_LABEL)
        for device_id in self._watched:
            entry_id = self._entry_of_device.get(device_id)
            if entry_id is None or entry_id in self._entry_seen_loaded:
                continue
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.state in _FAILED_SETUP:
                waiting.add(entry_id)
        return waiting

    def _loading(
        self, name: str, loaded: bool, down: bool, now: float
    ) -> tuple[bool, float | None]:
        """Loading is not down (ruling #445).

        One rule for the broker and every bridge. An upstream that has
        not loaded since Home Assistant started is still starting
        while the grace lasts, and nothing is recorded for it. Once
        the grace is over, one that never loaded and reads down is
        down from the start of the run, because it never came up in
        it. Returns whether to treat this reading as loading, and the
        moment a down that never loaded is dated from.
        """
        if loaded:
            self._note_loaded(name, now)
        if not down or name in self.upstreams_loaded_after:
            return False, None
        if self._in_startup_grace():
            return True, None
        return False, self._run_start()

    def _run_start(self) -> float:
        """When this run began listening."""
        if self._started_at is not None:
            return float(self._started_at)
        return self._grace_until - STARTUP_GRACE_SECONDS

    def _note_upstream_peaks(self) -> None:
        """Remember the most devices each standing outage has down.

        Read from the same counts the problem list rows print, once a
        tick after every device is judged, so the worst moment is the
        highest figure a person could have seen on the row (ruling
        #442).
        """
        for name, count in self.suppressed_down_counts.items():
            if count > self._upstream_peak.get(name, 0):
                self._upstream_peak[name] = count

    def _begin_upstream_peak(self, name: str) -> None:
        """Start a new outage's count from nothing."""
        self._upstream_peak[name] = 0

    def _upstream_ended(self, name: str) -> dict[str, int]:
        """The total and the worst moment an ended outage records.

        Read while the outage still claims its devices. The total is
        never printed below the worst, for the reason the row gives:
        where membership reads lower, the resolver has no answer for
        this name.
        """
        worst = self._upstream_worst(name)
        return {
            "devices": max(self.upstream_membership(name), worst),
            "worst": worst,
        }

    def _upstream_worst(self, name: str) -> int:
        """The most devices this outage had down, read as it ends.

        The current count is included because an outage can end on
        the same tick its last devices were judged, before the tick's
        note was taken. Clears the count, which belongs to the outage.
        """
        current = self.suppressed_down_counts.get(name, 0)
        return max(self._upstream_peak.pop(name, 0), current)

    def bridge_recovering_at(self, stack: str) -> float | None:
        """When this bridge's recovery began, or None."""
        return self._bridge_recovering_at.get(stack)

    def bridge_recovery_counts(self, stack: str) -> tuple[int, int]:
        """How many of this bridge's casualties are still down, and
        how many it took."""
        fell = self._bridge_fell.get(stack, 0)
        left = self._stack_casualties(stack)
        return left, max(fell, left)

    def upstream_membership(self, name: str) -> int:
        """Return how many watched devices sit behind a named upstream.

        Membership rather than casualties (ruling #401): the figure
        the card and the problem list print beside the casualty count,
        so a reader sees "74 of 77" and knows both what has fallen
        and what could. The name is what a row carries, the same four
        kinds `upstream_down_since_for` resolves: the broker, which
        carries every device on a stack with a reader; a stack; the
        Wi-Fi key, which carries every tied tracker; or an
        integration domain, which carries its watched devices.
        """
        if name == BROKER_LABEL:
            return self._upstream_devices(None)
        if name == WIFI_KEY:
            return len(getattr(self, "_wifi_ties", {}) or {})
        if name in self._stacks:
            return self._upstream_devices(name)
        return sum(
            1 for device_id, domain in self._watched.items()
            if domain == name and not self._freeze_muted(device_id)
        )

    def upstream_down_since_for(self, name: str) -> float | None:
        """Return when a named upstream went down, or None if it is up.

        The name is what a row or a push carries: the broker label, a
        bridge's stack, or an integration's domain (#382). The domain
        branch exists because the to-do row's stamp and the settle
        gate on the push both ask this by name, and a name that does
        not resolve leaves the row undated and the push unsent. A
        domain can hold several entries, so the outage is dated from
        the first told entry to fall.
        """
        if name == BROKER_LABEL:
            return self._broker_down_at
        since = self._bridge_down_at.get(name)
        if since is not None:
            return since
        if name == WIFI_KEY:
            return self._wifi_down_at
        stamps = []
        for entry_id in self._integration_told:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != name:
                continue
            first = self._entry_down_at.get(entry_id)
            if first is not None:
                stamps.append(first)
        return min(stamps) if stamps else None

    def _stack_for_device(self, device_id: str) -> str | None:
        """Return the stack whose bridge owns this device, if any."""
        domain = self._watched.get(device_id)
        if domain is None:
            return None
        for stack, reader in self._bridge_readers.items():
            if reader_for_domain({stack: reader}, domain) is not None:
                return stack
        return None

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
                # Still down across a restart, so still news when the
                # grace ends (ruling #291). Without this its recovery
                # would arrive with no failure before it, and an
                # automation pairing the two would never close.
                self._upstream_held[stack] = (
                    UPSTREAM_BRIDGE, stack, float(since), None
                )

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
        self._announce_held_upstreams()
        self._sample_integrations(now)
        # Wi-Fi before the broker gate: the trackers come from a
        # router integration and a dead MQTT broker says nothing
        # about them.
        self._sample_wifi(now)
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
            # A reader that cannot say whether it loaded is taken as
            # established.
            loading, from_start = self._loading(
                stack, _reader_loaded(reader), state == BRIDGE_DOWN, now
            )
            if loading:
                continue
            was = self._bridge_seen.get(stack)
            self._bridge_seen[stack] = state
            self._remember_bridge_state(stack, state)
            if was is not None and was != state:
                if state == BRIDGE_DOWN:
                    # When the outage began, not when this tick
                    # noticed (ruling #359). A reader that holds a
                    # dwell before believing an outage would
                    # otherwise stamp its own patience as the start,
                    # and the suppression rule reads a device that
                    # fell before its upstream as one that was
                    # already broken. On the reference rig that put
                    # every ZHA device's own row on the list during
                    # a real coordinator outage. Z2M's bridge
                    # announces itself instantly and offers no onset,
                    # so it stamps now exactly as it always did.
                    #
                    # An onset is believed only if it is a real
                    # moment: a number, not a bool, after the epoch,
                    # and not in the future. No reader can produce a
                    # zero or a negative one, and the guard is here
                    # because the cost of a wrong one is silence:
                    # an onset before every device's timestamp
                    # suppresses the whole fleet's rows behind a
                    # cause, which is the one direction this feature
                    # must never fail in.
                    began = now
                    onset = getattr(reader, "down_since", None)
                    if from_start is not None:
                        began = from_start
                        self._upstream_from_start.add(stack)
                    elif (
                        isinstance(onset, (int, float))
                        and not isinstance(onset, bool)
                        and 0.0 < onset <= now
                    ):
                        began = float(onset)
                    self._bridge_down_at[stack] = began
                    self._remember_bridge_state(stack, state, since=began)
                    self._begin_upstream_peak(stack)
                    self._record_system_event(
                        SYS_BRIDGE_DOWN, scope=stack
                    )
                    self._say_upstream_down(
                        UPSTREAM_BRIDGE, stack, stack, began
                    )
                elif was == BRIDGE_DOWN:
                    self._upstream_from_start.discard(stack)
                    since = self._bridge_down_at.pop(stack, None)
                    # Whatever it was carrying keeps that claim for a
                    # short while (ruling #436), and the recovery is
                    # watched rather than declared over (ruling
                    # #431). Read before the claim is asked for
                    # again, because by then the bridge is up.
                    if since is not None:
                        self._bridge_handback[stack] = (since, now)
                        self._bridge_recovering_at[stack] = now
                        self._bridge_fell[stack] = self._stack_casualties(
                            stack
                        )
                    self._record_system_event(
                        SYS_BRIDGE_UP,
                        scope=stack,
                        duration=(
                            now - since if since is not None else None
                        ),
                        **self._upstream_ended(stack),
                    )
                    self._say_upstream_restored(
                        UPSTREAM_BRIDGE, stack, stack, since, now
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

    _integration_resumed: bool
    _broker_reader: Any | None
    _broker_down_at: float | None

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
        # for muting: every device is watched and recorded, and
        # muting suppresses judgment and reporting alone.
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
        self._append_row(
            DATA_STORMS,
            {
                STORM_AT: now,
                STORM_ENTRY: entry_id,
                STORM_DOMAIN: domain,
                STORM_DEVICES: 0,
                STORM_DURATION: None,
            },
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
            "muting disabled for it, its devices learn "
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
        indistinguishable from a hub reconnecting, and muting it
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

    def _fold_storm_days(self, day: str) -> None:
        """Write the day's storm tally, one row per domain (#320).

        Count, median seconds between storms, median device count,
        median duration, kept on the retention setting. This is the
        record the raw one-hour rows cannot be, and the brief's
        flood sentence (ruling #321) is its reader.
        """
        for domain, storms in sorted(self._storm_day.items()):
            if not storms:
                continue
            times = sorted(at for at, _devices, _duration in storms)
            # Offset by one on purpose (ruling #328): the pairing is
            # each time with the next, so the shorter tail ends it.
            gaps = [
                later - earlier
                for earlier, later in zip(times, times[1:], strict=False)
            ]
            self._append_row(
                DATA_STORM_DAYS,
                {
                    STORM_DAY_DATE: day,
                    STORM_DAY_DOMAIN: domain,
                    STORM_DAY_COUNT: len(storms),
                    STORM_DAY_INTERVAL: round(_median(gaps), 1)
                    if gaps
                    else None,
                    STORM_DAY_DEVICES: round(
                        _median(
                            [devices for _at, devices, _d in storms]
                        ),
                        1,
                    ),
                    STORM_DAY_DURATION: round(
                        _median(
                            [duration for _at, _dev, duration in storms]
                        ),
                        1,
                    ),
                },
            )
            self._dirty = True
        self._storm_day.clear()
        keep = self.retention_days * 12
        rows = self.data.setdefault(DATA_STORM_DAYS, [])
        del rows[:-keep]

    def _storm_explained(self, start: float) -> bool:
        """Return whether a storm that began at `start` has a cause.

        Read from the system events log, which already holds every
        outage, maintenance window and restart with its time. A storm
        is explained when, at its start, an upstream outage or a
        maintenance window was open, or one had closed or Home
        Assistant had restarted within STORM_EXPLAINED_SECONDS. Each
        opener is paired with its own closer by kind and scope, so a
        bridge that came back does not close a broker outage that is
        still open (ruling #457).
        """
        opens = {
            SYS_BRIDGE_DOWN: SYS_BRIDGE_UP,
            SYS_BROKER_DOWN: SYS_BROKER_UP,
            SYS_INTEGRATION_DOWN: SYS_INTEGRATION_UP,
            SYS_WIFI_DOWN: SYS_WIFI_UP,
            SYS_MAINTENANCE_OPEN: SYS_MAINTENANCE_CLOSED,
        }
        closes = {closer: opener for opener, closer in opens.items()}
        open_now: dict[tuple[str, Any, Any], bool] = {}
        for row in self.data.get(DATA_SYSTEM_EVENTS) or []:
            if not isinstance(row, dict):
                continue
            when = row.get(SYS_WHEN)
            if not isinstance(when, (int, float)) or when > start:
                continue
            kind = row.get(SYS_KIND)
            scope = row.get(SYS_SCOPE)
            entry = pair_key(kind, scope, row.get(SYS_DETAIL))[2]
            if kind in opens:
                open_now[(kind, scope, entry)] = True
            elif kind in closes:
                open_now[(closes[kind], scope, entry)] = False
                if start - when <= STORM_EXPLAINED_SECONDS:
                    return True
            elif kind == SYS_RESTART and start - when <= STORM_EXPLAINED_SECONDS:
                return True
        return any(open_now.values())

    def _end_storm(
        self, entry_id: str, storm: dict[str, Any], now: float
    ) -> None:
        """Close a storm, on the series and in the events log."""
        domain = self._entry_domain(entry_id)
        duration = (
            storm["last_met"] - storm["start"] + STORM_RELEASE_SECONDS
        )
        announce = storm.get("announce", storm.get("recorded", True))
        if storm.get("recorded", True):
            self._close_storm_row(
                entry_id, now, duration, len(storm["devices"])
            )
            # The day's tally (ruling #320): raw rows keep one hour
            # for the polling verdict, so the daily record is
            # accumulated here and folded at midnight. Memory only:
            # a restart loses the pre-restart part of one day's
            # tally, and the reference fleet's nightly restart runs
            # after the fold, so an ordinary day is complete.
            # Only a storm nothing explains is tallied: one inside an
            # outage, a maintenance window or a restart is the house
            # recovering, and the tally is what the noisy-integration
            # advice reads (ruling #457). The raw row above is kept
            # either way, since the polling verdict needs every burst.
            if not self._storm_explained(storm["start"]):
                self._storm_day.setdefault(
                    self._entry_domain(entry_id), []
                ).append((now, len(storm["devices"]), duration))
        if announce:
            self._record_system_event(
                SYS_STORM_CLOSED,
                scope=domain,
                duration=duration,
                devices=len(storm["devices"]),
            )
        # The fourth surface a poller is silent on. #232 named three,
        # the opening event, the closing event and the episode stamp,
        # and this line was gated on the count instead, so an
        # integration ruled exempt went on announcing itself about a
        # hundred times an hour in a log a person reads. An
        # integration whose bursts are its own polling cadence is
        # behaving normally, and normal behaviour is not information.
        # The wording is corrected with it: nothing is muted from
        # learning by a storm and nothing has been since taint became
        # the only surviving muting (rulings #124 and #125), so the
        # count is named for what it is, the reports seen inside the
        # burst.
        if announce and storm["stamps"]:
            LOGGER.debug(
                "Storm on %s ended: %d devices, %d report(s) inside the "
                "burst, %.1f s duration",
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
        # After the rebuild, so the awaiting-enable counts are taken
        # against the registry view this close has just corrected
        # rather than the one the startup window left behind.
        self._evaluate_repairs(REPAIR_MOMENT_GRACE)
        # Batteries held during the window (ruling #346) are judged
        # now rather than at their next state change, which for a
        # battery can be hours away. A cell that read low through
        # the whole window is genuinely low and flags here.
        self._evaluate_all_batteries()
        if self._restored_from is not None:
            # The restore happened inside setup, before the notify
            # platform and the messenger existed, so the notice waits
            # for the window to shut rather than failing silently on a
            # cold boot (ruling #345). The restore is already done; a
            # report five minutes later is still true.
            self.hass.async_create_task(self._announce_restore())
        LOGGER.debug(
            # Same correction as the storm line: the grace window
            # mutes nothing from learning and has not since taint
            # became the only surviving muting (rulings #124 and
            # #125). The count is the reports that arrived inside the
            # window, which is worth one line at every start.
            "Startup grace closed after %d s: %d report(s) across %d "
            "device(s) inside the window; %d boot-blip taints "
            "aggregated",
            STARTUP_GRACE_SECONDS,
            self._grace_stamps,
            len(self._grace_devices),
            len(self._grace_taints),
        )
