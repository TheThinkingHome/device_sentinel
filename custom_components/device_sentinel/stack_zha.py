# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zha.py, Version: 0.27.10 (2026-10-27)

"""ZHA: everything Device Sentinel knows about this stack.

One file per coordinator stack (rule STACK-01), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection and a coordinator reader, built on
measurement rather than documentation (rule UP-03). Deliberate
coordinator pulls on a live ZHA, watched at thirty-second resolution,
showed:

1. Within 35 to 60 seconds of the radio losing power, ZHA's config
   entry leaves the loaded state and its entity roster empties. The
   entry is the signal; ZHA publishes no liveness of its own, and
   the coordinator device carries no entities to watch, so without
   this reader a dead coordinator reads as its children's problems.
2. Recovery is whole or nothing, four to six minutes from power,
   with no window where entities existed and read unavailable.
3. A routine reload, by contrast, takes every entity unavailable for
   nine seconds and returns, and a thirty-second poll misses it
   entirely. So this reader is never polled on a schedule, and it
   holds a dwell before it will say down.

WHAT IS NOT BUILT. A pairing window. `pairing_open` is always False
here: ZHA keeps no window state anywhere, and a pairing window
claimed wrongly discards real silences. What is built instead is the
join observer below: ZHA announces each device that joins or is
reconfigured, and that device's recovery is credited to a person's
hand (rule FRZ-17). Anything else falls to the per-device debounce.

WHAT IS UNPROVEN, AND SHIPS SAYING SO. The dwell of sixty seconds
comes from one radio, a few devices, and two outage runs, where every
coordinator failure was total. A partial mesh failure, a branch of a
large network dying while the coordinator lives, is not yet measured
(rule STACK-02).
"""

from __future__ import annotations

import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, callback
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
    ZHA_BEGUN_KEPT,
    ZHA_FULL_INIT,
    ZHA_GATEWAY_SIGNAL,
    ZHA_HANDLED_TAIL_SECONDS,
    ZHA_HANDLING_WINDOW_SECONDS,
    ZHA_INITIALIZED,
    ZHA_JOIN_MESSAGES,
    ZHA_JOINED,
    ZHA_LOG_OUTPUT,
    ZHA_PERMIT_DEFAULT_SECONDS,
    ZHA_PERMIT_LONGEST_SECONDS,
    ZHA_PERMIT_SERVICE,
    ZHA_RAW_INIT,
    ZHA_REPAIR,
)

STACK = STACK_ZHA

# Nothing but ZHA publishes on the zha domain.
SHARED_DOMAIN = False


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is ZHA's.

    ZHA owns its own domain outright, which is the simple case: the
    stack's name and the integration domain are the same string, so
    ownership and presence ask the same question.
    """
    return domain == STACK_ZHA


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves ZHA is running.

    The domain is the tell (rule STACK-01), so the device entry itself
    is not consulted. It stays in the signature because every stack
    module answers this question the same way and Z2M needs the device
    to find its bridge.
    """
    return owns_domain(domain)


def is_plumbing(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device is the stack itself, not hardware.

    No for ZHA. ZHA's coordinator carries no entities and is already
    set aside for that reason (rule WATCH-05).

    Every stack module answers this question so the walk can ask it
    without knowing which stacks exist (rule STACK-01). The signature
    matches the others; neither argument is consulted.
    """
    return False


def device_key(device: dr.DeviceEntry) -> None:
    """Return None: this stack's device identifiers are unverified.

    Z2M answers this with the IEEE address out of its identifier, and
    ZHA very likely carries something equivalent. Very likely is
    not measured, and a join key guessed wrong joins a verdict to the
    wrong device, so nothing is claimed here until somebody with the
    hardware sends a real identifier (rule STACK-02).
    """
    return None


class ZhaCoordinatorReader:
    """Read ZHA's liveness from its config entry, on demand.

    No subscription, no timer, no network call: the entry state is an
    in-process read of what Home Assistant already knows, so a
    healthy house costs nothing at all, and a dead one costs one
    dictionary lookup per sample.

    The dwell is the whole subtlety. A reload drops the entry for
    nine seconds and a dead radio drops it for as long as the radio
    is dead, so the first sighting of an unloaded entry is evidence
    of nothing: the reader remembers when it first saw it and keeps
    saying running until the dwell has passed (rule UP-03). A reload
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
        window claimed wrongly discards a real one (rule FRZ-17).
        """
        return False

    def pairing_active_within(
        self, grace_seconds: float, now: float
    ) -> bool:
        """Return False: no pairing window is observed on this stack.

        A window is not the only way a person's hand is recognized
        here. ZHA announces each device it re-pairs, reconfigures or
        removes, the coordinator records that device as handled, and
        the silence around it is discarded per device with no button
        pressed. Anything written for a reader should say that rather
        than sending them to Maintenance Mode for work ZHA already
        announces; Maintenance Mode covers what it does not, a
        battery pull or a power cycle.
        """
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

    @property
    def loaded(self) -> bool:
        """Whether ZHA's entry is loaded right now (rule UP-04).

        The state reads running through a reload's dwell, so it cannot
        say whether ZHA has actually come up since Home Assistant
        started; this can.
        """
        return self._entry_loaded() is True

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
        """Return when the entry actually went down, not when the reader
        was sure of it (rule UP-03).

        The dwell means this reader says down about a minute after
        the radio dies, and the suppression rule reads a device that
        fell before its upstream as a device that was already broken,
        so every ZHA device would keep its own problem row during a
        real coordinator outage. The outage began when the entry
        stopped being loaded; the dwell is how long this reader waits
        before believing it, and a wait is not a start time.

        None while the entry is loaded, and None on a stack whose
        reader cannot say, in which case the caller stamps the
        moment it noticed.
        """
        return self._first_down_at


class ZhaJoinObserver:
    """Report that a person handled a device, from what ZHA says.

    When a device comes back, did somebody cause it? A silence ended
    by a person measures the hand rather than the device, and its gap
    must not teach the device's rhythm (rule FRZ-15).

    Z2M answers this by publishing a pairing window. ZHA keeps no
    window state anywhere: zigpy's permit broadcasts and returns,
    and the frontend's Add Device sends a websocket command that
    reaches no event bus. What ZHA does announce, on the
    `zha_gateway_message` dispatcher signal, is the device itself.

    Measured with a probe, because a dispatcher signal is in process
    and nothing outside can see it: a re-pair fires `device_joined`
    then `device_fully_initialized` twice; a reconfigure fires
    `raw_device_initialized` then the full init; a removal fires
    `device_removed`; a battery swap and an ordinary recovery fire
    nothing at all.

    Three facts make this usable. The message always precedes the
    recovery, by two to eight seconds, so nothing needs correlating
    backwards. The full init carries `device_reg_id`, the registry id
    this integration already files records under, so there is no
    matching to get wrong. And a full init alone proves nothing: 9 to
    18 seconds after a restart, ZHA can send a full init for devices
    nobody touched, the device setting itself up again, and a device
    that changes its own network address sends a join and two full
    inits, exactly as a re-pair does.

    So a full init counts as handling only after one of two starts for
    the same address, within ZHA_HANDLING_WINDOW_SECONDS and until ZHA
    calls the device initialized: a raw init, which zigpy sends for a
    known device only when a person asks for it to be interviewed again
    (Reconfigure) or for a new one being paired; or a join while
    pairing is open. Pairing is read from what opening it leaves: the
    zha.permit action for its duration, and the log_output messages
    the Add Device page relays while it is open. A join with pairing
    closed, and a full init with no start, are logged and nothing else
    (rule FRZ-17).

    What it deliberately does not do: claim a pairing window for the
    dashboard. `pairing_open` stays False on this stack. The log relay
    that hints at it starts and stops dozens of times in an hour of
    ordinary clicking, which is too loose to show a person, though
    tight enough to tell a re-pair from a device moving on its own.

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
        # IEEE address -> when a person's handling of it began, on the
        # monotonic clock, so a clock change moves nothing (rule FRZ-17).
        self._begun: dict[str, float] = {}
        # The addresses whose handling began with a join: a re-pair,
        # told apart from a reconfigure, which begins with a raw init
        # (rule FRZ-05).
        self._joined: set[str] = set()
        # Until when pairing is open, on the same clock.
        self._pairing_until: float = -math.inf
        self._unsubscribe_permit: Any = None

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
        try:
            self._unsubscribe_permit = self._hass.bus.async_listen(
                EVENT_CALL_SERVICE, self._on_permit, event_filter=_is_permit
            )
        except Exception as err:  # noqa: BLE001 - an instrument never breaks setup
            LOGGER.debug("ZHA join observer could not watch zha.permit: %s", err)
        LOGGER.debug(
            "ZHA join observer listening on %s; joins will be logged "
            "and nothing else",
            ZHA_GATEWAY_SIGNAL,
        )
        return True

    @callback
    def _on_permit(self, event: Event) -> None:
        """Pairing opened by the zha.permit action, for as long as asked."""
        data = event.data.get("service_data") or {}
        asked = data.get("duration") if isinstance(data, dict) else None
        seconds = (
            float(asked)
            if isinstance(asked, (int, float)) and not isinstance(asked, bool) and math.isfinite(asked)
            else ZHA_PERMIT_DEFAULT_SECONDS
        )
        seconds = min(max(seconds, 0.0), ZHA_PERMIT_LONGEST_SECONDS)
        self._pairing_until = max(self._pairing_until, time.monotonic() + seconds)

    def async_stop(self) -> None:
        """Unsubscribe, so a reload leaves nothing behind."""
        if self._unsubscribe_permit is not None:
            try:
                self._unsubscribe_permit()
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("ZHA join observer permit unsubscribe failed: %s", err)
            self._unsubscribe_permit = None
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
        the ordinary answer for every device in a quiet house, and
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
            # A message type that is not a string, such as a list, would
            # crash the membership test outright: an unhashable value
            # cannot be looked up in a set, and the exception would
            # travel back into whatever dispatched the message, which is
            # ZHA. An instrument that can break the thing it watches is
            # worse than no instrument (rule STACK-08).
            LOGGER.info(
                "ZHA gateway message with a %s type; logged and "
                "ignored",
                type(kind).__name__,
            )
            return
        if kind == ZHA_LOG_OUTPUT:
            # ZHA's log, relayed only while its Add Device page is open:
            # pairing is open, at most this long after the last line.
            self._pairing_until = time.monotonic() + ZHA_PERMIT_LONGEST_SECONDS
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
        ieee = info.get("ieee")
        now = dt_util.utcnow().timestamp()
        tick = time.monotonic()
        if kind == ZHA_RAW_INIT and isinstance(ieee, str) and ieee:
            # A raw init inside a re-pair (zigpy sends one for a device
            # being paired) keeps the join: remove and pair again is a
            # re-pair, not a reconfigure.
            if not self._begun_lately(ieee, tick):
                self._joined.discard(ieee)
            self._begin(ieee, tick)
        if kind == ZHA_JOINED and isinstance(ieee, str) and ieee:
            if tick <= self._pairing_until:
                self._begin(ieee, tick)
                self._joined.add(ieee)
                while len(self._joined) > ZHA_BEGUN_KEPT:
                    self._joined.pop()
            else:
                # A device that changed its own network address joins
                # again with nobody near it. Without pairing open it is
                # not a person's (rule FRZ-17).
                LOGGER.debug(
                    "ZHA says a device joined with pairing closed: ieee=%s; "
                    "a device moving on its own, not counted as handled",
                    ieee,
                )
                self._begun.pop(ieee, None)
                return
        if kind == ZHA_FULL_INIT and not self._begun_lately(ieee, tick):
            # A full init with no join or reconfigure before it is the
            # device announcing itself again, most often 9 to 18 seconds
            # after a restart, with nobody near it. Logged, and nothing
            # is filed: a person did not handle it, its rhythm count
            # stands, and the report that follows teaches as any other
            # (rule FRZ-17).
            LOGGER.debug(
                "ZHA set up a device again on its own (%s): ieee=%s reg=%s "
                "name=%s; not counted as handled",
                kind,
                ieee,
                registry_id,
                info.get("user_given_name") or info.get("name"),
            )
            return
        LOGGER.debug(
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
        self.handled[registry_id] = now
        # A full init after a join is a re-pair, and is filed as one: it
        # alone restarts the device's 42-day count (rule FRZ-05).
        filed = (
            ZHA_REPAIR
            if kind == ZHA_FULL_INIT and isinstance(ieee, str) and ieee in self._joined
            else kind
        )
        if kind == ZHA_FULL_INIT and info.get("pairing_status") == ZHA_INITIALIZED and isinstance(ieee, str):
            # The last message of a pairing: the handling is done.
            self._begun.pop(ieee, None)
            self._joined.discard(ieee)
        if self._record is not None:
            self._record(registry_id, filed)

    def _begin(self, ieee: str, tick: float) -> None:
        """A person's handling of this address began now."""
        self._begun.pop(ieee, None)
        self._begun[ieee] = tick
        while len(self._begun) > ZHA_BEGUN_KEPT:
            self._begun.pop(next(iter(self._begun)))

    def _begun_lately(self, ieee: Any, tick: float) -> bool:
        """Whether a person's handling of this address began lately
        enough to explain a full init (rule FRZ-17). A re-pair sends its
        two full inits within half a minute of the join, but a sleepy
        device's configure can run for minutes; an entry older than the
        window is dropped as it is read, and the oldest go when the
        table grows past a house's worth."""
        if not isinstance(ieee, str) or not ieee:
            return False
        when = self._begun.get(ieee)
        if when is None:
            return False
        if not 0 <= tick - when <= ZHA_HANDLING_WINDOW_SECONDS:
            self._begun.pop(ieee, None)
            return False
        return True


@callback
def _is_permit(event_data: Any) -> bool:
    """Only the zha.permit action reaches _on_permit."""
    return event_data.get("domain") == "zha" and event_data.get("service") == ZHA_PERMIT_SERVICE


def make_join_observer(hass: HomeAssistant, record: Any = None) -> Any:
    """Return the join observer for ZHA."""
    return ZhaJoinObserver(hass, record)


def make_reader(hass: HomeAssistant) -> Any:
    """Return the coordinator reader for ZHA.

    It costs nothing on a house without ZHA: with no entry to read its
    state is unknown, and the sampler skips an unknown reading exactly
    as it skips a stack that has no reader at all.
    """
    return ZhaCoordinatorReader(hass)



def last_heard(hass: HomeAssistant, device: dr.DeviceEntry) -> float | None:
    """When ZHA's radio last heard a device, or None if it cannot be read.

    ZHA keeps this for every device it owns: the "Last seen" on the
    device's page in Home Assistant, moved by every message the radio
    receives from the device (repeats and replays do not move it), and
    saved in ZHA's database, so a reload or a restart does not reset
    it. It is ZHA's own Last Seen clock, so a value a restarted ZHA
    hands back from its cache is not taken for the device speaking
    (rule STACK-04). Read from what ZHA keeps in Home Assistant's data,
    without importing ZHA (rule STACK-08); anything not where it is
    expected, as on a ZHA that keeps it elsewhere, reads as None and
    the device is judged as one without a Last Seen clock.
    """
    try:
        ieee = next(
            str(identifier).lower()
            for domain, identifier in device.identifiers
            if domain == STACK_ZHA
        )
        proxies = hass.data[STACK_ZHA].gateway_proxy.device_proxies
        seen = next(
            proxy.device.last_seen
            for key, proxy in proxies.items()
            if str(key).lower() == ieee
        )
    except Exception:  # noqa: BLE001 - another integration's internals
        return None
    if isinstance(seen, bool) or not isinstance(seen, (int, float)):
        return None
    seen = float(seen)
    return seen if math.isfinite(seen) and seen > 0.0 else None
