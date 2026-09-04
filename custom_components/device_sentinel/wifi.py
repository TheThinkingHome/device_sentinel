# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: wifi.py, Version: 0.20.4 (2026-09-04)

"""The Wi-Fi outage: a capability, deliberately not a stack.

Every stack reader watches a thing that reports its own liveness: a
bridge topic, a broker heartbeat, a config entry. Wi-Fi has none, and
whether it can be seen at all depends on which router integration a
house happens to run. Most run none. So where router trackers on
watched devices exist, the outage is detectable; where they do not,
this feature does not exist for that house and costs it nothing: no
subscription, no sensor, no rung.

The trigger is trackers because trackers are the portable signal:
`device_tracker` entities with `source_type: router` are the common
contract across router integrations, where every client-count sensor
is one product's private spelling. Trackers also lead: on the
measured outage the router reported nine watched trackers not_home
inside sixty seconds while the slowest integration took four minutes
to notice, so the outage is declared before most of the devices
behind it know, and their unavailability arrives already explained.

The tie ladder binds a tracker to the watched device it shadows,
because on a real fleet they are separate registry devices. Two rungs,
both deterministic, neither a name: a normalized MAC shared between
the tracker and the device's registry connections, then the tracker's
full twelve-hex MAC embedded in one of the device's identifiers (the
shape NSPanel-class devices actually have). Names are ruled out
because people rename devices to be descriptive, and a wrong tie
suppresses an innocent device's verdicts, which is the one direction
this feature must never fail in. Devices no rung can claim wait for
the picker, honestly unclaimed until then.

Trigger and hold as ruled: three or more tied trackers not_home
inside a sliding sixty-second window starts a sixty-second hold; at
its end the outage is declared only if three or more are still gone,
dated from the first fall of the burst. A flap clears inside the hold
and nothing is said. Entity confirmation, how many claimed devices
already read unavailable at declaration, rides in the event and the
log as evidence and is never a gate, because a fleet whose Wi-Fi
devices all notice slowly would fail a confirmation gate during a
real outage.

Known limitations, recorded rather than hidden: a restart during an
outage stays silent, because restored trackers produce no fresh
not_home transitions to count; and an access point that keeps
broadcasting while its backhaul fails leaves stations associated and
trackers reading home, a fault this detector cannot see.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    LOGGER,
    SYS_WIFI_DOWN,
    SYS_WIFI_UP,
    UPSTREAM_WIFI,
    WIFI_BURST_FLOOR,
    WIFI_BURST_WINDOW_SECONDS,
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)

STATE_NOT_HOME = "not_home"
STATE_HOME = "home"
_HEX_ONLY = re.compile(r"[^0-9a-f]")


def normalize_mac(value: Any) -> str | None:
    """Reduce any MAC spelling to twelve lowercase hex characters.

    Routers report dashes and upper case, the registry stores colons
    and lower case, and identifiers embed the bare hex. One canonical
    form makes every rung an exact comparison rather than a fuzzy
    one.
    """
    if not isinstance(value, str):
        return None
    stripped = _HEX_ONLY.sub("", value.lower())
    return stripped if len(stripped) == 12 else None


class WifiMixin:
    """The Wi-Fi outage watcher, mixed into the coordinator.

    State lives on the coordinator (initialized beside the other
    upstream state): the tie maps, the burst window, the hold, and
    the declared outage. Nothing persists across a restart, which is
    the recorded restart-mid-outage limitation.
    """

    # ------------------------------------------------------------ ties

    def _rebuild_wifi_ties(self) -> None:
        """Resolve every watched device to its router tracker, or to
        nothing.

        Runs with the registry rebuild, so a tracker that appears, a
        device that gains a MAC, or a rename costs nothing and heals
        nothing by accident: both rungs are exact. The tie is stored
        as the tracker's entity id, per ruling: the discovery is the
        ladder, the keeping is the entity.
        """
        registry = er.async_get(self.hass)
        devices = dr.async_get(self.hass)

        # Every router tracker's MAC, from its state attribute first
        # (the router's own report), then from its registry device's
        # connections.
        tracker_by_mac: dict[str, str] = {}
        for entry in registry.entities.values():
            if entry.domain != "device_tracker" or entry.disabled_by:
                continue
            state = self.hass.states.get(entry.entity_id)
            if state is None or state.attributes.get("source_type") != "router":
                continue
            mac = normalize_mac(state.attributes.get("mac"))
            if mac is None and entry.device_id:
                owner = devices.async_get(entry.device_id)
                if owner is not None:
                    for kind, value in owner.connections:
                        if kind == dr.CONNECTION_NETWORK_MAC:
                            mac = normalize_mac(value)
                            break
            if mac is not None and mac not in tracker_by_mac:
                tracker_by_mac[mac] = entry.entity_id

        ties: dict[str, str] = {}
        for device_id in self._watched:
            device = devices.async_get(device_id)
            if device is None:
                continue
            tracker = None
            # Rung 1: a normalized MAC in the device's connections.
            for kind, value in device.connections:
                if kind != dr.CONNECTION_NETWORK_MAC:
                    continue
                tracker = tracker_by_mac.get(normalize_mac(value) or "")
                if tracker:
                    break
            # Rung 2: the full twelve-hex MAC inside an identifier.
            if tracker is None:
                for _domain, ident in device.identifiers:
                    bare = _HEX_ONLY.sub("", str(ident).lower())
                    for mac, entity_id in tracker_by_mac.items():
                        if mac in bare:
                            tracker = entity_id
                            break
                    if tracker:
                        break
            if tracker is not None:
                ties[device_id] = tracker

        changed = ties != self._wifi_ties
        self._wifi_ties = ties
        self._wifi_device_of = {t: d for d, t in ties.items()}
        # The boot-order retry gate. On a real boot the tracker
        # registry entries exist before the router integration has
        # polled, so their states are absent and the ladder ties
        # nothing; the create-once surfaces then read the house as
        # incapable forever. While ties are empty and any tracker
        # entry is still stateless, information is still arriving
        # and the tick retries the ladder. The condition is
        # terminal both ways: ties appearing ends it, and every
        # tracker having a state ends it, so a house of phone
        # trackers stops after its first look and a house with no
        # trackers never starts.
        self._wifi_retry_pending = not ties and any(
            entry.domain == "device_tracker"
            and not entry.disabled_by
            and self.hass.states.get(entry.entity_id) is None
            for entry in registry.entities.values()
        )
        if changed:
            LOGGER.info(
                "device_sentinel: wifi ties rebuilt, %d watched "
                "device(s) tied to a router tracker",
                len(ties),
            )
            self._resubscribe_wifi_trackers()

    def _resubscribe_wifi_trackers(self) -> None:
        """Listen to exactly the tied tracker set, and nothing else."""
        if self._wifi_unsub is not None:
            self._wifi_unsub()
            self._wifi_unsub = None
        # Ties that dissolved take their standing state with them.
        self._wifi_not_home = {
            entity_id: since
            for entity_id, since in self._wifi_not_home.items()
            if entity_id in self._wifi_device_of
        }
        if not self._wifi_ties:
            return
        self._wifi_unsub = async_track_state_change_event(
            self.hass,
            sorted(self._wifi_device_of),
            self._on_wifi_tracker_change,
        )

    @property
    def wifi_capable(self) -> bool:
        """Whether this house can see a Wi-Fi outage at all."""
        return bool(self._wifi_ties)

    # --------------------------------------------------------- listener

    @callback
    def _on_wifi_tracker_change(self, event: Event) -> None:
        """Count a tied tracker leaving, and forget one returning.

        Only a home to not_home transition feeds the burst: a tracker
        going unavailable is the router integration failing, not a
        station leaving, and counting it would let a router reload
        declare a network outage. During the startup grace nothing is
        counted, because Home Assistant restoring tracker states is
        exactly the outage's shape in miniature (the fully_kiosk
        lesson: 31 entities through unavailable and back in one
        second, with the startup tag the only thing separating them).
        """
        new_state = event.data.get("new_state")
        entity_id = event.data.get("entity_id")
        if new_state is None or entity_id not in self._wifi_device_of:
            return
        if new_state.state == STATE_NOT_HOME:
            if self._in_startup_grace():
                return
            old_state = event.data.get("old_state")
            if old_state is None or old_state.state != STATE_HOME:
                return
            now = dt_util.utcnow().timestamp()
            self._wifi_not_home.setdefault(entity_id, now)
            self._wifi_burst.append(now)
            self._prune_wifi_burst(now)
            if (
                self._wifi_down_at is None
                and self._wifi_hold_since is None
                and len(self._wifi_burst) >= WIFI_BURST_FLOOR
            ):
                self._wifi_hold_since = now
                self._wifi_first_fall = self._wifi_burst[0]
                LOGGER.info(
                    "device_sentinel: wifi burst, %d tied tracker(s) "
                    "not_home inside %ds, holding %ds before any "
                    "verdict",
                    len(self._wifi_burst),
                    int(WIFI_BURST_WINDOW_SECONDS),
                    int(WIFI_HOLD_SECONDS),
                )
        else:
            # home, unavailable, unknown: however it left not_home,
            # it no longer counts toward the floor and its device is
            # no longer claimed.
            self._wifi_not_home.pop(entity_id, None)

    def _prune_wifi_burst(self, now: float) -> None:
        """Keep only transitions inside the sliding window."""
        cutoff = now - WIFI_BURST_WINDOW_SECONDS
        self._wifi_burst = [t for t in self._wifi_burst if t > cutoff]

    # ---------------------------------------------------------- sampler

    @callback
    def _sample_wifi(self, now: float) -> None:
        """Judge the hold and the recovery on the tick.

        Tick-driven like every other upstream judgment: one sweep is
        simpler than timers to cancel and re-arm, and a hold that
        ends within a minute of its deadline is immaterial against an
        outage measured in minutes.
        """

        if self._wifi_retry_pending:
            self._rebuild_wifi_ties()
        if not self._wifi_ties:
            return
        if self._wifi_down_at is not None:
            if len(self._wifi_not_home) < WIFI_BURST_FLOOR:
                self._wifi_restore(now)
            return
        if self._wifi_hold_since is None:
            return
        if now - self._wifi_hold_since < WIFI_HOLD_SECONDS:
            return
        still_gone = len(self._wifi_not_home)
        if still_gone >= WIFI_BURST_FLOOR:
            self._wifi_declare(now, still_gone)
        else:
            LOGGER.info(
                "device_sentinel: wifi flap cleared inside the hold "
                "(%d tracker(s) still not_home), nothing reported",
                still_gone,
            )
            self._wifi_hold_since = None
            self._wifi_first_fall = None
            self._wifi_burst = []

    def _wifi_declare(self, now: float, still_gone: int) -> None:
        """Declare the outage, dated from the first fall."""
        since = self._wifi_first_fall or self._wifi_hold_since or now
        self._wifi_down_at = since
        self._wifi_hold_since = None
        confirmed = self._wifi_confirmed_count()
        LOGGER.info(
            "device_sentinel: wifi outage declared, %d tied "
            "tracker(s) not_home, %d claimed device(s) already "
            "unavailable at declaration",
            still_gone,
            confirmed,
        )
        self._record_system_event(
            SYS_WIFI_DOWN, scope=WIFI_KEY, devices=len(self._wifi_ties)
        )
        self._say_upstream_down(
            UPSTREAM_WIFI, WIFI_KEY, None, since, len(self._wifi_ties),
            confirmed=confirmed,
        )

    def _wifi_restore(self, now: float) -> None:
        """Close the outage once fewer than the floor remain gone."""
        since = self._wifi_down_at
        self._wifi_down_at = None
        self._wifi_first_fall = None
        self._wifi_burst = []
        LOGGER.info(
            "device_sentinel: wifi outage over after %.0fs",
            max(0.0, now - (since or now)),
        )
        self._record_system_event(
            SYS_WIFI_UP,
            scope=WIFI_KEY,
            duration=now - since if since is not None else None,
            devices=len(self._wifi_ties),
        )
        self._say_upstream_restored(
            UPSTREAM_WIFI, WIFI_KEY, None, since, now, len(self._wifi_ties)
        )

    def _wifi_confirmed_count(self) -> int:
        """How many claimed devices already read unavailable.

        Evidence, never a gate (ruled 4 September): a real outage on
        a fleet of slow integrations would show zero here at
        declaration and still be real. Recorded because it separates
        a network outage from a tracker-side artifact after the fact.
        """
        claimed = {
            device_id
            for device_id, tracker in self._wifi_ties.items()
            if tracker in self._wifi_not_home
        }
        if not claimed:
            return 0
        confirmed: set[str] = set()
        for entity_id, mapped in self._entity_map.items():
            device_id = mapped[0] if isinstance(mapped, tuple) else mapped
            if device_id not in claimed or device_id in confirmed:
                continue
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == STATE_UNAVAILABLE:
                confirmed.add(device_id)
        return len(confirmed)

    # ---------------------------------------------------------- readers

    def wifi_down_since(self, device_id: str) -> tuple[str, float] | None:
        """Return the Wi-Fi outage claiming this device, if any.

        A device is claimed only while its own tracker reads
        not_home: the outage explains what the router saw leave, and
        nothing else. A tied device whose tracker still reads home
        during a declared outage is reported on its own, which is
        what it deserves.
        """
        since = self._wifi_down_at
        if since is None:
            return None
        tracker = self._wifi_ties.get(device_id)
        if tracker is None or tracker not in self._wifi_not_home:
            return None
        return WIFI_KEY, since

    @property
    def wifi_down_at(self) -> float | None:
        """When the declared outage began, or None."""
        return self._wifi_down_at

    @property
    def wifi_diagnostics(self) -> dict[str, Any]:
        """The tie table and outage state, for a diagnostics download.

        Added after the day its absence cost a question a download
        should have answered: whether the ladder tied anything on a
        live system was unknowable without a template.
        """
        return {
            "ties": len(self._wifi_ties),
            "tied": dict(sorted(self._wifi_ties.items())),
            "trackers_not_home": len(self._wifi_not_home),
            "retry_pending": self._wifi_retry_pending,
            "down_since": (
                dt_util.utc_from_timestamp(self._wifi_down_at).isoformat()
                if self._wifi_down_at is not None
                else None
            ),
        }

    @property
    def wifi_attributes(self) -> dict[str, Any]:
        """What the Wi-Fi sensor publishes beside its state."""
        return {
            "tied_devices": len(self._wifi_ties),
            "trackers_not_home": len(self._wifi_not_home),
            "down_since": (
                dt_util.utc_from_timestamp(self._wifi_down_at).isoformat()
                if self._wifi_down_at is not None
                else None
            ),
        }
