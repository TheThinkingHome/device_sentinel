# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_freeze.py, Version: 0.27.10 (2026-10-27)

"""Freeze: the learned rhythm, the window, and the verdict.

The failure this exists for is the quiet one: a device that has
stopped reporting while its entities still hold their last values,
so every dashboard and automation keeps believing a dead reading.
Unavailable and unknown are caught here too, along with a device that
has never spoken since it was discovered.

Each device is measured against its own learned rhythm plus a grace
margin, never a fixed timeout, because a chatty motion sensor and a
twice-a-day rain gauge cannot share a number. A device is judged
frozen only once it has learned enough days; until then it is watched
for unavailable only. Buttons and remotes that speak only when pressed
learn a very long rhythm and are seldom called frozen (rules FRZ-01,
FRZ-07).

One of the subject modules split out of coordinator.py, along the
seam measured by which methods call which (rule CODE-11). These are
mixins on the coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

import math
from typing import Any
from homeassistant.const import (
    STATE_UNKNOWN,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from .device_fields import device_field
from .device_type import SOURCE_OWNER, TYPES_THAT_REPORT_ON_USE, list_name, measures
from .records import BAD_STATES
from .outage_detail import parse_detail
from .stacks import available_speaks, node_dead, node_up, reader_for_domain

from .rhythm_rules import lognormal_days, lognormal_rhythm
from .const import (
    CONF_UNAVAILABLE_MUTED_LABELS,
    EVENT_RESTING,
    DEV_LOGNORMAL_DAYS,
    RULE_LOGNORMAL,
    RULE_TRIMMED,
    BROKER_SCOPE,
    SYS_DURATION,
    SYS_DETAIL,
    SYS_WHEN,
    SYS_SCOPE,
    SYS_KIND,
    SYS_WIFI_UP,
    SYS_WIFI_DOWN,
    SYS_BROKER_UP,
    SYS_BROKER_DOWN,
    SYS_INTEGRATION_UP,
    SYS_RESTART,
    SYS_UNCLEAN_RESTART,
    SYS_INTEGRATION_DOWN,
    SYS_BRIDGE_UP,
    SYS_BRIDGE_DOWN,
    DATA_SYSTEM_EVENTS,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    DEFAULT_FREEZE_DELTA_LOW_MIN,
    TAINT_FLOOR_MINUTES,
    TAINT_SHARE_PCT,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_DOWN_SINCE,
    NODE_DEAD_STATE,
    DEV_FROZEN_SINCE,
    DEV_DOWN_BEGAN_AS,
    DEV_LAST_ACTIVITY,
    DEV_WATCHED_FROM,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    FREEZE_NOT_REPORTED_SECONDS,
    FREEZE_REF_RHYTHM_FAST,
    FREEZE_REF_RHYTHM_SLOW,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    LOGGER,
    PAIRING_GRACE_SECONDS_DEFAULT,
    TAINT_UNAVAILABLE,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
    WIFI_KEY,
    TAINT_UPSTREAM_DOWN,
    TAINT_CLOCK_JUMP,
    CLOCK_RESET_THRESHOLD_SECONDS,
)


class FreezeMixin:
    """Freeze: the learned rhythm, the window, and the verdict."""

    @staticmethod
    def _trimmed_maximum(
        daily_maximum_gaps: list[float],
    ) -> tuple[float | None, set[int]]:
        """Return (operative rhythm, indices of set-aside outliers).

        The top TRIM_TOP_K daily maxima are set aside as possible flukes and
        the rhythm is the maximum of the rest, so one bad day moves nothing
        while a spike that recurs raises the rhythm. Below TRIM_MIN_SAMPLES
        days nothing is trimmed, since an outlier cannot yet be told from the
        true rhythm.

        Only the newest DAILY_MAX_KEEP days are read, however many are
        stored, because more days mean more chances at a long gap and would
        widen every freeze window. The slice is here, where the rhythm is
        computed, so no caller can forget; the two callers that style a cell
        from the returned indices slice their own copy to match (rule FRZ-03).
        The wait in use is the shorter of this and the Log-Normal Percentile
        (`_freeze_rhythm`, rule FRZ-05).
        """
        daily_maximum_gaps = daily_maximum_gaps[-DAILY_MAX_KEEP:]
        if not daily_maximum_gaps:
            return None, set()
        if not all(
            isinstance(gap, (int, float)) and not isinstance(gap, bool) and math.isfinite(gap)
            for gap in daily_maximum_gaps
        ):
            # Anything but a number gives no rhythm, as an empty history does,
            # rather than a failure.
            return None, set()
        if len(daily_maximum_gaps) < TRIM_MIN_SAMPLES:
            return max(daily_maximum_gaps), set()
        by_value_descending = sorted(
            range(len(daily_maximum_gaps)),
            key=lambda index: daily_maximum_gaps[index],
            reverse=True,
        )
        set_aside_indices = set(by_value_descending[:TRIM_TOP_K])
        survivors = [
            gap
            for index, gap in enumerate(daily_maximum_gaps)
            if index not in set_aside_indices
        ]
        return max(survivors), set_aside_indices

    def _freeze_deltas(self) -> tuple[float, float]:
        """Return (delta_low, delta_high) in seconds from the options.

        The two freeze-config sliders: delta-low a fast-end grace
        floor in minutes, delta-high a slow-end grace ceiling in
        hours. Stored in their slider units, returned in seconds
        because the margin math is all in seconds.
        """
        options = self.entry.options
        low_min = options.get(
            CONF_FREEZE_DELTA_LOW, DEFAULT_FREEZE_DELTA_LOW_MIN
        )
        high_hr = options.get(
            CONF_FREEZE_DELTA_HIGH, DEFAULT_FREEZE_DELTA_HIGH_HR
        )
        return float(low_min) * 60.0, float(high_hr) * 3600.0

    def _freeze_grace(self, rhythm: float) -> float:
        """Return the grace margin for a rhythm, in seconds (rule FRZ-06).

        grace = a * rhythm^p, with a and p solved so the curve passes through
        delta-low grace at the fast reference rhythm and delta-high grace at
        the slow one. The two deltas set the whole shape, and the result is
        clamped to [delta-low, delta-high], so they are also the floor and
        ceiling. The rhythm itself is never touched here: grace is only the
        patience added on top of it.
        """
        delta_low, delta_high = self._freeze_deltas()
        # Solve the power curve through the two reference points.
        p = math.log(delta_high / delta_low) / math.log(
            FREEZE_REF_RHYTHM_SLOW / FREEZE_REF_RHYTHM_FAST
        )
        a = delta_low / (FREEZE_REF_RHYTHM_FAST**p)
        grace = a * (rhythm**p)
        return min(delta_high, max(delta_low, grace))

    def _esphome_flags(self, device_id: str) -> tuple[bool | None, bool | None]:
        """Return an ESPHome device's deep-sleep and connection flags.

        Home Assistant keeps both only in the ESPHome integration's runtime
        data: whether the device deep-sleeps, which nothing public says, and
        whether its connection is up, which the device's Status sensor shows.
        ESPHome sets the connection flag before it writes the entities
        unavailable on a drop, and before any state arrives on a reconnect.
        The read is wrapped, so a missing entry or attribute, or a value that
        is not True or False, answers None and leaves the device on the
        ordinary freeze rule. The first failure per entry is logged once at
        info, so a moved field shows without filling the log (rule STACK-08).
        """
        entry_id = self._entry_of_device.get(device_id)
        if entry_id is None:
            return None, None
        try:
            runtime = self.hass.config_entries.async_get_entry(entry_id).runtime_data
            deep_sleep = runtime.device_info.has_deep_sleep
            connected = runtime.available
            if not isinstance(deep_sleep, bool) or not isinstance(connected, bool):
                # None or any other shape is a changed field, not an answer.
                raise TypeError(f"{type(deep_sleep).__name__}, {type(connected).__name__}")
            return deep_sleep, connected
        except Exception:  # noqa: BLE001
            if entry_id not in self._deep_sleep_unreadable:
                self._deep_sleep_unreadable.add(entry_id)
                LOGGER.info(
                    "device_sentinel: could not read whether an ESPHome "
                    "device deep-sleeps or is connected; it is judged by "
                    "the freeze rule"
                )
            return None, None

    def _esphome_deep_sleep(self, device_id: str) -> bool | None:
        """Whether an ESPHome device deep-sleeps, or None if unknown (rule STACK-08)."""
        return self._esphome_flags(device_id)[0]

    def _awake_esphome(self, device_id: str) -> bool:
        """Whether this is an ESPHome device whose connection speaks for it.

        An ESPHome device that does not deep-sleep is never newly judged
        frozen while Home Assistant's connection to it is up, because a device
        that hangs loses the connection with everything else. An entity of
        its own reading unavailable while the connection is up, such as a
        firmware update entity with the ESPHome dashboard stopped, does not
        change this. A deep-sleep device shows available while it sleeps, so
        it keeps the freeze rule, and so does a device whose flags cannot be
        read (rules FRZ-07, STACK-07).
        """
        if self._watched.get(device_id) != "esphome":
            return False
        return self._esphome_flags(device_id) == (False, True)

    def _awake_matter(self, device_id: str) -> bool:
        """Whether this is a Matter device whose being available speaks for it.

        A Matter device not behind a bridge, of a type that reports only on
        use, is never newly judged frozen while any of its entities reads
        available, whatever powers it. Such a device reports only when
        someone uses it, so a learned rhythm is a guess and its frozen
        verdicts are noise. A lost one is still reported unavailable, since
        Matter marks it away and Home Assistant follows within minutes.
        A sensor, or any other type, keeps the freeze rule, because Matter can
        call a silent sensor available. So does a device whose type cannot be
        read, one whose entities read nothing but unknown, and one behind a
        Matter bridge, which may keep a dead sensor reachable (rules FRZ-07,
        STACK-06).
        """
        if not available_speaks(self._watched.get(device_id)):
            return False
        known = self.type_of(device_id)  # type: ignore[attr-defined]
        words = known.get("words")
        if not isinstance(words, str) or list_name(words) not in TYPES_THAT_REPORT_ON_USE:
            return False
        # A child device, or one gone from the registry, keeps the rule.
        device = dr.async_get(self.hass).async_get(device_id)
        if device_field(device, "via_device_id", "") is not None:
            return False
        # A type read from the entities is not trusted over a measuring
        # entity: a sensor with a switch is still a sensor. A type the owner
        # set is trusted.
        if known.get("source") != SOURCE_OWNER and measures(
            er.async_entries_for_device(er.async_get(self.hass), device_id)
        ):
            return False
        return True

    def _matter_available_now(self, device_id: str) -> bool:
        """Whether _awake_matter applies now: some entity of the device reads
        something other than unknown or unavailable (rule STACK-06).

        The page and the Slow Reporting Devices card read this, so neither
        says a device is spared while its entities read nothing but unknown.
        """
        if not self._awake_matter(device_id):
            return False
        states = self._live_entity_states(device_id)  # type: ignore[attr-defined]
        known = [s for s in states if s not in (STATE_UNKNOWN, EVENT_RESTING)]
        if not known:
            # A button never pressed reads unknown, and its battery is the only
            # value it shows, so any entity of its own holding a value shows it
            # available. One that reads nothing at all keeps the freeze rule.
            known = [
                s for s in self._states_of(self._own_entities.get(device_id, ()))  # type: ignore[attr-defined]
                if s not in (STATE_UNKNOWN, EVENT_RESTING)
            ]
        return bool(known) and not all(s in BAD_STATES for s in known)

    def _dropped_esphome(self, device_id: str) -> bool:
        """Whether an ESPHome device that does not sleep has lost its connection.

        Such a device is unavailable whatever its Status sensor reads, and
        nothing its entities show while the connection is down is the device
        speaking: ESPHome keeps the Status sensor available and switches it
        off on a drop (rule STACK-07).
        """
        if self._watched.get(device_id) != "esphome":
            return False
        return self._esphome_flags(device_id) == (False, False)

    def _connection_only(self, device_id: str) -> bool:
        """Whether an ESPHome device has nothing to report but its connection:
        every entity of its own switched on is a firmware notice or a command
        button, whatever it has switched off (rule WATCH-04).
        """
        return (
            self._watched.get(device_id) == "esphome"
            and device_id in self._devices_with_entities
            and device_id not in self._devices_enabled_real  # type: ignore[attr-defined]
        )

    def _esphome_back(self, device_id: str, record: dict[str, Any]) -> None:
        """An ESPHome connection coming back is the device speaking, because
        ESPHome connects only when the device answers (rule STACK-07).

        Read each sweep, so a reconnect is noticed whatever its entities do;
        after a restart the first reading counts as coming back. Taken only
        while a down verdict stands, and not while the deciding entities
        still say unavailable: that is a sensor down on a live device, not a
        device back.
        """
        if self._watched.get(device_id) != "esphome":
            return
        connected = self._esphome_flags(device_id) == (False, True)
        before = self._esphome_was_connected.get(device_id)  # type: ignore[attr-defined]
        self._esphome_was_connected[device_id] = connected  # type: ignore[attr-defined]
        if not connected or before is True:
            return
        if record.get(DEV_FROZEN_CATEGORY) is None:
            return
        states = self._live_entity_states(device_id)  # type: ignore[attr-defined]
        known = [s for s in states if s not in (STATE_UNKNOWN, EVENT_RESTING)]
        if known and all(s in BAD_STATES for s in known):
            return
        self._record_activity(  # type: ignore[attr-defined]
            device_id, self._entry_of_device.get(device_id)
        )

    def _dead_node(self, device_id: str) -> bool:
        """Whether the device's own stack says its node is dead (rule STACK-05).

        Read from the node status sensor a stack keeps, as Z-Wave JS does.
        Such a device is unavailable while the sensor reads dead, because Home
        Assistant keeps its other entities available and nothing else would
        show it. Z-Wave learns a node is dead only when a command to it fails,
        so this catches a device somebody tried to reach; one nobody reaches
        is left to the freeze rule. A sensor that is switched off, missing or
        unreadable says nothing, and neither does a stack without one.
        """
        entity_id = self._node_status_entity.get(device_id)
        if entity_id is None:
            self._dead_nodes.discard(device_id)
            return False
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None or entry.disabled_by is not None:
            # Switched off says nothing from now on.
            self._dead_nodes.discard(device_id)
            return False
        domain = self._watched.get(device_id)
        state = self.hass.states.get(entity_id)
        reading = state.state if state is not None else None
        if reading is not None and node_dead(domain, reading):
            self._dead_nodes.add(device_id)
            return True
        if reading is not None and node_up(domain, reading):
            self._dead_nodes.discard(device_id)
            return False
        # Unreadable or not yet known, as through a reload or a restart:
        # the last word holds until the stack says otherwise, also
        # across a restart through the saved outage start.
        if device_id in self._dead_nodes:
            return True
        record = self.data[DATA_DEVICES].get(device_id)
        saved = record.get(DEV_DOWN_SINCE) if isinstance(record, dict) else None
        # Only a node known dead is held: an outage that began some other way
        # is not.
        return (
            isinstance(saved, list)
            and len(saved) == 2
            and saved[1] == NODE_DEAD_STATE
        )

    def _freeze_rhythm(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Return the rhythm in use for a device, kept in memory (rule FRZ-23).

        The minute check asks for every device's wait every minute, but the
        wait changes only when a day folds in, a reset is made, the Freeze
        and Unavailable Detection settings change, or the record is loaded
        afresh. Each kept
        result carries a stamp of its inputs: the day list itself, its length
        and newest day, the count since a reset, and the two settings. The
        fold's append and trim change the length and newest day; every other
        writer replaces the list. A stamp that no longer matches means the
        inputs moved, so the wait is worked out again and nothing has to
        remember to clear it. Nothing is written to disk.
        """
        daily = record.get(DEV_DAILY_MAX)
        if not isinstance(daily, list):
            return self._compute_freeze_rhythm(record)
        since = record.get(DEV_LOGNORMAL_DAYS)
        stamp = (
            len(daily),
            daily[-1] if daily else None,
            since if isinstance(since, (int, float, type(None))) else repr(since),
            self._freeze_deltas(),
        )
        # One entry per device record, which lives as long as the device, so a
        # replaced day list overwrites the device's entry rather than leaving
        # the old list behind. The store is cleared if it ever holds more than
        # twice the house's devices, so records for deleted devices cannot
        # build up.
        memo = self._rhythm_memo
        kept = memo.get(id(record))
        if (
            kept is not None
            and kept[0] is record
            and kept[1] is daily
            and kept[2] == stamp
        ):
            return kept[3]
        found = self._compute_freeze_rhythm(record)
        if found is not None:
            found["window"] = found["rhythm"] + self._freeze_grace(found["rhythm"])
        if len(memo) > 2 * len(self.data.get(DATA_DEVICES) or {}) + 64:
            memo.clear()
        memo[id(record)] = (record, daily, stamp, found)
        return found

    def _compute_freeze_rhythm(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Work out the rhythm in use for a device, and both rules' figures.

        The rhythm in use is the shorter of the Trimmed Maximum and the
        Log-Normal Percentile (rule FRZ-05). After bad days the Trimmed
        Maximum is stretched and the Log-Normal Percentile, which sets them
        aside, is shorter; after a device starts reporting more often, the
        Trimmed Maximum follows within 14 days while the Log-Normal
        Percentile, reading up to 42, lags. The grace margin rises with the
        rhythm, so the shorter rhythm always gives the shorter wait. A tie
        goes to the Trimmed Maximum, the rule a device has from its first
        armed day.

        None where the device is not armed (rule FRZ-01). The Log-Normal
        Percentile is None before 28 days, or 28 days since a reset, and the
        Trimmed Maximum is then the only rule. Each rule's days are the days
        it read, bad days included, as its name gives them: "14-Day Trimmed
        Maximum", "37-Day Log-Normal Percentile" (rule FRZ-04).
        """
        daily = record.get(DEV_DAILY_MAX) or []
        if len(daily) < FREEZE_ARMING_DAYS:
            return None
        if not all(
            isinstance(gap, (int, float)) and not isinstance(gap, bool) and math.isfinite(gap)
            for gap in daily
        ):
            # A history holding anything but a number cannot be judged, so the
            # device waits as a young one does, rather than its minute check and
            # its page failing. Only a fault could put one there; the file check
            # removes them on load.
            return None
        trimmed, _ = self._trimmed_maximum(daily)
        if trimmed is None or trimmed <= 0:
            return None
        found: dict[str, Any] = {
            "trimmed": trimmed,
            "trimmed_days": min(len(daily), DAILY_MAX_KEEP),
            "lognormal": None,
            "lognormal_days": None,
            "rule": RULE_TRIMMED,
            "rhythm": trimmed,
        }
        fit = lognormal_rhythm(daily, lognormal_days(record))
        # The fit itself rides along, so the fold's slowdown check reads
        # it rather than working the rule out a second time.
        found["fit"] = fit
        if fit is not None:
            found["lognormal"] = fit["rhythm"]
            found["lognormal_days"] = fit["days"]
            if fit["rhythm"] < trimmed:
                found["rule"] = RULE_LOGNORMAL
                found["rhythm"] = fit["rhythm"]
        found["days"] = (
            found["lognormal_days"]
            if found["rule"] == RULE_LOGNORMAL
            else found["trimmed_days"]
        )
        return found

    def _init_rule_counts(self) -> None:
        """Start the day's counts of the two freeze rules (rule FRZ-23).

        Held in memory and begun again at a restart; the line they make is
        written into the Telemetry report at each fold. `_lognormal_listed`
        remembers, for each device listed while the Log-Normal Percentile was
        in use, when it was listed and how much longer the Trimmed Maximum
        would have waited, so its recovery can say whether the Trimmed Maximum
        would ever have listed it.
        """
        self._rule_counts_since: float = dt_util.utcnow().timestamp()
        # Each device's wait, kept until its inputs change (rule FRZ-23).
        self._rhythm_memo: dict[int, tuple[Any, Any, Any, Any]] = {}
        self._lognormal_listings = 0
        self._lognormal_only = 0
        self._lognormal_listed: dict[str, tuple[float, float]] = {}
        self.rule_day_line: str | None = None

    def _note_frozen_listing(self, device_id: str, record: dict[str, Any], now: float) -> None:
        """Count a frozen listing made while the Log-Normal Percentile decided."""
        found = self._freeze_rhythm(record)
        if not found or found["rule"] != RULE_LOGNORMAL:
            return
        lead = (
            found["trimmed"] + self._freeze_grace(found["trimmed"])
            - found["rhythm"] - self._freeze_grace(found["rhythm"])
        )
        self._lognormal_listings += 1
        self._lognormal_listed[device_id] = (now, lead)

    def _note_frozen_cleared(self, device_id: str, now: float) -> None:
        """Count a recovery the Trimmed Maximum would never have listed."""
        listed = self._lognormal_listed.pop(device_id, None)
        if listed is not None and now - listed[0] < listed[1]:
            self._lognormal_only += 1

    def rule_counts_fold(self, now: float) -> None:
        """Write the day's line of the two rules and begin the counts again."""
        trimmed = lognormal = 0
        # Watched devices only (rule WATCH-09).
        for _device_id, record in self.watched_records():
            found = self._freeze_rhythm(record)
            if not found:
                continue
            if found["rule"] == RULE_LOGNORMAL:
                lognormal += 1
            else:
                trimmed += 1
        since = dt_util.as_local(dt_util.utc_from_timestamp(self._rule_counts_since))
        self.rule_day_line = (
            f"From {since:%b %d %H:%M}: {trimmed} device(s) waited on the "
            f"{RULE_TRIMMED} and {lognormal} on the {RULE_LOGNORMAL} at the "
            f"fold; {self._lognormal_listings} frozen listing(s) were made "
            f"under the {RULE_LOGNORMAL}, {self._lognormal_only} of them "
            f"by a device that spoke again before the {RULE_TRIMMED} would "
            f"have listed it."
        )
        self._rule_counts_since = now
        self._lognormal_listings = 0
        self._lognormal_only = 0

    def use_trimmed_maximum(self, device_id: str) -> bool:
        """Start a device's Log-Normal Percentile count again, by hand.

        The dashboard's button does what a firmware update, a battery change
        or a re-pair does, for a change Device Sentinel cannot see. The device
        waits on the Trimmed Maximum until it has 28 new days. False for a
        device with no record (rule FRZ-05).
        """
        record = self.data[DATA_DEVICES].get(device_id)
        if record is None or self.is_held(device_id):  # type: ignore[attr-defined]
            # A removed device's held record has no page (rule WATCH-07).
            return False
        record[DEV_LOGNORMAL_DAYS] = 0
        self._mark_cold_dirty()
        self._mark_changed()
        # Kept in the log: the learned day count is gone for good, and
        # this line is its only trace (rule GEN-10).
        LOGGER.info(
            "%s set to the %s by hand, until it has 28 new days",
            self._device_name(device_id),
            RULE_TRIMMED,
        )
        return True

    @staticmethod
    def rule_label(found: dict[str, Any] | None) -> str | None:
        """The rule in use as people read it: "37-Day Log-Normal Percentile"."""
        if not found:
            return None
        return f"{found['days']}-Day {found['rule']}"

    def _freeze_window(self, record: dict[str, Any]) -> float | None:
        """Return the freeze window for a device, in seconds, or None.

        The window is the rhythm in use plus the grace margin (rule FRZ-06).
        None means the device is not yet armed: it has too few learned days
        for a trustworthy rhythm, so it is watched for unavailable and unknown
        but never called frozen, because there is no window to miss (rule
        FRZ-01). The rhythm in use is the shorter of the two rules
        (`_freeze_rhythm`).
        """
        found = self._freeze_rhythm(record)
        if found is None:
            return None
        window = found.get("window")
        if window is None:
            window = found["rhythm"] + self._freeze_grace(found["rhythm"])
        return window

    def _recovered_during_pairing(self, device_id: str, now: float) -> bool:
        """Return whether this device recovered during a pairing window.

        A pairing window is open for the whole coordinator, so any device
        behind it that recovers while the window is open, or within the grace
        after it closed, is a pairing candidate (rule FRZ-16). The per-device
        signal is the integration domain, and which stack owns a domain is
        that stack's own question, not this detector's (rule STACK-01): a
        domain no stack claims, or a stack with no reader, gives no reader
        here. A device that merely shares a domain with the stack is caught
        too, but that costs one discarded gap, the safe direction. No reader,
        no bridge, or any failure returns False and the taint decision stands
        (rule FRZ-15).
        """
        reader = reader_for_domain(
            self._bridge_readers, self._watched.get(device_id)
        )
        if reader is None:
            return False
        try:
            return reader.pairing_active_within(
                PAIRING_GRACE_SECONDS_DEFAULT, now
            )
        except Exception as err:  # noqa: BLE001 - a fault falls to the taint
            LOGGER.debug(
                "Pairing reader for %s faulted, treating as not pairing: %s",
                device_id,
                err,
            )
            return False

    @staticmethod
    def _retract_today_max(
        record: dict[str, Any], gap: float, before: float | None
    ) -> None:
        """Undo the daily-max bump a now-discarded gap just made.

        The gap update runs before the pairing, maintenance, handled,
        set-aside and commanded checks, so a discarded gap that was the day's
        largest is pulled back out, or it would widen the rhythm it should
        never touch. Only the exact value is retracted, and only when it is
        the current max, so a larger unrelated gap is left alone. The day's
        longest gap from before this one goes back in its place, so the real
        gaps the device had earlier that day are kept (rule FRZ-15).
        """
        if record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] == gap:
            record[DEV_TODAY_MAX] = before

    def _taint_debounce(self, record: dict[str, Any]) -> float:
        """Return the unavailable a device tolerates before a taint.

        Short absences are mesh blips and the silence around them is still
        learned; an unavailable at or over this is real downtime and the gap
        is discarded. The value is a floor plus a share of the device's own
        freeze window, so a fast device keeps the floor while a slow one earns
        more patience. An unarmed device has no window yet, so it falls back
        to the floor alone (rule FRZ-14).
        """
        floor = (
            float(TAINT_FLOOR_MINUTES) * 60.0
        )
        share = (
            float(TAINT_SHARE_PCT) / 100.0
        )
        window = self._freeze_window(record)
        if window is None:
            return floor
        return floor + window * share

    def _device_down_category(
        self, device_id: str, record: dict[str, Any], now: float, mutes: bool = True
    ) -> str | None:
        """Return the down category for a device, or None if alive.

        If any live entity is fresh, the device is alive, whatever its other
        entities read; a device is down only when nothing on it is reporting.
        The category is then read from the deciding entities
        (_live_entity_states, main entities first): unavailable when every one
        that says anything says unavailable, an unknown among them counting as
        nothing, and frozen when they hold values the clock says are stale. A
        device whose main entities are unavailable while another entity of its
        own is actively reporting is alive (_reporting_through_others; rules
        UNAV-01, UNAV-02).
        """
        # A device muted for everything keeps its clock and rhythm but is
        # given no verdict of any kind, so the mute is enforced here where
        # the judging runs, not by hiding the verdict afterwards (rule
        # MUTE-01).
        if device_id in self._muted_devices:
            return None
        # Two mutes, each its own kind: the freeze mute silences frozen and
        # never reported, the unavailable mute unavailable. A device muted for
        # both is given no verdict. With mutes False, the verdict as it would be
        # with no freeze or unavailable mute: whether the device is still down
        # at all (rule MUTE-06).
        muted_freeze = mutes and self._freeze_muted(device_id)
        muted_unavailable = mutes and self._unavailable_muted(device_id)
        if muted_freeze and muted_unavailable:
            return None
        standing = record.get(DEV_FROZEN_CATEGORY)
        # A device gone while muted for unavailable is given nothing, unless its
        # trouble began as a freeze the freeze mute does not cover, which stands
        # until the device reports. How the trouble began decides, not the order
        # of the two (rules MUTE-06, UNAV-02).
        gone = (
            FREEZE_CATEGORY_FROZEN
            if not muted_freeze
            and (
                standing == FREEZE_CATEGORY_FROZEN
                or (
                    standing in (FREEZE_CATEGORY_UNAVAILABLE, None)
                    and record.get(DEV_DOWN_BEGAN_AS) == FREEZE_CATEGORY_FROZEN
                )
            )
            else None
        )

        # A hub, or a device a hub controls, is judged by its hub: never frozen,
        # never "never reported". A freeze-muted hub that goes down is still
        # reported (rules STACK-09, MUTE-06).
        if self.judged_by_hub(device_id):  # type: ignore[attr-defined]
            category = self._hub_category(device_id, record, now)  # type: ignore[attr-defined]
            if category == FREEZE_CATEGORY_UNAVAILABLE and muted_unavailable:
                return gone
            return self._muted_away(category, muted_freeze, muted_unavailable)

        # An ESPHome device with nothing but firmware notices and command
        # buttons, such as a Bluetooth proxy, is judged by its connection alone,
        # its only report: unavailable while it is dropped, never frozen or never
        # reported (rule WATCH-04).
        if self._connection_only(device_id):
            if self._dropped_esphome(device_id):
                return None if muted_unavailable else FREEZE_CATEGORY_UNAVAILABLE
            if standing == FREEZE_CATEGORY_UNAVAILABLE and not self._awake_esphome(device_id):
                # Its connection cannot be read: held until it can.
                return None if muted_unavailable else standing
            return None

        # Never reported: zero lifetime events past the grace window. Checked
        # first because such a device has no rhythm to miss and may have no live
        # entity to read. A device with learned history has reported, whatever
        # its clock and counter say now, because a lost clocks file empties both
        # (rule FRZ-09). A freeze-muted device is never called never reported,
        # and is read on below, so one that is unavailable, dead or dropped is
        # still told (rule MUTE-06).
        if (
            not muted_freeze
            and record[DEV_EVENT_COUNT] == 0
            and record[DEV_LAST_ACTIVITY] is None
            and not record.get(DEV_DAILY_MAX)
        ):
            if device_id not in self._devices_with_entities:
                # Nothing that could report, so never reported says nothing about the
                # device. A ZHA coordinator owns no entity and never will, and would be
                # reported while working perfectly. A device whose entities are all
                # disabled still qualifies: those entities exist, and the row is the
                # prompt to switch them on (rule FRZ-09).
                return None
            first = record.get(DEV_FIRST_OBSERVED)
            if first is not None:
                try:
                    observed = dt_util.parse_datetime(first)
                    age = now - observed.timestamp() if observed else 0.0
                except (ValueError, AttributeError):
                    age = 0.0
                if age >= FREEZE_NOT_REPORTED_SECONDS:
                    return FREEZE_CATEGORY_NEVER_REPORTED
            return None

        window = self._freeze_window(record)

        # An ESPHome device whose connection is down is unavailable, and a
        # standing frozen verdict escalates to it (rule STACK-07).
        if self._dropped_esphome(device_id):
            return self._gone_under_mute(device_id, record, now, gone) if muted_unavailable else FREEZE_CATEGORY_UNAVAILABLE

        # A node its own stack calls dead is unavailable, and a standing frozen
        # verdict moves to it, as for ESPHome (rule STACK-05).
        if self._dead_node(device_id):
            return self._gone_under_mute(device_id, record, now, gone) if muted_unavailable else FREEZE_CATEGORY_UNAVAILABLE

        # Frozen: armed, and silent past its window while entities
        # still hold values. Judged first because it is the timer's
        # own verdict.
        silence = self._observed_silence(record, now, device_id, window)
        frozen = (
            window is not None
            and silence is not None
            and silence >= window
            and not muted_freeze
        )

        states = self._live_entity_states(device_id)
        if not states:
            # Nothing readable. Two different situations arrive here and only one
            # of them can be judged.
            #
            # A device whose entities are in the registry but have no state objects
            # has not finished loading. Every restart passes through that state while
            # the owning integration sets up, and during it the clock alone reads a
            # down device as frozen. The next tick corrects the verdict when the
            # states appear, but the correction writes a kind onto an item that
            # should never have moved, and pushes each time (rule LIST-06).
            #
            # A device with no registry entities at all is the case this branch is
            # for: there is nothing to read and nothing coming, so the clock is the
            # whole story.
            if self._has_registered_entities(device_id):
                if self._node_reads_up(device_id):  # type: ignore[attr-defined]
                    # Nothing readable but the node status, and it says the node is up:
                    # judged by the clock alone.
                    return FREEZE_CATEGORY_FROZEN if frozen else None
                if muted_unavailable and standing == FREEZE_CATEGORY_UNAVAILABLE:
                    # A standing unavailable verdict hidden by the mute has passed the
                    # debounce already (rule UNAV-03).
                    self._gone_under_mute(device_id, record, now, gone, listed=True)
                return self._held(standing, gone, muted_freeze, muted_unavailable)
            return FREEZE_CATEGORY_FROZEN if frozen else None

        # Unknown is neither down nor alive: a button reads unknown until it is
        # first pressed, so a device whose entities say nothing but unknown is
        # judged by its clock (rule UNAV-02).
        known = [s for s in states if s not in (STATE_UNKNOWN, EVENT_RESTING)]
        if not known or all(s in BAD_STATES for s in known):
            # An awake ESPHome device whose entities read unknown is still
            # connected, so frozen is not shown unless a frozen verdict already
            # stands, because a device of buttons reads unknown until one is pressed
            # (rules STACK-07, UNAV-02). A Matter button never pressed is the same
            # while an entity of its own, such as its battery, holds a value (rule
            # STACK-06).
            if (
                frozen
                and record.get(DEV_FROZEN_CATEGORY) != FREEZE_CATEGORY_FROZEN
                and (self._awake_esphome(device_id) or self._matter_available_now(device_id))
            ):
                frozen = False
            if known:
                # Every entity that says anything says unavailable: the device is down
                # now, whatever the clock says, which needs no arming because it reads
                # present state. Unless another entity of its own has reported since: a
                # device actively reporting is alive, whatever its main entity reads
                # (rule UNAV-01).
                if self._reporting_through_others(device_id):  # type: ignore[attr-defined]
                    return FREEZE_CATEGORY_FROZEN if frozen else None
                return self._gone_under_mute(device_id, record, now, gone) if muted_unavailable else FREEZE_CATEGORY_UNAVAILABLE
            # Nothing but unknown: a device already down stays down until it says
            # something, never told as a recovery (rule UNAV-02).
            # Unavailable outranks frozen, and frozen unknown; a standing unknown
            # does not stop the clock.
            if standing == FREEZE_CATEGORY_UNAVAILABLE:
                if muted_unavailable and standing == FREEZE_CATEGORY_UNAVAILABLE:
                    # A standing unavailable verdict hidden by the mute has passed the
                    # debounce already (rule UNAV-03).
                    self._gone_under_mute(device_id, record, now, gone, listed=True)
                return self._held(standing, gone, muted_freeze, muted_unavailable)
            if self._gone_as_unavailable(record) and (  # type: ignore[attr-defined]
                muted_unavailable or self._listed_but_for_mute(device_id, record)
            ):
                # Nothing but unknown on a device muted for unavailable whose outage
                # began as unavailable: still that outage, not a new freeze. Once the
                # mute is lifted it reads as a device never muted does: unavailable if
                # the outage lasted long enough to be listed, judged by its clock if it
                # was a blip. A device never gone is judged by its clock (rules MUTE-08,
                # UNAV-02).
                return gone if muted_unavailable else FREEZE_CATEGORY_UNAVAILABLE
            if frozen:
                return FREEZE_CATEGORY_FROZEN
            if standing == FREEZE_CATEGORY_UNKNOWN:
                return self._muted_away(standing, muted_freeze, muted_unavailable)
            return None

        # Some entity is not bad. If the clock says frozen and the non-bad
        # entities are stale, the device is frozen: a fresh entity would have
        # re-armed the timer, so frozen True here means the values are held, not
        # live. Unless the device's own connection says otherwise: an awake
        # ESPHome device whose connection is up has nothing new to say, which is
        # not a freeze, and an available Matter device of a type that reports
        # only on use is the same (rules FRZ-07, STACK-06, STACK-07). A verdict
        # already standing is kept until the device reports, so a device is not
        # told as recovered because a rule changed (rule UNAV-02).
        if (
            frozen
            and record.get(DEV_FROZEN_CATEGORY) != FREEZE_CATEGORY_FROZEN
            and (self._awake_esphome(device_id) or self._awake_matter(device_id))
        ):
            return None
        if frozen:
            return FREEZE_CATEGORY_FROZEN
        return None

    def _frozen_start(self, device_id: str, record: dict[str, Any], now: float) -> float:
        """When a freeze began: the device's last report plus its freeze window,
        counting only time Device Sentinel was listening, the moment it would
        have been listed. Worked out rather than kept, so a device listed again
        when a mute is lifted, or one that froze while muted, is dated from
        when the freeze began. Now, when that cannot be read (rule MUTE-08).
        """
        window = self._freeze_window(record)
        if window is None:
            return now
        found = self._silence_spans(record, now, device_id, window)
        if found is None:
            return now
        last, spans = found
        # The wall time at which the counted silence reached the window: walk
        # forward from the last report, stepping over each span nobody was
        # listening, however long (rule FRZ-10).
        at, remaining = last, window
        for start, end in sorted((max(a, last), b) for a, b in spans if b > last):
            if end <= at:
                continue
            start = max(start, at)
            if at + remaining <= start:
                break
            remaining -= start - at
            at = end
        return min(now, at + remaining)

    @staticmethod
    def _never_reported_start(record: dict[str, Any], now: float) -> float:
        """When a device qualified as never reported: first seen plus the wait,
        worked out as a freeze's start is, so a mute lifted later does not
        date it from the lift. Now, when that cannot be read (rule MUTE-08).
        """
        first = record.get(DEV_FIRST_OBSERVED)
        if not isinstance(first, str):
            return now
        try:
            observed = dt_util.parse_datetime(first)
        except (ValueError, TypeError):
            return now
        if observed is None:
            return now
        return min(now, observed.timestamp() + FREEZE_NOT_REPORTED_SECONDS)

    @staticmethod
    def _outage_began(record: dict[str, Any], now: float) -> float:
        """When the device as a whole went down, from its saved start, or now."""
        saved = record.get(DEV_DOWN_SINCE)
        if (
            isinstance(saved, list)
            and len(saved) == 2
            and isinstance(saved[0], (int, float))
            and not isinstance(saved[0], bool)
            and saved[0] <= now
        ):
            return float(saved[0])
        return now

    def _gone_under_mute(
        self,
        device_id: str,
        record: dict[str, Any],
        now: float,
        gone: str | None,
        *,
        listed: bool = False,
    ) -> str | None:
        """An unavailable verdict an unavailable mute hides, remembered once the
        outage has lasted past the debounce, so that a lift after its entities
        turn to unknown lists it as a device never muted would have been. Not
        persisted: after a restart such a device is judged by its clock (rule
        UNAV-02).
        """
        saved = self._saved_down_since(record)  # type: ignore[attr-defined]
        if saved is not None and (listed or now - saved[0] >= FREEZE_UNAVAILABLE_DEBOUNCE):
            self._unavailable_under_mute[device_id] = saved[0]  # type: ignore[attr-defined]
        return gone

    def _listed_but_for_mute(self, device_id: str, record: dict[str, Any]) -> bool:
        """Whether this outage was hidden by an unavailable mute after it
        had lasted long enough to be listed (see _gone_under_mute)."""
        saved = self._saved_down_since(record)  # type: ignore[attr-defined]
        start = self._unavailable_under_mute.get(device_id)  # type: ignore[attr-defined]
        return saved is not None and start is not None and saved[0] == start

    def _apply_freeze_verdict(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> bool:
        """Judge one device and store the verdict if it changed.

        Returns True when the verdict flipped, so the caller can
        refresh the sensor once per flip rather than on every reading.
        A debounce holds an unavailable or unknown verdict
        until the device has been down long enough to rule out a
        mid-transition flip; the frozen verdict needs no debounce
        because its window already is the wait.
        """
        category = self._device_down_category(device_id, record, now)
        # A record missing these fields is filled at load (rule STOR-19), so
        # this is the sweep's own guard for a record made some other way:
        # default them before reading, or the direct read raises KeyError and
        # the sweep's per-device guard skips that record.
        record.setdefault(DEV_FROZEN_CATEGORY, None)
        record.setdefault(DEV_FROZEN_SINCE, None)
        current = record[DEV_FROZEN_CATEGORY]
        # A verdict a mute takes away while the device is still down is
        # remembered, so its item leaves silently whichever kind it showed (rule
        # MUTE-07). Read before the verdict is stored, while the record still
        # holds it.
        if category is None and current is not None:
            if self._device_down_category(device_id, record, now, mutes=False) is not None:
                self._muted_down.add(device_id)  # type: ignore[attr-defined]
        elif category is not None:
            self._muted_down.discard(device_id)  # type: ignore[attr-defined]

        if category in (
            FREEZE_CATEGORY_UNAVAILABLE,
            FREEZE_CATEGORY_UNKNOWN,
        ):
            # Debounce the transition: only publish once the device
            # has read down for longer than a quick-succession flip.
            since = record.get(DEV_FROZEN_SINCE)
            # A hub's lost connection is already confirmed over two readings: it is
            # dated from when it was first seen gone and published without the
            # debounce (rules STACK-09, UNAV-03).
            hub_lost = (
                self.hub_down_since(device_id, now)  # type: ignore[attr-defined]
                if category == FREEZE_CATEGORY_UNAVAILABLE
                and self.is_hub(device_id)  # type: ignore[attr-defined]
                else None
            )
            if hub_lost is not None:
                # From when the connection went, whatever stood before it: an earlier
                # frozen verdict is not its start.
                if current != FREEZE_CATEGORY_UNAVAILABLE:
                    record[DEV_FROZEN_SINCE] = hub_lost
            elif current == FREEZE_CATEGORY_FROZEN:
                # A frozen device turns unavailable only once it has been gone past the
                # debounce, as any device does: a stack restart's first minute, before
                # its outage is confirmed and held, is not one (rule UNAV-03).
                saved = self._saved_down_since(record)  # type: ignore[attr-defined]
                if saved is None or (now - saved[0]) < FREEZE_UNAVAILABLE_DEBOUNCE:
                    return False
            elif current is None:
                if since is None:
                    # Dated from the saved start of the outage when one is held, because the
                    # sweep sees a drop up to a minute late, and after a restart much later.
                    # The debounce still counts from the moment the whole device went (rule
                    # UNAV-04).
                    record[DEV_FROZEN_SINCE] = self._outage_began(record, now)
                    self._dirty = True
                    # Critical, not merely dirty: the debounce counts
                    # from this stamp and it is cleared below, so a
                    # crash between one reaching disk and the other
                    # would bring a device back reported down for hours.
                    self._critical = True
                    return False
                if (now - since) < FREEZE_UNAVAILABLE_DEBOUNCE:
                    return False

        if category == current:
            # A blip stamps a down-since before any verdict is published. If the
            # device came back by republishing a retained value, its contact clock
            # never advanced, so the report path never ran and nothing there cleared
            # the stamp. Clear it here instead: a stamp with no verdict behind it has
            # nothing left to time, and leaving it would date the next outage from
            # the old blip and skip the debounce that outage is owed. A published
            # verdict is untouched, so a republish still cannot erase a standing
            # silence (rule FRZ-11).
            if (
                category is None
                and record.get(DEV_FROZEN_SINCE) is not None
            ):
                record[DEV_FROZEN_SINCE] = None
                self._dirty = True
                self._critical = True
            return False

        record[DEV_FROZEN_CATEGORY] = category
        # How the trouble began, saved with the record so a restart cannot turn
        # a freeze that went unavailable into a drop (rule UNAV-07). Kept while
        # a mute is all that took the verdict away, so lifting one of two mutes
        # finds how the trouble began; the device's next report clears it.
        if category is None and device_id not in self._muted_down:  # type: ignore[attr-defined]
            record[DEV_DOWN_BEGAN_AS] = None
        elif current is None and category is not None:
            record[DEV_DOWN_BEGAN_AS] = category
        if category == FREEZE_CATEGORY_FROZEN and current != FREEZE_CATEGORY_FROZEN:
            self._note_frozen_listing(device_id, record, now)
        elif current == FREEZE_CATEGORY_FROZEN:
            self._note_frozen_cleared(device_id, now)
        # Its own entities' last good values are kept from the verdict's
        # start, in this same immediate save, and forgotten when it ends,
        # a mute taking it away included (rule WATCH-12).
        if category is None:
            self._release_values(device_id, record)  # type: ignore[attr-defined]
        elif current is None:
            self._hold_values(device_id, record)  # type: ignore[attr-defined]
        if category is None:
            record[DEV_FROZEN_SINCE] = None
        elif current is None:
            record[DEV_FROZEN_SINCE] = record.get(DEV_FROZEN_SINCE) or (
                self._frozen_start(device_id, record, now)
                if category == FREEZE_CATEGORY_FROZEN
                else self._never_reported_start(record, now)
                if category == FREEZE_CATEGORY_NEVER_REPORTED
                else now
            )
        self._dirty = True
        self._critical = True
        LOGGER.debug(
            "Device %s freeze verdict: %s",
            self._device_name(device_id),
            category or "alive",
        )
        return True

    def _clear_freeze_verdict(
        self, device_id: str, record: dict[str, Any]
    ) -> None:
        """Clear a device's freeze verdict on its first real report.

        A device that reports is alive by definition, so its verdict
        and the down-since stamp are cleared at once. Called from the
        report path, this is the live-recovery half of detection: the
        moment a frozen device speaks, it leaves the report. Its held
        values and its watch end with it (rule WATCH-12).
        """
        self._release_values(device_id, record)  # type: ignore[attr-defined]
        if record.get(DEV_FROZEN_CATEGORY) is not None:
            if record.get(DEV_FROZEN_CATEGORY) == FREEZE_CATEGORY_FROZEN:
                self._note_frozen_cleared(device_id, dt_util.utcnow().timestamp())
            record[DEV_FROZEN_CATEGORY] = None
            record[DEV_DOWN_BEGAN_AS] = None
            record[DEV_FROZEN_SINCE] = None
            self._dirty = True
            self._critical = True
            # The moment a down device speaks, its item goes: the
            # recovery half of the lifecycle runs here in the report
            # path, not on the next tick.
            self._sync_problem_list()
            self._notify()
        elif record.get(DEV_FROZEN_SINCE) is not None:
            # A pending, un-published down stamp (inside the debounce);
            # clear it silently, no verdict was ever shown.
            record[DEV_FROZEN_SINCE] = None
            self._dirty = True
        if record.get(DEV_DOWN_BEGAN_AS) is not None:
            # Kept under a mute: a report ends it (rule UNAV-07).
            record[DEV_DOWN_BEGAN_AS] = None
            self._dirty = True

    def _judge_all_devices(self) -> None:
        """Judge every watched device for a freeze verdict.

        Runs on a timer tick and at startup. A flip on any device
        refreshes the sensors once. This is the sweep that fires the
        frozen verdict when a window closes with no report, and the
        unavailable/unknown verdict once the debounce clears.
        """
        now = dt_util.utcnow().timestamp()
        self._note_silences(now)
        self._trim_episodes(now)
        self._note_drops(now)
        if self._in_startup_grace():
            # Nothing is judged inside the grace: every verdict stays as the last
            # start left it, and the first sweep after the window shuts applies
            # whatever is still true then, once. Judging here would move a device
            # between kinds a minute into a start and push a false recovery (rule
            # WATCH-10).
            return
        flipped = False
        for device_id in self._watched:
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            if self._held_by_upstream(device_id, now):
                continue
            # Guard each device: one malformed record must never kill
            # the whole sweep, which would stop verdicts, saving and
            # refreshing for every device.
            try:
                self._esphome_back(device_id, record)
                if self._apply_freeze_verdict(device_id, record, now):
                    flipped = True
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Skipped a device in the freeze sweep after an "
                    "unexpected error judging it: %s",
                    self._device_name(device_id),
                )
        if flipped:
            self._notify()

    def _note_drops(self, now: float) -> None:
        """Start or end each device's outage from what it reads now (rule UNAV-04).

        Run each minute, inside the startup grace and for muted devices too,
        since muting stops judgment and not learning. It catches what no state
        change announces: an ESPHome connection dropping or coming back, and an
        entity renamed or removed.
        """
        for device_id in self._watched:
            self._settle_down(device_id, None)  # type: ignore[attr-defined]

    def _held_by_upstream(self, device_id: str, now: float) -> bool:
        """Whether the device's upstream is down or still handing back.

        A restart or an outage says nothing about the devices, on any stack
        (rule UP-06). While the device's broker, bridge, coordinator,
        integration or Wi-Fi network is down, and through the window its
        devices are given to rejoin (rule UP-08), the device's verdict stays
        exactly as it was, working, frozen or unavailable, and so does any
        debounce stamp. Home Assistant's own restart is held by the startup
        grace, which judges nothing. After that each device is judged on its
        own again.

        Without the hold, a device frozen before a bridge went down turns
        unavailable the moment the bridge goes, its frozen record closes, the
        bus hears it recover, and the brief tells one silence twice.
        """
        return self.upstream_down_since(device_id) is not None

    def _observed_silence(
        self,
        record: dict[str, Any],
        now: float,
        device_id: str | None = None,
        window: float | None = None,
    ) -> float | None:
        """How long this device was silent while anyone was listening (rule FRZ-10).

        Wall-clock silence counts the time the system was off, which no device
        is responsible for. On return the fastest reporters would cross their
        windows first, purely by arithmetic: a six-minute power cut produces
        frozen verdicts on every device with a window of a few minutes. What
        is counted instead is the silence before the last save plus the
        silence since this start, so the unwatched middle counts against
        nobody. The credit lapses the moment a device reports, and needs no
        cap: a device already silent beforehand carries that silence into the
        sum and is caught at the first sweep after the startup grace.
        """
        found = self._silence_spans(record, now, device_id, window)
        if found is None:
            return None
        last, spans = found
        return max(0.0, (now - last) - _covered(spans, last, now))

    def _silence_spans(
        self,
        record: dict[str, Any],
        now: float,
        device_id: str | None = None,
        window: float | None = None,
    ) -> tuple[float, list[tuple[float, float]]] | None:
        """Where a device's silence is counted from, and the spans inside
        it that count against nobody (_observed_silence)."""
        last = record.get(DEV_LAST_ACTIVITY)
        if not isinstance(last, (int, float)):
            return None
        # A device set aside, excluded or removed and then watched again is
        # judged from the moment it was watched again, because the time nobody
        # watched it is not its silence (rule WATCH-08). A clock restarted since
        # is later than that moment and wins.
        back = record.get(DEV_WATCHED_FROM)
        if isinstance(back, (int, float)) and not isinstance(back, bool) and last < back <= now:
            last = float(back)
        spans: list[tuple[float, float]] = []
        if (
            self._downtime > 0.0
            and self._last_alive is not None
            and last <= self._last_alive
        ):
            spans.append((self._last_alive, self._last_alive + self._downtime))
        if device_id is not None:
            spans.extend(self._outage_spans_for(device_id, last, window))
        return float(last), spans

    def _gap_untrusted(
        self, device_id: str, record: dict[str, Any], last: float, stamp: float
    ) -> str | None:
        """Why a gap ending now cannot be learned, or None (rule FRZ-12).

        A gap is learned only if Device Sentinel could trust all of it. Two
        things break that trust here.

        An upstream outage on the device's path that the device could have
        reported into. An outage shorter than the device's rhythm and lying
        wholly inside it, from the last report to the end of the rhythm, could
        only have swallowed a report the device was not yet due to send: the
        gap then ends at the next report, still within the device's normal
        range, so it is learned whole. An outage that reaches past the rhythm,
        into the grace when the device was due, or is as long as the rhythm,
        pollutes the gap, and it is forgotten. The outages are the stored ones
        and any still open, by the ladder the holds read
        (`upstream_down_since`), counted as running to this report, because an
        upstream's return is stored at the next minute check while
        Zigbee2MQTT's devices report the moment the bridge is back. A device
        with no rhythm yet forgets any gap an outage touched (rule UP-07).

        A jump of the system clock since the last minute check, which that
        check restarts every clock for, but only after this gap has been
        measured across it (rule FRZ-21).
        """
        spans = [
            (begun, ended)
            for begun, ended in self._outage_spans_for(device_id, last, None)
            if ended > last and begun < stamp
        ]
        held = self.upstream_down_since(device_id)
        if held is not None and held[1] < stamp:
            spans.append((held[1], stamp))
        if spans:
            found = self._freeze_rhythm(record)
            rhythm = found["rhythm"] if found else None
            if not (
                isinstance(rhythm, (int, float))
                and not isinstance(rhythm, bool)
                and math.isfinite(rhythm)
                and rhythm > 0
            ):
                # No usable rhythm: nothing to judge the outage against,
                # so the safe side, forgetting the gap.
                rhythm = None
            for begun, ended in spans:
                if (
                    rhythm is None
                    or ended - begun >= rhythm
                    or begun < last
                    or ended > last + rhythm
                ):
                    return TAINT_UPSTREAM_DOWN
        wall, mono = self._tick_wall, self._tick_mono
        if wall is not None and mono is not None:
            drift = (dt_util.utcnow().timestamp() - wall) - (self._monotonic() - mono)
            if abs(drift) >= CLOCK_RESET_THRESHOLD_SECONDS:
                return TAINT_CLOCK_JUMP
        return None

    def _outage_spans_for(
        self, device_id: str, last: float, window: float | None
    ) -> list[tuple[float, float]]:
        """The outages of this device's upstreams that its silence leaves out.

        Time an upstream was down is not counted as its devices' silence,
        exactly as Device Sentinel's own downtime is not (rules UP-07,
        FRZ-10). Otherwise, when a long bridge outage ends and the rejoin
        window closes, every living device behind it is announced frozen on
        hours it could not have been heard in.

        The outages come from the stored returns, so a restart in the middle
        of an outage cannot erase them. An outage that began only after the
        device was already past its window is left out, so a device frozen
        before the outage keeps that verdict.
        """
        found: list[tuple[float, float]] = []
        for start, end in self._device_outages(device_id):
            if end <= last:
                continue
            if window is not None and start >= last + window:
                continue
            found.append((start, end))
        return found

    def _device_outages(self, device_id: str) -> list[tuple[float, float]]:
        """Every stored outage of an upstream this device depends on."""
        spans = self._stored_outages()
        found: list[tuple[float, float]] = []
        stack = self._stack_for_device(device_id)
        if stack is not None:
            found.extend(spans.get((SYS_BRIDGE_UP, stack), []))
        domain = self._watched.get(device_id)
        if domain is not None:
            # An integration entry's outage is its own devices' only:
            # one Shelly plug's entry failing says nothing about the
            # plug beside it on another entry (rule UP-01). A row that
            # names no entry, written before entries were recorded,
            # still covers the integration.
            found.extend(spans.get((SYS_INTEGRATION_UP, domain), []))
            entry_id = self._entry_of_device.get(device_id)
            if entry_id is not None:
                found.extend(
                    spans.get((SYS_INTEGRATION_UP, f"{domain}|{entry_id}"), [])
                )
        if self._rides_the_broker(device_id):
            found.extend(spans.get((SYS_BROKER_UP, BROKER_SCOPE), []))
        if device_id in getattr(self, "_wifi_ties", {}):
            found.extend(spans.get((SYS_WIFI_UP, WIFI_KEY), []))
        return found

    def _stored_outages(self) -> dict[tuple[str, str], list[tuple[float, float]]]:
        """Each upstream's outages, from the system events, cached.

        An outage ends at its stored return and began that return's
        duration earlier, or at the matching stored fall when the
        return carries no duration, as a broker's return may not.
        """
        events = self.data.get(DATA_SYSTEM_EVENTS) or []
        last = events[-1] if events else None
        key = (len(events), last.get(SYS_WHEN) if isinstance(last, dict) else repr(last))
        cached = getattr(self, "_outage_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        falls = {
            SYS_BRIDGE_DOWN: SYS_BRIDGE_UP,
            SYS_INTEGRATION_DOWN: SYS_INTEGRATION_UP,
            SYS_BROKER_DOWN: SYS_BROKER_UP,
            SYS_WIFI_DOWN: SYS_WIFI_UP,
        }
        opened: dict[tuple[str, str], float] = {}
        spans: dict[tuple[str, str], list[tuple[float, float]]] = {}
        # Where each upstream last came back. An outage cannot have begun
        # before that, so a corrupt duration, or a fall stamped at zero, covers
        # at most the time since the last return and never the whole history,
        # which would silence every device behind that upstream for as long as
        # the row was stored.
        returned: dict[tuple[str, str], float] = {}
        fell: dict[tuple[str, str], float] = {}
        for row in events:
            if not isinstance(row, dict):
                continue
            kind, scope, when = row.get(SYS_KIND), row.get(SYS_SCOPE), row.get(SYS_WHEN)
            if (
                not isinstance(when, (int, float))
                or isinstance(when, bool)
                or not math.isfinite(when)
            ):
                continue
            if kind in (SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP):
                # Kept per entry, so its fall pairs with its own return
                # and its time is credited to its own devices only
                # (rule UP-07).
                entry_id = parse_detail(row.get(SYS_DETAIL))[0]
                if entry_id is not None:
                    scope = f"{scope}|{entry_id}"
            if kind in falls:
                opened.setdefault((falls[kind], str(scope)), float(when))
                fell.setdefault((falls[kind], str(scope)), float(when))
                continue
            if kind not in falls.values():
                continue
            slot = (str(kind), str(scope))
            duration = row.get(SYS_DURATION)
            began = opened.pop(slot, None)
            if (
                isinstance(duration, (int, float))
                and not isinstance(duration, bool)
                and math.isfinite(duration)
                and duration > 0
            ):
                began = float(when) - float(duration)
            # Every upstream stores its fall as well as its return. A
            # fall is recorded when it is noticed, which can be minutes
            # after the outage began (one dated from the start of the
            # run), never hours; a return whose fall is not on record is
            # credited at most that slack. So a corrupt duration cannot
            # forgive a silence that began long before, which would
            # credit a device frozen for days back under its window and
            # read it as recovered without speaking.
            recorded_fall = fell.pop(slot, None)
            floors = [returned.get(slot)]
            if recorded_fall is not None:
                floors.append(recorded_fall - _FALL_SLACK_SECONDS)
            else:
                floors.append(float(when) - _FALL_SLACK_SECONDS)
            floor = max((f for f in floors if f is not None), default=None)
            if began is not None and floor is not None and began < floor:
                began = floor
            if began is not None and began < when:
                spans.setdefault(slot, []).append((began, float(when)))
            returned[slot] = max(float(when), returned.get(slot, float(when)))
        self._outage_cache = (key, spans)
        return spans

    def _stop_spans(self) -> list[tuple[float, float]]:
        """Every stop of Device Sentinel itself, from the stored restarts.

        Each restart row carries the moment this run began and how long the
        previous run had been down, so a stop spans from that moment less its
        duration to that moment. Read from storage the way the upstream
        outages are, so several stops inside one long gap are all found, and
        the current run's own stop is added from memory in case its row is not
        yet written (rule FRZ-12).
        """
        events = self.data.get(DATA_SYSTEM_EVENTS) or []
        last = events[-1] if events else None
        key = (len(events), last.get(SYS_WHEN) if isinstance(last, dict) else repr(last))
        cached = getattr(self, "_stop_cache", None)
        if cached is None or cached[0] != key:
            spans: list[tuple[float, float]] = []
            for row in events:
                if not isinstance(row, dict) or row.get(SYS_KIND) not in (
                    SYS_RESTART, SYS_UNCLEAN_RESTART
                ):
                    continue
                when, duration = row.get(SYS_WHEN), row.get(SYS_DURATION)
                if (
                    not isinstance(when, (int, float))
                    or isinstance(when, bool)
                    or not math.isfinite(when)
                    or not isinstance(duration, (int, float))
                    or isinstance(duration, bool)
                    or not math.isfinite(duration)
                    or duration <= 0
                ):
                    continue
                spans.append((float(when) - float(duration), float(when)))
            self._stop_cache = (key, spans)
            cached = self._stop_cache
        spans = list(cached[1])
        if self._downtime > 0.0 and self._last_alive is not None:
            spans.append((self._last_alive, self._last_alive + self._downtime))
        return spans

    def _stopped_within(self, start: float, end: float) -> float:
        """How much of [start, end] Device Sentinel was stopped for.

        A completed gap is learned minus the time Device Sentinel was stopped,
        because a device that reported while nobody was listening was not
        silent, and a gap measuring the stop teaches every device it is slower
        than it is (rule FRZ-12).
        """
        return _covered(self._stop_spans(), start, end)

    @property
    def frozen_devices_list(self) -> list[dict[str, Any]]:
        """Return devices judged frozen, unknown, or unavailable.

        The Device: Frozen problem sensor. One row per down device, carrying
        its category (the worst of what its entities show) and the UTC time
        the verdict began, so a person sees what is down, how, and for how
        long. A device muted for the kind its verdict is, is left out at once,
        even while its verdict is held behind a down upstream, where the sweep
        does not judge it (rule MUTE-07).
        """
        rows: list[dict[str, Any]] = []
        for device_id, record in self.watched_records():
            if device_id in self._muted_devices:
                continue
            category = record.get(DEV_FROZEN_CATEGORY)
            if category is None:
                continue
            if self._muted_away(
                category,
                self._freeze_muted(device_id),
                self._unavailable_muted(device_id),
            ) is None:
                continue
            rows.append(
                {
                    "device_id": device_id,
                    "name": self._device_name(device_id),
                    "integration": self._watched.get(device_id, "?"),
                    "category": category,
                    "since": record.get(DEV_FROZEN_SINCE),
                }
            )
        rows.sort(key=lambda row: (row["category"], row["name"]))
        return rows

    def _broken_before(
        self, name: str, since: float | None, down_since: float
    ) -> bool:
        """Whether a device was already broken when its upstream went.

        Such a device keeps its own row, because the upstream is not the
        reason for it (rule UP-05). An outage dated from the start of this run
        is the exception: nothing inside the run happened before it, and every
        device behind it failed either with it or while it stood. Without
        this, a restart taken during an integration outage would list each
        device behind it on its own.
        """
        if since is None:
            return False
        if name in self._upstream_from_start:
            return False
        return since < down_since

    @property
    def reportable_down_rows(self) -> list[dict[str, Any]]:
        """Return the down devices worth reporting on their own.

        While a device's upstream is down, the fault is the upstream and the
        devices are its symptoms, so they are not reported, and the verdict
        itself holds as it was (rules UP-05, UP-06). Stopping one add-on would
        otherwise raise a problem and a push for every device behind it
        without naming the bridge, the one thing a person can act on.

        Two devices survive the suppression. One whose verdict began before
        the upstream went down was broken already, so it keeps its row rather
        than vanishing into the outage and reappearing when it clears. One
        still down after the upstream returns is the most useful row of the
        week: everything else came back and this did not.
        """
        rows: list[dict[str, Any]] = []
        # A burst of tied devices waits for the router before it is reported
        # (rule UP-15), and a device whose upstream has not loaded yet waits for
        # it (rule UP-04).
        held = self.wifi_burst_held() | self.loading_held()
        for row in self.frozen_devices_list:
            upstream = self.upstream_down_since(row["device_id"])
            if upstream is None:
                if row["device_id"] not in held:
                    rows.append(row)
                continue
            name, down_since = upstream
            since = row.get("since")
            if self._broken_before(name, since, down_since):
                rows.append(row)
        return rows

    def _down_with_upstream(
        self, record: dict[str, Any], name: str, down_since: float
    ) -> bool:
        """Whether a device behind a down upstream went down with it.

        A device's verdict is held while its upstream is down (rule UP-06),
        so on a house that was healthy when the upstream went no device is
        given one, and a count built from verdicts would read zero: no row, no
        push, and a brief saying none went down. What the device reads is
        counted instead, as Home Assistant shows it: a standing verdict, or the
        device reading unavailable or unknown as a whole (its saved outage
        start, rule UNAV-04). A device whose own verdict began before the
        outage keeps its own row and is not counted here (rule UP-05).
        """
        category = record.get(DEV_FROZEN_CATEGORY)
        if category is not None:
            return not self._broken_before(
                name, record.get(DEV_FROZEN_SINCE), down_since
            )
        return self._saved_down_since(record) is not None  # type: ignore[attr-defined]

    @property
    def suppressed_down_counts(self) -> dict[str, int]:
        """Return how many devices each downed upstream took down.

        Every upstream that claims a watched device has an entry, at
        zero before any device behind it reads down, so the row
        appears when the upstream goes rather than when a device is
        judged ("None of its 4 devices have gone down yet"). Devices
        muted for unavailable are counted, as they are in the total
        behind the upstream, and stay suppressed on their own (rules
        UP-05, UP-11).
        """
        counts: dict[str, int] = {}
        for device_id, record in self.watched_records():
            upstream = self.upstream_down_since(device_id)
            if upstream is None:
                continue
            name, down_since = upstream
            if name == WIFI_KEY:
                continue
            counts.setdefault(name, 0)
            if self._down_with_upstream(record, name, down_since):
                counts[name] += 1
        for row in self.frozen_devices_list:
            upstream = self.upstream_down_since(row["device_id"])
            if upstream is None or upstream[0] != WIFI_KEY:
                continue
            name, down_since = upstream
            since = row.get("since")
            if self._broken_before(name, since, down_since):
                continue
            counts[name] = counts.get(name, 0) + 1
        # A Wi-Fi outage counts the devices it took, not the devices Home
        # Assistant has finished marking down. The two are the same for a
        # bridge, whose devices are unavailable the moment it goes; not for a
        # network, where each device goes unavailable on its own timer, so the
        # count would creep up for many minutes while every device was down from
        # the first. The row lives for the whole outage on that count, so it
        # appears when the outage is declared rather than when the verdicts
        # catch up (rule UP-11).
        if self.wifi_down_at is not None:
            counts[WIFI_KEY] = max(
                counts.get(WIFI_KEY, 0), self.wifi_casualties
            )
        return counts

    @property
    def frozen_devices_count(self) -> int:
        """Return how many devices are down (frozen, unavailable, or
        unknown) right now."""
        return len(self.frozen_devices_list)

    def _freeze_muted(self, device_id: str) -> bool:
        """Return whether a device is muted from freeze judgment: frozen and
        never reported (rule MUTE-06).

        The same broad-to-narrow ladder as battery and signal (rule MUTE-04):
        the device keeps its clock and learned rhythm, so lifting the mute is
        instant and it returns with its history; it is simply never given a freeze or
        never-reported verdict. Unavailable has its own mute. This is the
        release valve for a device that is intermittent by nature.
        """
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_FREEZE_MUTED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_FREEZE_MUTED_LABELS, [])
        ):
            return True
        if device_id in options.get(CONF_FREEZE_MUTED_DEVICES, []):
            return True
        # A hub's mute covers the devices it controls (rule STACK-09).
        return self.hub_mutes(device_id, self._freeze_muted)  # type: ignore[attr-defined]

    def _freeze_muted_own(self, device_id: str) -> bool:
        """The freeze mute, as the reports name it (FRZ)."""
        return self._freeze_muted(device_id)

    def _unavailable_muted(self, device_id: str) -> bool:
        """Whether a device is muted from unavailable judgment: unavailable and
        dropping out, nothing else (rule MUTE-06).

        Set by label or on the device, never by integration; a hub's mute
        covers the devices it controls, as every other mute does.
        """
        options = self.entry.options
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_UNAVAILABLE_MUTED_LABELS, [])
        ):
            return True
        if device_id in options.get(CONF_UNAVAILABLE_MUTED_DEVICES, []):
            return True
        return self.hub_mutes(device_id, self._unavailable_muted)  # type: ignore[attr-defined]

    def _held(
        self,
        standing: str | None,
        gone: str | None,
        muted_freeze: bool,
        muted_unavailable: bool,
    ) -> str | None:
        """A standing verdict kept while nothing new can be read, with the
        device's mutes applied: an unavailable that began as a freeze keeps
        the freeze under an unavailable mute (rule MUTE-06).
        """
        if standing == FREEZE_CATEGORY_UNAVAILABLE and muted_unavailable:
            return gone
        return self._muted_away(standing, muted_freeze, muted_unavailable)

    @staticmethod
    def _muted_away(
        category: str | None, muted_freeze: bool, muted_unavailable: bool
    ) -> str | None:
        """A verdict with the kinds the device's mutes take away removed."""
        if muted_freeze and category in (
            FREEZE_CATEGORY_FROZEN,
            FREEZE_CATEGORY_NEVER_REPORTED,
        ):
            return None
        if muted_unavailable and category in (
            FREEZE_CATEGORY_UNAVAILABLE,
            FREEZE_CATEGORY_UNKNOWN,
        ):
            return None
        return category

    @staticmethod
    def _coerce_taint_reasons(devices: dict[str, dict[str, Any]]) -> int:
        """Give a stored boolean taint the reason it always meant (rule FRZ-14).

        The field was once true or false, and the only writer was the
        unavailable path, so a stored true means exactly that. False is left
        alone: falsy is still how every caller asks whether a device is
        tainted. Returns how many were converted, zero once storage has been
        written by this version.
        """
        converted = 0
        for record in devices.values():
            if record.get(DEV_TAINTED) is True:
                record[DEV_TAINTED] = TAINT_UNAVAILABLE
                converted += 1
        return converted


def _covered(spans: list[tuple[float, float]], start: float, end: float) -> float:
    """How much of [start, end] the spans cover, each minute counted once."""
    clipped = sorted(
        (max(a, start), min(b, end)) for a, b in spans if b > start and a < end
    )
    total = 0.0
    reach = start
    for a, b in clipped:
        if b <= reach:
            continue
        total += b - max(a, reach)
        reach = b
    return total


# How far before its recorded fall an outage may be dated.
_FALL_SLACK_SECONDS = 3600.0
