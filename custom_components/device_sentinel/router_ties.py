# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: router_ties.py, Version: 0.27.7 (2026-10-27)

"""Router ties: which watched devices a router says have left.

Renamed from `wifi.py` in 0.20.8, with no change in behaviour, ahead
of a second capability taking that name. The split is by what answers
the question rather than by subject (#391). This file asks a router
integration which of the watched devices left the network, which is
attribution: how many, and which ones, so they are counted rather
than listed. Whether the network itself is up is a different question
with a different source, answered from the host without any router
integration at all, and it belongs in `wifi.py`.

The rename changed no behaviour, and kept the `wifi` upstream kind and
the `Bridge: WiFi` sensor under their names, because both are a
published contract. The file has grown since: the medium judgment
(rulings #415 to #434) and the router-integration exclusion (#420).

The Wi-Fi outage: a capability, deliberately not a stack.

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

An outage still open is kept in storage as it stands, and after a
restart it is taken back from there whole: its start, its fallen set,
its worst count and what it announced, so its claim holds and its
recovery carries its real length and worst moment (rule UP-04).

Known limitation, recorded rather than hidden: an access point that
keeps broadcasting while its backhaul fails leaves stations associated
and trackers reading home, a fault this detector cannot see.
"""

from __future__ import annotations

import asyncio
import math

import re
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    WIFI_BURST_HOLD_SECONDS,
    DATA_SYSTEM_EVENTS,
    DATA_WIFI_OUTAGE,
    DEV_FROZEN_CATEGORY,
    LOGGER,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_DOWN,
    WIFI_OUTAGE_DECLARED,
    WIFI_OUTAGE_DEVICES,
    WIFI_OUTAGE_FALLEN,
    WIFI_OUTAGE_PUSHED,
    WIFI_OUTAGE_RECOVERING,
    WIFI_OUTAGE_SCAN_DOWN,
    UPSTREAM_SETTLE_SECONDS,
    WIFI_OUTAGE_SINCE,
    WIFI_OUTAGE_TOLD,
    WIFI_OUTAGE_WORST,
    SYS_WIFI_UP,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_RECOVERY_WITHDRAWN,
    UPSTREAM_WIFI,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_LABELS,
    DATA_DEVICES,
    DATA_EXCLUSION_OFFERS,
    DATA_ROUTERS_SEEN,
    DATA_WIFI_MEDIUM,
    DATA_WIFI_MEDIUM_REJECTED,
    DEV_FROZEN_SINCE,
    AUTO_EXCLUDED_INTEGRATIONS,
    DEFAULT_EXCLUDED_BEFORE_0277,
    DEFAULT_EXCLUDED_INTEGRATIONS,
    OFFER_CLOSED,
    OFFER_OPEN,
    ROUTER_INTEGRATIONS,
    SYS_EXCLUSION_OFFERED,
    SYS_FIRST_SEEN_EXCLUDED,
    WIFI_BURST_FLOOR,
    WIFI_FALLEN_UNUSABLE_SECONDS,
    WIFI_HANDBACK_SECONDS,
    WIFI_TIE_RETRY_SECONDS,
    WIFI_LOOKBACK_SECONDS,
    WIFI_BURST_SHARE,
    WIFI_RECOVERY_SHARE,
    WIFI_SETTLE_TICKS,
    WIFI_BURST_WINDOW_SECONDS,
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)
from .device_fields import device_field, identifier_values
from .normalise import wifi_outage_ok

STATE_NOT_HOME = "not_home"
STATE_HOME = "home"
_HEX_ONLY = re.compile(r"[^0-9a-f]")

# Wired markers, read from each integration's source rather than
# guessed from its name. TP-Link publishes `connection`, whose wired
# value is the word itself and whose wireless value is the network's
# own name; Fritz publishes `connection_type`, whose wired value is
# its own CONNECTION_TYPE_LAN constant. No integration publishes a
# positive "wifi" marker, which is why this is an exclusion rather
# than an allow list: an allow list would have emptied the reference
# fleet's entire tie set.
#
# Unifi, Asuswrt, Netgear, Ubus and Huawei publish no marker at all.
# Unifi and Huawei filter instead, offering a setting for whether to
# create wired trackers, so on those systems a wired client is
# usually absent rather than labelled. A house that publishes
# nothing keeps every tie it had, which is the same posture the rest
# of this module takes toward absent information.
WIRED_MARKERS = (
    ("connection", "wired"),
    ("connection_type", "lan"),
)

# What a router states outright about a client's medium, read as
# stated (ruling #417). UniFi carries `essid`, `radio` and `ap_mac`
# on a wireless client. TP-Link carries none of those and instead
# spells the network's own name into `connection` and the band into
# `band`, so a client reading `connection=IoT band=2G` is the router
# saying it is wireless as plainly as UniFi does. Measured on the
# reference fleet: 8,815 tracker lines, zero occurrences of the UniFi
# spellings, and 29 of 40 trackers left unknown by reading only
# those. Every one of the 29 is wireless by TP-Link's own account.
WIRELESS_KEYS = ("essid", "ssid", "radio", "radio_proto", "ap_mac")

# The medium is scored rather than fixed by one reading (ruling
# #415), and a minority that reaches this share of the evidence
# sends the tracker to unknown rather than to its majority (ruling
# #427). Measured, not chosen: the tightest contradiction on either
# fleet is 2 against 22, the next 1 against 52, and the thirteen
# plainly false readings on the reference fleet are all one or two
# samples against 45 to 184. A tenth discards every one of them and
# is reached by none. Unknown is the safe state because unknown keeps
# the tie.
MEDIUM_MINORITY_SHARE = 0.10

# And a minority overrules nothing until there is this much evidence
# behind it (ruling #432).
#
# This is the whole of the answer to the stripped reading found on 14
# September, and the only one available. When a client leaves, TP-Link strips
# its network name and band and reports it as wired, which is byte for byte
# what it publishes for a genuine wired client. A tie rebuild landing between
# the attribute update and the state update reads `home` carrying that shape.
# Refusing the shape was tried and reverted: it turns every real wired device
# on the fleet into unknown. The two cases cannot be told apart from one
# reading, so they are told apart by how often each occurs. The share was
# measured over ten days, where the tightest contradiction on either fleet was
# 2 against 22. On six samples one bad reading is sixteen percent: on 14
# September three known-wireless devices went to unknown on a single stripped
# reading each, hours after a fresh install. A share means nothing until there
# are enough samples for it to be a share of anything.
MEDIUM_MINORITY_FLOOR = 20


def tracker_medium(attributes: Any) -> str:
    """Return wired, wireless or unknown for one reading.

    Wired wins, because it is the exclusion the tie ladder acts on.
    A named network or a band is the router stating wireless outright
    (ruling #417); `band=None` and `connection=wired` together are
    what TP-Link publishes for a wired client and, for one sample at
    every router restart, for every client at once.
    """
    if not isinstance(attributes, dict):
        return "unknown"
    for key, wired_value in WIRED_MARKERS:
        value = attributes.get(key)
        if isinstance(value, str) and value.strip().lower() == wired_value:
            return "wired"
    for key in WIRELESS_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            return "wireless"
    band = attributes.get("band")
    if isinstance(band, str) and band.strip() and band.strip().lower() != "none":
        return "wireless"
    connection = attributes.get("connection")
    if isinstance(connection, str) and connection.strip():
        return "wireless"
    return "unknown"


def medium_from_score(score: dict[str, int]) -> str:
    """Judge a tracker's medium from its accumulated evidence.

    Majority wins. A minority below MEDIUM_MINORITY_SHARE of the
    whole is a router restart or a stale entry and is ignored (#415).
    A minority at or above it is a device that cannot be told, and
    that is unknown (#427).
    """
    wired = int(score.get("wired", 0))
    wireless = int(score.get("wireless", 0))
    total = wired + wireless
    if total == 0:
        return "unknown"
    minority = min(wired, wireless)
    if (
        minority
        and total >= MEDIUM_MINORITY_FLOOR
        and minority >= MEDIUM_MINORITY_SHARE * total
    ):
        return "unknown"
    return "wired" if wired > wireless else "wireless"


def _no_router_state(state: Any) -> bool:
    """Whether a tracker has no state from its router yet: none at all,
    Home Assistant's restored placeholder, or unavailable or unknown
    with no source type, as a router integration that loaded but cannot
    reach its router publishes (rule UP-16)."""
    if state is None or state.attributes.get("restored"):
        return True
    return (
        state.state in (STATE_UNAVAILABLE, "unknown")
        and "source_type" not in state.attributes
    )


def _usable_tracker_state(state: Any) -> bool:
    """Whether a tracker reads a state its router gave: not absent, not
    Home Assistant's placeholder, not unavailable or unknown (rule
    UP-16)."""
    return (
        state is not None
        and not state.attributes.get("restored")
        and state.state not in (STATE_UNAVAILABLE, "unknown")
    )


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


class RouterTiesMixin:
    """The Wi-Fi outage watcher, mixed into the coordinator.

    State lives on the coordinator (initialized beside the other
    upstream state): the tie maps, the burst window, the hold, and
    the declared outage. The outage itself is kept in storage while
    it stands and taken back from there after a restart (rule UP-04).
    """

    # Declared for the type checker, which otherwise infers it from
    # its first assignment here; the coordinator initializes it.
    _wifi_declared_from: float | None
    _wifi_fallen: dict[str, float]
    _wifi_scan_down_at: float | None
    _wifi_resumed: bool
    _wifi_resume_seed: bool
    _wifi_fallen_unsub: Any
    _wifi_fallen_unusable_since: dict[str, float]
    _wifi_retry_until: float | None
    _wifi_down_row_written: bool

    # ---------------------------------------------------------- medium

    def _wifi_medium_score(self, tracker: str) -> dict[str, int]:
        """The persisted evidence for one tracker, or empty."""
        table = self.data.setdefault(DATA_WIFI_MEDIUM, {})
        return table.get(tracker) or {}

    def _score_wifi_medium(
        self, tracker: str, reading: str, stamp: float
    ) -> str:
        """Fold one home reading into the score and return the
        judgment (rulings #415, #418, #428).

        A sample is one state update, not one look at the state. The
        tie rebuild runs on every registry change and on every rejoin
        sweep, and scoring on each run counted one unchanged reading
        ten times over during setup alone, which buried the next real
        reading below the minority line. The state's own last_updated
        is the stamp, and a reading is counted once per stamp.

        A reading of unknown carries no evidence and is not counted,
        which is what a router that has not polled yet publishes. A
        reading that the judgment then discards as a minority is
        counted separately: that count is what makes the case for a
        source-restart grace measurable. Thirteen such readings were
        found on the reference fleet, all one or two samples against
        45 to 184, and the grace was set aside on that measurement.
        """
        table = self.data.setdefault(DATA_WIFI_MEDIUM, {})
        score = table.setdefault(tracker, {"wired": 0, "wireless": 0})
        fresh = self._wifi_medium_stamp.get(tracker) != stamp
        if fresh and reading in ("wired", "wireless"):
            self._wifi_medium_stamp[tracker] = stamp
            score[reading] = int(score.get(reading, 0)) + 1
            self._dirty = True
        judged = medium_from_score(score)
        if fresh and reading in ("wired", "wireless") and reading != judged:
            if judged != "unknown":
                # Persisted (ruling #434). Held in memory until
                # 0.21.7 and wiped at every restart, which made it
                # read empty forever: on the reference fleet four
                # trackers carried a discarded reading each and the
                # published count read nothing at all. The count
                # exists so the case for a general source-restart
                # grace can be judged over weeks.
                table = self.data.setdefault(DATA_WIFI_MEDIUM_REJECTED, {})
                table[tracker] = int(table.get(tracker, 0)) + 1
                self._dirty = True
        return judged

    def wifi_medium_of(self, tracker: str) -> str:
        """What the evidence says this tracker is."""
        return medium_from_score(self._wifi_medium_score(tracker))

    @property
    def wifi_medium_rejected(self) -> dict[str, int]:
        """Readings the scoring has discarded, per tracker, for the
        life of the install (rulings #428 and #434)."""
        return dict(self.data.get(DATA_WIFI_MEDIUM_REJECTED) or {})

    # ------------------------------------------------------------ ties

    @staticmethod
    def _tie_for(device: Any, tracker_by_mac: dict[str, Any], owner: str | None) -> Any:
        """The tracker a device is tied to by MAC, or None (rungs 1 and 2)."""
        tracker = None
        # Rung 1: a normalized MAC in the device's connections.
        for kind, value in device_field(device, "connections", set()):
            if kind != dr.CONNECTION_NETWORK_MAC:
                continue
            found = tracker_by_mac.get(normalize_mac(value) or "")
            if found and found[1] != owner:
                tracker = found[0]
                break
        # Rung 2: the full twelve-hex MAC inside an identifier.
        # Every part after the domain is searched, whatever the
        # identifier's length (issue #16: hOn's has three).
        if tracker is None:
            for _domain, parts in identifier_values(device):
                for ident in parts:
                    bare = _HEX_ONLY.sub("", str(ident).lower())
                    for mac, found in tracker_by_mac.items():
                        if mac in bare and found[1] != owner:
                            tracker = found[0]
                            break
                    if tracker:
                        break
                if tracker:
                    break
        return tracker

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
        tracker_by_mac: dict[str, tuple[str, str]] = {}
        census: dict[str, int] = {}
        wired: list[str] = []
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
                    for kind, value in device_field(owner, "connections", set()):
                        if kind == dr.CONNECTION_NETWORK_MAC:
                            mac = normalize_mac(value)
                            break
            # A medium is judged only while the tracker is home. A
            # router does not maintain a disconnected client's
            # attributes: on the reference fleet an outage left seven
            # wireless trackers reading wired, and because a skipped
            # tracker was never looked at again the tie set fell from
            # twelve to six and stayed there. The feature that detects
            # Wi-Fi outages was being shrunk by Wi-Fi outages.
            #
            # So an away tracker keeps whatever it was last judged
            # while connected, which is the #221 principle: a live
            # reading confirms or doubts a classification and never
            # decides one on its own.
            if state.state == STATE_HOME:
                medium = self._score_wifi_medium(
                    entry.entity_id,
                    tracker_medium(state.attributes),
                    state.last_updated.timestamp(),
                )
            else:
                medium = self.wifi_medium_of(entry.entity_id)
                if medium == "unknown" and not self._wifi_medium_score(
                    entry.entity_id
                ):
                    medium = None
                if medium is None:
                    # Never seen home, so nothing is known about it.
                    # Unknown keeps the tie, because the exclusion
                    # acts only on a published wired marker (#388).
                    medium = "unknown"
            census[medium] = census.get(medium, 0) + 1
            if medium == "wired":
                # A wired client cannot be taken down by a Wi-Fi
                # outage, and counting one toward the floor lets a
                # switch reboot declare a network outage that never
                # happened. Found on the reference fleet, where four
                # PoE cameras and a printer tied themselves in.
                wired.append(entry.entity_id)
                continue
            if mac is not None and mac not in tracker_by_mac:
                tracker_by_mac[mac] = (entry.entity_id, entry.platform)

        ties: dict[str, str] = {}
        for device_id in self._watched:
            device = devices.async_get(device_id)
            if device is None:
                continue
            # The self-tie bar (ruling #419). A router integration
            # registers every client on the network as its own
            # registry device, so without this a client is tied to
            # its own tracker: the device and the witness are the
            # same object, the tie cannot fail to agree with itself,
            # and three computers powering down inside a minute
            # declare a network outage. Measured on the second fleet,
            # where 126 of 205 tied devices were this and sixteen of
            # nineteen declared outages came from it.
            owner = self._watched.get(device_id)
            try:
                tracker = self._tie_for(device, tracker_by_mac, owner)
            except Exception as err:  # noqa: BLE001 - another integration's data
                # One device's registry entry must not stop the ties
                # being built for the house (issue #16).
                self._note_odd_device(device, str(device.name_by_user or device.name or device_id), err)  # type: ignore[attr-defined]
                tracker = None
            if tracker is not None:
                ties[device_id] = tracker

        self._wifi_medium_census = census
        self._wifi_wired_skipped = sorted(wired)
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
        # trackers never starts. Home Assistant's own "unavailable"
        # placeholder, written at its start for an integration not yet
        # loaded, is no state from the router either, nor is a plain
        # unavailable from one that cannot reach its router; otherwise
        # a router answering late never ties again (rule UP-16). The
        # retry runs only for WIFI_TIE_RETRY_SECONDS after the first
        # look, then stops whatever it reads: an orphaned tracker reads
        # the placeholder for ever, and the ladder was rebuilt every
        # minute for the life of the run.
        now = dt_util.utcnow().timestamp()
        if self._wifi_retry_until is None:
            self._wifi_retry_until = now + WIFI_TIE_RETRY_SECONDS
        self._wifi_retry_pending = not ties and now < self._wifi_retry_until and any(
            entry.domain == "device_tracker"
            and not entry.disabled_by
            and _no_router_state(self.hass.states.get(entry.entity_id))
            for entry in registry.entities.values()
        )
        if changed:
            LOGGER.info(
                "device_sentinel: wifi ties rebuilt, %d watched "
                "device(s) tied to a router tracker",
                len(ties),
            )
            self._resubscribe_wifi_trackers()

    def _router_integrations_present(self) -> set[str]:
        """Return the router integrations this house actually has.

        Read from the entity registry rather than from the config
        entries, because what matters is that the integration
        publishes router trackers, which is the thing that duplicates
        hardware and lets a device be tied to its own tracker.
        """
        registry = er.async_get(self.hass)
        return {
            entry.platform
            for entry in registry.entities.values()
            if entry.domain == "device_tracker"
            and entry.platform in ROUTER_INTEGRATIONS
        }

    def _first_seen_exclusions_present(self) -> set[str]:
        """The integrations excluded when first seen that this house has:
        its router integrations (#420), and those of
        AUTO_EXCLUDED_INTEGRATIONS with an entry in Home Assistant
        (ruling #711)."""
        present = self._router_integrations_present()
        entries = self.hass.config_entries
        # An entry a person ignored or disabled is not an integration
        # the house has (adversarial round of 0.26.8).
        present |= {
            domain
            for domain in AUTO_EXCLUDED_INTEGRATIONS
            if entries.async_entries(domain, include_ignore=False, include_disabled=False)
        }
        return present

    def _choice_made(self, domain: str) -> bool:
        """Whether the person has already decided something about this
        integration (James, 20 October 2026): muted it for anything, or
        muted or excluded any of its devices, on the device or by a
        label. Their choice stands, and a first sighting does not
        exclude it over them.

        Read from the options and the registry, not from the watched
        view, because a device the default list already sets aside has
        no place in that view (seventh adversarial round of 0.26.8).
        """
        options = self.entry.options

        def listed(key: str) -> set[str]:
            value = options.get(key)
            return {v for v in value if isinstance(v, str)} if isinstance(value, (list, tuple)) else set()

        for key in (
            CONF_MUTED_INTEGRATIONS,
            CONF_FREEZE_MUTED_INTEGRATIONS,
            CONF_BATTERY_MUTED_INTEGRATIONS,
            CONF_SIGNAL_MUTED_INTEGRATIONS,
        ):
            if domain in listed(key):
                return True
        devices: set[str] = set()
        for key in (
            CONF_EXCLUDED_DEVICES,
            CONF_MUTED_DEVICES,
            CONF_FREEZE_MUTED_DEVICES,
            CONF_UNAVAILABLE_MUTED_DEVICES,
            CONF_BATTERY_MUTED_DEVICES,
            CONF_SIGNAL_MUTED_DEVICES,
        ):
            devices |= listed(key)
        labels: set[str] = set()
        for key in (
            CONF_MUTED_LABELS,
            CONF_FREEZE_MUTED_LABELS,
            CONF_UNAVAILABLE_MUTED_LABELS,
            CONF_BATTERY_MUTED_LABELS,
            CONF_SIGNAL_MUTED_LABELS,
        ):
            labels |= listed(key)
        registry = dr.async_get(self.hass)
        for entry in self.hass.config_entries.async_entries(domain):
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                if device.id in devices:
                    return True
                if labels & set(device_field(device, "labels", set()) or ()):
                    return True
        return False

    def _leave_as_chosen(self, domain: str) -> bool:
        """A #711 integration the person decided about; never a router
        integration, which #420 excludes whatever was muted."""
        return domain in AUTO_EXCLUDED_INTEGRATIONS and self._choice_made(domain)

    async def _sight_router_integrations(self) -> None:
        """Exclude a router integration the first time it is seen
        (ruling #420), and each of AUTO_EXCLUDED_INTEGRATIONS (#711), on
        a new install; on a house that already exists, recommend it
        (Ruled Change 70, rule MUTE-02).

        Fires once per integration, ever. A new install gets these from
        the default list, and one the default lacks, such as a FRITZ!Box
        router, is added in its first run. On a house that already
        exists nothing is added behind the person's back: an
        integration seen for the first time raises a card on the
        Recommendations tab, told once in the brief, with an Exclude
        button and a tick to keep watching it. One the person has
        already decided about, by a mute or an exclusion of it or its
        devices, is left as they chose. After that the integration is
        recorded and never new again.

        Runs one at a time.
        """
        if self._stopped:  # type: ignore[attr-defined]
            return
        lock = getattr(self, "_sighting_lock", None)
        if lock is None:
            lock = self._sighting_lock = asyncio.Lock()
        async with lock:
            # Checked again once the lock is held: a reload may have come
            # while it waited (eighth adversarial round of 0.26.8).
            if self._stopped:  # type: ignore[attr-defined]
                return
            await self._sight_once()

    def exclusion_offers(self) -> dict[str, str]:
        """Each integration recommended for exclusion, "open" while its
        card stands and "closed" once it was excluded (Ruled Change 70).
        Read defensively: the shape is this release's own."""
        found = self.data.get(DATA_EXCLUSION_OFFERS)
        if not isinstance(found, dict):
            return {}
        return {
            str(domain): state
            for domain, state in found.items()
            if state in (OFFER_OPEN, OFFER_CLOSED)
        }

    async def _sight_once(self) -> None:
        """One sighting; see _sight_router_integrations.

        Reads the list and writes it with no wait between, so a change
        the person makes at the same moment is never written over; the
        file is saved last (sixth adversarial round of 0.26.8).
        """
        present = self._first_seen_exclusions_present()
        seen = set(self.data.get(DATA_ROUTERS_SEEN) or [])
        fresh = present - seen
        stored = self.entry.options.get(CONF_EXCLUDED_INTEGRATIONS)
        # The first run of a new install (Ruled Change 70).
        new_install = self.setup_count <= 1 and not self._pin_before_0277  # type: ignore[attr-defined]
        offers = self.exclusion_offers()
        pinned = False
        if stored is None and self._pin_before_0277:  # type: ignore[attr-defined]
            # A house that already exists and never saved its list
            # follows the default, so the names this release adds to it
            # would exclude without asking: the list it already used is
            # written as its own, once (Ruled Change 70).
            stored = list(DEFAULT_EXCLUDED_BEFORE_0277)
            pinned = True
        current = (
            [name for name in stored if isinstance(name, str)]
            if isinstance(stored, (list, tuple))
            # A list damaged by hand is not a reason to fail the start
            # (fifth adversarial round of 0.26.8).
            else ([] if stored is not None else list(self.default_exclusions()))  # type: ignore[attr-defined]
        )
        # A card whose integration is now excluded is closed for good:
        # taken back later, it does not come back (Ruled Change 70).
        closing = {
            domain for domain, state in offers.items()
            if state == OFFER_OPEN and domain in current
        }
        if not fresh and not pinned and not closing:
            return
        told: list[str] = []
        offered: list[str] = []
        adding: list[str] = []
        kept_out: list[str] = []
        if new_install and stored is None:
            # A list never saved is the default. Those the default
            # already holds are excluded by it; a #711 name the person
            # has decided about is taken off it, as they chose; one the
            # default lacks, such as a FRITZ!Box router, is added (sixth
            # adversarial round of 0.26.8).
            default = set(DEFAULT_EXCLUDED_INTEGRATIONS)
            kept_out = [n for n in sorted(fresh & set(AUTO_EXCLUDED_INTEGRATIONS)) if self._choice_made(n)]
            # A router is excluded as #420 always did, whatever was muted
            # (seventh adversarial round of 0.26.8).
            adding = [n for n in sorted(fresh - default) if not self._leave_as_chosen(n)]
            told = sorted(((fresh & default) - set(kept_out)) | set(adding))
            new_list = [n for n in current if n not in kept_out] + adding
        elif new_install:
            adding = [
                name for name in sorted(fresh)
                if name not in current and not self._leave_as_chosen(name)
            ]
            told = adding
            new_list = current + adding
        else:
            # A house that already exists: recommended, not excluded,
            # routers and media alike, unless the person has decided
            # about it already (Ruled Change 70).
            offered = [
                name for name in sorted(fresh)
                if name not in current
                and name not in offers
                and not self._choice_made(name)
            ]
            new_list = current
        write = pinned or bool(kept_out or adding)
        # Each one excluded is told in the brief, so a person who watched
        # it on purpose sees it and can take it back; before the next
        # midnight, its devices' history is kept.
        for name in told:
            self._record_system_event(SYS_FIRST_SEEN_EXCLUDED, scope=name)  # type: ignore[attr-defined]
        # Each one recommended is told once, pointing to its card: only
        # one with devices has a card to point to (second adversarial
        # round of 0.27.7).
        registry = dr.async_get(self.hass)
        for name in offered:
            if any(
                dr.async_entries_for_config_entry(registry, entry.entry_id)
                for entry in self.hass.config_entries.async_entries(name)
            ):
                self._record_system_event(SYS_EXCLUSION_OFFERED, scope=name)  # type: ignore[attr-defined]
        if offered or closing:
            updated = dict(offers)
            for name in offered:
                updated[name] = OFFER_OPEN
            for name in closing:
                updated[name] = OFFER_CLOSED
            self.data[DATA_EXCLUSION_OFFERS] = updated
            mark = getattr(self, "_mark_changed", None)
            if mark is not None:
                mark()
        self.data[DATA_ROUTERS_SEEN] = sorted(seen | present)
        if write:
            if adding:
                LOGGER.info(
                    "device_sentinel: integration(s) %s seen for the "
                    "first time and excluded from watching; unexclude on the "
                    "Configure screen to watch them",
                    ", ".join(adding),
                )
            options = {**self.entry.options, CONF_EXCLUDED_INTEGRATIONS: new_list}
            # The snapshot the update listener compares with is set
            # first, so neither the listener (which may run at once,
            # while running) nor the next settings change names the
            # exclusion list as a setting the person changed. At a start
            # the listener is not yet in place, so the view is rebuilt
            # here for the devices to be set aside at once; while
            # running, the listener rebuilds it again, which is harmless
            # (adversarial rounds of 0.26.8).
            self._options_seen = dict(options)
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            self._rebuild_registry_view()  # type: ignore[attr-defined]
        if not self._stopped:  # type: ignore[attr-defined]
            await self._save_now()

    @property
    def wifi_recovering_at(self) -> float | None:
        """When this outage's recovery began, or None."""
        return self._wifi_recovering_at

    @property
    def wifi_returned_count(self) -> int:
        """How many of the fallen set are home again."""
        return len(self._wifi_returned)

    @property
    def wifi_casualties(self) -> int:
        """How many watched devices this outage took.

        The trackers that fell in it, counted as the devices they are
        tied to. A tracker with no watched device behind it is not a
        casualty of anything.
        """
        return sum(
            1 for tracker in self._wifi_fallen
            if tracker in self._wifi_device_of
        )

    @property
    def wifi_fallen_set(self) -> set[str]:
        """The trackers that fell during the standing outage."""
        return set(self._wifi_fallen)

    def _wifi_recovery_needed(self, fell: int) -> int:
        """How many of the fallen set must return to announce a
        recovery (ruling #423).

        A bare share with no floor. A floor of three was measured
        against churn and rejected here: on a three device outage it
        requires all three back, which is the hours-long hold this
        rule exists to remove. Closing early is the cheap error,
        because whatever is still away goes back to per-device
        detection rather than being forgotten (ruling #426).
        """
        return math.ceil(WIFI_RECOVERY_SHARE * fell) if fell else 0

    def _wifi_burst_needed(self) -> int:
        """Return how many tied trackers must fall together to declare
        an outage (ruling #421).

        The greater of the floor and a share of the tied set. Three
        was measured against churn on a twelve tracker fleet, where
        three is a quarter of the house and a share cannot
        discriminate at all; on a hundred device fleet the same three
        is three percent. The floor protects the small fleet and the
        share protects the large one, and they meet at thirty tied
        trackers.
        """
        return max(
            WIFI_BURST_FLOOR,
            math.ceil(WIFI_BURST_SHARE * len(self._wifi_ties)),
        )

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
            # A tracker that falls while the outage stands joins the
            # fallen set unless it has already returned once: a
            # returned member never rejoins (ruling #422), or the set
            # can never empty and the shipped defect returns wearing
            # a different hat.
            if (
                self._wifi_down_at is not None
                and entity_id not in self._wifi_returned
            ):
                self._wifi_fallen.setdefault(entity_id, now)
            # A member that returned and has gone away again during
            # the settle is a loss (ruling #425). Membership of the
            # returned set stays permanent (#422), so losses are
            # counted in their own right rather than by subtracting
            # from the return count: the two rulings would otherwise
            # cancel and no loss could ever be seen.
            elif self._wifi_announced and entity_id in self._wifi_returned:
                self._wifi_settle_losses += 1
            self._wifi_burst.append(now)
            self._prune_wifi_burst(now)
            if (
                self._wifi_down_at is None
                and self._wifi_hold_since is None
                and not self.wifi_scan_configured
                and len(self._wifi_burst) >= self._wifi_burst_needed()
            ):
                self._wifi_hold_since = now
                self._wifi_first_fall = self._wifi_burst[0]
                LOGGER.info(
                    "device_sentinel: wifi burst, %d tied tracker(s) "
                    "not_home inside %ds against a threshold of %d "
                    "on %d tied, holding %ds before any verdict",
                    len(self._wifi_burst),
                    int(WIFI_BURST_WINDOW_SECONDS),
                    self._wifi_burst_needed(),
                    len(self._wifi_ties),
                    int(WIFI_HOLD_SECONDS),
                )
        else:
            # home, unavailable, unknown: however it left not_home,
            # it no longer counts toward the floor and its device is
            # no longer claimed.
            self._wifi_not_home.pop(entity_id, None)
            # And if it was a casualty of the standing outage, it has
            # returned, permanently (ruling #422).
            if entity_id in self._wifi_fallen:
                was = len(self._wifi_returned)
                self._wifi_returned.add(entity_id)
                # The recovering row counts what has not come back
                # (ruling #431), and that number is what a person
                # watches. It is not the casualty count, which does
                # not move during a recovery, so nothing else marks
                # the list for rewriting and the row would sit at its
                # opening number until the outage closed. Observed on
                # the staged outage of 15 September 10:03: the row
                # read 11 of 11 throughout while the returns climbed
                # from nought to nine.
                if (
                    self._wifi_recovering_at is not None
                    and len(self._wifi_returned) != was
                ):
                    self._notify()

    def _wired_can_rejoin(self) -> bool:
        """Whether any skipped tracker has come back as wireless.

        The safety net, swept on the tick rather than driven by an
        event. A state change says a tracker returned; it does not say
        the router has finished re-reporting its attributes, and on
        the reference fleet those arrived in scan batches thirty five
        seconds apart. Reading them a minute later reads them settled,
        and a tie that recovers within a minute is indistinguishable
        from one that recovers at once, because nothing is said about
        an outage for sixty seconds anyway.

        Costs one dictionary read per skipped tracker per minute, and
        nothing at all where none were skipped.
        """
        for entity_id in self._wifi_wired_skipped:
            state = self.hass.states.get(entity_id)
            if state is None or state.state != STATE_HOME:
                continue
            if tracker_medium(state.attributes) != "wired":
                LOGGER.info(
                    "device_sentinel: %s is home and no longer reads "
                    "wired, rebuilding wifi ties",
                    entity_id,
                )
                return True
        return False

    def _prune_wifi_burst(self, now: float) -> None:
        """Keep only transitions inside the sliding window."""
        cutoff = now - WIFI_BURST_WINDOW_SECONDS
        self._wifi_burst = [t for t in self._wifi_burst if t > cutoff]

    # ---------------------------------------------------------- sampler

    @callback
    def wifi_confirmation(self) -> dict[str, Any]:
        """What the ties can say about an outage the scan declared.

        Where the scan is primary (#391) this is the whole of the
        ties' contribution to detection: how many watched devices the
        router says have left, and which. The count is what turns
        twenty individual reports into one line naming a cause.
        """
        away = [
            device_id
            for device_id, tracker in self._wifi_ties.items()
            if tracker in self._wifi_not_home
        ]
        return {
            "tied": len(self._wifi_ties),
            "away": len(away),
            "devices": sorted(away),
        }

    @callback
    def _sample_wifi(self, now: float) -> None:
        """Judge the hold and the recovery on the tick.

        Tick-driven like every other upstream judgment: one sweep is
        simpler than timers to cancel and re-arm, and a hold that
        ends within a minute of its deadline is immaterial against an
        outage measured in minutes.
        """

        if self._wifi_retry_pending or self._wired_can_rejoin():
            self._rebuild_wifi_ties()
        self._resume_wifi_outage(now)
        # A standing outage is judged whether or not anything is tied:
        # one the scan declared on a house with no ties still has to
        # end when the network is heard (rule UP-16).
        if self._wifi_down_at is not None:
            self._sample_wifi_recovery(now)
            return
        if not self._wifi_ties:
            return
        if self._wifi_hold_since is None:
            return
        if now - self._wifi_hold_since < WIFI_HOLD_SECONDS:
            return
        # The same threshold the burst used (ruling #421). These
        # disagreed in 0.21.0: the burst scaled with the fleet and
        # the hold did not, so a burst of seven decaying to three
        # still declared on a fleet where three is ordinary churn.
        # Only trackers that left with the burst count, by the same
        # line the fallen set is drawn with: one already away before
        # it is not a casualty, and phones away all day must not lift
        # a small flap over the threshold (rule UP-12).
        floor = (self._wifi_first_fall or self._wifi_hold_since) - WIFI_BURST_WINDOW_SECONDS
        still_gone = sum(
            1 for when in self._wifi_not_home.values() if when >= floor
        )
        if still_gone >= self._wifi_burst_needed():
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

    @callback
    def on_wifi_scan_down(self, since: float, missing: list[str]) -> None:
        """The scan says the network is gone, so declare it (#391).

        The same outage the ties would have declared, dated from when
        the network actually went. What the ties add is the count:
        how many watched devices the router says went with it.
        """
        if self._wifi_down_at is not None:
            return
        self._wifi_down_at = since
        self._wifi_declared_from = since
        self._wifi_hold_since = None
        self._seed_wifi_fallen(since)
        self._wifi_backdate()
        confirmed = self._wifi_confirmed_count()
        seen = self.wifi_confirmation()
        LOGGER.info(
            "device_sentinel: wifi outage declared by scan (%s), "
            "%d tied device(s), %d away by the router, %d already "
            "unavailable",
            ", ".join(missing),
            seen["tied"],
            seen["away"],
            confirmed,
        )
        self._begin_upstream_peak(WIFI_KEY)
        # Dated from the outage's start as backdated, the start its row
        # and its stored state keep (rules UP-04, UP-11).
        start = self._wifi_down_at if self._wifi_down_at is not None else since
        self._record_system_event(
            SYS_WIFI_DOWN, scope=WIFI_KEY, devices=len(self._wifi_ties),
            when=start,
        )
        # From here a backdate may re-date it; never an older one.
        self._wifi_down_row_written = True
        self._say_upstream_down(
            UPSTREAM_WIFI, WIFI_KEY, None, start, len(self._wifi_ties),
            confirmed=confirmed,
        )
        self._remember_wifi_outage(critical=True)

    @callback
    def on_wifi_scan_restored(
        self, since: float | None, now: float
    ) -> None:
        """The scan hears every chosen network again.

        It reports the return; it does not end the outage. Hearing
        the network is not the same as the devices on it being back,
        and the recovery rule is what knows the difference
        (ruling #429).

        Until 0.21.5 this called the restore directly, so on any
        house with a network configured the whole recovery rule was
        dead: the fallen set, the announce, the settle and the
        reopen never ran. Measured on 14 September, the trackers came
        home at 15:13:38, the scan closed the outage at 15:13:58, and
        the five Motion Blinds devices behind it finished
        reconnecting between 15:14:16 and 15:14:18. Every one was
        handed back under #426 inside that twenty second window,
        wrote its own row and announced itself, and twenty seconds
        later they were all fine. The same half-applied shape as the
        fallen set: a rule built for the tie route and never given to
        the scan.
        """
        if self._wifi_down_at is None:
            return
        if not self._wifi_fallen:
            # Nothing fell in it, so there is nothing to wait for: the
            # outage ends when the network is heard, with no
            # recovering phase between, inside the startup grace too,
            # since a resumed outage's empty set stays empty (rule
            # UP-16).
            self._wifi_restore(now)
            return
        LOGGER.info(
            "device_sentinel: wifi scan hears the network again, "
            "%d of %d fallen tracker(s) home; the settle decides "
            "when the outage ends",
            len(self._wifi_returned),
            len(self._wifi_fallen),
        )
        if self._wifi_recovering_at is None:
            self._wifi_recovering_at = now
            self._record_system_event(
                SYS_WIFI_RECOVERING, scope=WIFI_KEY, when=now
            )
            self._notify()
        self._sample_wifi_recovery(now)

    def _wifi_handback_now(self) -> float:
        return dt_util.utcnow().timestamp()

    def _wifi_claimed_now(self) -> set[str]:
        """Every watched device this outage is currently claiming."""
        return {
            device_id
            for device_id in self.data.get(DATA_DEVICES, {})
            if self.upstream_down_since(device_id) is not None
        }

    def _sample_wifi_recovery(self, now: float) -> None:
        """Judge the recovery of a standing outage on the tick.

        Announced when a share of the fallen set has returned
        (#423), then settled: the settle extends while returns keep
        arriving and closes after two consecutive quiet ticks (#424),
        which rides the burst out rather than cutting it at a fixed
        delay. Three losses during the settle withdraw the announce
        (#425), reusing the declaration floor because three trackers
        falling together is what declared the outage in the first
        place.

        An outage with nothing in its fallen set ends when the network
        is heard, because there is nothing else to wait for; until
        0.27.5 it returned here and stayed open until a restart,
        claiming every device that failed meanwhile (rule UP-16).
        """
        if self._wifi_resume_waiting():
            return
        self._drop_removed_wifi_fallen(now)
        fell = len(self._wifi_fallen)
        if not fell:
            if self._wifi_scan_down_at is None:
                self._wifi_restore(now)
            return
        back = len(self._wifi_returned)

        if back >= fell:
            # Every member of the fallen set is home, so there is
            # provably nothing left to wait for (ruling #430).
            # Checked before the announce, because a recovery that is already complete
            # has nothing to settle: announcing and then serving out
            # two quiet ticks would hold the outage open for two
            # minutes over devices that are all back.
            self._wifi_restore(now)
            return
        if not self._wifi_announced:
            if back >= self._wifi_recovery_needed(fell):
                self._wifi_announced = True
                self._wifi_peak_back = back
                self._wifi_quiet_ticks = 0
                self._wifi_settle_losses = 0
                if self._wifi_recovering_at is None:
                    self._wifi_recovering_at = now
                    self._record_system_event(
                        SYS_WIFI_RECOVERING, scope=WIFI_KEY, when=now
                    )
                    self._notify()
                LOGGER.info(
                    "device_sentinel: wifi recovery announced, %d of "
                    "%d returned, settling",
                    back,
                    fell,
                )
            return

        if self._wifi_settle_losses >= WIFI_BURST_FLOOR:
            LOGGER.info(
                "device_sentinel: wifi recovery withdrawn, %d of the "
                "returned went away again during the settle",
                self._wifi_settle_losses,
            )
            self._wifi_announced = False
            self._wifi_settle_losses = 0
            self._wifi_peak_back = back
            self._wifi_quiet_ticks = 0
            self._wifi_recovering_at = None
            self._record_system_event(
                SYS_WIFI_RECOVERY_WITHDRAWN, scope=WIFI_KEY, when=now
            )
            self._notify()
            return
        if back > self._wifi_peak_back:
            self._wifi_peak_back = back
            self._wifi_quiet_ticks = 0
            return

        self._wifi_quiet_ticks += 1
        if self._wifi_quiet_ticks >= WIFI_SETTLE_TICKS:
            self._wifi_restore(now)

    def _seed_wifi_fallen(self, since: float) -> None:
        """Open the fallen set for an outage starting at `since`.

        Called by both routes that declare one. The ties declare from
        a burst of trackers; a house that can hear its own radio
        declares from the scan instead (#391) and the burst branch is
        switched off entirely. 0.21.1 built the fallen set in the tie
        route alone, so on any house with a network configured there
        was never a fallen set at all and the recovery ran against an
        empty one. Found by a staged outage on 14 September; neither
        fleet file configures a network and no harness case did
        either, so nothing covered the scan route.

        A tracker already away before the outage began is left out
        (ruling #409): it is not a casualty and must not vote against
        recovery. Anything the scan route cannot date is taken as
        part of the outage, because the scan knows the network went
        and knows nothing about when each tracker followed.
        """
        self._wifi_fallen = {
            entity_id: when
            for entity_id, when in self._wifi_not_home.items()
            if when >= since - WIFI_BURST_WINDOW_SECONDS
        }
        self._wifi_returned = set()
        self._wifi_fallen_unusable_since = {}
        self._wifi_announced = False
        self._wifi_peak_back = 0
        self._wifi_quiet_ticks = 0
        self._wifi_settle_losses = 0
        self._wifi_recovering_at = None

    def _wifi_declare(self, now: float, still_gone: int) -> None:
        """Declare the outage, dated from the first fall."""
        since = self._wifi_first_fall or self._wifi_hold_since or now
        self._wifi_down_at = since
        self._wifi_declared_from = since
        self._wifi_hold_since = None
        self._seed_wifi_fallen(since)
        self._wifi_backdate()
        confirmed = self._wifi_confirmed_count()
        LOGGER.info(
            "device_sentinel: wifi outage declared, %d tied "
            "tracker(s) not_home, %d claimed device(s) already "
            "unavailable at declaration",
            still_gone,
            confirmed,
        )
        self._begin_upstream_peak(WIFI_KEY)
        # Dated from the outage's start as backdated, the start its row
        # and its stored state keep (rules UP-04, UP-11).
        since = self._wifi_down_at
        self._record_system_event(
            SYS_WIFI_DOWN, scope=WIFI_KEY, devices=len(self._wifi_ties),
            when=since,
        )
        # From here a backdate may re-date it; never an older one.
        self._wifi_down_row_written = True
        self._say_upstream_down(
            UPSTREAM_WIFI, WIFI_KEY, None, since, len(self._wifi_ties),
            confirmed=confirmed,
        )
        self._remember_wifi_outage(critical=True)

    def _wifi_outage_snapshot(self) -> dict[str, Any] | None:
        """The standing outage as it is stored, or None (rule UP-04)."""
        since = self._wifi_down_at
        if since is None:
            return None
        stored = self.data.get(DATA_WIFI_OUTAGE)
        before = (
            stored.get(WIFI_OUTAGE_WORST, 0)
            if isinstance(stored, dict) else 0
        )
        worst = max(
            int(before) if isinstance(before, int) else 0,
            int(self._upstream_peak.get(WIFI_KEY, 0) or 0),
            int(self.suppressed_down_counts.get(WIFI_KEY, 0) or 0),
        )
        said = self._upstream_said.get(WIFI_KEY)
        held = self._upstream_held.get(WIFI_KEY)
        if said is not None:
            devices = said[3]
        elif held is not None:
            devices = held[3]
        else:
            devices = len(self._wifi_ties)
        return {
            WIFI_OUTAGE_SINCE: float(since),
            WIFI_OUTAGE_DECLARED: float(self._wifi_declared_from or since),
            WIFI_OUTAGE_FALLEN: {
                tracker: float(when)
                for tracker, when in self._wifi_fallen.items()
            },
            WIFI_OUTAGE_WORST: worst,
            WIFI_OUTAGE_DEVICES: int(devices or 0),
            WIFI_OUTAGE_TOLD: said is not None,
            WIFI_OUTAGE_PUSHED: self._wifi_down_push_owed(since),
            WIFI_OUTAGE_SCAN_DOWN: (
                float(self._wifi_scan_down_at)
                if self._wifi_scan_down_at is not None
                else None
            ),
            WIFI_OUTAGE_RECOVERING: (
                float(self._wifi_recovering_at)
                if self._wifi_recovering_at is not None
                else None
            ),
        }

    def _wifi_down_push_owed(self, since: float) -> bool:
        """Whether the down push has gone, or goes in this minute's sync.

        Marked as soon as it is owed, not when the push task has run,
        so the critical save of the same tick carries it to disk: a
        power cut in the minute after would otherwise push the down a
        second time, sounding (rule UP-09). Owed is what the push gate
        reads: past the grace, settled for a minute, with a row.
        """
        if WIFI_KEY in self._upstream_announced:
            return True
        if self._upstream_phase.get(WIFI_KEY) == "down":
            return True
        return (
            not self._in_startup_grace()
            and dt_util.utcnow().timestamp() - since >= UPSTREAM_SETTLE_SECONDS
            and WIFI_KEY in self.suppressed_down_counts
        )

    def _remember_wifi_outage(self, critical: bool = False) -> None:
        """Keep the standing outage in storage, or remove it once over.

        Written when the outage opens, and again whenever its start,
        fallen set, worst count or announcements change, so a restart
        resumes it as it stood; removed when it ends (James, 26 October
        2026; rule UP-04). It lives in the main file, which a routine
        write takes only when marked, so every change marks it.
        Opening, ending, and a change to whether its down was told or
        pushed are saved at once: a power cut that lost a push already
        sent would push the down a second time, sounding (rule UP-09).
        Any other change is saved with the next routine write and at a
        clean stop.
        """
        snapshot = self._wifi_outage_snapshot()
        if snapshot is None:
            if self.data.pop(DATA_WIFI_OUTAGE, None) is not None:
                self._mark_cold_dirty()
                self._critical = True
            return
        stored = self.data.get(DATA_WIFI_OUTAGE)
        if stored == snapshot:
            return
        if not isinstance(stored, dict) or any(
            stored.get(flag) != snapshot[flag]
            for flag in (WIFI_OUTAGE_TOLD, WIFI_OUTAGE_PUSHED)
        ):
            critical = True
        self.data[DATA_WIFI_OUTAGE] = snapshot
        self._mark_cold_dirty()
        if critical:
            self._critical = True

    def _wifi_resume_waiting(self) -> bool:
        """Whether a resumed outage still waits for the startup grace.

        After a restart the router has not reported yet, so which of the
        stored fallen trackers are home again is not known until the
        grace ends. Then each one reading home is counted as returned
        and each one still away as away, and the recovery is judged
        against the stored set as usual; one not known yet is heard when
        it comes home (_on_wifi_fallen_change). Nothing is added to the
        set: a tracker away before the outage was never in it (rules
        UP-04, UP-16).
        """
        if not self._wifi_resume_seed:
            return False
        if self._in_startup_grace():
            return True
        self._wifi_resume_seed = False
        if self._wifi_down_at is None:
            return False
        if not self.wifi_scan_configured:
            # No adapter answered through the grace, so nothing will
            # hear the network; the trackers decide alone.
            self._wifi_scan_down_at = None
        for tracker, fell_at in self._wifi_fallen.items():
            state = self.hass.states.get(tracker)
            if state is None:
                continue
            if state.state == STATE_NOT_HOME:
                self._wifi_not_home.setdefault(tracker, fell_at)
            elif state.state == STATE_HOME:
                self._wifi_returned.add(tracker)
        return False

    def _listen_to_wifi_fallen(self) -> None:
        """Listen to a resumed outage's stored fallen trackers.

        By entity id, not through the ties: after a restart the router
        integration may answer late, or a second one may stand while
        the one whose trackers fell is still loading, so the ties can
        be missing or formed without them and a tracker coming home
        would go unheard. The outage then never closed (rule UP-16).
        """
        self._stop_wifi_fallen_listener()
        if self._wifi_down_at is None or not self._wifi_fallen:
            return
        self._wifi_fallen_unsub = async_track_state_change_event(
            self.hass, sorted(self._wifi_fallen), self._on_wifi_fallen_change
        )

    def _stop_wifi_fallen_listener(self) -> None:
        """Stop listening to the fallen trackers: the outage is over or
        the entry unloads."""
        if self._wifi_fallen_unsub is not None:
            self._wifi_fallen_unsub()
            self._wifi_fallen_unsub = None

    @callback
    def _on_wifi_fallen_change(self, event: Event[EventStateChangedData]) -> None:
        """A resumed outage's fallen tracker reading home has returned.

        Away stays away, and no state, Home Assistant's placeholder or
        unavailable means not known yet. Inside the grace nothing is
        counted: the grace's end reads every one as it then stands
        (rule UP-16).
        """
        new_state = event.data.get("new_state")
        entity_id = event.data.get("entity_id")
        if (
            self._wifi_down_at is None
            or self._wifi_resume_seed
            or new_state is None
            or new_state.state != STATE_HOME
            or entity_id not in self._wifi_fallen
            or entity_id in self._wifi_returned
        ):
            return
        self._wifi_not_home.pop(entity_id, None)
        self._wifi_returned.add(entity_id)
        if self._wifi_recovering_at is not None:
            self._notify()

    def _drop_removed_wifi_fallen(self, now: float) -> None:
        """Let go of fallen trackers that can never come home.

        One whose entity is gone from the registry (its router
        integration deleted, or removed by hand), and one with no usable
        state for WIFI_FALLEN_UNUSABLE_SECONDS: none, Home Assistant's
        placeholder, or unavailable or unknown, as a router never reached
        again or an integration disabled leaves it. Left in the set
        either held the outage open for ever, claiming every device that
        failed meanwhile. The time runs from the first check that finds
        it without a usable state, or from the resume (rule UP-16).
        """
        registry = er.async_get(self.hass)
        unusable = self._wifi_fallen_unusable_since
        gone = []
        for tracker in self._wifi_fallen:
            if registry.async_get(tracker) is None:
                gone.append(tracker)
                continue
            if _usable_tracker_state(self.hass.states.get(tracker)):
                unusable.pop(tracker, None)
                continue
            if now - unusable.setdefault(tracker, now) >= WIFI_FALLEN_UNUSABLE_SECONDS:
                gone.append(tracker)
        if not gone:
            return
        LOGGER.info(
            "device_sentinel: %d fallen wifi tracker(s) removed or "
            "without a usable state for %d hours were let go: %s",
            len(gone),
            int(WIFI_FALLEN_UNUSABLE_SECONDS // 3600),
            ", ".join(sorted(gone)),
        )
        for tracker in gone:
            unusable.pop(tracker, None)
        for tracker in gone:
            self._wifi_fallen.pop(tracker, None)
            self._wifi_returned.discard(tracker)
        self._remember_wifi_outage()

    def _resume_wifi_outage(self, now: float) -> None:
        """Take back, once a run, a Wi-Fi outage open before the restart.

        Read from the stored outage alone (James, 26 October 2026): its
        start as backdated, its fallen trackers with their fall times,
        its worst count, its announced count, whether its down was told
        and pushed, and the scan's down mark. So it stands again exactly
        as it was, across any number of restarts: its devices stay
        claimed, its start does not move, and its recovery carries its
        real length and its worst moment (rules UP-04, UP-11). A file
        written by 0.27.4 or before holds no stored outage, and nothing
        is resumed. A stored outage that is not whole is dropped.

        A down the bus heard is owed its restored, with the count it was
        announced with (rule UP-10); one held for the grace is held
        again. A down already pushed is marked so: no second down push,
        which as a first push would sound, and its over push is still
        owed when it ends (rule UP-09).
        """
        if self._wifi_resumed:
            return
        self._wifi_resumed = True
        if self._wifi_down_at is not None:
            return
        stored = self.data.get(DATA_WIFI_OUTAGE)
        if stored is None:
            return
        if not wifi_outage_ok(stored) or stored[WIFI_OUTAGE_SINCE] > now:
            LOGGER.info(
                "device_sentinel: a stored wifi outage that was not "
                "whole was dropped, and nothing was resumed"
            )
            self.data.pop(DATA_WIFI_OUTAGE, None)
            self._dirty = True
            return
        since = float(stored[WIFI_OUTAGE_SINCE])
        self._wifi_down_at = since
        self._wifi_declared_from = float(stored[WIFI_OUTAGE_DECLARED])
        self._wifi_hold_since = None
        self._seed_wifi_fallen(since)
        self._wifi_fallen = {
            str(tracker): float(when)
            for tracker, when in stored[WIFI_OUTAGE_FALLEN].items()
        }
        self._wifi_resume_seed = True
        # What each tracker read before the restart is not known, so its
        # time without a usable state runs from the resume (rule UP-16).
        self._wifi_fallen_unusable_since = {
            tracker: now for tracker in self._wifi_fallen
        }
        self._listen_to_wifi_fallen()
        scan_down = stored[WIFI_OUTAGE_SCAN_DOWN]
        self._wifi_scan_down_at = (
            float(scan_down) if scan_down is not None else None
        )
        # A recovery under way stays under way: its row was written
        # once, and the Problem List keeps reading recovering
        # (rules UP-16, LIST-13).
        recovering = stored[WIFI_OUTAGE_RECOVERING]
        self._wifi_recovering_at = (
            float(recovering) if recovering is not None else None
        )
        # The open down row in the events is this outage's own.
        self._wifi_down_row_written = True
        # The worst count carries across, so the return records it.
        self._upstream_peak[WIFI_KEY] = int(stored[WIFI_OUTAGE_WORST])
        devices = int(stored[WIFI_OUTAGE_DEVICES])
        if stored[WIFI_OUTAGE_TOLD]:
            self._upstream_said[WIFI_KEY] = (UPSTREAM_WIFI, None, since, devices)
            self._upstream_owed.add(WIFI_KEY)
        else:
            self._say_upstream_down(UPSTREAM_WIFI, WIFI_KEY, None, since, devices)
        if stored[WIFI_OUTAGE_PUSHED]:
            self._upstream_announced[WIFI_KEY] = devices
            self._upstream_phase[WIFI_KEY] = "down"
        LOGGER.info(
            "device_sentinel: wifi outage open since %s resumed after "
            "the restart",
            dt_util.utc_from_timestamp(since).isoformat(),
        )

    def _wifi_restore(self, now: float) -> None:
        """Close the outage: called when every fallen tracker is home
        (ruling #430) or when the recovery has settled (#423, #424)."""
        since = self._wifi_down_at
        # Read before the outage is cleared, or there is nothing left
        # to ask: whatever it was claiming keeps that claim for a
        # short while (ruling #433), dated from the outage rather
        # than from now, so a device that never comes back still
        # shows as down since the network went.
        # The second stamp is wall clock, not the sample's own time.
        # `upstream_down_since` takes no clock and cannot be given
        # one, so a stamp from the sample would be compared against a
        # different clock and the window would never expire.
        closed_at = self._wifi_handback_now()
        # Read while the outage still stands, or its count is gone.
        ended = self._upstream_ended(WIFI_KEY)
        self._wifi_handback = {
            device_id: (since or now, closed_at)
            for device_id in self._wifi_claimed_now()
        }
        self._wifi_down_at = None
        self._wifi_declared_from = None
        self._wifi_first_fall = None
        self._wifi_resume_seed = False
        self._stop_wifi_fallen_listener()
        self._wifi_down_row_written = False
        self._wifi_burst = []
        left =len(self._wifi_fallen) - len(self._wifi_returned)
        self._wifi_fallen = {}
        self._wifi_returned = set()
        self._wifi_fallen_unusable_since = {}
        self._wifi_announced = False
        self._wifi_peak_back = 0
        self._wifi_quiet_ticks = 0
        LOGGER.info(
            "device_sentinel: wifi outage over after %.0fs, %d "
            "device(s) still away and handed back to per-device "
            "detection",
            max(0.0, now - (since or now)),
            left,
        )
        self._record_system_event(
            SYS_WIFI_UP,
            scope=WIFI_KEY,
            duration=now - since if since is not None else None,
            **ended,
        )
        # No count is passed, so the restored carries the count its
        # down was announced with: ties rebuilt during the outage must
        # not give the pair two numbers (rule UP-10).
        self._say_upstream_restored(
            UPSTREAM_WIFI, WIFI_KEY, None, since, now
        )
        # Over, so nothing is left to resume (rule UP-04).
        self._remember_wifi_outage()

    def _wifi_confirmed_count(self) -> int:
        """How many claimed devices already read unavailable.

        Evidence, never a gate (ruled 4 September): a real outage on
        a fleet of slow integrations would show zero here at
        declaration and still be real. Recorded because it separates
        a network outage from a tracker-side artifact after the fact.

        Claimed is what the outage claims: a tied device whose tracker
        was away before the outage began is not one, so its
        unavailable entity is not counted (rules UP-10, UP-15).
        """
        claimed = {
            device_id
            for device_id in self.data.get(DATA_DEVICES, {})
            if self.wifi_down_since(device_id) is not None
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

        Claimed for the life of the outage rather than while its own
        tracker happens to be away (ruling #411).

        The two are not the same and the difference is the fault the
        second fleet reported. Trackers lead and verdicts trail: on
        12 September the trackers were home 76 seconds after the peak
        while the entities behind them were still going unavailable on
        their own timers, 41 seconds to four minutes on the measured
        3 September outage. A claim tied to the live tracker state had
        expired by the time its casualties reached the problem list,
        so forty-odd devices were listed individually and nothing
        named the cause.

        Not a device a radio stack owns (ruling #412): Zigbee, Z-Wave
        and Matter hardware has its own bridge rung and its own
        medium, and a Wi-Fi outage does not explain it. Everything
        else is either Wi-Fi or wired, and a wired device is counted
        among the casualties even though a wired tracker is never
        counted toward declaring an outage (ruling #413): declaring
        wants precision, attributing wants coverage.

        The claim ends when the outage does (ruling #426). Whatever is
        still down then is its own problem, with its own timing.
        """
        since = self._wifi_down_at
        if since is None:
            # The outage is over, and a device it claimed is given a
            # short window to come back before it becomes its own
            # problem (ruling #433). Hearing the network is not the
            # same as the devices on it being back, and neither is
            # the settle ending: on 14 September the settle closed
            # 120 seconds before the last tracker came home, and six
            # devices wrote their own rows inside that gap.
            held = self._wifi_handback.get(device_id)
            if held is not None:
                if self._wifi_handback_now() - held[1] < WIFI_HANDBACK_SECONDS:
                    return WIFI_KEY, held[0]
                self._wifi_handback.pop(device_id, None)
            return None
        if device_id in self._radio_owned:
            return None
        # A tied device whose tracker fell in this outage is claimed
        # on that evidence, whether or not a verdict has landed yet.
        # One whose tracker was already away when the outage began is
        # not a casualty of it, so its tracker claims nothing: it is
        # judged by its own failure time below, like any other device
        # (rule UP-15, ruling #409).
        tracker = self._wifi_ties.get(device_id)
        if tracker is not None and tracker in self._wifi_fallen:
            return WIFI_KEY, since
        # And so is anything else that failed inside the window, tie
        # or no tie. Without this the claim reaches only hardware the
        # router happens to track, and the devices that most need
        # explaining are the ones it does not: the reference fleet's
        # three presence sensors carry no tracker at all and were
        # listed individually through every outage it has had.
        record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
        began = record.get(DEV_FROZEN_SINCE)
        if began is not None and began >= since:
            return WIFI_KEY, since
        return None

    def _wifi_backdate(self) -> None:
        """Date the outage from the first device that noticed it.

        Ruling #440. The outage is first dated from its first tracker
        to leave, which is when the router noticed, not when the
        network went. A tied device whose tracker fell in this outage
        and whose own failure began no more than WIFI_LOOKBACK_SECONDS
        earlier went down with the network, not before it; left as
        it was, the rule for an already broken device kept each one's
        row, and 53 were listed beside the second fleet's outage row
        on 16 September. Only a device the router saw leave can say
        so, and only within the router's own detection time, so a
        device broken for hours keeps its row.

        Run at declaration and on every tick, because a detector dates
        a failure when it began, and that verdict can land after the
        outage was declared. A start moved back moves its down row with
        it, so the row, the stored state and the Problem List give one
        start (rules UP-11, LIST-13). The tick's run also keeps the
        stored outage up to date (rule UP-04).
        """
        if self._wifi_down_at is None or self._wifi_declared_from is None:
            return
        self._wifi_backdate_once(self._wifi_down_at, self._wifi_declared_from)
        self._remember_wifi_outage()

    def _move_wifi_down_row(self, since: float) -> None:
        """Re-date the standing outage's down row to its start.

        Found wherever it sits: its recovering and withdrawn rows may
        come after it. A return met first means no down row is open
        (rules UP-11, LIST-13). Only once this outage's own row is
        written: the backdate at declaration runs before it, and the
        open row it would find then is one an older release left behind.
        """
        if not getattr(self, "_wifi_down_row_written", False):
            return
        for row in reversed(self.data.get(DATA_SYSTEM_EVENTS) or []):
            if not isinstance(row, dict) or row.get(SYS_SCOPE) != WIFI_KEY:
                continue
            kind = row.get(SYS_KIND)
            if kind == SYS_WIFI_UP:
                return
            if kind == SYS_WIFI_DOWN:
                row[SYS_WHEN] = since
                self._mark_cold_dirty()
                return

    def _wifi_backdate_once(self, down_at: float, declared_from: float) -> None:
        """One pass of the backdate; see _wifi_backdate."""
        floor = declared_from - WIFI_LOOKBACK_SECONDS
        earliest = down_at
        records = self.data.get(DATA_DEVICES, {})
        for device_id, tracker in self._wifi_ties.items():
            if device_id in self._radio_owned:
                continue
            if tracker not in self._wifi_fallen:
                continue
            began = (records.get(device_id) or {}).get(DEV_FROZEN_SINCE)
            if began is not None and floor <= began < earliest:
                earliest = float(began)
        if earliest < down_at:
            LOGGER.info(
                "device_sentinel: wifi outage dated back %.0fs to the "
                "first device that noticed it",
                down_at - earliest,
            )
            self._wifi_down_at = earliest
            self._move_wifi_down_row(earliest)

    def wifi_burst_held(self) -> set[str]:
        """Tied devices whose rows wait for the router (ruling #446).

        A device's own integration can notice a network drop minutes
        before the router marks it away, so a burst of verdicts can
        land before an outage can be declared. When enough tied
        devices to declare an outage fail inside one burst window,
        each waits WIFI_BURST_HOLD_SECONDS from its own failure: the
        outage claims it if one is declared in that time, and its row
        appears, dated from its failure, if not.

        Once an outage stands its claim decides for every device it
        has taken, and a burst device the router has not marked away
        yet keeps waiting out its own hold, because the router's
        second wave can come minutes after its first: on the second
        fleet, 16 September, five minutes. Nothing is held for a
        device the router does not track or a radio stack owns.
        """
        if not self._wifi_ties:
            return set()
        now = dt_util.utcnow().timestamp()
        records = self.data.get(DATA_DEVICES, {})
        # While an outage stands, a burst device that failed within
        # the lookback of it waits for as long as the outage does: its
        # tracker may leave in a later wave, and until then neither
        # rule of the claim reaches it.
        standing_floor = (
            self._wifi_declared_from - WIFI_LOOKBACK_SECONDS
            if self._wifi_down_at is not None
            and self._wifi_declared_from is not None
            else None
        )
        recent: list[tuple[float, str]] = []
        for device_id in self._wifi_ties:
            if device_id in self._radio_owned:
                continue
            record = records.get(device_id) or {}
            if record.get(DEV_FROZEN_CATEGORY) is None:
                continue
            began = record.get(DEV_FROZEN_SINCE)
            if began is None:
                continue
            waiting = 0.0 <= now - began <= WIFI_BURST_HOLD_SECONDS
            if standing_floor is not None and standing_floor <= began <= now:
                waiting = True
            if waiting:
                recent.append((float(began), device_id))
        recent.sort()
        need = self._wifi_burst_needed()
        held: set[str] = set()
        start = 0
        for end in range(len(recent)):
            while recent[end][0] - recent[start][0] > (
                WIFI_BURST_WINDOW_SECONDS
            ):
                start += 1
            if end - start + 1 >= need:
                held.update(device for _, device in recent[start:end + 1])
        return held

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
            "medium_census": dict(sorted(self._wifi_medium_census.items())),
            "medium_seen": {
                tracker: self.wifi_medium_of(tracker)
                for tracker in sorted(self.data.get(DATA_WIFI_MEDIUM, {}))
            },
            "medium_scores": {
                tracker: dict(score)
                for tracker, score in sorted(
                    self.data.get(DATA_WIFI_MEDIUM, {}).items()
                )
            },
            "medium_rejected": dict(sorted(self.wifi_medium_rejected.items())),
            "wired_skipped": list(self._wifi_wired_skipped),
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
        """What the Wi-Fi sensor publishes beside its state.

        The recovery is published as well as the outage, because the
        probe can only record what the integration says. Without
        these a staged outage shows the declare and the clear with
        nothing in between, which is exactly where the settle is
        being decided.
        """
        fell = len(self._wifi_fallen)
        return {
            "tied_devices": len(self._wifi_ties),
            "trackers_not_home": len(self._wifi_not_home),
            "down_since": (
                dt_util.utc_from_timestamp(self._wifi_down_at).isoformat()
                if self._wifi_down_at is not None
                else None
            ),
            "threshold": self._wifi_burst_needed(),
            "fallen": fell,
            "returned": len(self._wifi_returned),
            "recovery_needed": self._wifi_recovery_needed(fell),
            "announced": self._wifi_announced,
            "quiet_ticks": self._wifi_quiet_ticks,
            "settle_losses": self._wifi_settle_losses,
            "networks": list(self.wifi_networks) or None,
            "medium_rejected": sum(self.wifi_medium_rejected.values()),
        }
