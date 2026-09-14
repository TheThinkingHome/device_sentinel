# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: router_ties.py, Version: 0.21.6 (2026-09-14)

"""Router ties: which watched devices a router says have left.

Renamed from `wifi.py` in 0.20.8, with no change in behaviour, ahead
of a second capability taking that name. The split is by what answers
the question rather than by subject (#391). This file asks a router
integration which of the watched devices left the network, which is
attribution: how many, and which ones, so they are counted rather
than listed. Whether the network itself is up is a different question
with a different source, answered from the host without any router
integration at all, and it belongs in `wifi.py`.

Everything below is unchanged from the file this replaces, including
the `wifi` upstream kind and the `Bridge: WiFi` sensor, because both
are a published contract and the rename does not touch them.

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

Known limitations, recorded rather than hidden: a restart during an
outage stays silent, because restored trackers produce no fresh
not_home transitions to count; and an access point that keeps
broadcasting while its backhaul fails leaves stations associated and
trackers reading home, a fault this detector cannot see.
"""

from __future__ import annotations

import math

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
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_DEVICES,
    DATA_ROUTERS_SEEN,
    DATA_WIFI_MEDIUM,
    DEV_FROZEN_SINCE,
    DEFAULT_EXCLUDED_INTEGRATIONS,
    ROUTER_INTEGRATIONS,
    WIFI_BURST_FLOOR,
    WIFI_BURST_SHARE,
    WIFI_RECOVERY_SHARE,
    WIFI_SETTLE_TICKS,
    WIFI_BURST_WINDOW_SECONDS,
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)

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

# Positive wireless confirmation, again only where published: an
# SSID exists for a wireless client and not for a wired one. Unifi
# spells it `essid` and Fritz `ssid`. Recorded in the diagnostics
# rather than acted on: no measured case needs it, and a tie the
# exclusion already kept does not need a second reason to stay.
SSID_KEYS = ("essid", "ssid")

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
# This is the whole of the answer to the stripped reading found on
# 14 September, and the only one available. When a client leaves,
# TP-Link strips its network name and band and reports it as wired,
# which is byte for byte what it publishes for a genuine wired
# client. A tie rebuild landing between the attribute update and the
# state update reads `home` carrying that shape. Refusing the shape
# was tried and reverted: it turns every real wired device on the
# fleet into unknown. The two cases cannot be told apart from one
# reading, so they are told apart by how often each occurs. The share was measured over ten days,
# where the tightest contradiction on either fleet was 2 against 22.
# On six samples one bad reading is sixteen percent: on 14 September
# three known-wireless devices went to unknown on a single stripped
# reading each, hours after a fresh install. A share means nothing
# until there are enough samples for it to be a share of anything.
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
    the declared outage. Nothing persists across a restart, which is
    the recorded restart-mid-outage limitation.
    """

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
                self._wifi_medium_rejected[tracker] = (
                    self._wifi_medium_rejected.get(tracker, 0) + 1
                )
        return judged

    def wifi_medium_of(self, tracker: str) -> str:
        """What the evidence says this tracker is."""
        return medium_from_score(self._wifi_medium_score(tracker))

    @property
    def wifi_medium_rejected(self) -> dict[str, int]:
        """Readings the scoring has discarded, per tracker, this
        session (ruling #428)."""
        return dict(self._wifi_medium_rejected)

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
                    for kind, value in owner.connections:
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
            tracker = None
            # Rung 1: a normalized MAC in the device's connections.
            for kind, value in device.connections:
                if kind != dr.CONNECTION_NETWORK_MAC:
                    continue
                found = tracker_by_mac.get(normalize_mac(value) or "")
                if found and found[1] != owner:
                    tracker = found[0]
                    break
            # Rung 2: the full twelve-hex MAC inside an identifier.
            if tracker is None:
                for _domain, ident in device.identifiers:
                    bare = _HEX_ONLY.sub("", str(ident).lower())
                    for mac, found in tracker_by_mac.items():
                        if mac in bare and found[1] != owner:
                            tracker = found[0]
                            break
                    if tracker:
                        break
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

    async def _sight_router_integrations(self) -> None:
        """Exclude a router integration the first time it is seen
        (ruling #420).

        Fires once per integration, ever. A new install gets these
        from the default list and never reaches here; an install that
        already exists gets one added the first time it appears. After
        that the integration is recorded and never new again, so a
        person who unexcludes it keeps that choice, which is what
        keeps this from being a default that reasserts itself.

        The write is grow-only. Updating options reloads the entry, so
        a sighting that adds nothing must not write at all, or every
        upgrade on every system with an already-excluded router does a
        pointless reload and re-runs this on the way back up.
        """
        present = self._router_integrations_present()
        if not present:
            return
        seen = set(self.data.get(DATA_ROUTERS_SEEN) or [])
        fresh = present - seen

        # Recorded whether or not anything is added, and before the
        # options are touched. Whether or not: a router already on
        # the person's list must still stop being new, or the day
        # they unexclude it the next restart excludes it again, which
        # is the reasserting default this rule exists to avoid.
        # Before: updating options reloads the entry, and a reload
        # that reads these as unseen would add them again on the way
        # back up, forever.
        if fresh:
            self.data[DATA_ROUTERS_SEEN] = sorted(seen | present)
            await self._save_now()
        if not fresh:
            return

        stored = self.entry.options.get(CONF_EXCLUDED_INTEGRATIONS)
        current = list(
            stored if stored is not None else DEFAULT_EXCLUDED_INTEGRATIONS
        )
        adding = [name for name in sorted(fresh) if name not in current]
        if not adding:
            return

        LOGGER.info(
            "device_sentinel: router integration(s) %s seen for the "
            "first time and excluded from watching; unexclude on the "
            "Configure screen to watch them",
            ", ".join(adding),
        )
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **self.entry.options,
                CONF_EXCLUDED_INTEGRATIONS: current + adding,
            },
        )

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
                self._wifi_returned.add(entity_id)

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
        if not self._wifi_ties:
            return
        if self._wifi_down_at is not None:
            self._sample_wifi_recovery(now)
            return
        if self._wifi_hold_since is None:
            return
        if now - self._wifi_hold_since < WIFI_HOLD_SECONDS:
            return
        # The same threshold the burst used (ruling #421). These
        # disagreed in 0.21.0: the burst scaled with the fleet and
        # the hold did not, so a burst of seven decaying to three
        # still declared on a fleet where three is ordinary churn.
        still_gone = len(self._wifi_not_home)
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
        self._wifi_hold_since = None
        self._seed_wifi_fallen(since)
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
        self._record_system_event(
            SYS_WIFI_DOWN, scope=WIFI_KEY, devices=len(self._wifi_ties)
        )
        self._say_upstream_down(
            UPSTREAM_WIFI, WIFI_KEY, None, since, len(self._wifi_ties),
            confirmed=confirmed,
        )

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
        LOGGER.info(
            "device_sentinel: wifi scan hears the network again, "
            "%d of %d fallen tracker(s) home; the settle decides "
            "when the outage ends",
            len(self._wifi_returned),
            len(self._wifi_fallen),
        )
        if self._wifi_recovering_at is None:
            self._wifi_recovering_at = now
            self._notify()
        self._sample_wifi_recovery(now)

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
        """
        fell = len(self._wifi_fallen)
        if not fell:
            return
        back = len(self._wifi_returned)

        if back >= fell:
            # Every member of the fallen set is home, so there is
            # provably nothing left to wait for (ruling #430).
            # Checked before the
            # announce, because a recovery that is already complete
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
        self._wifi_announced = False
        self._wifi_peak_back = 0
        self._wifi_quiet_ticks = 0
        self._wifi_settle_losses = 0
        self._wifi_recovering_at = None

    def _wifi_declare(self, now: float, still_gone: int) -> None:
        """Declare the outage, dated from the first fall."""
        since = self._wifi_first_fall or self._wifi_hold_since or now
        self._wifi_down_at = since
        self._wifi_hold_since = None
        self._seed_wifi_fallen(since)
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
        left = len(self._wifi_fallen) - len(self._wifi_returned)
        self._wifi_fallen = {}
        self._wifi_returned = set()
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
            return None
        if device_id in self._radio_owned:
            return None
        # A tied device whose tracker fell in this outage is claimed
        # on that evidence, whether or not a verdict has landed yet.
        tracker = self._wifi_ties.get(device_id)
        if tracker is not None and (
            tracker in self._wifi_fallen or tracker in self._wifi_not_home
        ):
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
            "medium_rejected": dict(sorted(self._wifi_medium_rejected.items())),
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
            "medium_rejected": sum(self._wifi_medium_rejected.values()),
        }
