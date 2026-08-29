# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zha.py, Version: 0.19.2 (2026-08-28)

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    LOGGER,
    STACK_ZHA,
    ZHA_DOWN_DWELL_SECONDS,
    ZHA_GATEWAY_SIGNAL,
    ZHA_HANDLED_TAIL_SECONDS,
    ZHA_JOIN_MESSAGES,
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

    @property
    def down_since(self) -> float | None:
        """Return when the entry actually went down, not when we were
        sure of it (ruling #359).

        The dwell means this reader says down about a minute after
        the radio dies, and the suppression rule reads a device that
        fell before its upstream as a device that was already broken.
        On the reference rig on 28 August that made every ZHA device
        keep its own problem row during a real coordinator outage,
        which is the noise the upstream row exists to end. The outage
        began when the entry stopped being loaded; the dwell is how
        long this reader waits before believing it, and a wait is not
        a start time.

        None while the entry is loaded, and None on a stack whose
        reader cannot say, in which case the caller stamps the
        moment it noticed, exactly as before.
        """
        return self._first_down_at


class ZhaJoinObserver:
    """Report that a person handled a device, from what ZHA says.

    The question is #145's, and ZHA answers it at the moment of
    recovery: when a device comes back, did somebody cause it? A
    silence ended by a person measures the hand rather than the
    device, and its gap must not teach the device's rhythm.

    Z2M answers this by publishing a pairing window. ZHA keeps no
    window state anywhere: zigpy's permit broadcasts and returns,
    and the frontend's Add Device sends a websocket command that
    reaches no event bus. What ZHA does announce, on the
    `zha_gateway_message` dispatcher signal, is the device itself.

    Measured on 29 August 2026 with a throwaway probe, because a
    dispatcher signal is in process and nothing outside can see it:
    a re-pair fires `device_joined` then `device_fully_initialized`
    twice; a reconfigure fires `raw_device_initialized` then the
    full init; a removal fires `device_removed`; a battery swap and
    an ordinary recovery fire nothing at all.

    Three measured facts make this usable. The message always
    precedes the recovery, by two to eight seconds across eighteen
    observed recoveries, so nothing needs correlating backwards. The
    full init carries `device_reg_id`, the registry id this
    integration already files records under, so there is no matching
    to get wrong. And a restart does not produce these for the
    fleet, so no startup guard is needed; a restart that does carry
    one is carrying a real join.

    What it deliberately does not do: claim a pairing window.
    `pairing_open` stays False on this stack. The window is
    unobservable, and the log relay that hints at it started and
    stopped 27 times in an hour of ordinary clicking.

    Everything is guarded. A house without ZHA never constructs it,
    a dispatcher that refuses the connection leaves the integration
    untouched, and a message that cannot be understood is named as
    such rather than parsed hopefully.
    """

    def __init__(self, hass: HomeAssistant, record: Any = None) -> None:
        """Hold the hass reference and the callback that records.

        The callback takes a device registry id and a message kind,
        and is what turns an observation into a fact the reports can
        use. None leaves this an observer, which is what a test uses
        to watch it without a coordinator behind it.
        """
        self._hass = hass
        self._record = record
        self._unsubscribe: Any = None
        self.seen: int = 0
        # Registry id -> when that device was last handled.
        self.handled: dict[str, float] = {}

    def async_start(self) -> bool:
        """Subscribe to the gateway signal. False if it could not."""
        if self._unsubscribe is not None:
            return True
        try:
            self._unsubscribe = async_dispatcher_connect(
                self._hass, ZHA_GATEWAY_SIGNAL, self._on_message
            )
        except Exception as err:  # noqa: BLE001 - an instrument never breaks setup
            LOGGER.warning(
                "ZHA join observer could not subscribe to %s: %s",
                ZHA_GATEWAY_SIGNAL,
                err,
            )
            return False
        LOGGER.info(
            "ZHA join observer listening on %s; joins will be logged "
            "and nothing else",
            ZHA_GATEWAY_SIGNAL,
        )
        return True

    def async_stop(self) -> None:
        """Unsubscribe, so a reload leaves nothing behind."""
        if self._unsubscribe is None:
            return
        try:
            self._unsubscribe()
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("ZHA join observer unsubscribe failed: %s", err)
        self._unsubscribe = None

    def handled_since(self, device_id: str, now: float) -> float | None:
        """Return when a person last handled this device, if lately.

        None when nobody has touched it inside the tail, which is
        the ordinary answer for every device on a quiet fleet, and
        the answer every other stack gives always.
        """
        when = self.handled.get(device_id)
        if when is None:
            return None
        if now - when > ZHA_HANDLED_TAIL_SECONDS:
            return None
        return when

    def forget(self, device_id: str) -> None:
        """Drop a device's tag once its recovery has used it."""
        self.handled.pop(device_id, None)

    @callback
    def _on_message(self, message: Any) -> None:
        """Record one handling, and log it."""
        if not isinstance(message, dict):
            LOGGER.info(
                "ZHA gateway message in an unexpected shape (%s); "
                "logged and ignored",
                type(message).__name__,
            )
            return
        kind = message.get("type")
        if not isinstance(kind, str):
            # A message type that is not a string. Found by the
            # adversarial round with a list, which crashed the
            # membership test outright: an unhashable value cannot be
            # looked up in a set, and the exception would have
            # travelled back into whatever dispatched the message,
            # which is ZHA. An instrument that can break the thing it
            # watches is worse than no instrument (ruling #360).
            LOGGER.info(
                "ZHA gateway message with a %s type; logged and "
                "ignored",
                type(kind).__name__,
            )
            return
        if kind not in ZHA_JOIN_MESSAGES:
            # Groups, logs and the rest. Counted by silence: this
            # instrument is about joins and says nothing else, so a
            # busy network does not fill the log.
            return
        self.seen += 1
        info = message.get("device_info")
        if not isinstance(info, dict):
            # `raw_device_initialized` carries its fields at the top
            # level rather than under device_info, measured 29
            # August. Both shapes are read rather than one assumed.
            info = message
        registry_id = info.get("device_reg_id")
        LOGGER.info(
            "ZHA says a device was handled (%s): ieee=%s reg=%s "
            "status=%s name=%s",
            kind,
            info.get("ieee"),
            registry_id,
            info.get("pairing_status"),
            info.get("user_given_name") or info.get("name"),
        )
        if not isinstance(registry_id, str) or not registry_id:
            # `device_joined` and `raw_device_initialized` carry the
            # ieee and no registry id; the full init that follows
            # carries both, and it is what the recording waits for.
            # A device this integration cannot name is one it cannot
            # file, and mapping an ieee to a device by guesswork
            # would attach a person's action to the wrong record.
            return
        self.handled[registry_id] = dt_util.utcnow().timestamp()
        if self._record is not None:
            self._record(registry_id, kind)


def make_join_observer(hass: HomeAssistant, record: Any = None) -> Any:
    """Return the join observer for ZHA."""
    return ZhaJoinObserver(hass, record)


def make_reader(hass: HomeAssistant) -> Any:
    """Return the coordinator reader for ZHA.

    Built since 0.19.0. It costs nothing on a house without ZHA:
    with no entry to read its state is unknown, and the sampler
    skips an unknown reading exactly as it skips a stack that has no
    reader at all.
    """
    return ZhaCoordinatorReader(hass)
