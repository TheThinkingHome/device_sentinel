# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.13 (2026-07-27)

"""Coordinator for the Device Sentinel integration.

Step 2: the passive telemetry recorder. It observes every watched
device's activity from the event bus, learns reporting-gap statistics
into storage, and reports coverage. It detects nothing and alerts
nothing; detection arrives in later steps.

Core rules implemented here, all ruled in the project document:
- Service-type devices are classified out entirely (no clocks, no
  statistics, no storage), with a startup audit log naming them.
- The completed-gap principle: learning ingests only finished gaps.
- The startup grace and the storm detector exclude echo stamps
  (restored states, republishes) from learning while still keeping
  the activity clock current.
- The taint rule: a gap that spans an unavailable stretch is an
  outage, not normal silence, and never feeds statistics.
- Daily maxima roll at local midnight into a bounded per-device set.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_REPORTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_CLEAR_MARGIN,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_EXCLUDED_INTEGRATIONS,
    CONF_SIGNAL_EXCLUDED_LABELS,
    CONF_SIGNAL_SENSITIVITY,
    DEFAULT_SIGNAL_SENSITIVITY,
    CONF_EXCLUDED_LABELS,
    DATA_TODO_ITEMS,
    CONF_LOW_THRESHOLD,
    DAILY_MAX_KEEP,
    DEFAULT_LOW_THRESHOLD,
    DATA_STATS_EPOCH,
    REPORT_CLASSIFICATION,
    REPORT_DIR,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
    SIGNAL_ARMING_DAYS,
    SIGNAL_SENSITIVITY_MAX,
    SIGNAL_SENSITIVITY_MIN,
    SIGNAL_TRIM_LADDER_FORTNIGHT,
    SIGNAL_TRIM_LADDER_WEEK,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
    DATA_DEVICES,
    DATA_FIRST_INSTALLED,
    DATA_SETUP_COUNT,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    SIGNAL_NAME_TERMS,
    RAIL_CONFIRM_DAYS,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    STATS_EPOCH,
    LEARNING_MIN_DAYS,
    LOGGER,
    RENDER_TICK_SECONDS,
    STARTUP_GRACE_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_HISTORY_SECONDS,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    TAINT_DEBOUNCE_SECONDS,
    TODO_DESCRIPTION,
    TODO_KIND,
    TODO_OURS,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,)

BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _new_device_record(now_iso: str, seed_ts: float | None) -> dict[str, Any]:
    """Return a fresh per-device statistics record."""
    return {
        DEV_LAST_ACTIVITY: seed_ts,
        DEV_DAILY_MAX: [],
        DEV_TODAY_MAX: None,
        DEV_FIRST_OBSERVED: now_iso,
        DEV_EVENT_COUNT: 0,
        DEV_TAINTED: False,
        DEV_SIGNAL_VALUE: None,
        DEV_SIGNAL_TODAY_MIN: None,
        DEV_SIGNAL_DAILY_MIN: [],
        DEV_SIGNAL_BELOW_SINCE: None,
        DEV_SIGNAL_BELOW_TODAY: 0.0,
        DEV_SIGNAL_DWELL_DAILY: [],
        DEV_SIGNAL_LAST_CHANGE: None,
        DEV_BATTERY_LOW: False,
        DEV_BATTERY_SINCE: None,
        DEV_BATTERY_VALUE: None,
        DEV_BATTERY_DAILY: [],
    }


class DeviceSentinelCoordinator:
    """Owns Device Sentinel's storage, registry view, and telemetry."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, version: str
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.version = version
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self.data: dict[str, Any] = {}
        self.storage_healthy: bool = False
        self._dirty: bool = False

        # Registry view, rebuilt on registry changes.
        self._entity_map: dict[str, tuple[str, str | None]] = {}
        self._watched: dict[str, str] = {}  # device_id -> integration domain
        # Names and labels, cached from the registry at classify
        # time. The options cascade reads them on every form open,
        # and re-walking the registry there would race a rebuild.
        self._device_names: dict[str, str] = {}  # device_id -> name
        self._device_labels: dict[str, frozenset[str]] = {}
        self._entity_labels: dict[str, frozenset[str]] = {}
        # Exclusion suppresses judgment, not observation: these sets
        # gate reporting only. Clocks, statistics, and vouching keep
        # running for everything in them, so undo is instant and the
        # rhythm history carries no holes.
        self._excluded_devices: dict[str, str] = {}  # device_id -> reason
        self._excluded_entities: dict[str, str] = {}  # entity_id -> reason
        self._set_aside: dict[str, tuple[str, str]] = {}  # id -> (name, domain)
        self._last_seen_entity: dict[str, str] = {}  # device_id -> entity_id
        self._signal_entities: set[str] = set()
        self._signal_devices: set[str] = set()
        # device_id -> (entity_id, is_binary). Election prefers the
        # percentage entity; the binary low flag is the fallback.
        self._battery_entity: dict[str, tuple[str, bool]] = {}
        # entity_id -> device_id, the reverse index the intake uses.
        self._battery_entity_reverse: dict[str, str] = {}
        self._pending_unavailable: dict[str, tuple[float, str]] = {}
        self._taint_consumed_at: dict[str, float] = {}
        self.deviceless_count: int = 0

        # Grace and storm state.
        self._grace_until: float = 0.0
        self._grace_stamps: int = 0
        self._grace_devices: set[str] = set()
        self._grace_taints: set[str] = set()
        self._storm_feed_q: dict[str, deque[tuple[float, str]]] = {}
        self._storm_active: dict[str, dict[str, Any]] = {}
        self._storm_history: dict[str, deque[float]] = {}
        self._storm_exempt: set[str] = set()

        self._listeners: list[Any] = []
        self._unsubs: list[Any] = []

    # ------------------------------------------------------------- setup

    @staticmethod
    def _prune_legacy_fields(devices: dict[str, dict[str, Any]]) -> int:
        """Remove stored keys outside the current record schema.

        _new_device_record is the authoritative field set. Any key in
        a stored record that is not in a fresh record was written by a
        past version and is dead (the frozen fields the rail rework
        dropped, for instance). Returns how many keys were removed
        across all records, zero once storage is clean.
        """
        allowed = set(_new_device_record("", None).keys())
        removed = 0
        for record in devices.values():
            for key in [k for k in record if k not in allowed]:
                del record[key]
                removed += 1
        return removed

    async def async_setup(self) -> None:
        """Load storage, build the registry view, and start listening."""
        loaded = await self._store.async_load()
        if loaded is None:
            LOGGER.info(
                "Device Sentinel v%s: no existing storage, creating %s",
                self.version,
                STORAGE_KEY,
            )
            loaded = {
                DATA_FIRST_INSTALLED: dt_util.utcnow().isoformat(),
                DATA_SETUP_COUNT: 0,
                DATA_DEVICES: {},
            }
        loaded[DATA_SETUP_COUNT] = int(loaded.get(DATA_SETUP_COUNT, 0)) + 1
        loaded.setdefault(DATA_FIRST_INSTALLED, dt_util.utcnow().isoformat())
        loaded.setdefault(DATA_DEVICES, {})
        loaded.setdefault(DATA_TODO_ITEMS, [])
        if loaded.get(DATA_STATS_EPOCH) != STATS_EPOCH:
            wiped = 0
            for record in loaded[DATA_DEVICES].values():
                record[DEV_DAILY_MAX] = []
                record[DEV_TODAY_MAX] = None
                record[DEV_EVENT_COUNT] = 0
                record[DEV_TAINTED] = False
                record[DEV_SIGNAL_VALUE] = None
                record[DEV_SIGNAL_TODAY_MIN] = None
                record[DEV_SIGNAL_DAILY_MIN] = []
                record[DEV_SIGNAL_BELOW_SINCE] = None
                record[DEV_SIGNAL_BELOW_TODAY] = 0.0
                record[DEV_SIGNAL_DWELL_DAILY] = []
                record[DEV_SIGNAL_LAST_CHANGE] = None
                record.setdefault(DEV_BATTERY_LOW, False)
                record.setdefault(DEV_BATTERY_SINCE, None)
                record.setdefault(DEV_BATTERY_VALUE, None)
                record.setdefault(DEV_BATTERY_DAILY, [])
                wiped += 1
            loaded[DATA_STATS_EPOCH] = STATS_EPOCH
            LOGGER.info(
                "Statistics epoch %s: learned statistics reset for %d "
                "devices so rhythms are learned under the final rule "
                "set; activity clocks and identity kept",
                STATS_EPOCH,
                wiped,
            )
        else:
            for record in loaded[DATA_DEVICES].values():
                record.setdefault(DEV_SIGNAL_VALUE, None)
                record.setdefault(DEV_SIGNAL_TODAY_MIN, None)
                record.setdefault(DEV_SIGNAL_DAILY_MIN, [])
                record.setdefault(DEV_SIGNAL_BELOW_SINCE, None)
                record.setdefault(DEV_SIGNAL_BELOW_TODAY, 0.0)
                record.setdefault(DEV_SIGNAL_DWELL_DAILY, [])
                record.setdefault(DEV_SIGNAL_LAST_CHANGE, None)
                record.setdefault(DEV_BATTERY_LOW, False)
                record.setdefault(DEV_BATTERY_SINCE, None)
                record.setdefault(DEV_BATTERY_VALUE, None)
                record.setdefault(DEV_BATTERY_DAILY, [])
        # Strip any keys a past version wrote that the current record
        # schema no longer holds (0.4.10). _new_device_record is the
        # one authoritative field set; anything outside it is dead,
        # like the frozen fields the rail rework removed. The prune is
        # idempotent: once a record is clean it finds nothing. Any new
        # field must be added to _new_device_record or this removes it
        # on the next load.
        legacy = self._prune_legacy_fields(loaded[DATA_DEVICES])
        if legacy:
            LOGGER.info(
                "Storage prune: removed %d legacy field(s) no longer "
                "in the record schema",
                legacy,
            )

        self.data = loaded
        await self._store.async_save(self.data)
        self.storage_healthy = True

        self._grace_until = (
            dt_util.utcnow().timestamp() + STARTUP_GRACE_SECONDS
        )

        self._rebuild_registry_view(audit=True)

        self._unsubs.append(
            self.hass.bus.async_listen(
                "state_changed",
                self._on_state_changed,
                event_filter=self._event_filter,
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_STATE_REPORTED,
                self._on_state_reported,
                event_filter=self._event_filter,
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._on_registry_updated
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated
            )
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._on_midnight, hour=0, minute=0, second=0
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._on_render_tick,
                timedelta(seconds=RENDER_TICK_SECONDS),
            )
        )
        self._unsubs.append(
            async_call_later(
                self.hass, STARTUP_GRACE_SECONDS, self._on_grace_closed
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_HOMEASSISTANT_STOP, self._on_hass_stop
            )
        )

        self._evaluate_all_batteries()

        LOGGER.info(
            "Device Sentinel v%s setup complete: setup_count=%s, "
            "first_installed=%s, watching %d of %d devices "
            "(%d set aside), %d deviceless entities",
            self.version,
            self.setup_count,
            self.first_installed,
            len(self._watched),
            len(self._watched) + len(self._set_aside),
            len(self._set_aside),
            self.deviceless_count,
        )
        await self.hass.async_add_executor_job(
            self._write_reports, "setup"
        )

    async def async_shutdown(self) -> None:
        """Stop listening and flush storage."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._dirty:
            await self._store.async_save(self.data)
            self._dirty = False

    # ---------------------------------------------------- registry view

    def _primary_domain(self, device: dr.DeviceEntry) -> str:
        """Return the integration domain owning a device.

        Multi-homed devices (known to their own integration and to a
        network tracker at once) attribute to the registry's
        primary_config_entry, the entry that created the device, with
        a sorted fallback so the pick is deterministic either way.
        """
        entry_ids: list[str] = []
        primary = getattr(device, "primary_config_entry", None)
        if primary is not None:
            entry_ids.append(primary)
        entry_ids.extend(sorted(device.config_entries))
        for entry_id in entry_ids:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                return entry.domain
        return "unknown"

    def _rebuild_registry_view(self, audit: bool = False) -> None:
        """Classify devices and rebuild the entity-to-device map."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        options = self.entry.options
        excluded_device_ids = set(
            options.get(CONF_EXCLUDED_DEVICES, [])
        )
        excluded_labels = set(options.get(CONF_EXCLUDED_LABELS, []))
        excluded_integrations = set(
            options.get(CONF_EXCLUDED_INTEGRATIONS, [])
        )

        watched: dict[str, str] = {}
        device_names: dict[str, str] = {}
        device_labels: dict[str, frozenset[str]] = {}
        set_aside: dict[str, tuple[str, str]] = {}
        excluded_devices: dict[str, str] = {}
        excluded_entities: dict[str, str] = {}
        for device in dev_reg.devices.values():
            domain = self._primary_domain(device)
            name = device.name_by_user or device.name or device.id
            if device.entry_type is dr.DeviceEntryType.SERVICE:
                set_aside[device.id] = (name, domain)
                continue
            watched[device.id] = domain
            device_names[device.id] = name
            device_labels[device.id] = frozenset(device.labels or ())
            # Device-level exclusion reasons, named broadest first
            # so the reason recorded is the one that would survive a
            # prune. The integration test uses the primary domain, so
            # an integration exclude catches only devices it owns,
            # never multi-homed hardware it merely sees.
            if domain in excluded_integrations:
                excluded_devices[device.id] = "integration"
            elif excluded_labels & set(device.labels or ()):
                excluded_devices[device.id] = "label"
            elif device.id in excluded_device_ids:
                excluded_devices[device.id] = "device"

        entity_map: dict[str, tuple[str, str | None]] = {}
        entity_labels: dict[str, frozenset[str]] = {}
        last_seen_entity: dict[str, str] = {}
        signal_entities: set[str] = set()
        signal_devices: set[str] = set()
        battery_entity: dict[str, tuple[str, bool]] = {}
        deviceless = 0
        for ent in ent_reg.entities.values():
            if ent.device_id is None:
                deviceless += 1
                continue
            if ent.device_id not in watched:
                continue
            entity_map[ent.entity_id] = (ent.device_id, ent.config_entry_id)
            entity_labels[ent.entity_id] = frozenset(ent.labels or ())
            if excluded_labels & set(ent.labels or ()):
                # An entity carrying an excluded label does not feed
                # its device's judgment. This is the label axis, not a
                # per-entity exclude: the explicit entity exclude was
                # removed (ruled 2026-07-19 evening) as residue from
                # the entity-level Entity Sentinel blueprint.
                excluded_entities[ent.entity_id] = "label"
            if self._is_last_seen(ent):
                last_seen_entity[ent.device_id] = ent.entity_id
            if self._is_signal(ent):
                if ent.disabled_by is None:
                    signal_entities.add(ent.entity_id)
                    signal_devices.add(ent.device_id)
            if ent.disabled_by is None and self._is_battery(ent):
                is_binary = ent.entity_id.startswith("binary_sensor.")
                current = battery_entity.get(ent.device_id)
                # Percentage beats binary; among equals, first wins.
                if current is None or (current[1] and not is_binary):
                    battery_entity[ent.device_id] = (
                        ent.entity_id,
                        is_binary,
                    )

        self._watched = watched
        self._device_names = device_names
        self._device_labels = device_labels
        self._set_aside = set_aside
        self._excluded_devices = excluded_devices
        self._excluded_entities = excluded_entities
        self._entity_map = entity_map
        self._entity_labels = entity_labels
        self._last_seen_entity = last_seen_entity
        self._signal_entities = signal_entities
        self._signal_devices = signal_devices
        self._battery_entity = battery_entity
        self._battery_entity_reverse = {
            entity_id: device_id
            for device_id, (entity_id, _) in battery_entity.items()
        }
        self.deviceless_count = deviceless

        now_iso = dt_util.utcnow().isoformat()
        devices: dict[str, Any] = self.data.setdefault(DATA_DEVICES, {})
        for device_id in watched:
            if device_id not in devices:
                devices[device_id] = _new_device_record(
                    now_iso, self._seed_from_last_seen(device_id)
                )
                self._dirty = True
        for device_id in list(devices):
            if device_id not in watched:
                del devices[device_id]
                self._dirty = True

        if audit and set_aside:
            names = "; ".join(
                f"{name} ({domain})"
                for name, domain in sorted(set_aside.values())
            )
            LOGGER.info(
                "Set aside %d service devices from telemetry: %s",
                len(set_aside),
                names,
            )

    @staticmethod
    def _is_last_seen(ent: er.RegistryEntry) -> bool:
        """Recognize a last_seen entity from registry fields alone."""
        hay = " ".join(
            str(x)
            for x in (ent.entity_id, ent.unique_id, ent.original_name)
            if x
        ).lower()
        return "last_seen" in hay or "last seen" in hay

    @staticmethod
    def _is_signal(ent: er.RegistryEntry) -> bool:
        """Recognize a signal-strength entity from registry fields."""
        if str(ent.original_device_class) == "signal_strength" or str(
            getattr(ent, "device_class", None)
        ) == "signal_strength":
            return True
        hay = " ".join(
            str(x)
            for x in (ent.entity_id, ent.unique_id, ent.original_name)
            if x
        ).lower()
        return any(term in hay for term in SIGNAL_NAME_TERMS)

    @staticmethod
    def _is_battery(ent: er.RegistryEntry) -> bool:
        """Recognize a battery entity from its registry device class.

        Percentage batteries are sensors with device_class battery;
        binary low flags are binary_sensors with device_class battery.
        Chargers, battery_charging flags, and the like carry other
        device classes and are correctly ignored.
        """
        if str(ent.original_device_class or ent.device_class) != "battery":
            return False
        return ent.entity_id.startswith(("sensor.", "binary_sensor."))

    def _seed_from_last_seen(self, device_id: str) -> float | None:
        """Seed a new device's clock from its last_seen entity, if any."""
        entity_id = self._last_seen_entity.get(device_id)
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in BAD_STATES:
            return None
        parsed = dt_util.parse_datetime(state.state)
        if parsed is None:
            return None
        # A naive datetime (no offset in the source string) would have
        # .timestamp() assume local time, so a last_seen from an
        # integration that omits the zone could seed the clock wrong
        # by the UTC offset. Anchor any naive value to UTC, matching
        # the UTC discipline every stored timestamp already follows.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed.timestamp()

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        """Rebuild the registry view when devices or entities change."""
        self._rebuild_registry_view()
        self._notify()

    # ---------------------------------------------------------- intake

    @callback
    def _event_filter(self, event_data: Any) -> bool:
        """Fast pre-filter: only entities mapped to watched devices."""
        return event_data.get("entity_id") in self._entity_map

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Handle a state change for a watched device's entity."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        entity_id = event.data["entity_id"]
        device_id, entry_id = self._entity_map[entity_id]
        if new_state.state in BAD_STATES:
            # Debounced: note when the absence began, taint only if it
            # lasts. A dead device never recovers, never completes a
            # gap, and so needs no taint to stay unlearned.
            self._pending_unavailable.setdefault(
                entity_id,
                (dt_util.utcnow().timestamp(), new_state.state),
            )
            return
        pending = self._pending_unavailable.pop(entity_id, None)
        if pending is not None:
            began, bad_state = pending
            gone = dt_util.utcnow().timestamp() - began
            same_episode = began <= self._taint_consumed_at.get(
                device_id, 0.0
            )
            if gone >= TAINT_DEBOUNCE_SECONDS and not same_episode:
                record = self.data[DATA_DEVICES].get(device_id)
                if record is not None and not record[DEV_TAINTED]:
                    record[DEV_TAINTED] = True
                    self._dirty = True
                    if dt_util.utcnow().timestamp() < self._grace_until:
                        self._grace_taints.add(device_id)
                    else:
                        LOGGER.info(
                            "Device tainted: %s was %s for %.0f s; its "
                            "next completed gap will not feed learning",
                            entity_id,
                            bad_state,
                            gone,
                        )
        self._record_activity(
            device_id, entry_id, entity_id, new_state.state
        )
        if entity_id in self._battery_entity_reverse:
            self._evaluate_battery(
                self._battery_entity_reverse[entity_id],
                notify_on_change=True,
            )

    @callback
    def _on_state_reported(self, event: Event) -> None:
        """Handle a same-value report for a watched device's entity."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in BAD_STATES:
            return
        entity_id = event.data["entity_id"]
        device_id, entry_id = self._entity_map[entity_id]
        self._record_activity(
            device_id, entry_id, entity_id, new_state.state
        )

    @callback
    def _record_activity(
        self,
        device_id: str,
        entry_id: str | None,
        entity_id: str | None = None,
        state: str | None = None,
    ) -> None:
        """Stamp the device clock, completing a gap for learning if clean."""
        now = dt_util.utcnow().timestamp()
        record = self.data[DATA_DEVICES].get(device_id)
        if record is None:
            record = _new_device_record(dt_util.utcnow().isoformat(), None)
            self.data[DATA_DEVICES][device_id] = record

        if entity_id in self._signal_entities and state is not None:
            try:
                value = float(state)
            except ValueError:
                value = None
            if value is not None:
                self._feed_signal(record, value, now)

        storm = self._storm_feed(entry_id, device_id, now)
        grace = now < self._grace_until

        # A taint is consumed by any real-value stamp: the outage ended
        # here, and the spanning gap is excluded by whichever rule
        # applies. Exclusions are independent, not exclusive.
        tainted = record[DEV_TAINTED]
        if tainted:
            record[DEV_TAINTED] = False
            self._taint_consumed_at[device_id] = now

        last = record[DEV_LAST_ACTIVITY]
        if grace:
            self._grace_stamps += 1
            self._grace_devices.add(device_id)
        elif storm is not None:
            storm["stamps"] += 1
            storm["devices"].add(device_id)
        elif tainted:
            if last is not None:
                LOGGER.info(
                    "Completed gap of %.0f s on a tainted device excluded "
                    "from learning (spanned an unavailable stretch)",
                    now - last,
                )
        elif last is not None:
            gap = now - last
            if record[DEV_TODAY_MAX] is None or gap > record[DEV_TODAY_MAX]:
                record[DEV_TODAY_MAX] = gap

        record[DEV_LAST_ACTIVITY] = now
        record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
        self._dirty = True

    # ----------------------------------------------------------- storms

    def _roll_battery(self, record: dict[str, Any]) -> None:
        """Append today's battery level to the daily discharge series.

        One point per day, sampled here at the rollover: the value,
        not the delta, so the series is self-describing (89, 89, 88,
        80, 65) and a missed midnight leaves a gap the velocity flag
        can later divide across rather than a false cliff. Only records
        when there is a level to record, so a device without a battery
        keeps an empty series. The velocity judgment waits until this
        history has depth, the way the dwell danger line waited on the
        floor; today this only records.
        """
        level = record.get(DEV_BATTERY_VALUE)
        if level is None:
            return
        record.setdefault(DEV_BATTERY_DAILY, []).append(level)
        del record[DEV_BATTERY_DAILY][:-DAILY_MAX_KEEP]

    def _roll_dwell(self, record: dict[str, Any], now: float) -> None:
        """Close the day's dwell into the rolling daily percentages.

        An open below-timer closes at now rather than freezing at its
        last reading: a link that dies below the line was below the
        line the whole silence, so its day reads 100 percent, which is
        the truth (the completed-gap principle turned inside out,
        ruled 2026-07-18). A device still below at midnight is
        re-stamped so the new day keeps accumulating without a seam.

        The percentage is against the full day. Recording starts from
        day one while the floor is still settling; the early numbers
        are provisional the same way rhythm floors were before day 7,
        and are recorded anyway rather than gated (ruled 2026-07-18).
        """
        below_since = record.get(DEV_SIGNAL_BELOW_SINCE)
        accumulated = float(record.get(DEV_SIGNAL_BELOW_TODAY) or 0.0)
        if below_since is not None:
            accumulated += max(0.0, now - below_since)
            record[DEV_SIGNAL_BELOW_SINCE] = now
        had_line = self._danger_line(record) is not None
        if had_line:
            pct = min(100.0, 100.0 * accumulated / 86400.0)
            record.setdefault(DEV_SIGNAL_DWELL_DAILY, []).append(
                round(pct, 2)
            )
            del record[DEV_SIGNAL_DWELL_DAILY][:-DAILY_MAX_KEEP]
        record[DEV_SIGNAL_BELOW_TODAY] = 0.0

    def _feed_signal(
        self, record: dict[str, Any], value: float, now: float
    ) -> None:
        """Route one signal reading, and track whether it moves.

        The floor and the dwell timer see only real readings; a rail
        value (255, -128) is the type's fill value, not a measurement,
        so it feeds neither (ruled 2026-07-18). But every reading,
        rail or real, updates the frozen clock, because a signal that
        never changes is not reporting whatever value it is frozen at.
        last_change advances only when the value actually differs, so
        the gap since last_change is how long the signal has been
        flat while the device kept reporting.
        """
        previous = record.get(DEV_SIGNAL_VALUE)
        if previous is None or value != previous:
            record[DEV_SIGNAL_LAST_CHANGE] = now
        record[DEV_SIGNAL_VALUE] = value

        if value in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI):
            return
        today_min = record.get(DEV_SIGNAL_TODAY_MIN)
        if today_min is None or value < today_min:
            record[DEV_SIGNAL_TODAY_MIN] = value
        self._feed_dwell(record, value, now)

    def _feed_dwell(
        self, record: dict[str, Any], value: float, now: float
    ) -> None:
        """Run the below-the-line timer for one real reading.

        Signal is reported as dwell, not crossings (ruled 2026-07-18):
        a battery moves one direction, but signal is noisy and always
        recovering, so the unit is time spent below the danger line,
        accumulated by a timer and rolled into a daily percentage. A
        momentary dip that recovers never counts for more than the
        moment it lasted.

        At the floor counts as below it: a device sitting exactly on
        its trimmed floor is living at its lows, which is the thing
        being measured. The line exists from the first recorded day
        (k=0, floor = lowest real reading) and simply settles as the
        trim ladder matures.
        """
        line = self._danger_line(record)
        below_since = record.get(DEV_SIGNAL_BELOW_SINCE)
        if line is None:
            record[DEV_SIGNAL_BELOW_SINCE] = None
            return
        if value <= line:
            if below_since is None:
                record[DEV_SIGNAL_BELOW_SINCE] = now
        elif below_since is not None:
            record[DEV_SIGNAL_BELOW_TODAY] = (
                float(record.get(DEV_SIGNAL_BELOW_TODAY) or 0.0)
                + max(0.0, now - below_since)
            )
            record[DEV_SIGNAL_BELOW_SINCE] = None

    def _danger_line(self, record: dict[str, Any]) -> float | None:
        """Return this device's line: its trimmed floor, or None with
        no history.

        The floor is the line (ruled 2026-07-19). Rail values never
        feed it: a device whose whole history is rail has no floor at
        all rather than a false one, which was the Door Laundry bug
        (a floor of 255 from the stuck period made a garbage line).

        The trim ladder grows with the soak: under a week nothing is
        dropped and the floor is the lowest real reading, so the line
        exists from the first day; at a week the single lowest is
        dropped; at two weeks the two lowest are. The user's
        sensitivity setting shifts k (left calmer, right twitchier),
        clamped so at least one reading always survives to be the
        floor. Dropping the LOWEST values is the opposite of the
        rhythm trim, which drops the highest, because for signal the
        spuriously bad reading is the anomaly to set aside.
        """
        history = self._signal_history(record)
        if not history:
            return None
        effective_k = self._signal_effective_k(len(history))
        return sorted(history)[effective_k]

    @staticmethod
    def _signal_history(record: dict[str, Any]) -> list[float]:
        """Return the device's daily signal lows with rail values
        removed. Rails are fill values, not readings, so they never
        feed the floor and never count toward the trim."""
        return [
            value
            for value in (record.get(DEV_SIGNAL_DAILY_MIN) or [])
            if value not in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        ]

    def _signal_slider(self) -> int:
        """Return the sensitivity slider, clamped to its band. This is
        the k behind the SIGNAL header's sensitivity word: it is global,
        the same
        for every device, unlike the per-device effective k which also
        carries each device's ladder rung."""
        slider = int(
            self.entry.options.get(
                CONF_SIGNAL_SENSITIVITY, DEFAULT_SIGNAL_SENSITIVITY
            )
        )
        return max(SIGNAL_SENSITIVITY_MIN, min(slider, SIGNAL_SENSITIVITY_MAX))

    def _signal_slider_label(self) -> str:
        """Return the sensitivity slider as a word, not a number.

        The report used to show the slider as K, which collided with
        the trim depth the same report calls k. A word states what the
        setting does: calmer settings trim fewer lows so the floor
        sits lower and flags less, sensitive settings the reverse.
        """
        return {
            -2: "Calm",
            -1: "Stable",
            0: "Normal",
            1: "Watchful",
            2: "Sensitive",
        }.get(self._signal_slider(), "Normal")

    def _signal_effective_k(self, days: int) -> int:
        """Return how many of the lowest readings the floor trims for
        a device with this many non-rail days: the ladder rung shifted
        by the slider, clamped so at least one reading survives."""
        if days >= 2 * SIGNAL_ARMING_DAYS:
            base_k = SIGNAL_TRIM_LADDER_FORTNIGHT
        elif days >= SIGNAL_ARMING_DAYS:
            base_k = SIGNAL_TRIM_LADDER_WEEK
        else:
            base_k = 0
        return max(0, min(base_k + self._signal_slider(), days - 1))

    def signal_railed(self, record: dict[str, Any]) -> bool:
        """Return whether this device's signal is stuck at the rail.

        A rail is the type's fill value, 255 for LQI or -128 for RSSI:
        the empty value of a field the device stopped populating,
        which reads as perfect signal and is the opposite. It is
        confirmed over time, not on a single reading: the daily low
        has sat at a rail for RAIL_CONFIRM_DAYS consecutive days
        (ruled 2026-07-19 evening, replacing the live repeat counter
        the frozen rework proved unreliable). Reading the daily-low
        series the report already keeps means no live counter and no
        per-reading state: a rail that comes and goes within a day
        never confirms, while one that holds across days does.

        The plausible-value freeze, a real reading that stops moving,
        is not judged here: a device with a strong steady link reports
        the same value for hours and cannot be told from a stuck one.
        The project document records that rabbit hole and the learned
        flat-stretch approach that could restore it if it is ever
        worth building.
        """
        lows = record.get(DEV_SIGNAL_DAILY_MIN) or []
        if len(lows) < RAIL_CONFIRM_DAYS:
            return False
        rails = (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        recent = lows[-RAIL_CONFIRM_DAYS:]
        return all(value in rails for value in recent)

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
                    LOGGER.info(
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
            LOGGER.info(
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

    # ------------------------------------------------------------ timers

    @callback
    def _on_grace_closed(self, _now: Any) -> None:
        """Log the startup grace summary."""
        LOGGER.info(
            "Startup grace closed after %d s: %d stamps across %d devices "
            "excluded from learning; %d boot-blip taints aggregated",
            STARTUP_GRACE_SECONDS,
            self._grace_stamps,
            len(self._grace_devices),
            len(self._grace_taints),
        )

    async def _on_midnight(self, _now: Any) -> None:
        """Roll today's maxima into the bounded daily set."""
        now = dt_util.utcnow().timestamp()
        pushed = 0
        for record in self.data[DATA_DEVICES].values():
            if record[DEV_TODAY_MAX] is not None:
                record[DEV_DAILY_MAX].append(record[DEV_TODAY_MAX])
                del record[DEV_DAILY_MAX][:-DAILY_MAX_KEEP]
                record[DEV_TODAY_MAX] = None
                pushed += 1
            if record.get(DEV_SIGNAL_TODAY_MIN) is not None:
                record[DEV_SIGNAL_DAILY_MIN].append(
                    record[DEV_SIGNAL_TODAY_MIN]
                )
                del record[DEV_SIGNAL_DAILY_MIN][:-DAILY_MAX_KEEP]
                record[DEV_SIGNAL_TODAY_MIN] = None
            self._roll_dwell(record, now)
            self._roll_battery(record)
        if pushed:
            self._dirty = True
            await self._store.async_save(self.data)
            self._dirty = False
        LOGGER.info(
            "Day rollover: pushed daily maxima for %d of %d watched devices",
            pushed,
            len(self.data[DATA_DEVICES]),
        )
        await self.hass.async_add_executor_job(self._write_reports)

    def _write_reports(self, trigger: str = "manual") -> None:
        """Write both diagnostic files to /config/device_sentinel/.

        They live under /config because custom_components is code and
        is overwritten on every update (a ruled decision). Written at
        every setup and after every midnight rollover, so the files
        always exist from first boot and are never staler than the
        last restart or midnight. Stale pre-0.2.6 .txt files are
        removed so the folder holds one truth.
        """
        report_directory = self.hass.config.path(REPORT_DIR)
        os.makedirs(report_directory, exist_ok=True)
        for stale_name in REPORT_STALE_FILES:
            stale_path = os.path.join(report_directory, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)
        self._write_telemetry(report_directory, trigger)
        self._write_classification(report_directory, trigger)

    @staticmethod
    def _trimmed_maximum(
        daily_maximum_gaps: list[float],
    ) -> tuple[float | None, set[int]]:
        """Return (operative rhythm, indices of set-aside outliers).

        The trimmed maximum is the Step 4 window rhythm, previewed
        here for display: the top TRIM_TOP_K daily maxima are set
        aside as suspected anomalies, and the rhythm is the maximum
        of the survivors. One anomalous day therefore moves nothing,
        while a spike that recurs leaves a second high value among
        the survivors and correctly raises the rhythm. Below
        TRIM_MIN_SAMPLES days nothing is trimmed: with so few samples
        an apparent outlier cannot be told from the true rhythm.
        """
        if not daily_maximum_gaps:
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

    def _fmt_gap(self, seconds: Any) -> str:
        """Format a gap for the report."""
        if seconds is None:
            return "-"
        if seconds >= 3600:
            return f"{seconds / 3600:.2f}h"
        return f"{seconds:.0f}s"

    def _format_maxima_cell(self, daily_maximum_gaps: list[float]) -> str:
        """Render the maxima list newest-first with the trim visible.

        Set-aside outliers are struck through (excluded from the
        window basis); the operative rhythm is bold. They can never
        be the same value styled twice, because the operative rhythm
        is by definition chosen after the outliers are removed.
        """
        if not daily_maximum_gaps:
            return "-"
        operative, set_aside_indices = self._trimmed_maximum(
            daily_maximum_gaps
        )
        # Bold exactly one survivor equal to the operative rhythm.
        operative_index = None
        for index, gap in enumerate(daily_maximum_gaps):
            if index not in set_aside_indices and gap == operative:
                operative_index = index
                break
        parts = []
        # Storage appends oldest-to-newest; display newest first.
        for index in reversed(range(len(daily_maximum_gaps))):
            text = self._fmt_gap(daily_maximum_gaps[index])
            if index in set_aside_indices:
                parts.append(f"~~{text}~~")
            elif index == operative_index:
                parts.append(f"**{text}**")
            else:
                parts.append(text)
        return ", ".join(parts)

    def _format_signal_lows_cell(self, record: dict[str, Any]) -> str:
        """Render the daily signal lows newest-first with the marks.

        Three states, and a value is only ever one of them: the floor
        is bold, values strictly below the floor are struck through
        (the trimmed lows, set aside so a spurious bad reading does
        not define the line), and rail fill values are italic (seen
        and shown, but never fed to the floor).

        Two rules make repeated values read cleanly (ruled 2026-07-19,
        after a flat button series showed one 48 bold, one struck, and
        two plain). The floor mark lands on the EARLIEST recorded
        occurrence of the floor value, so a reader sees when the
        device first reached its low. And a value equal to the floor
        is never struck: only values strictly below the floor are
        trimmed, so the same number is never both the line and an
        outlier. This can leave more than k values struck when the
        trimmed lows repeat, or fewer, which is correct: the marks now
        describe the values, not the positions the trim happened to
        pick.
        """
        stored = list(record.get(DEV_SIGNAL_DAILY_MIN) or [])
        if not stored:
            return "-"
        rails = (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        floor = self._danger_line(record)
        # The earliest (lowest stored index) occurrence of the floor
        # value is the one to bold, so its first appearance is marked.
        floor_index = None
        if floor is not None:
            for index, value in enumerate(stored):
                if value == floor:
                    floor_index = index
                    break
        parts = []
        for index in reversed(range(len(stored))):
            value = stored[index]
            text = f"{value:g}"
            if value in rails:
                parts.append(f"*{text}*")
            elif index == floor_index:
                parts.append(f"**{text}**")
            elif floor is not None and value < floor:
                # Strictly below the floor: a trimmed low. A value
                # equal to the floor is never struck.
                parts.append(f"~~{text}~~")
            else:
                parts.append(text)
        return " ".join(parts)


    def _format_battery_cell(self, record: dict[str, Any]) -> str:
        """Render the daily battery levels newest-first, with any
        level at or below the low threshold bold. No trim and no
        strike: every recorded level is a real reading, and the point
        is the shape of the discharge over days, not an outlier. A
        healthy battery holds flat then falls; the bold values are the
        days it spent at or below the line."""
        levels = list(record.get(DEV_BATTERY_DAILY) or [])
        if not levels:
            return "-"
        threshold = self.low_threshold
        parts = []
        for index in reversed(range(len(levels))):
            level = levels[index]
            text = f"{level:g}"
            if level <= threshold:
                parts.append(f"**{text}**")
            else:
                parts.append(text)
        return " ".join(parts)

    def _write_telemetry(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write device_telemetry.md, the learned-rhythms table.

        The triage view for a doubted detection: each device's full
        daily-maxima history (newest first), the trimmed-maximum
        preview of its window basis, its clock source, and the
        tunables in effect, so the tuning knobs get set against real
        numbers. The trim shown here is display-only during the soak;
        the detection engine adopts the same rule at Step 4.
        """
        dev_reg = dr.async_get(self.hass)
        sample_note = (
            f"k={TRIM_TOP_K} once a device has {TRIM_MIN_SAMPLES} "
            f"daily maxima; below that nothing is trimmed and the "
            f"window basis is the plain maximum (too few samples to "
            f"tell an outlier from the rhythm)."
        )
        lines = [
            f"# Device Sentinel v{self.version} learned statistics",
            "",
            f"Written {dt_util.now().isoformat(timespec='seconds')} "
            f"({trigger})",
            "",
            f"All series read newest first. SIGNAL is each device's "
            f"daily signal minima; the floor (the line dwell is "
            f"measured against) is **bold**, the trimmed lowest "
            f"readings are ~~struck~~, and rail fill values 255/-128 "
            f"are *italic* (shown but never fed to the floor). A "
            f"warning sign at the front of the cell marks a device "
            f"whose daily low has sat at a rail for three days: a "
            f"stuck reading that shows as perfect signal and is the "
            f"opposite, a near-certain fault worth a power cycle or a "
            f"re-bind. The trim grows with the soak (none under "
            f"{SIGNAL_ARMING_DAYS} days, drop 1 lowest at "
            f"{SIGNAL_ARMING_DAYS}, drop 2 at {2 * SIGNAL_ARMING_DAYS}), "
            f"shifted by the sensitivity word in the header (Calm "
            f"trims fewer lows so the floor sits lower and flags less, "
            f"Sensitive the reverse), applied to readings going "
            f"forward only. DWELL% is the share of each day spent at "
            f"or below the floor: healthy devices brushing their floor "
            f"read 0-5 percent, which proves the line has teeth; "
            f"sustained dwell is the anomaly, and outliers clustered "
            f"in one room mean that room needs a router. BAT LEVEL is "
            f"the daily battery level, with any reading at or below "
            f"the low threshold **bold**. excl means signal-excluded: "
            f"still recorded, not judged.",
            "",
            f"Rule: the window basis is the **trimmed maximum** of "
            f"the rolling daily maxima: the top {TRIM_TOP_K} value(s) "
            f"are ~~set aside~~ as suspected anomalies and the basis "
            f"is the max of the survivors. {sample_note}",
            "",
            f"Tunables: grace {STARTUP_GRACE_SECONDS} s, storm "
            f"{STORM_DEVICE_THRESHOLD} devices/"
            f"{STORM_WINDOW_SECONDS:g} s (exempt at "
            f"{STORM_EXEMPT_PER_HOUR}/h), taint debounce "
            f"{TAINT_DEBOUNCE_SECONDS} s, arming floor "
            f"{LEARNING_MIN_DAYS} days, keep {DAILY_MAX_KEEP} days.",
            "",
            f"| DEVICE | DAYS | GAPS (K={TRIM_TOP_K}) | CLOCK | "
            f"EVENTS | SIGNAL ({self._signal_slider_label()}) | "
            f"DWELL% | BAT LEVEL (floor {self.low_threshold:g}%) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        rows = []
        for device_id, record in self.data[DATA_DEVICES].items():
            device = dev_reg.async_get(device_id)
            device_name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            daily_maximum_gaps = record.get(DEV_DAILY_MAX) or []
            operative, _ = self._trimmed_maximum(daily_maximum_gaps)
            rows.append(
                (
                    device_name,
                    len(daily_maximum_gaps),
                    operative,
                    self._format_maxima_cell(daily_maximum_gaps),
                    "seen"
                    if device_id in self._last_seen_entity
                    else "clock",
                    int(record.get(DEV_EVENT_COUNT, 0)),
                    self._format_signal_lows_cell(record),
                    list(record.get(DEV_SIGNAL_DWELL_DAILY) or []),
                    self._format_battery_cell(record),
                    self.signal_railed(record),
                    self._signal_excluded(device_id),
                )
            )
        rows.sort(key=lambda row: (row[2] is None, -(row[2] or 0)))
        for (
            device_name,
            day_count,
            operative,
            maxima_cell,
            clock_source,
            event_count,
            lows_cell,
            dwell_daily,
            battery_cell,
            railed,
            sig_excluded,
        ) in rows:
            dwell_text = (
                " ".join(f"{pct:g}" for pct in reversed(dwell_daily))
                if dwell_daily
                else "-"
            )
            # A confirmed rail (daily low at the fill value for three
            # days) is marked in the signal cell itself, not a column:
            # a warning sign ahead of the lows so it reads at a glance.
            signal_cell = f"\u26a0\ufe0f {lows_cell}" if railed else lows_cell
            if sig_excluded:
                # Excluded devices keep recording (their lows still
                # show) but are not judged: no dwell, no rail mark.
                dwell_text = "excl"
                signal_cell = lows_cell
            lines.append(
                f"| {device_name} | {day_count} | "
                f"{maxima_cell} | "
                f"{clock_source} | {event_count} | {signal_cell} | "
                f"{dwell_text} | {battery_cell} |"
            )
        lines.append("")
        lines.append(f"{len(rows)} watched devices.")
        path = os.path.join(report_directory, REPORT_TELEMETRY)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.info("Telemetry report written to %s", path)

    def _write_classification(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write classification.md, the audit view.

        Answers "why is my device not watched" and "why is this thing
        in my report": every watched device with integration, clock
        source, and a COPIES count that makes duplicate registry
        devices (network-tracker ghosts, multi-homed doubles) visible
        at a glance; every set-aside device with its integration; and
        the deviceless count.
        """
        dev_reg = dr.async_get(self.hass)
        watched_rows = []
        name_copy_counts: dict[str, int] = {}
        for device_id, integration_domain in self._watched.items():
            device = dev_reg.async_get(device_id)
            device_name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            clock_source = (
                "seen" if device_id in self._last_seen_entity else "clock"
            )
            watched_rows.append(
                (device_name, integration_domain, clock_source)
            )
            name_copy_counts[device_name] = (
                name_copy_counts.get(device_name, 0) + 1
            )
        lines = [
            f"# Device Sentinel v{self.version} classification",
            "",
            f"Written {dt_util.now().isoformat(timespec='seconds')} "
            f"({trigger})",
            "",
            f"Watching {len(self._watched)} of "
            f"{len(self._watched) + len(self._set_aside)} devices; "
            f"{len(self._set_aside)} set aside (entry_type service); "
            f"{self.deviceless_count} deviceless entities visible only "
            f"at entity level. COPIES above 1 means duplicate registry "
            f"devices sharing a name (network-tracker ghosts, "
            f"multi-homed doubles): exclude-list candidates.",
            "",
            f"## Watched ({len(self._watched)})",
            "",
            "| DEVICE | INTEGRATION | CLOCK | COPIES |",
            "|---|---|---|---|",
        ]
        for device_name, integration_domain, clock_source in sorted(
            watched_rows
        ):
            lines.append(
                f"| {device_name} | {integration_domain} | "
                f"{clock_source} | {name_copy_counts[device_name]} |"
            )
        if self._excluded_devices or self._excluded_entities:
            lines.append("")
            lines.append(
                f"## Excluded from judgment "
                f"({len(self._excluded_devices)} devices, "
                f"{len(self._excluded_entities)} entities)"
            )
            lines.append("")
            lines.append(
                "Exclusion suppresses judgment, not observation: these "
                "keep their clocks and statistics and never appear in "
                "detections. An excluded entity still vouches for its "
                "device."
            )
            lines.append("")
            lines.append("| ITEM | KIND | REASON |")
            lines.append("|---|---|---|")
            for device_id, reason in sorted(
                self._excluded_devices.items(),
                key=lambda pair: pair[0],
            ):
                device = dev_reg.async_get(device_id)
                item_name = (
                    (device.name_by_user or device.name or device_id)
                    if device
                    else device_id
                )
                lines.append(f"| {item_name} | device | {reason} |")
            for entity_id, reason in sorted(
                self._excluded_entities.items()
            ):
                lines.append(f"| {entity_id} | entity | {reason} |")
        lines.append("")
        lines.append(f"## Set aside ({len(self._set_aside)})")
        lines.append("")
        lines.append("| DEVICE | INTEGRATION |")
        lines.append("|---|---|")
        for device_name, integration_domain in sorted(
            self._set_aside.values()
        ):
            lines.append(f"| {device_name} | {integration_domain} |")
        path = os.path.join(report_directory, REPORT_CLASSIFICATION)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.info("Classification report written to %s", path)

    async def _on_render_tick(self, _now: Any) -> None:
        """Sweep storms, persist if dirty, refresh the sensors."""
        self._sweep_storms(dt_util.utcnow().timestamp())
        if self._dirty:
            await self._store.async_save(self.data)
            self._dirty = False
        self._notify()

    async def _on_hass_stop(self, _event: Event) -> None:
        """Flush storage at shutdown."""
        if self._dirty:
            await self._store.async_save(self.data)
            self._dirty = False

    # --------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, update_callback: Any) -> Any:
        """Register a sensor refresh callback; return an unsubscriber."""
        self._listeners.append(update_callback)

        def _unsub() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _unsub

    @callback
    def _notify(self) -> None:
        """Refresh all registered sensors."""
        for update_callback in self._listeners:
            update_callback()

    # -------------------------------------------------------- properties

    @property
    def setup_count(self) -> int:
        """Return how many times the integration has set up."""
        return int(self.data.get(DATA_SETUP_COUNT, 0))

    @property
    def first_installed(self) -> str | None:
        """Return the ISO timestamp of the first ever setup."""
        return self.data.get(DATA_FIRST_INSTALLED)

    @property
    def watched_count(self) -> int:
        """Return the number of watched devices."""
        return len(self._watched)

    @property
    def set_aside_count(self) -> int:
        """Return the number of service devices set aside."""
        return len(self._set_aside)

    @property
    def learning_buckets(self) -> dict[str, int]:
        """Return counts of devices by learning progress."""
        buckets = {"observing": 0, "building": 0, "established": 0}
        for record in self.data.get(DATA_DEVICES, {}).values():
            days = len(record[DEV_DAILY_MAX])
            if days == 0:
                buckets["observing"] += 1
            elif days < LEARNING_MIN_DAYS:
                buckets["building"] += 1
            else:
                buckets["established"] += 1
        return buckets

    @property
    def signal_tracked(self) -> dict[str, int]:
        """Return counts of devices with a learned signal floor.

        Tracked means the device has a floor and so a live line: the
        signal analogue of Devices Learned. Split by scale for the
        curious; the dwell rule is identical for both. Learning counts
        devices that report signal but have no floor yet, which since
        the floor exists from the first recorded day means a device
        whose history is entirely rail values (a floor of nothing
        rather than a false one). Excluded devices still count here:
        exclusion suppresses judgment, not observation.
        """
        counts = {"lqi": 0, "rssi": 0, "learning": 0}
        for record in self.data.get(DATA_DEVICES, {}).values():
            line = self._danger_line(record)
            if line is None:
                if record.get(DEV_SIGNAL_VALUE) is not None:
                    counts["learning"] += 1
                continue
            if line >= 0:
                counts["lqi"] += 1
            else:
                counts["rssi"] += 1
        return counts

    @property
    def signal_tracked_count(self) -> int:
        """Return how many devices have a signal line, after excludes.

        The state for Tracked Signals: devices with a floor that are
        not signal-excluded. Exclusion suppresses judgment, so an
        excluded device is not something we are watching for signal.
        """
        counts = self.signal_tracked
        watched = counts["lqi"] + counts["rssi"]
        excluded = sum(
            1
            for device_id, record in self.data.get(DATA_DEVICES, {}).items()
            if self._danger_line(record) is not None
            and self._signal_excluded(device_id)
        )
        return watched - excluded

    @property
    def battery_tracked_count(self) -> int:
        """Return how many devices we watch for battery, after excludes.

        A device is battery-tracked when a battery entity was elected
        for it and it is not battery-excluded. The battery analogue of
        Tracked Signals.
        """
        return sum(
            1
            for device_id in self._battery_entity
            if not self._battery_excluded(device_id)
        )

    @property
    def battery_tracked_list(self) -> list[dict[str, Any]]:
        """Return the devices watched for battery, for the attribute."""
        return sorted(
            (
                {"name": self._device_names.get(device_id)}
                for device_id in self._battery_entity
                if not self._battery_excluded(device_id)
            ),
            key=lambda row: row["name"] or "",
        )

    @property
    def freeze_tracked_count(self) -> int:
        """Return how many devices are eligible for freeze detection.

        A device with a learned rhythm (an established reporting
        cadence) is freeze-judgeable, minus the global device
        excludes. The Step 6 engine is not built; this counts the set
        it will act on, the surfaces-before-engines pattern. A freeze
        exclude per section joins when that engine ships.
        """
        return sum(
            1
            for device_id, record in self.data.get(DATA_DEVICES, {}).items()
            if len(record.get(DEV_DAILY_MAX) or []) >= LEARNING_MIN_DAYS
            and device_id not in self._excluded_devices
        )

    @property
    def freeze_tracked_list(self) -> list[dict[str, Any]]:
        """Return the freeze-eligible devices, for the attribute."""
        return sorted(
            (
                {"name": self._device_names.get(device_id)}
                for device_id, record in self.data.get(
                    DATA_DEVICES, {}
                ).items()
                if len(record.get(DEV_DAILY_MAX) or []) >= LEARNING_MIN_DAYS
                and device_id not in self._excluded_devices
            ),
            key=lambda row: row["name"] or "",
        )

    @property
    def frozen_devices_list(self) -> list[dict[str, Any]]:
        """Return devices judged frozen, unknown, or unavailable.

        The Frozen Devices problem sensor. Step 6, the freeze engine,
        is not built, so this is empty now and the sensor is a
        placeholder: the shape ships ahead of the engine so the engine
        is a reader, not a new surface (surfaces before engines). Each
        row will carry a category (frozen, unknown, unavailable) once
        the engine fills it.
        """
        return []

    @property
    def frozen_devices_count(self) -> int:
        """Return how many devices are frozen; zero until Step 6."""
        return len(self.frozen_devices_list)

    @property
    def signal_problem_list(self) -> list[dict[str, Any]]:
        """Return devices with a signal problem, each tagged by kind.

        Two kinds (ruled 2026-07-19 evening). A rail: the daily low
        has sat at the fill value (255, -128) for three days, a stale
        reading that shows as perfect signal. A low: the device dwells
        below its danger line (the dwell judgment, still soaking, so
        this kind stays quiet until its threshold is ruled). Reported
        together because both are signal problems a person discovers
        here and may then exclude, and kept apart by kind because a
        rail is a fault and a low is a weak link. Signal-excluded
        devices are observed but never judged, so they stay off this
        list until re-included by hand.
        """
        problems: list[dict[str, Any]] = []
        for device_id, record in self.data.get(DATA_DEVICES, {}).items():
            if self._signal_excluded(device_id):
                continue
            if self.signal_railed(record):
                problems.append(
                    {
                        "name": self._device_names.get(device_id),
                        "kind": "rail",
                        "value": record.get(DEV_SIGNAL_VALUE),
                    }
                )
        # Rail problems first, then by name. The low kind joins here
        # once the dwell danger line is ruled.
        problems.sort(key=lambda row: (row["kind"] != "rail", row["name"] or ""))
        return problems

    @property
    def signal_problem_count(self) -> int:
        """Return how many devices have a signal problem."""
        return len(self.signal_problem_list)

    @property
    def classification_breakdown(self) -> dict[str, dict[str, int]]:
        """Return per-integration watched and set-aside counts."""
        breakdown: dict[str, dict[str, int]] = {}
        for domain in self._watched.values():
            breakdown.setdefault(
                domain, {"watched": 0, "set_aside": 0}
            )["watched"] += 1
        for _name, domain in self._set_aside.values():
            breakdown.setdefault(
                domain, {"watched": 0, "set_aside": 0}
            )["set_aside"] += 1
        return breakdown

    @property
    def todo_items(self) -> list[dict[str, Any]]:
        """Return the stored problem items, alphabetical by name."""
        return self.data.get(DATA_TODO_ITEMS, [])

    def _sort_todo_items(self) -> None:
        """Enforce alphabetical order by the common name.

        Order is owned by the integration and re-imposed on every
        write, because a readable list beats one ordered by age. User
        reordering does not stick, by design: this is a
        system-maintained problem list, not a personal one.
        """
        self.data[DATA_TODO_ITEMS].sort(
            key=lambda record: (
                record.get(TODO_SORT_NAME) or record.get(TODO_SUMMARY) or ""
            ).lower()
        )

    async def async_todo_add(
        self,
        summary: str,
        description: str | None,
        sort_name: str,
        kind: str | None,
        ours: bool,
        uid: str,
    ) -> None:
        """Add one item and persist, keeping the list alphabetical."""
        self.data[DATA_TODO_ITEMS].append(
            {
                TODO_UID: uid,
                TODO_SUMMARY: summary,
                TODO_DESCRIPTION: description,
                TODO_STATUS: "needs_action",
                TODO_SORT_NAME: sort_name,
                TODO_KIND: kind,
                TODO_OURS: ours,
            }
        )
        self._sort_todo_items()
        await self._store.async_save(self.data)
        self._notify()

    async def async_todo_update(
        self,
        uid: str | None,
        summary: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Apply an edit to one item.

        A status of completed is the acknowledgment: the item stays on
        the list and the engine goes quiet about it. Only a recovery
        deletes it.
        """
        for record in self.data[DATA_TODO_ITEMS]:
            if record[TODO_UID] != uid:
                continue
            if summary is not None:
                record[TODO_SUMMARY] = summary
                record[TODO_SORT_NAME] = (
                    record.get(TODO_SORT_NAME) or summary
                )
            if description is not None:
                record[TODO_DESCRIPTION] = description
            if status is not None:
                record[TODO_STATUS] = status
            break
        self._sort_todo_items()
        await self._store.async_save(self.data)
        self._notify()

    async def async_todo_delete(self, uids: list[str]) -> None:
        """Delete items by uid, whoever created them."""
        self.data[DATA_TODO_ITEMS] = [
            record
            for record in self.data[DATA_TODO_ITEMS]
            if record[TODO_UID] not in uids
        ]
        await self._store.async_save(self.data)
        self._notify()

    @property
    def low_threshold(self) -> float:
        """Return the configured low threshold (options flow, live)."""
        return float(
            self.entry.options.get(
                CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
            )
        )

    @callback
    def _evaluate_battery(
        self, device_id: str, notify_on_change: bool = False
    ) -> None:
        """Judge one device's battery against the threshold.

        The hysteresis, carried from Battery Sentinel 1.2.0: flag at
        or below the threshold; once flagged, stay flagged until the
        value climbs past threshold plus the clear margin, so a cell
        hovering exactly at the line never flaps. The margin is small
        (2) because a load-driven rest-rebound is a genuine recovery
        and is allowed to clear the flag (ruled 2026-07-13).

        below-threshold-since: the first crossing stamps the time,
        later evaluations carry it, recovery clears it. It lives in
        storage, so it survives restarts by construction.

        An unavailable or unknown battery value changes nothing: the
        last verdict holds, because liveness is Step 4's job and a
        dead reading is not a level reading.
        """
        election = self._battery_entity.get(device_id)
        record = self.data[DATA_DEVICES].get(device_id)
        if election is None or record is None:
            return
        battery_entity_id, is_binary = election
        state = self.hass.states.get(battery_entity_id)
        if state is None or state.state in BAD_STATES:
            return

        was_low = bool(record.get(DEV_BATTERY_LOW))
        if is_binary:
            is_low = state.state == "on"
            level = None
        else:
            try:
                level = float(state.state)
            except ValueError:
                return
            threshold = self.low_threshold
            if was_low:
                is_low = level < threshold + BATTERY_CLEAR_MARGIN
            else:
                is_low = level <= threshold

        changed = (
            is_low != was_low
            or record.get(DEV_BATTERY_VALUE) != level
        )
        record[DEV_BATTERY_VALUE] = level
        if is_low and not was_low:
            record[DEV_BATTERY_LOW] = True
            record[DEV_BATTERY_SINCE] = dt_util.utcnow().isoformat()
            LOGGER.info(
                "Battery low: %s at %s (threshold %s)",
                battery_entity_id,
                "on" if is_binary else level,
                self.low_threshold,
            )
        elif was_low and not is_low:
            record[DEV_BATTERY_LOW] = False
            record[DEV_BATTERY_SINCE] = None
            LOGGER.info(
                "Battery recovered: %s at %s",
                battery_entity_id,
                "off" if is_binary else level,
            )
        if changed:
            self._dirty = True
            if notify_on_change:
                self._notify()

    @callback
    def _evaluate_all_batteries(self) -> None:
        """Judge every elected battery; used at setup and on options
        changes, so a threshold slid upward flags immediately."""
        for device_id in self._battery_entity:
            self._evaluate_battery(device_id)

    async def async_options_updated(self) -> None:
        """Re-judge the fleet under new options, live, no restart."""
        self._rebuild_registry_view()
        LOGGER.info(
            "Options updated: low threshold now %s, %d devices and %d "
            "entities excluded; re-evaluating",
            self.low_threshold,
            len(self._excluded_devices),
            len(self._excluded_entities),
        )
        self._evaluate_all_batteries()
        if self._dirty:
            await self._store.async_save(self.data)
            self._dirty = False
        self._notify()

    @property
    def battery_low_list(self) -> list[dict[str, Any]]:
        """Return the low list, one row per device, area then name.

        Row shape follows the blueprint contract: name, entity_id,
        area, level, since (below-threshold-since), last_seen (the
        battery entity's own last report), age, kind: device.
        """
        dev_reg = dr.async_get(self.hass)
        area_reg_names: dict[str, str] = {}
        rows: list[dict[str, Any]] = []
        for device_id, (entity_id, is_binary) in (
            self._battery_entity.items()
        ):
            # Judgment suppression: the verdict is still computed and
            # stored (observation), it is just never reported here.
            # Battery-only excludes stack on top of the global list.
            if (
                device_id in self._excluded_devices
                or entity_id in self._excluded_entities
                or self._battery_excluded(device_id)
            ):
                continue
            record = self.data[DATA_DEVICES].get(device_id)
            if not record or not record.get(DEV_BATTERY_LOW):
                continue
            device = dev_reg.async_get(device_id)
            device_name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            area_name = "Unassigned"
            if device and device.area_id:
                if device.area_id not in area_reg_names:
                    from homeassistant.helpers import area_registry as ar

                    area = ar.async_get(self.hass).async_get_area(
                        device.area_id
                    )
                    area_reg_names[device.area_id] = (
                        area.name if area else device.area_id
                    )
                area_name = area_reg_names[device.area_id]
            state = self.hass.states.get(entity_id)
            since = record.get(DEV_BATTERY_SINCE)
            since_dt = dt_util.parse_datetime(since) if since else None
            rows.append(
                {
                    "name": device_name,
                    "entity_id": entity_id,
                    "area": area_name,
                    "level": record.get(DEV_BATTERY_VALUE),
                    "since": since,
                    "last_seen": (
                        state.last_reported.isoformat()
                        if state and state.last_reported
                        else None
                    ),
                    "age": (
                        dt_util.get_age(since_dt) if since_dt else "unknown"
                    ),
                    "kind": "device",
                }
            )
        rows.sort(key=lambda row: (row["area"], row["name"]))
        return rows

    @property
    def battery_low_count(self) -> int:
        """Return the number of devices currently battery-low."""
        return sum(
            1
            for device_id, (entity_id, _) in self._battery_entity.items()
            if device_id not in self._excluded_devices
            and entity_id not in self._excluded_entities
            and not self._battery_excluded(device_id)
            and (self.data[DATA_DEVICES].get(device_id) or {}).get(
                DEV_BATTERY_LOW
            )
        )

    def _battery_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from battery judgment
        only. Device-level by ruling, so a battery-entity re-election
        cannot dodge it; the integration test uses the owning domain,
        so one tick covers a whole family of phones. The label test
        reads the device's own labels, which is how a device can be
        excluded from battery judgment without opening this dialog."""
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_BATTERY_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_BATTERY_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_BATTERY_EXCLUDED_DEVICES, [])

    def _signal_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from signal judgment
        only. The same broad-to-narrow ladder as battery. Exclusion
        suppresses judgment, not observation: the device keeps
        recording its floor and dwell in storage, so re-inclusion is
        instant and arrives with history; it simply stops being
        reported. This is the manual removal from tracking the
        frozen-signal ruling requires, for a device that resists
        every recovery."""
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_SIGNAL_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_SIGNAL_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_SIGNAL_EXCLUDED_DEVICES, [])

    @property
    def detected_batteries(self) -> list[dict[str, Any]]:
        """Return every device with an elected battery, for the
        options picker: what you see is what is being judged."""
        rows = [
            {
                "device_id": device_id,
                "name": self._device_names.get(device_id, device_id),
                "entity_id": entity_id,
                "integration": self._watched.get(device_id, "?"),
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, (entity_id, _) in self._battery_entity.items()
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    @property
    def detected_signals(self) -> list[dict[str, Any]]:
        """Return every device with a signal reading, for the signal
        options picker: pick-from-detected, what you see is what is
        being judged. Excluded devices are present, because an
        excluded device is exactly the thing this picker exists to
        un-tick."""
        rows = [
            {
                "device_id": device_id,
                "name": self._device_names.get(device_id, device_id),
                "integration": self._watched.get(device_id, "?"),
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, record in self.data.get(
                DATA_DEVICES, {}
            ).items()
            if record.get(DEV_SIGNAL_VALUE) is not None
            or record.get(DEV_SIGNAL_DAILY_MIN)
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    @property
    def watched_device_rows(self) -> list[dict[str, Any]]:
        """Return every watched device, for the exclusions picker.

        Service-type devices are absent because they were never
        watched, so the list cannot offer an exclusion that would do
        nothing. Excluded devices are present: the list is what is
        being judged, and an excluded device is still a device you
        may want to un-exclude.
        """
        rows = [
            {
                "device_id": device_id,
                "name": self._device_names.get(device_id, device_id),
                "integration": integration_domain,
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, integration_domain in self._watched.items()
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    def _enable_matching_entities(
        self,
        matches: Callable[[er.RegistryEntry], bool],
        kind: str,
    ) -> dict[str, int]:
        """Enable integration-disabled entities a matcher recognizes,
        on watched devices. User-disabled entities are respected and
        only counted, never re-enabled: a user who turned something
        off meant it. Home Assistant reloads the owning config entries
        automatically a short delay after enabling.

        Split by kind (signals, last_seen, battery) so a user can
        enable exactly the diagnostic they want without turning on the
        others. Each kind is its own button, its own press.
        """
        ent_reg = er.async_get(self.hass)
        enabled = 0
        skipped_user = 0
        for ent in list(ent_reg.entities.values()):
            if ent.device_id not in self._watched:
                continue
            if not matches(ent):
                continue
            if ent.disabled_by is None:
                continue
            if ent.disabled_by is er.RegistryEntryDisabler.USER:
                skipped_user += 1
                continue
            ent_reg.async_update_entity(ent.entity_id, disabled_by=None)
            enabled += 1
        LOGGER.info(
            "Enable %s: enabled %d entities; %d left alone because a "
            "user disabled them. Home Assistant reloads the owning "
            "integrations shortly",
            kind,
            enabled,
            skipped_user,
        )
        return {"enabled": enabled, "skipped_user": skipped_user}

    async def async_enable_signal_entities(self) -> dict[str, int]:
        """Enable integration-disabled signal-strength entities."""
        return self._enable_matching_entities(self._is_signal, "signals")

    async def async_enable_last_seen_entities(self) -> dict[str, int]:
        """Enable integration-disabled last_seen entities."""
        return self._enable_matching_entities(
            self._is_last_seen, "last_seen"
        )

    async def async_enable_battery_entities(self) -> dict[str, int]:
        """Enable integration-disabled battery-percentage entities.

        Percentage batteries only (the sensor, not the binary low
        flag): the percentage is what the discharge series records,
        and the low flag is caught by the battery threshold whether
        or not this entity is on.
        """
        return self._enable_matching_entities(
            self._is_battery_percentage, "battery"
        )

    @staticmethod
    def _is_battery_percentage(ent: er.RegistryEntry) -> bool:
        """Recognize a battery-percentage sensor, excluding the binary
        low flag. The percentage is what feeds the discharge series."""
        if str(ent.original_device_class or ent.device_class) != "battery":
            return False
        return ent.entity_id.startswith("sensor.")

    @property
    def clock_source_split(self) -> dict[str, Any]:
        """Return the last_seen versus recorded-clock split."""
        with_ls = sum(
            1 for dev in self._watched if dev in self._last_seen_entity
        )
        without_by_domain: dict[str, int] = {}
        for dev, domain in self._watched.items():
            if dev not in self._last_seen_entity:
                without_by_domain[domain] = (
                    without_by_domain.get(domain, 0) + 1
                )
        return {
            "with_last_seen": with_ls,
            "without_last_seen": len(self._watched) - with_ls,
            "with_signal": len(self._signal_devices & set(self._watched)),
            "without_signal": len(
                set(self._watched) - self._signal_devices
            ),
            "without_by_integration": without_by_domain,
        }
