# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: coordinator.py, Version: 0.7.2 (2026-07-22)

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

import math
import contextlib
import os
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
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
from homeassistant.helpers.dispatcher import async_dispatcher_send
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
    CONF_FREEZE_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_EXCLUDED_LABELS,
    CONF_SIGNAL_SENSITIVITY,
    DEFAULT_SIGNAL_SENSITIVITY,
    CONF_EXCLUDED_LABELS,
    DATA_TODO_ITEMS,
    CONF_LOW_THRESHOLD,
    DAILY_MAX_KEEP,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_REMINDER_TIME,
    DATA_STATS_EPOCH,
    REPORT_CLASSIFICATION,
    REPORT_DIR,
    REPORT_BRIEF_PREFIX,
    REPORT_EPISODES,
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
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
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
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_DELTA_HIGH,
    DEFAULT_FREEZE_DELTA_LOW_MIN,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    FREEZE_REF_RHYTHM_FAST,
    FREEZE_REF_RHYTHM_SLOW,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNKNOWN,
    FREEZE_CATEGORY_PRIORITY,
    FREEZE_CATEGORY_NOT_REPORTED,
    FREEZE_NOT_REPORTED_SECONDS,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    LOGGER,
    RENDER_TICK_SECONDS,
    STARTUP_GRACE_SECONDS,
    EPISODE_ENDED_REBOOT,
    EPISODE_ENDED_RECONNECT,
    EPISODE_ENDED_RESTART,
    EPISODE_ENDED_RESUMED,
    EPISODE_KEEP_DAYS,
    FREEZE_KINDS_FOR_CAUSE,
    INCIDENT_ACKNOWLEDGED,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    OUTBOX_KEEP,
    OUTBOX_SHAPE_DEVICE,
    OUTBOX_SHAPE_EVENT,
    OUT_DEVICE_ID,
    OUT_SHAPE,
    OUT_TEXT,
    OUT_WHEN,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    COALESCE_MINUTES_MAX,
    COALESCE_MINUTES_MIN,
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    DEFAULT_COALESCE_MINUTES,
    DEFAULT_EPISODE_SHARE_PCT,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_WINDOW,
    STORAGE_KEY,
    STORAGE_VERSION,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_HISTORY_SECONDS,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    TAINT_DEBOUNCE_SECONDS,
    BRIEF_KEEP_DAYS,
    CONF_REMINDER_TIME,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_OUTBOX,
    DATA_TODO_JOURNAL,
    SIGNAL_PROBLEM_ADDITION,
    TODO_ACKED_AT,
    TODO_DESCRIPTION,
    TODO_DEVICE_ID,
    TODO_JOURNAL_KEEP,
    TODO_KIND_BATTERY,
    TODO_KIND_SIGNAL,
    TODO_KINDS,
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
        DEV_FROZEN_CATEGORY: None,
        DEV_FROZEN_SINCE: None,
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
        # Two-tier persistence (0.6.5, analysis finding E1). _dirty
        # alone is routine churn (activity clocks) and coalesces into
        # a delayed save; _critical marks a change a reboot must not
        # lose (a verdict, a battery flip, a problem-list change) and
        # forces the immediate save the tick used to do for
        # everything. Acknowledgments and options changes keep their
        # own direct awaited saves and never wait for a tick.
        self._critical: bool = False
        # Whether a delayed routine save is already scheduled. The
        # 0.6.5 flaw, caught by the storage watch within its first
        # hour: async_delay_save reschedules on every call, so a
        # dirty tick every minute pushed the 900-second deadline
        # forward forever and the routine write never fired. The
        # delayed save is now scheduled only when none is pending;
        # the flag clears when the write fires (inside
        # _data_to_save) and at every immediate save, since a direct
        # save cancels the store's pending delayed write.
        self._delay_pending: bool = False

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
        self._outbox_pending: set[str] = set()
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
        loaded.setdefault(DATA_TODO_JOURNAL, [])
        loaded.setdefault(DATA_EPISODES, [])
        loaded.setdefault(DATA_INCIDENTS, [])
        loaded.setdefault(DATA_OUTBOX, [])
        # 0.6.0: the list is engine-owned. Anything stored without a
        # device_id is a hand-typed item from the pre-sync backbone
        # (the create feature is gone with this release) and is
        # purged, so every install lands on a list the sync alone
        # maintains. Engine items gain the new fields in place.
        engine_items = [
            record
            for record in loaded[DATA_TODO_ITEMS]
            if record.get(TODO_DEVICE_ID)
        ]
        purged = len(loaded[DATA_TODO_ITEMS]) - len(engine_items)
        if purged:
            LOGGER.info(
                "Problem list: purged %d hand-typed item(s); the list "
                "is maintained by detections alone from 0.6.0",
                purged,
            )
        loaded[DATA_TODO_ITEMS] = engine_items
        for record in engine_items:
            record.setdefault(TODO_KINDS, {})
            record.setdefault(TODO_ACKED_AT, None)
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
        # Judge freezes once before the setup report is written, so a
        # device already down (frozen, unavailable, or never reported)
        # shows in that first report rather than reading a false
        # all-clear until the next tick or the midnight rollover.
        # Verdicts are measured from the stored clock, which survives
        # the restart, so this is the same judgment the tick reaches,
        # run early.
        self._judge_all_devices()
        # Sync the problem list only after that judgment pass, never
        # before: the detections are rebuilt by the pass, so the sync
        # sees the same problems it saw before the reboot and a
        # still-present problem keeps its item (and its checkbox). A
        # sync against not-yet-judged lists would read as a fleet-wide
        # recovery and mass-delete the list at every boot.
        self._sync_problem_list()

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
        if self._dirty or self._critical:
            await self._save_now()

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
        # Guarded rather than indexed: the filter has already checked
        # membership, but that safety lives in HA dispatching filter
        # and handler in one loop turn. The guard makes the invariant
        # local, so a future dispatch change cannot raise here.
        mapped = self._entity_map.get(entity_id)
        if mapped is None:
            return
        device_id, entry_id = mapped
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
        # Same guard as _on_state_changed, same reason.
        mapped = self._entity_map.get(entity_id)
        if mapped is None:
            return
        device_id, entry_id = mapped
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

        # The episode's verdict, decided by which branch above ran:
        # a gap this stamp completed cleanly is learned, anything the
        # exclusions caught says so and why. A lever-ended gap
        # measures the lever, not the device (#104).
        if grace:
            learned = "no (startup grace)"
        elif storm is not None:
            learned = "no (storm)"
        elif tainted:
            learned = "no (taint, unavailable)"
        else:
            learned = "yes"
        self._close_episode(device_id, now, learned)

        record[DEV_LAST_ACTIVITY] = now
        record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
        self._dirty = True

        # Recovery is live: a device that reports is alive, so any
        # standing freeze verdict clears the instant it speaks, and
        # the device leaves the report at that moment rather than at
        # the next sweep.
        self._clear_freeze_verdict(device_id, record)

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
        # The roll is what confirms a rail (three daily lows at the
        # fill value), so the sync runs here and the item appears
        # with the rollover rather than a minute behind it.
        self._sync_problem_list()
        if pushed or self._dirty or self._critical:
            await self._save_now()
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
        self._write_episodes(report_directory, trigger)
        # The brief's window runs from the last brief time to now, so
        # a regenerate mid-day writes the in-progress one and the
        # scheduled write at the brief hour closes the day (#116).
        now = dt_util.utcnow().timestamp()
        self._write_brief(
            report_directory,
            trigger,
            self._brief_window_start(now),
            now,
            complete=trigger == "daily brief",
        )

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

    # ------------------------------------------------------ freeze margin

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
        """Return the grace margin for a rhythm, in seconds (#85).

        grace = a * rhythm^p, where a and p are solved so the curve
        passes through delta-low grace at the fast reference rhythm
        and delta-high grace at the slow one. The two deltas therefore
        set the whole shape, not just the ends, and the result is
        clamped to [delta-low, delta-high] so they double as the hard
        floor and ceiling. The rhythm itself is never touched here: it
        is the measured trimmed maximum, and grace is only the
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

    def _freeze_window(self, record: dict[str, Any]) -> float | None:
        """Return the freeze window for a device, in seconds, or None.

        The window is the learned rhythm plus the grace margin. None
        means the device is not yet armed for freeze: it has too few
        learned days for a trustworthy rhythm (the arming gate, #27),
        so it is watched for unavailable and unknown but never called
        frozen, because there is no window to miss.
        """
        daily = record[DEV_DAILY_MAX]
        if len(daily) < FREEZE_ARMING_DAYS:
            return None
        rhythm, _ = self._trimmed_maximum(daily)
        if rhythm is None or rhythm <= 0:
            return None
        return rhythm + self._freeze_grace(rhythm)

    # ------------------------------------------------ device-down judgment

    def _live_entity_states(self, device_id: str) -> list[str]:
        """Return the current states of a device's live (enabled)
        entities. A missing state object means the entity is not live
        and is skipped, so the judgment reads only what a person could
        see reporting.
        """
        states: list[str] = []
        for entity_id, (owner, _) in self._entity_map.items():
            if owner != device_id:
                continue
            state = self.hass.states.get(entity_id)
            if state is not None:
                states.append(state.state)
        return states

    def _device_down_category(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> str | None:
        """Return the down category for a device, or None if alive.

        The rule (#device-level): if any live entity is fresh, the
        device is alive, whatever its other entities read. A device is
        down only when nothing on it is reporting. Then the category
        is read from what the entities show, and a mix resolves to the
        most definite state (unavailable dominates frozen dominates
        unknown), because a device with most entities unavailable is a
        dead device whose remaining entities have simply not flipped
        yet.
        """
        # A globally-excluded or freeze-excluded device keeps its
        # clock and rhythm but is never given a verdict of any kind.
        # Global exclusion suppresses all judgment, so it is checked
        # here rather than only filtered from the report: no verdict
        # is computed or stored for a device the person has told the
        # integration to ignore.
        if (
            device_id in self._excluded_devices
            or self._freeze_excluded(device_id)
        ):
            return None

        # Never reported: zero lifetime events past the grace window.
        # Checked first because it is categorically different from a
        # device that reported and stopped, and because such a device
        # has no rhythm to miss and may have no live entity to read.
        if record[DEV_EVENT_COUNT] == 0 and record[DEV_LAST_ACTIVITY] is None:
            first = record.get(DEV_FIRST_OBSERVED)
            if first is not None:
                try:
                    observed = dt_util.parse_datetime(first)
                    age = now - observed.timestamp() if observed else 0.0
                except (ValueError, AttributeError):
                    age = 0.0
                if age >= FREEZE_NOT_REPORTED_SECONDS:
                    return FREEZE_CATEGORY_NOT_REPORTED
            return None

        window = self._freeze_window(record)
        last = record[DEV_LAST_ACTIVITY]

        # Frozen: armed, and silent past its window while entities
        # still hold values. Judged first because it is the timer's
        # own verdict.
        frozen = (
            window is not None
            and last is not None
            and (now - last) >= window
        )

        states = self._live_entity_states(device_id)
        if not states:
            # No live entities to read. A silent armed device with no
            # readable state is still a freeze by its clock.
            return FREEZE_CATEGORY_FROZEN if frozen else None

        any_unavailable = STATE_UNAVAILABLE in states
        any_unknown = STATE_UNKNOWN in states
        all_bad = all(s in BAD_STATES for s in states)

        # If every live entity reads bad, the device is down now,
        # regardless of the clock: this is the unavailable/unknown
        # path, which needs no arming because it reads present state.
        if all_bad:
            present = {
                FREEZE_CATEGORY_UNAVAILABLE: any_unavailable,
                FREEZE_CATEGORY_UNKNOWN: any_unknown,
                FREEZE_CATEGORY_FROZEN: frozen,
            }
            for category in FREEZE_CATEGORY_PRIORITY:
                if present.get(category):
                    return category
            return FREEZE_CATEGORY_UNAVAILABLE

        # Some entity is not bad. If the clock says frozen and the
        # non-bad entities are stale (not fresh), the device is
        # frozen; a genuinely fresh entity would have re-armed the
        # timer, so reaching here with frozen True means the values
        # are held, not live.
        if frozen:
            return FREEZE_CATEGORY_FROZEN
        return None

    def _apply_freeze_verdict(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> bool:
        """Judge one device and store the verdict if it changed.

        Returns True when the verdict flipped, so the caller can
        refresh the sensor once per flip rather than on every reading
        (#234). A debounce holds an unavailable or unknown verdict
        until the device has been down long enough to rule out a
        mid-transition flip; the frozen verdict needs no debounce
        because its window already is the wait.
        """
        category = self._device_down_category(device_id, record, now)
        # Pre-0.5.0 records predate the freeze fields, and the storage
        # prune removes unknown keys but never adds missing ones, so
        # such a record arrives here without them. Default them before
        # reading, or the direct read raises KeyError and, with the
        # sweep's per-device guard, that record is skipped.
        record.setdefault(DEV_FROZEN_CATEGORY, None)
        record.setdefault(DEV_FROZEN_SINCE, None)
        current = record[DEV_FROZEN_CATEGORY]

        if category in (
            FREEZE_CATEGORY_UNAVAILABLE,
            FREEZE_CATEGORY_UNKNOWN,
        ):
            # Debounce the transition: only publish once the device
            # has read down for longer than a quick-succession flip.
            since = record.get(DEV_FROZEN_SINCE)
            if current is None:
                if since is None:
                    record[DEV_FROZEN_SINCE] = now
                    self._dirty = True
                    return False
                if (now - since) < FREEZE_UNAVAILABLE_DEBOUNCE:
                    return False

        if category == current:
            return False

        record[DEV_FROZEN_CATEGORY] = category
        if category is None:
            record[DEV_FROZEN_SINCE] = None
        elif current is None:
            record[DEV_FROZEN_SINCE] = record.get(DEV_FROZEN_SINCE) or now
        self._dirty = True
        self._critical = True
        LOGGER.info(
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
        moment a frozen device speaks, it leaves the report.
        """
        if record.get(DEV_FROZEN_CATEGORY) is not None:
            record[DEV_FROZEN_CATEGORY] = None
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

    # ------------------------------------------------ silence episodes

    def _open_episode_for(self, device_id: str) -> dict[str, Any] | None:
        """Return a device's episode still awaiting its lag, if any.

        Awaiting means either fully open (no end recorded) or ended by
        an intervention whose lag cannot be known until the device
        speaks again. Both are completed by the same next report. A
        resumed episode is finished and carries no lag by design (it
        had no lever to measure from), so it never blocks the next
        episode for that device.
        """
        for episode in reversed(self.data.get(DATA_EPISODES) or []):
            if episode[EP_DEVICE_ID] != device_id:
                continue
            if episode[EP_ENDED] is None:
                return episode
            if (
                episode[EP_ENDED] != EPISODE_ENDED_RESUMED
                and episode[EP_LAG] is None
            ):
                return episode
            return None
        return None

    def _note_silences(self, now: float) -> None:
        """Open an episode for any device well into its own patience.

        The threshold is basis plus a share of that device's grace
        (#105, configurable since #117): the silence has spent that share of the
        distance from the rhythm to the freeze line. Basis alone,
        shipped at 0.6.7, was too sensitive at the fast end, where a
        rhythm of seconds is exceeded constantly and trivial silences
        filled the file, while the same rule was properly selective
        for a device measured in hours. A share of grace scales with
        the patience each device has earned, so a 36-second device
        opens at minutes and an hours-long device opens at hours,
        both a clear distance short of judgment.

        Devices whose freeze judgment is suppressed are skipped
        (#106). Exclusion suppresses judgment and reporting while
        observation continues, and this file exists to explain
        verdicts: a device that can never be judged frozen has no
        verdict to explain, so its silences are noise here. A device
        excluded only for battery or signal is still judged for
        freeze and still belongs.
        """
        if now < self._grace_until:
            # Startup grace: every stored clock is stale by however
            # long the system was down, so opening episodes here
            # would manufacture a batch of rows that the startup
            # storm closes seconds later, all of them describing the
            # restart rather than any device. Silences that matter
            # are still open in the record from before the restart,
            # and new ones open once grace closes (0.7.0).
            return
        for device_id in self._watched:
            if device_id in self._excluded_devices or self._freeze_excluded(
                device_id
            ):
                continue
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            last = record.get(DEV_LAST_ACTIVITY)
            if last is None:
                continue
            daily = record.get(DEV_DAILY_MAX) or []
            if len(daily) < FREEZE_ARMING_DAYS:
                continue
            basis, _ = self._trimmed_maximum(daily)
            if basis is None or basis <= 0:
                continue
            window = self._freeze_window(record)
            grace = (window - basis) if window is not None else 0.0
            if now - last <= basis + self.episode_share * grace:
                continue
            if self._open_episode_for(device_id) is not None:
                continue
            self.data.setdefault(DATA_EPISODES, []).append(
                {
                    EP_DEVICE_ID: device_id,
                    EP_NAME: self._device_name(device_id),
                    EP_SINCE: last,
                    EP_BASIS: basis,
                    EP_WINDOW: window,
                    EP_ENDED: None,
                    EP_AT: None,
                    EP_LAG: None,
                    EP_LEARNED: None,
                }
            )
            self._dirty = True

    def _close_episode(
        self, device_id: str, now: float, learned: str | None
    ) -> None:
        """Complete a device's episode when it genuinely reports.

        Two shapes complete here. A still-open episode closes as
        resumed: the device chose to speak, and the learned column
        says whether its gap reached the statistics. An episode
        already stamped by an intervention gains only its lag, the
        time from the lever to the first genuine report, which is the
        column that separates a wedge (seconds) from a device that
        was merely quiet (hours).
        """
        episode = self._open_episode_for(device_id)
        if episode is None:
            return
        if episode[EP_ENDED] is None:
            episode[EP_ENDED] = EPISODE_ENDED_RESUMED
            episode[EP_AT] = now
            episode[EP_LEARNED] = learned
        else:
            episode[EP_LAG] = max(0.0, now - (episode[EP_AT] or now))
            if episode[EP_LEARNED] is None:
                episode[EP_LEARNED] = learned
        self._dirty = True

    def _stamp_intervention(self, cause: str, now: float) -> None:
        """Mark every open episode as ended by an intervention.

        A reboot or a bridge reconnect truncates a silence: we know
        the device had been quiet at least this long, never how much
        longer it would have stayed quiet. The row keeps that honesty
        by recording the cause and waiting for the lag.
        """
        stamped = 0
        for episode in self.data.get(DATA_EPISODES) or []:
            if episode[EP_ENDED] is None:
                episode[EP_ENDED] = cause
                episode[EP_AT] = now
                stamped += 1
        if stamped:
            self._dirty = True
            LOGGER.info(
                "Stamped %d open silence episode(s) as %s", stamped, cause
            )

    def _trim_episodes(self, now: float) -> None:
        """Drop episodes older than the statistics window.

        Fourteen days by timestamp, matching the daily-maxima series
        the file exists to explain. An episode still awaiting its lag
        survives the boundary: an unfinished story is not old news.
        """
        cutoff = now - EPISODE_KEEP_DAYS * 86400.0
        episodes = self.data.get(DATA_EPISODES) or []
        kept = [
            episode
            for episode in episodes
            if episode[EP_SINCE] >= cutoff
            or episode[EP_ENDED] is None
            or (
                episode[EP_ENDED] != EPISODE_ENDED_RESUMED
                and episode[EP_LAG] is None
            )
        ]
        if len(kept) != len(episodes):
            self.data[DATA_EPISODES] = kept
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
        flipped = False
        for device_id in self._watched:
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            # Guard each device: one malformed record must never kill
            # the whole sweep, which would stop verdicts, saving, and
            # refreshing for every device (the 0.5.1 tick crash).
            try:
                if self._apply_freeze_verdict(device_id, record, now):
                    flipped = True
            except Exception:  # noqa: BLE001
                LOGGER.info(
                    "Skipped a device in the freeze sweep after an "
                    "unexpected error judging it: %s",
                    self._device_name(device_id),
                )
        if flipped:
            self._notify()

    def _device_name(self, device_id: str) -> str:
        """Return a device's display name for logging and the report."""
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id)
        if device is not None and (device.name_by_user or device.name):
            return device.name_by_user or device.name
        return device_id

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

    @staticmethod
    def _report_cell(text: str) -> str:
        """Return text safe for a Markdown table cell or report line.

        Device names are user-controlled: a pipe in a name would
        split its table row and a newline would break it entirely.
        Escaping here, at the single choke point every name passes on
        its way into a report, keeps the files intact whatever a
        device is called. Cosmetic hardening, not a security fix; the
        reports are local files.
        """
        return (
            text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
        )

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
            f"Written {self._format_report_time(dt_util.now())} "
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
            "STATUS is Reported (judged for everything) or Excluded "
            "with the reason in parentheses: GLB global (all judgment "
            "off), BAT battery, SIG signal, FRZ freeze. GLB shows "
            "alone; the section reasons combine, Excluded (BAT, FRZ). "
            "An excluded device keeps recording; exclusion suppresses "
            "judgment, not observation.",
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
        ]
        lines.extend(self._reporting_lines())
        lines += [
            "## Learned statistics",
            "",
            f"| DEVICE (INTEGRATION) | STATUS | GAPS (K={TRIM_TOP_K}) | "
            f"CLOCK | EVENTS | SIGNAL ({self._signal_slider_label()}) | "
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
            integration = self._watched.get(device_id, "?")
            device_label = f"{self._report_cell(device_name)} ({integration})"
            daily_maximum_gaps = record.get(DEV_DAILY_MAX) or []
            operative, _ = self._trimmed_maximum(daily_maximum_gaps)
            rows.append(
                (
                    device_label,
                    self._device_status(device_id),
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
        # Alphabetical by the device label, case-insensitive: the table
        # is a reference chart a person scans by name, so strict
        # alphabetical is what they expect (the descending-gap order
        # that suited the soak is gone; the Reporting Devices section
        # above already surfaces what is in trouble).
        rows.sort(key=lambda row: row[0].lower())
        for (
            device_label,
            status,
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
                f"| {device_label} | {status} | "
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

    @staticmethod
    def _episode_duration(seconds: float | None) -> str:
        """Return a duration in the report's mixed units."""
        if seconds is None:
            return ""
        seconds = max(0.0, seconds)
        if seconds >= 3600:
            return f"{seconds / 3600:.2f}h"
        if seconds >= 60:
            return f"{seconds / 60:.0f}m"
        return f"{seconds:.0f}s"

    def _episode_stamp(self, epoch: float | None) -> str:
        """Return a local timestamp for an episode column."""
        if epoch is None:
            return ""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %d %H:%M")

    @staticmethod
    def _human_span(seconds: float | None) -> str:
        """Return a duration in the units a person thinks in."""
        if seconds is None:
            return "?"
        seconds = max(0.0, seconds)
        if seconds >= 86400:
            return f"{seconds / 86400:.1f}d"
        if seconds >= 3600:
            return f"{seconds / 3600:.1f}h"
        if seconds >= 60:
            return f"{seconds / 60:.0f}m"
        return f"{seconds:.0f}s"

    @staticmethod
    def _brief_moment(epoch: float) -> str:
        """Return a readable local time for the brief."""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%b %-d, %-I:%M %p")

    def _brief_phrase(self, row: dict[str, Any]) -> str:
        """Return one incident as a sentence a person would write.

        Plain language, never category names: a reader should not
        need to know what "frozen" means inside this integration to
        understand that a device stopped reporting. A resolution
        carries how long it lasted and what ended it in the same
        phrase, which over a fortnight is the column that says
        whether a device recovers on its own or only when levered.
        """
        kind = row[INC_KIND]
        event = row[INC_EVENT]
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            cause = row.get(INC_CAUSE)
            base = f"recovered after {span}"
            return f"{base}, {cause}" if cause else base
        if event == INCIDENT_ACKNOWLEDGED:
            return "acknowledged"
        wording = {
            "frozen": "stopped reporting",
            "not_reported": "has never reported",
            "unavailable": "went unavailable",
            "unknown": "went unknown",
            "signal": "signal railed",
        }
        if kind == "battery":
            return "battery fell low"
        return wording.get(kind, kind)

    def _brief_now_rows(self) -> list[tuple[str, str, float, str]]:
        """Return the standing state: what is wrong right now.

        Read from the problem list rather than recomputed, so the
        brief and the list can never disagree. Excluded devices are
        absent because this is a report, and acknowledged items are
        present but marked, because a record shows what a person
        chose to live with.
        """
        now = dt_util.utcnow().timestamp()
        rows: list[tuple[str, str, float, str]] = []
        for record in self.todo_items:
            device_id = record.get(TODO_DEVICE_ID)
            if not device_id or device_id in self._excluded_devices:
                continue
            name = record.get(TODO_SORT_NAME) or device_id
            acked = record.get(TODO_STATUS) == "completed"
            for kind, since in (record.get(TODO_KINDS) or {}).items():
                problem = {
                    "frozen": "stopped reporting",
                    "not_reported": "never reported",
                    "unavailable": "unavailable",
                    "unknown": "unknown",
                    "signal": "signal railed",
                    "battery": self._brief_battery_text(device_id),
                }.get(kind, kind)
                if acked:
                    problem = f"{problem} (acknowledged)"
                rows.append((name, problem, since or now, kind))
        rows.sort(key=lambda row: row[2])
        return rows

    def _brief_battery_text(self, device_id: str) -> str:
        """Return the battery cell with its level where known."""
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        if isinstance(level, (int, float)):
            shown = (
                f"{int(level)}%"
                if float(level).is_integer()
                else f"{level}%"
            )
            return f"battery {shown}"
        return "battery low"

    @property
    def episode_share(self) -> float:
        """Return the configured episode-opening share, as a fraction.

        Live from options (#117): a silence opens an episode once it
        has spent this much of the distance from the device's rhythm
        to its freeze line. Clamped to the same band the screen
        offers, so a hand-edited entry cannot produce a threshold
        that records everything or nothing.
        """
        raw = int(
            self.entry.options.get(
                CONF_EPISODE_SHARE, DEFAULT_EPISODE_SHARE_PCT
            )
        )
        return min(SHARE_PCT_MAX, max(SHARE_PCT_MIN, raw)) / 100.0

    @property
    def coalesce_seconds(self) -> float:
        """Return the routine-save interval in seconds.

        Live from options (#117), clamped to the offered band. Only
        routine activity waits: verdicts, battery flips, list changes
        and acknowledgments always write immediately, so this governs
        wear and crash-window, never correctness.
        """
        raw = int(
            self.entry.options.get(
                CONF_COALESCE_MINUTES, DEFAULT_COALESCE_MINUTES
            )
        )
        minutes = min(
            COALESCE_MINUTES_MAX, max(COALESCE_MINUTES_MIN, raw)
        )
        return minutes * 60.0

    def _brief_window_start(self, now: float) -> float:
        """Return the start of the current brief window.

        The most recent brief hour at or before now, so the window
        always runs brief-to-brief rather than by calendar day: an
        overnight problem stays in one report instead of being split
        across two. A user who wants calendar days sets the brief
        time to midnight.
        """
        local_now = dt_util.as_local(dt_util.utc_from_timestamp(now))
        raw = str(
            self.entry.options.get(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME)
        )
        try:
            hour, minute = (int(part) for part in raw.split(":")[:2])
        except ValueError:
            hour, minute = 8, 0
        candidate = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate > local_now:
            candidate -= timedelta(days=1)
        return candidate.timestamp()

    def _write_brief(
        self,
        report_directory: str,
        trigger: str,
        window_start: float,
        window_end: float,
        complete: bool,
    ) -> None:
        """Write the daily brief for a window.

        The one report written for a person rather than a maintainer
        (#116): what is wrong now, what happened in the last 24
        hours, plain language, human units, no basis or window or
        lag or exclusion reasoning. Regenerating mid-day writes the
        in-progress brief with its scope stated and marked
        incomplete, replacing itself until the real brief publishes
        and starts a new day.
        """
        now_rows = self._brief_now_rows()
        incidents = [
            row
            for row in (self.data.get(DATA_INCIDENTS) or [])
            if window_start <= row[INC_WHEN] <= window_end
            and row[INC_DEVICE_ID] not in self._excluded_devices
        ]
        incidents.sort(key=lambda row: row[INC_WHEN], reverse=True)
        opened = sum(
            1 for row in incidents if row[INC_EVENT] == INCIDENT_OPENED
        )
        resolved = sum(
            1 for row in incidents if row[INC_EVENT] == INCIDENT_RESOLVED
        )
        acked_now = sum(
            1
            for record in self.todo_items
            if record.get(TODO_STATUS) == "completed"
        )
        scope = (
            f"{self._brief_moment(window_end)}. Covering the 24 hours "
            f"since {self._brief_moment(window_start)}."
            if complete
            else f"In progress. From "
            f"{self._brief_moment(window_start)} to "
            f"{self._brief_moment(window_end)} (incomplete)."
        )
        lines = [
            "# Device Sentinel daily brief",
            "",
            scope,
            "",
            "## Now",
            "",
        ]
        if not now_rows:
            lines += ["Nothing needs attention.", ""]
        else:
            devices = len({row[0] for row in now_rows})
            summary = (
                f"{devices} device{'s' if devices != 1 else ''} "
                f"need{'' if devices != 1 else 's'} attention"
            )
            if acked_now == 1:
                summary += ", one of them acknowledged."
            elif acked_now > 1:
                summary += f", {acked_now} of them acknowledged."
            else:
                summary += "."
            now = dt_util.utcnow().timestamp()
            lines += [
                summary,
                "",
                "| DEVICE | PROBLEM | SINCE | FOR |",
                "|---|---|---|---|",
            ]
            for name, problem, since, kind in now_rows:
                # A device that has never reported has no last-seen
                # time; the stamp is when it was discovered in the
                # registry, and saying so stops a reader taking it
                # for the moment the device broke (#118).
                when = (
                    f"discovered {self._brief_moment(since)}"
                    if kind == "not_reported"
                    else self._brief_moment(since)
                )
                lines.append(
                    f"| {self._report_cell(name)} | {problem} "
                    f"| {when} "
                    f"| {self._human_span(now - since)} |"
                )
            lines.append("")
        lines += ["## Last 24 hours", ""]
        if not incidents:
            lines += ["Nothing happened.", ""]
        else:
            lines += [
                f"{len(incidents)} event"
                f"{'s' if len(incidents) != 1 else ''}. "
                f"{opened} problem{'s' if opened != 1 else ''} "
                f"started, {resolved} ended.",
                "",
                "| TIME | DEVICE | WHAT HAPPENED |",
                "|---|---|---|",
            ]
            for row in incidents:
                lines.append(
                    f"| {self._brief_moment(row[INC_WHEN])} "
                    f"| {self._report_cell(row[INC_NAME])} "
                    f"| {self._brief_phrase(row)} |"
                )
            lines.append("")
        stamp = dt_util.as_local(
            dt_util.utc_from_timestamp(window_end)
        ).strftime("%Y-%m-%d")
        path = os.path.join(
            report_directory, f"{REPORT_BRIEF_PREFIX}{stamp}.md"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self._trim_briefs(report_directory)

    def _trim_briefs(self, report_directory: str) -> None:
        """Keep the most recent briefs, drop the rest."""
        try:
            names = sorted(
                name
                for name in os.listdir(report_directory)
                if name.startswith(REPORT_BRIEF_PREFIX)
                and name.endswith(".md")
            )
        except OSError:
            return
        for name in names[:-BRIEF_KEEP_DAYS]:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(report_directory, name))

    def _write_episodes(self, report_directory: str, trigger: str) -> None:
        """Write the silence-episode report.

        The forensic file (#103). One row per episode, newest first,
        recording what the other two reports cannot: whether a long
        silence ended because the device chose to speak or because
        something made it speak. That distinction is the difference
        between a rhythm the statistics should learn and a wedge no
        amount of patience would have fixed, and it is invisible in
        any per-device summary because a device produces one episode
        per occurrence, not one number.
        """
        episodes = list(self.data.get(DATA_EPISODES) or [])
        episodes.sort(key=lambda row: row[EP_SINCE], reverse=True)
        now = dt_util.utcnow().timestamp()
        open_count = sum(1 for row in episodes if row[EP_ENDED] is None)
        lines = [
            f"# Device Sentinel v{self.version} silence episodes",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            "",
            "One row per episode: a device whose silence passed its "
            "own learned basis. Devices reporting within their rhythm "
            "never appear. An episode closes when the device reports "
            "again (resumed) or when something intervened (a reboot, "
            "a bridge reconnect), which truncates the silence at a "
            "lower bound. LAG is how long after an intervention the "
            "device took to speak: seconds means the intervention "
            "revived it, hours means it was never stuck. LEARNED says "
            "whether the completed gap reached the statistics, and "
            "why not when it did not. Kept "
            f"{EPISODE_KEEP_DAYS} days; {len(episodes)} episode(s), "
            f"{open_count} still open.",
            "",
        ]
        if not episodes:
            lines += [
                "No device has been silent past its own rhythm since "
                "this record began.",
                "",
            ]
        else:
            lines += [
                "| SILENT SINCE | DEVICE | BASIS | WINDOW | SILENCE | "
                "ENDED | AT | LAG | LEARNED |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for row in episodes:
                end_epoch = row[EP_AT]
                silence = (
                    (end_epoch - row[EP_SINCE])
                    if end_epoch is not None
                    else (now - row[EP_SINCE])
                )
                lines.append(
                    f"| {self._episode_stamp(row[EP_SINCE])} "
                    f"| {self._report_cell(row[EP_NAME] or row[EP_DEVICE_ID])} "
                    f"| {self._episode_duration(row[EP_BASIS])} "
                    f"| {self._episode_duration(row[EP_WINDOW])} "
                    f"| {self._episode_duration(silence)} "
                    f"| {row[EP_ENDED] or 'open'} "
                    f"| {self._episode_stamp(end_epoch)} "
                    f"| {self._episode_duration(row[EP_LAG])} "
                    f"| {row[EP_LEARNED] or ''} |"
                )
            lines.append("")
        path = os.path.join(report_directory, REPORT_EPISODES)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

    def _write_classification(
        self, report_directory: str, trigger: str
    ) -> None:
        """Write classification.md, the audit view.

        One row per device, so a device's whole standing reads across
        a single line: whether it is Watched (has hardware, recording)
        or Set aside (a service device with nothing to watch), and, for
        a watched device, whether the global exclude has it and why.
        Every device is watched and recorded; exclusion only suppresses
        judgment and reporting, so an excluded device still carries a
        Watched check, with the reason alongside it. COPIES flags a
        name shared by more than one registry device. Section excludes
        (battery, signal, freeze) are not shown here; they live in the
        telemetry STATUS column, because a section-excluded device is
        still judged for everything else and is not excluded wholesale.
        """
        dev_reg = dr.async_get(self.hass)

        name_copy_counts: dict[str, int] = {}
        for device_id, integration_domain in self._watched.items():
            device = dev_reg.async_get(device_id)
            name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            name_copy_counts[name] = name_copy_counts.get(name, 0) + 1

        # Build one row per device, watched and set-aside together, so
        # the table reads as a single audit.
        rows: list[tuple[str, str, str, str, str, str]] = []
        for device_id, integration_domain in self._watched.items():
            device = dev_reg.async_get(device_id)
            name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            reason = self._excluded_devices.get(device_id)
            excluded_cell = f"Global ({reason})" if reason else ""
            copies = name_copy_counts.get(name, 1)
            rows.append(
                (
                    name,
                    integration_domain,
                    "yes",  # watched
                    excluded_cell,
                    "",  # set aside
                    str(copies) if copies > 1 else "",
                )
            )
        for name, integration_domain in self._set_aside.values():
            rows.append(
                (name, integration_domain, "", "", "yes", "")
            )
        rows.sort(key=lambda row: row[0].lower())

        total = len(self._watched) + len(self._set_aside)
        lines = [
            f"# Device Sentinel v{self.version} classification",
            "",
            f"Written {self._format_report_time(dt_util.now())} "
            f"({trigger})",
            "",
            f"One row per device. Watching {len(self._watched)} of "
            f"{total}; {len(self._set_aside)} set aside (service "
            f"devices with no hardware to watch); {self.deviceless_count} "
            f"deviceless entities visible only at entity level. Every "
            f"device is watched and recorded; EXCLUDED only suppresses "
            f"judgment and reporting, and names why. COPIES above 1 is a "
            f"name shared by more than one registry device (a "
            f"network-tracker ghost or a multi-homed double).",
            "",
            "| DEVICE | INTEGRATION | WATCHED | EXCLUDED | SET ASIDE | "
            "COPIES |",
            "|---|---|---|---|---|---|",
        ]
        for name, integration, watched, excluded, set_aside, copies in rows:
            watched_mark = "\u2713" if watched else ""
            set_aside_mark = "\u2713" if set_aside else ""
            lines.append(
                f"| {self._report_cell(name)} | {integration} | "
                f"{watched_mark} | "
                f"{excluded} | {set_aside_mark} | {copies} |"
            )

        if self._excluded_entities:
            lines.append("")
            lines.append(
                f"## Excluded entities ({len(self._excluded_entities)})"
            )
            lines.append("")
            lines.append(
                "Individual entities excluded from judgment. An "
                "excluded entity still vouches for its device."
            )
            lines.append("")
            lines.append("| ENTITY | REASON |")
            lines.append("|---|---|")
            for entity_id, reason in sorted(
                self._excluded_entities.items()
            ):
                lines.append(f"| {entity_id} | {reason} |")

        path = os.path.join(report_directory, REPORT_CLASSIFICATION)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        LOGGER.info("Classification report written to %s", path)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        """Return the live data for the store's delayed save.

        A method rather than a lambda so the delayed save always
        serializes the state at write time, not at schedule time.
        Running means the pending delayed write is firing right now,
        so the pending flag clears here and the next dirty tick may
        schedule the next window.
        """
        self._delay_pending = False
        return self.data

    async def _save_now(self) -> None:
        """The single immediate-save path.

        Every direct save runs through here so the bookkeeping can
        never be missed at one of the scattered sites: both tier
        flags clear, and the pending flag clears because the store
        cancels its pending delayed write when a direct save lands.
        """
        await self._store.async_save(self.data)
        self._dirty = False
        self._critical = False
        self._delay_pending = False

    async def _on_render_tick(self, _now: Any) -> None:
        """Sweep storms, judge freezes, persist if dirty, refresh.

        The freeze sweep runs here rather than on a per-device timer:
        at 60-second granularity a window that closes is caught within
        a minute, which is immaterial against windows of minutes to
        hours, and one sweep is simpler than 125 scheduled callbacks
        to cancel and re-arm. Detection is still live in the sense
        that matters, a freeze shows on the next tick after its window
        closes, and clears the instant the device reports (that half
        runs in the report path, not here).
        """
        self._sweep_storms(dt_util.utcnow().timestamp())
        self._judge_all_devices()
        # The sync follows the sweep every tick, so a freeze the
        # sweep just fired, a battery level that drifted, or a rail
        # the midnight roll confirmed reaches the list within the
        # same minute it was detected. Idempotent and cheap: a clean
        # pass changes nothing and writes nothing.
        self._sync_problem_list()
        if self._critical:
            # Something a reboot must not lose changed this tick:
            # save now, exactly as every tick did before 0.6.5.
            await self._save_now()
        elif self._dirty and not self._delay_pending:
            # Routine clock churn only: coalesce. Scheduled once per
            # window, never rescheduled by later dirty ticks, because
            # async_delay_save restarts its timer on every call and
            # a fleet that is always dirty would push the deadline
            # forward forever (the 0.6.6 fix). The store flushes
            # pending delayed saves itself at shutdown's final-write
            # event.
            self._delay_pending = True
            self._store.async_delay_save(
                self._data_to_save, self.coalesce_seconds
            )
            self._dirty = False
        elif self._dirty:
            # A window is already pending; its write will carry this
            # tick's churn since the data serializes at fire time.
            self._dirty = False
        self._notify()

    async def _on_hass_stop(self, _event: Event) -> None:
        """Stamp open silences as intervention-ended, then flush.

        A restart is an intervention: it can revive a wedged radio,
        so any silence running when it happens is truncated rather
        than completed. Stamping here, before the flush, is what
        makes the distinction survive into the next boot.
        """
        self._stamp_intervention(
            EPISODE_ENDED_REBOOT, dt_util.utcnow().timestamp()
        )
        if self._dirty or self._critical:
            await self._save_now()

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
        excludes. This counts the set freeze detection judges; the
        per-section freeze exclude narrows it further.
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

        The Device: Frozen problem sensor. One row per down device,
        carrying its category (the
        worst of what its entities show) and the UTC time the verdict
        began, so a person sees what is down, how, and for how long.
        Excluded devices are suppressed from the report but keep their
        verdict, so undoing an exclude shows them again at once.
        """
        rows: list[dict[str, Any]] = []
        for device_id, record in self.data[DATA_DEVICES].items():
            if device_id not in self._watched:
                continue
            if device_id in self._excluded_devices:
                continue
            category = record.get(DEV_FROZEN_CATEGORY)
            if category is None:
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

    @property
    def frozen_devices_count(self) -> int:
        """Return how many devices are down (frozen, unavailable, or
        unknown) right now."""
        return len(self.frozen_devices_list)

    @staticmethod
    def _format_report_time(when: datetime) -> str:
        """Return a local time a person reads at a glance, like
        'July 21, 2026 at 7:19 AM'. Built without strftime's platform
        specific %-d and %-I so it is the same on every host: the
        month name and AM/PM come from strftime, the day and hour are
        integers so they carry no leading zero.
        """
        month = when.strftime("%B")
        hour_24 = when.hour
        hour_12 = hour_24 % 12 or 12
        meridiem = "AM" if hour_24 < 12 else "PM"
        return (
            f"{month} {when.day}, {when.year} at "
            f"{hour_12}:{when.minute:02d} {meridiem}"
        )

    def _todo_tag_of(self, device_id: str) -> str:
        """Return the todo-state tag for a device with a fault.

        The same three states the sync produces, worded for a
        diagnostics reader: open, acknowledged, or removed from the
        list by hand while the fault persists. A device has one todo
        item covering all its faults, so both lines of a two-fault
        device carry the same tag.
        """
        status = self._todo_status_of(device_id)
        if status == "needs_action":
            return "[\u25cb open]"
        if status == "completed":
            return "[\u2713 acknowledged]"
        return "[\u2717 removed from list]"

    def _todo_signal_since(self, device_id: str) -> float | None:
        """Return when a device's signal fault was added to the list.

        A rail carries no physical start time (it is derived from the
        daily-low series), so its age is measured from the todo item's
        signal-kind stamp, the moment the sync first listed it. This
        keeps the section consistent with the list it mirrors.
        """
        for record in self.todo_items:
            if record.get(TODO_DEVICE_ID) == device_id:
                return (record.get(TODO_KINDS) or {}).get("signal")
        return None

    def _reporting_lines(self) -> list[str]:
        """Return the telemetry report's Reporting Devices section.

        Every device with a fault, grouped by family (freeze, then
        battery, then signal) and alphabetical within each group, so
        the whole trouble picture reads in one place. This is
        diagnostics, not notification: an acknowledged item is shown
        here, tagged acknowledged, because the checkbox silences the
        phone, never the record of what is wrong. A device in two
        families appears in both, each line carrying that family's
        own age. The header count is distinct devices, so it can be
        smaller than the number of lines.

        Age source per family: freeze from its frozen-since, battery
        from its below-threshold-since, signal from when the sync
        listed it (a rail has no stored start of its own).
        """
        now = dt_util.utcnow().timestamp()
        as_of = self._format_report_time(dt_util.now())

        def _elapsed(seconds: float | None) -> str:
            if seconds is None:
                return "?"
            # Clamped: a since ahead of the clock (an NTP correction
            # after an offline boot) must not print a negative age.
            seconds = max(0.0, seconds)
            if seconds >= 3600:
                return f"{seconds / 3600:.1f}h"
            return f"{seconds / 60:.0f}m"

        def _age_from_epoch(since: float | None) -> str:
            return _elapsed(now - since if since is not None else None)

        def _age_from_iso(since: str | None) -> str:
            if not since:
                return "?"
            parsed = dt_util.parse_datetime(since)
            return _elapsed(now - parsed.timestamp() if parsed else None)

        freeze_lines: list[str] = []
        for row in sorted(
            self.frozen_devices_list, key=lambda r: r["name"].lower()
        ):
            tag = self._todo_tag_of(row["device_id"])
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            freeze_lines.append(
                f"- **{shown_name}** ({row['category']}) for "
                f"{_age_from_epoch(row.get('since'))} {tag}"
            )

        battery_lines: list[str] = []
        for row in sorted(
            self.battery_low_list, key=lambda r: r["name"].lower()
        ):
            level = row.get("level")
            if isinstance(level, (int, float)):
                shown = (
                    f"{int(level)}%"
                    if float(level).is_integer()
                    else f"{level}%"
                )
            else:
                shown = "low"
            tag = self._todo_tag_of(row["device_id"])
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            battery_lines.append(
                f"- **{shown_name}** ({shown}) for "
                f"{_age_from_iso(row.get('since'))} {tag}"
            )

        signal_lines: list[str] = []
        for row in sorted(
            self.signal_problem_list,
            key=lambda r: (r["name"] or "").lower(),
        ):
            tag = self._todo_tag_of(row["device_id"])
            age = _age_from_epoch(
                self._todo_signal_since(row["device_id"])
            )
            shown_name = self._report_cell(
                row["name"] or row["device_id"]
            )
            signal_lines.append(
                f"- **{shown_name}** ({row['kind']}) for {age} {tag}"
            )

        count = len(self._problem_device_ids())
        if count == 0:
            return [
                "## Reporting Devices (0)",
                "",
                f"As of {as_of}, nothing is frozen, unavailable, "
                f"unknown, low on battery, or railed.",
                "",
            ]
        out = [
            f"## Reporting Devices ({count})",
            "",
            f"As of {as_of}. Every device with a fault, grouped by "
            f"family. A duration is how long the fault had lasted "
            f"when this was written. The tag is the problem list "
            f"state: open, acknowledged (silenced from notifications, "
            f"still shown here), or removed from the list by hand "
            f"while the fault persists.",
            "",
        ]
        if freeze_lines:
            out += ["### Freeze", "", *freeze_lines, ""]
        if battery_lines:
            out += ["### Battery", "", *battery_lines, ""]
        if signal_lines:
            out += ["### Signal", "", *signal_lines, ""]
        return out

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
                        "device_id": device_id,
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
        """Return the stored problem items in display order."""
        return self.data.get(DATA_TODO_ITEMS, [])

    def _sort_todo_items(self) -> None:
        """Enforce the display order: open alphabetical, then
        acknowledged in the order they were checked.

        Order is owned by the integration and re-imposed on every
        write, because a readable list beats one ordered by age; user
        reordering does not stick, by design. The open block sorts
        alphabetically by the device's common name. The acknowledged
        block follows, oldest acknowledgment first, so the checked
        section reads as a stable history rather than reshuffling as
        problems come and go around it.
        """
        self.data[DATA_TODO_ITEMS].sort(
            key=lambda record: (
                record.get(TODO_STATUS) == "completed",
                (
                    record.get(TODO_ACKED_AT) or ""
                    if record.get(TODO_STATUS) == "completed"
                    else (
                        record.get(TODO_SORT_NAME)
                        or record.get(TODO_SUMMARY)
                        or ""
                    ).lower()
                ),
            )
        )

    async def async_todo_update(
        self,
        uid: str | None,
        summary: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Apply a user edit to one item.

        A status of completed is the acknowledgment: the item stays on
        the list, marked done, and Step 8 will send nothing about a
        device while its item sits acknowledged. The check time is
        stamped because it orders the acknowledged block. Only a full
        recovery deletes the item; unchecking simply reopens it. Text
        edits do not stick: the sync owns the wording and rewrites it
        from the detections.
        """
        for record in self.data[DATA_TODO_ITEMS]:
            if record[TODO_UID] != uid:
                continue
            if summary is not None:
                record[TODO_SUMMARY] = summary
            if description is not None:
                record[TODO_DESCRIPTION] = description
            if status is not None and status != record.get(TODO_STATUS):
                record[TODO_STATUS] = status
                record[TODO_ACKED_AT] = (
                    dt_util.utcnow().isoformat()
                    if status == "completed"
                    else None
                )
                # The checkbox lands on the timeline too: a brief
                # that says a device recovered should also be able
                # to say when someone decided to live with it.
                if status == "completed":
                    for kind in record.get(TODO_KINDS, {}):
                        self._record_incident(
                            device_id=record[TODO_DEVICE_ID],
                            name=record.get(TODO_SORT_NAME)
                            or record[TODO_DEVICE_ID],
                            kind=kind,
                            event=INCIDENT_ACKNOWLEDGED,
                        )
            break
        self._sort_todo_items()
        self._flush_outbox_lines()
        await self._save_now()
        self._notify()

    async def async_todo_delete(self, uids: list[str]) -> None:
        """Delete items the user removed by hand.

        Deleting an item whose device is still detected is the hard
        un-acknowledge: the next sync re-adds it fresh, and that
        re-add lands in the journal like any other, so Step 8 will
        announce it again.
        """
        self.data[DATA_TODO_ITEMS] = [
            record
            for record in self.data[DATA_TODO_ITEMS]
            if record[TODO_UID] not in uids
        ]
        await self._save_now()
        self._notify()

    # ------------------------------------------- the problem-list sync

    def _current_problems(self) -> dict[str, dict[str, Any]]:
        """Return every detected problem, one entry per device.

        Reads the same three properties the Problems sensors publish
        (frozen_devices_list, battery_low_list, signal_problem_list),
        so the todo can never disagree with the sensors: one source,
        two readers. The freeze category string is the kind itself; a
        device carries at most one freeze kind but may stack battery
        and signal on top. since is normalized to epoch seconds where
        the detection has one; a rail has none, so the sync stamps the
        moment the kind first appears on the item instead.
        """
        problems: dict[str, dict[str, Any]] = {}

        def _entry(device_id: str, name: str | None) -> dict[str, Any]:
            return problems.setdefault(
                device_id,
                {"name": name or device_id, "kinds": {}, "level": None},
            )

        for row in self.frozen_devices_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][row["category"]] = row.get("since")

        for row in self.battery_low_list:
            entry = _entry(row["device_id"], row.get("name"))
            since = row.get("since")
            since_dt = dt_util.parse_datetime(since) if since else None
            entry["kinds"][TODO_KIND_BATTERY] = (
                since_dt.timestamp() if since_dt else None
            )
            entry["level"] = row.get("level")

        for row in self.signal_problem_list:
            entry = _entry(row["device_id"], row.get("name"))
            entry["kinds"][TODO_KIND_SIGNAL] = None

        return problems

    @staticmethod
    def _kind_word(kind: str, level: Any) -> str:
        """Return one kind as the person reads it in the item text."""
        if kind == TODO_KIND_BATTERY:
            if level is None:
                return "battery low"
            shown = int(level) if float(level).is_integer() else level
            return f"battery {shown}%"
        if kind == TODO_KIND_SIGNAL:
            return "signal (rail)"
        return kind.replace("_", " ")

    def _problem_item_text(
        self, name: str, kinds: dict[str, float | None], level: Any
    ) -> tuple[str, str]:
        """Return the summary and description for one item.

        The summary leads with the human readable device name, the
        one thing ruled front and center, then the kinds in a fixed
        order: the freeze verdict first because it says whether the
        device is alive, then battery, then signal. The description
        expands each kind with its readable local start time, so the
        list line stays short and the tap-open carries the story.
        """
        order = [
            kind
            for kind in kinds
            if kind not in (TODO_KIND_BATTERY, TODO_KIND_SIGNAL)
        ]
        if TODO_KIND_BATTERY in kinds:
            order.append(TODO_KIND_BATTERY)
        if TODO_KIND_SIGNAL in kinds:
            order.append(TODO_KIND_SIGNAL)

        summary = (
            f"{name}: "
            + ", ".join(self._kind_word(kind, level) for kind in order)
        )
        lines = []
        for kind in order:
            word = self._kind_word(kind, level)
            since = kinds.get(kind)
            if since is not None:
                when = self._format_report_time(
                    dt_util.as_local(dt_util.utc_from_timestamp(since))
                )
                lines.append(f"{word.capitalize()} since {when}.")
            else:
                lines.append(f"{word.capitalize()}.")
        return summary, " ".join(lines)

    # ------------------------------------------------ message composer

    # How bad a problem is, worst first. A device with several
    # problems is described by its worst one, because a phone line
    # has room for one fact and the reader needs the one that
    # matters. Silence outranks battery and signal: a device that
    # cannot be heard from cannot be trusted to report either.
    _KIND_SEVERITY = (
        "unavailable",
        "frozen",
        "unknown",
        "not_reported",
        "battery",
        "signal",
    )

    _EVENT_WORDING = {
        "frozen": "stopped reporting",
        "unavailable": "went unavailable",
        "unknown": "went unknown",
        "signal": "signal railed",
    }

    _STATE_WORDING = {
        "frozen": "stopped reporting",
        "unavailable": "has been unavailable",
        "unknown": "has been unknown",
        "signal": "signal has been railed",
    }

    @staticmethod
    def _clock(epoch: float) -> str:
        """Return a bare local time, as a person would say it."""
        return dt_util.as_local(
            dt_util.utc_from_timestamp(epoch)
        ).strftime("%-I:%M %p")

    def _battery_phrase(self, device_id: str, state: bool) -> str:
        """Return the battery clause with its level where known."""
        record = self.data[DATA_DEVICES].get(device_id) or {}
        level = record.get(DEV_BATTERY_VALUE)
        if isinstance(level, (int, float)):
            shown = f"{level:g}%"
            return (
                f"battery is at {shown}"
                if state
                else f"battery fell to {shown}"
            )
        return "battery is low" if state else "battery fell low"

    def _compose_event(self, row: dict[str, Any]) -> str:
        """Return one incident as a sentence of history.

        Used by the log today, and by the brief and a future spoken
        answer later: one composer, so the same event can never be
        described three different ways by three different renderers.
        """
        name = row[INC_NAME]
        kind = row[INC_KIND]
        when = self._clock(row[INC_WHEN])
        event = row[INC_EVENT]
        if event == INCIDENT_ACKNOWLEDGED:
            return f"{name} acknowledged at {when}."
        if event == INCIDENT_RESOLVED:
            span = self._human_span(row.get(INC_DURATION))
            cause = row.get(INC_CAUSE)
            tail = ""
            if cause == "on its own":
                tail = ", on its own"
            elif cause:
                tail = f", revived by a {cause}"
            if row.get(INC_DURATION) is None:
                return f"{name} recovered at {when}{tail}."
            return f"{name} recovered at {when} after {span}{tail}."
        if kind == "not_reported":
            return f"{name} has never reported since it was discovered."
        if kind == "battery":
            phrase = self._battery_phrase(row[INC_DEVICE_ID], False)
            return f"{name} {phrase} at {when}."
        wording = self._EVENT_WORDING.get(kind, kind)
        return f"{name} {wording} at {when}."

    def _compose_device_line(self, device_id: str) -> str | None:
        """Return what is wrong with one device, right now.

        The shape a phone holds: one line per device, replaced in
        place as things change (#108), so it describes a state rather
        than an event and carries no timestamp. Several problems at
        once are named by the worst with the rest counted, because
        the line has room for one fact.
        """
        record = next(
            (
                item
                for item in self.todo_items
                if item.get(TODO_DEVICE_ID) == device_id
            ),
            None,
        )
        if record is None:
            return None
        kinds = record.get(TODO_KINDS) or {}
        if not kinds:
            return None
        ordered = sorted(
            kinds,
            key=lambda kind: (
                self._KIND_SEVERITY.index(kind)
                if kind in self._KIND_SEVERITY
                else len(self._KIND_SEVERITY)
            ),
        )
        worst = ordered[0]
        name = record.get(TODO_SORT_NAME) or device_id
        since = kinds.get(worst)
        ago = (
            self._human_span(dt_util.utcnow().timestamp() - since)
            if since
            else None
        )
        if worst == "not_reported":
            clause = (
                f"has never reported in {ago}"
                if ago
                else "has never reported"
            )
        elif worst == "battery":
            clause = self._battery_phrase(device_id, True)
        else:
            wording = self._STATE_WORDING.get(worst, worst)
            clause = f"{wording} {ago} ago" if ago else wording
        extra = len(ordered) - 1
        tail = (
            f", and {extra} more problem{'s' if extra != 1 else ''}"
            if extra
            else ""
        )
        return f"{name} {clause}{tail}."

    def _flush_outbox_lines(self) -> None:
        """Compose the device line for every device touched this pass.

        Deferred until the problem list has settled, because the line
        is a statement about the device's current state rather than
        about any one event. A device whose problems all cleared
        produces no line: the phone clears silently (#109), and there
        is nothing to say.
        """
        for device_id in sorted(self._outbox_pending):
            line = self._compose_device_line(device_id)
            if line is not None:
                self._note_outbox(
                    device_id, line, OUTBOX_SHAPE_DEVICE
                )
        self._outbox_pending.clear()

    def _note_outbox(
        self, device_id: str, text: str, shape: str
    ) -> None:
        """Record a composed message without sending it.

        The dry run (#120): nothing sends yet, so every sentence the
        engine would say is logged and kept where it can be read and
        argued with for days before the first one reaches a phone.
        """
        LOGGER.info("Would send (%s): %s", shape, text)
        outbox = self.data.setdefault(DATA_OUTBOX, [])
        outbox.append(
            {
                OUT_WHEN: dt_util.utcnow().timestamp(),
                OUT_DEVICE_ID: device_id,
                OUT_TEXT: text,
                OUT_SHAPE: shape,
            }
        )
        del outbox[:-OUTBOX_KEEP]
        self._dirty = True

    def _record_incident(
        self,
        device_id: str,
        name: str,
        kind: str,
        event: str,
        cause: str | None = None,
        duration: float | None = None,
    ) -> None:
        """Append one event to the incident log.

        The whole life of a problem on one timeline: opened when a
        detection first names it, resolved when it clears (with the
        cause and the duration where we know them), acknowledged when
        a person checks the box. Renderers read this and nothing
        else, so what the phone says, what the brief says, and what
        a future voice answer says can never disagree.
        """
        entry = {
            INC_DEVICE_ID: device_id,
            INC_NAME: name,
            INC_KIND: kind,
            INC_EVENT: event,
            INC_WHEN: dt_util.utcnow().timestamp(),
            INC_CAUSE: cause,
            INC_DURATION: duration,
        }
        incidents = self.data.setdefault(DATA_INCIDENTS, [])
        incidents.append(entry)
        # The event sentence can be composed here: it describes what
        # just happened. The device line cannot, because it describes
        # the device's whole state and the problem list has not
        # settled yet, so it is deferred to the flush below (#120).
        self._note_outbox(
            device_id, self._compose_event(entry), OUTBOX_SHAPE_EVENT
        )
        self._outbox_pending.add(device_id)
        cutoff = (
            dt_util.utcnow().timestamp() - INCIDENT_KEEP_DAYS * 86400.0
        )
        self.data[DATA_INCIDENTS] = [
            row for row in incidents if row[INC_WHEN] >= cutoff
        ]
        self._dirty = True

    def _incident_opened_at(
        self, device_id: str, kind: str
    ) -> float | None:
        """Return when this device's current problem of a kind began.

        The most recent opening with no resolution after it. Used to
        compute a resolution's duration, so the brief can say how
        long a problem lasted without the renderer doing arithmetic
        on a raw log.
        """
        opened: float | None = None
        for row in self.data.get(DATA_INCIDENTS) or []:
            if row[INC_DEVICE_ID] != device_id or row[INC_KIND] != kind:
                continue
            if row[INC_EVENT] == INCIDENT_OPENED:
                opened = row[INC_WHEN]
            elif row[INC_EVENT] == INCIDENT_RESOLVED:
                opened = None
        return opened

    def _recovery_cause(self, device_id: str) -> str | None:
        """Return how a device's silence ended, if the record says.

        Borrowed from the episode record rather than guessed: an
        episode closed by an intervention names the lever, and one
        the device closed itself says so. Only silences carry a
        cause; a battery or a rail recovering has no lever to name.
        """
        for episode in reversed(self.data.get(DATA_EPISODES) or []):
            if episode[EP_DEVICE_ID] != device_id:
                continue
            ended = episode[EP_ENDED]
            if ended is None:
                return None
            if ended == EPISODE_ENDED_RESUMED:
                return "on its own"
            return ended.replace("intervention (", "").rstrip(")")
        return None

    def _resolve_incident(
        self, device_id: str, name: str, kind: str, now: float
    ) -> None:
        """Close one problem on the incident timeline.

        Carries the duration, computed from the matching opening, and
        the cause where the episode record knows it. A resolution
        with no opening behind it (a problem that predates the log)
        is still recorded, simply without a duration.
        """
        opened = self._incident_opened_at(device_id, kind)
        duration = (now - opened) if opened is not None else None
        cause = (
            self._recovery_cause(device_id)
            if kind in FREEZE_KINDS_FOR_CAUSE
            else None
        )
        self._record_incident(
            device_id,
            name,
            kind,
            INCIDENT_RESOLVED,
            cause=cause,
            duration=duration,
        )

    def _journal_addition(
        self, device_id: str, name: str, kind: str
    ) -> None:
        """Record one addition and announce it on the dispatcher.

        The journal plus the signal is the whole Step 8 contract: an
        addition to the list is the notification trigger, so the
        engine to come subscribes here and never re-derives newness
        from raw detections.
        """
        when = dt_util.utcnow().isoformat()
        journal = self.data.setdefault(DATA_TODO_JOURNAL, [])
        journal.append(
            {
                "device_id": device_id,
                "name": name,
                "kind": kind,
                "when": when,
            }
        )
        del journal[:-TODO_JOURNAL_KEEP]
        async_dispatcher_send(
            self.hass,
            SIGNAL_PROBLEM_ADDITION,
            {
                "device_id": device_id,
                "name": name,
                "kind": kind,
                "when": when,
            },
        )

    @callback
    def _sync_problem_list(self) -> None:
        """Reconcile the todo against the detections, immediately.

        A full diff rather than incremental patches: idempotent, so a
        missed call self-heals on the next, and cheap at fleet scale.
        One item per device, keyed by device_id, whatever mix of
        problems it carries. An item appears the moment its device is
        first detected, its text follows the kinds as they come and
        go, and it is deleted the moment the last kind clears, open
        or acknowledged alike: recovery is the automatic re-arm, so
        the next failure is a new incident and a fresh item. The
        acknowledged status and its check time are never touched by
        the sync; silencing is exactly what the checkbox is for.

        Persistence rides the dirty flag: the render tick, the report
        paths, and shutdown all flush it, so a sync is safe to call
        from any detection path without its own await.
        """
        problems = self._current_problems()
        items = self.data.get(DATA_TODO_ITEMS, [])
        now = dt_util.utcnow().timestamp()
        changed = False
        kept: list[dict[str, Any]] = []

        for record in items:
            device_id = record.get(TODO_DEVICE_ID)
            problem = problems.pop(device_id, None)
            if problem is None:
                # Every kind cleared: the recovery deletes the item,
                # acknowledged or not. Each kind resolves on the
                # incident timeline first, so the brief can tell the
                # end of the story as well as its beginning.
                for kind in record.get(TODO_KINDS, {}):
                    self._resolve_incident(
                        device_id,
                        record.get(TODO_SORT_NAME) or device_id,
                        kind,
                        now,
                    )
                changed = True
                continue
            stored_kinds: dict[str, float | None] = record.get(
                TODO_KINDS, {}
            )
            new_kinds: dict[str, float | None] = {}
            for kind, since in problem["kinds"].items():
                if kind in stored_kinds:
                    # Keep the item's own stamp when the detection
                    # carries none, so a rail's first-seen time is
                    # not rewritten on every pass.
                    new_kinds[kind] = (
                        since
                        if since is not None
                        else stored_kinds[kind]
                    )
                else:
                    new_kinds[kind] = since if since is not None else now
                    self._journal_addition(
                        device_id, problem["name"], kind
                    )
                    self._record_incident(
                        device_id, problem["name"], kind, INCIDENT_OPENED
                    )
            for kind in stored_kinds:
                if kind not in new_kinds:
                    self._resolve_incident(
                        device_id, problem["name"], kind, now
                    )
            summary, description = self._problem_item_text(
                problem["name"], new_kinds, problem["level"]
            )
            if (
                new_kinds != stored_kinds
                or record.get(TODO_SUMMARY) != summary
                or record.get(TODO_DESCRIPTION) != description
                or record.get(TODO_SORT_NAME) != problem["name"]
            ):
                record[TODO_KINDS] = new_kinds
                record[TODO_SUMMARY] = summary
                record[TODO_DESCRIPTION] = description
                record[TODO_SORT_NAME] = problem["name"]
                changed = True
            kept.append(record)

        for device_id, problem in problems.items():
            kinds = {
                kind: (since if since is not None else now)
                for kind, since in problem["kinds"].items()
            }
            summary, description = self._problem_item_text(
                problem["name"], kinds, problem["level"]
            )
            kept.append(
                {
                    TODO_UID: uuid.uuid4().hex,
                    TODO_DEVICE_ID: device_id,
                    TODO_SUMMARY: summary,
                    TODO_DESCRIPTION: description,
                    TODO_STATUS: "needs_action",
                    TODO_ACKED_AT: None,
                    TODO_SORT_NAME: problem["name"],
                    TODO_KINDS: kinds,
                }
            )
            for kind in kinds:
                self._journal_addition(device_id, problem["name"], kind)
                self._record_incident(
                    device_id, problem["name"], kind, INCIDENT_OPENED
                )
            changed = True

        if changed:
            self.data[DATA_TODO_ITEMS] = kept
            self._sort_todo_items()
            self._dirty = True
            self._critical = True
            self._notify()
        # The list is settled, so a device line now describes reality.
        self._flush_outbox_lines()

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
        if is_low != was_low:
            # A flag flip reaches the list at once, both ways: the
            # item appears the moment the cell crosses the line and
            # deletes the moment it clears the margin. The flip and
            # its since stamp must survive a reboot, so it is
            # critical for the save tier too.
            self._critical = True
            self._sync_problem_list()
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
        # Exclusions changed here remove verdicts at the source, so
        # the sync sees the shrunken lists and deletes the items of
        # anything the person just excluded, immediately.
        self._sync_problem_list()
        if self._dirty or self._critical:
            await self._save_now()
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
                    "device_id": device_id,
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

    def _problem_device_ids(self) -> set[str]:
        """Return the device_ids that currently have any fault.

        The union of the three problem lists, the same sets the todo
        sync reads. A device here is one the todo is expected to hold
        an item for; the report's status icon is judged against this
        set, not against the todo alone, so a healthy Reported device
        wears no icon.
        """
        ids: set[str] = set()
        for row in self.frozen_devices_list:
            ids.add(row["device_id"])
        for row in self.battery_low_list:
            ids.add(row["device_id"])
        for row in self.signal_problem_list:
            ids.add(row["device_id"])
        return ids

    def _todo_status_of(self, device_id: str) -> str | None:
        """Return a device's todo item status, or None when absent.

        "needs_action" or "completed" for an item the sync holds,
        None when no item exists for the device.
        """
        for record in self.todo_items:
            if record.get(TODO_DEVICE_ID) == device_id:
                return record.get(TODO_STATUS)
        return None

    def _device_status(self, device_id: str) -> str:
        """Return a device's exclusion status for the report column.

        Two states, one grammar: "Reported" when nothing excludes it,
        or "Excluded (...)" naming why. GLB is the global exclude,
        shown alone because it covers everything and a globally
        excluded device is never offered to the section lists. BAT,
        SIG, and FRZ are the section excludes, listed in column order
        when more than one applies.

        The 0.6.1 todo icon lived here for one release and moved to
        the Reporting Devices section at 0.6.2: the same state shown
        twice was redundant and confusing, and the section is where a
        fault's whole story reads, list state included.
        """
        if device_id in self._excluded_devices:
            return "Excluded (GLB)"
        tags = []
        if self._battery_excluded(device_id):
            tags.append("BAT")
        if self._signal_excluded(device_id):
            tags.append("SIG")
        if self._freeze_excluded(device_id):
            tags.append("FRZ")
        if tags:
            return f"Excluded ({', '.join(tags)})"
        return "Reported"

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

    def _freeze_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from freeze judgment
        only. The same broad-to-narrow ladder as battery and signal,
        and the same principle: the device keeps its clock and its
        learned rhythm, so re-including it is instant and arrives with
        history; it simply is never given a freeze, unavailable,
        unknown, or not-reported verdict. This is the release valve
        for a device that is intermittent by nature, silenced in the
        freeze report without being hidden from the rest.
        """
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_FREEZE_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_FREEZE_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_FREEZE_EXCLUDED_DEVICES, [])

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

    async def async_regenerate_reports(self) -> dict[str, int]:
        """Judge every device now, then rewrite both report files.

        For a person hunting a problem: fix a frozen device, press
        this, and the report reflects the fix at once rather than at
        the next tick or the nightly write. Judgment runs first so the
        down-devices section and the verdicts are current, then both
        files are written with a fresh timestamp that confirms the run.
        """
        self._judge_all_devices()
        await self.hass.async_add_executor_job(
            self._write_reports, "manual"
        )
        return {"regenerated": 2}

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
