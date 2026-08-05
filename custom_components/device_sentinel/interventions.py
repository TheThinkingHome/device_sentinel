# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: interventions.py, Version: 0.12.1 (2026-08-05)

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

from .const import (
    BRIDGE_DOWN,
    BRIDGE_UNKNOWN,
    EPISODE_ENDED_RECONNECT,
    EPISODE_ENDED_RESTART,
    LOGGER,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_HISTORY_SECONDS,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
)


class InterventionMixin:
    """Interventions: bridge state, pairing windows, and storms."""

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
        """
        now = dt_util.utcnow().timestamp()
        for stack, reader in self._bridge_readers.items():
            sample = self._read_bridge(stack, reader)
            if sample is None:
                continue
            state, pairing = sample
            if state == BRIDGE_UNKNOWN:
                continue
            was = self._bridge_seen.get(stack)
            self._bridge_seen[stack] = state
            if was is not None and was != state:
                if state == BRIDGE_DOWN:
                    self._bridge_down_at[stack] = now
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
        if entry_id is None or entry_id in self._storm_exempt:
            return None
        queue = self._storm_feed_q.setdefault(entry_id, deque())
        queue.append((now, device_id))
        cutoff = now - STORM_WINDOW_SECONDS
        while queue and queue[0][0] < cutoff:
            queue.popleft()
        distinct = len({dev for _, dev in queue})

        storm = self._storm_active.get(entry_id)
        if distinct >= STORM_DEVICE_THRESHOLD:
            if storm is None:
                history = self._storm_history.setdefault(entry_id, deque())
                history.append(now)
                cutoff_h = now - STORM_HISTORY_SECONDS
                while history and history[0] < cutoff_h:
                    history.popleft()
                if len(history) >= STORM_EXEMPT_PER_HOUR:
                    self._storm_exempt.add(entry_id)
                    self._storm_feed_q.pop(entry_id, None)
                    entry = self.hass.config_entries.async_get_entry(
                        entry_id
                    )
                    LOGGER.debug(
                        "Integration %s reclassified as synchronized "
                        "polling (%d storms inside an hour); storm "
                        "exclusion disabled for it, its devices learn "
                        "their poll cadence as rhythm",
                        entry.domain if entry else entry_id,
                        len(history),
                    )
                    return None
                storm = {
                    "start": now,
                    "last_met": now,
                    "stamps": 0,
                    "devices": set(),
                }
                self._storm_active[entry_id] = storm
                # A storm is a radio-level event, most often a bridge
                # or hub reconnecting: it can revive a wedged device,
                # so any silence running now is truncated, not
                # completed, exactly as a reboot truncates one. Inside
                # startup grace the storm is the restart itself, and
                # is named as such: the brief quotes this cause, and
                # crediting a reconnect for a restart's work would
                # mislead the recovery ladder later.
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

    def _end_storm(
        self, entry_id: str, storm: dict[str, Any], now: float
    ) -> None:
        """Close a storm and log its full accounting."""
        if storm["stamps"]:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            domain = entry.domain if entry else entry_id
            LOGGER.debug(
                "Storm on %s ended: %d devices, %d stamps excluded from "
                "learning, %.1f s duration",
                domain,
                len(storm["devices"]),
                storm["stamps"],
                storm["last_met"] - storm["start"] + STORM_RELEASE_SECONDS,
            )
        self._storm_active.pop(entry_id, None)

    def _sweep_storms(self, now: float) -> None:
        """Close storms whose feed has gone quiet."""
        for entry_id, storm in list(self._storm_active.items()):
            if now - storm["last_met"] > STORM_RELEASE_SECONDS:
                self._end_storm(entry_id, storm, now)

    @callback
    def _on_grace_closed(self, _now: Any) -> None:
        """Log the startup grace summary."""
        LOGGER.debug(
            "Startup grace closed after %d s: %d stamps across %d devices "
            "excluded from learning; %d boot-blip taints aggregated",
            STARTUP_GRACE_SECONDS,
            self._grace_stamps,
            len(self._grace_devices),
            len(self._grace_taints),
        )
