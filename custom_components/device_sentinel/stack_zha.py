# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zha.py, Version: 0.19.0 (2026-08-28)

"""ZHA: everything Device Sentinel knows about this stack.

One file per coordinator stack (ruling #218), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection, and since 0.19.0 a coordinator reader,
built on measurement rather than documentation (ruling #358). Two
deliberate coordinator pulls on 28 August 2026, watched at
thirty-second resolution on a live ZHA at Home Assistant 2026.8.3:

1. Within 35 to 60 seconds of the radio losing power, ZHA's config
   entry leaves the loaded state and its entity roster empties. The
   entry is the signal; ZHA publishes no liveness of its own, and
   the coordinator device carries no entities to watch, which is why
   a dead coordinator was reported as its children's problems before
   this reader existed.
2. Recovery is whole or nothing, four to six minutes from power,
   with no window where entities existed and read unavailable.
3. A routine reload, by contrast, takes every entity unavailable for
   nine seconds and returns, and a thirty-second poll missed it
   entirely. That is why this reader is never polled on a schedule,
   and why it holds a dwell before it will say down.

WHAT IS NOT BUILT. Pairing. `pairing_open` is always False here, so
a ZHA house falls to the per-device debounce for interventions
exactly as it did before (ruling #138). Pairing is expected to be
observable through the `zha.permit` service call, but expected is
not measured, and a pairing window claimed wrongly discards real
silences (rulings #142, #218).

WHAT IS UNPROVEN, AND SHIPS SAYING SO. The dwell of sixty seconds
comes from one radio, one fleet of two devices, and two outage runs.
On that fleet every coordinator failure is total, so the case this
cannot have tested is a partial mesh failure: a branch of a large
network dying while the coordinator lives. Tim Plas's 234 device
fleet is where that gets measured, and the number moves if his
numbers say so.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    LOGGER,
    STACK_ZHA,
    ZHA_DOWN_DWELL_SECONDS,
)

STACK = STACK_ZHA


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is ZHA's.

    ZHA owns its own domain outright, which is the simple case: the
    stack's name and the integration domain are the same string, so
    ownership and presence ask the same question.
    """
    return domain == STACK_ZHA


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves ZHA is running.

    The domain is the tell (rulings #139 and #143), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def device_key(device: dr.DeviceEntry) -> None:
    """Return None: this stack's device identifiers are unverified.

    Z2M answers this with the IEEE address out of its identifier, and
    ZHA very likely carries something equivalent. Very likely is
    not measured, and a join key guessed wrong joins a verdict to the
    wrong device, so nothing is claimed here until somebody with the
    hardware sends a real identifier (rulings #218 and #219).
    """
    return None


class ZhaCoordinatorReader:
    """Read ZHA's liveness from its config entry, on demand.

    No subscription, no timer, no network call: the entry state is an
    in-process read of what Home Assistant already knows, so a
    healthy fleet costs nothing at all, and a dead one costs one
    dictionary lookup per sample.

    The dwell is the whole subtlety. A reload drops the entry for
    nine seconds and a dead radio drops it for as long as the radio
    is dead, so the first sighting of an unloaded entry is evidence
    of nothing: the reader remembers when it first saw it and keeps
    saying running until the dwell has passed (ruling #358). A reload
    therefore never reaches the reporting layer, and an outage
    reaches it about a minute in, well inside the four to six minutes
    ZHA takes to come back.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the hass reference; nothing is read until asked."""
        self._hass = hass
        self._first_down_at: float | None = None
        self._last_heard: str | None = None

    async def async_start(self) -> bool:
        """Take a first reading, so the sensor has something to say.

        Returns True the way the Z2M reader does. There is nothing
        here that can fail to start: with no ZHA entry the state
        simply reads unknown.
        """
        self._sample()
        return True

    def async_stop(self) -> None:
        """Nothing to unsubscribe: nothing was subscribed."""
        return None

    @property
    def stack(self) -> str:
        """Return the stack this reader speaks for."""
        return STACK_ZHA

    @property
    def last_heard(self) -> str | None:
        """Return when the entry was last seen loaded, if ever."""
        return self._last_heard

    @property
    def pairing_open(self) -> bool:
        """Return False: pairing is not read on this stack yet.

        Deliberately a constant rather than a guess. The detector
        reads this to decide whether to discard a silence, and a
        window claimed wrongly discards a real one (rulings #142,
        #147).
        """
        return False

    def pairing_active_within(
        self, grace_seconds: float, now: float
    ) -> bool:
        """Return False: no pairing window is observed on this stack."""
        return False

    @property
    def state(self) -> str:
        """Return the coordinator state a person would read.

        Unknown when no ZHA entry exists at all, which is a house
        without ZHA rather than a fault. Running while the entry is
        loaded, and while it is unloaded but still inside the dwell.
        Down only once the entry has been unloaded for longer than a
        reload takes.
        """
        return self._sample()

    def _entry_loaded(self) -> bool | None:
        """Return whether ZHA's entry is loaded, or None if absent."""
        try:
            entries = self._hass.config_entries.async_entries(STACK_ZHA)
        except Exception as err:  # noqa: BLE001 - a fault reads unknown
            LOGGER.debug("ZHA entry could not be read: %s", err)
            return None
        if not entries:
            return None
        # Any loaded entry means ZHA is up. More than one entry is a
        # multi-radio house, and one live radio is not an outage.
        return any(
            entry.state is ConfigEntryState.LOADED for entry in entries
        )

    def _sample(self) -> str:
        """Read the entry now, holding the dwell across readings."""
        loaded = self._entry_loaded()
        now = dt_util.utcnow().timestamp()
        if loaded is None:
            self._first_down_at = None
            return BRIDGE_UNKNOWN
        if loaded:
            self._first_down_at = None
            self._last_heard = dt_util.utcnow().isoformat()
            return BRIDGE_RUNNING
        if self._first_down_at is None:
            self._first_down_at = now
            return BRIDGE_RUNNING
        if now - self._first_down_at < ZHA_DOWN_DWELL_SECONDS:
            return BRIDGE_RUNNING
        return BRIDGE_DOWN

    @property
    def down_for(self) -> float | None:
        """Return how long the entry has been unloaded, for the sensor."""
        if self._first_down_at is None:
            return None
        return dt_util.utcnow().timestamp() - self._first_down_at


def make_reader(hass: HomeAssistant) -> Any:
    """Return the coordinator reader for ZHA.

    Built since 0.19.0. It costs nothing on a house without ZHA:
    with no entry to read its state is unknown, and the sampler
    skips an unknown reading exactly as it skips a stack that has no
    reader at all.
    """
    return ZhaCoordinatorReader(hass)
