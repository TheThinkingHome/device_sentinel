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
    CONF_EXCLUDED_AREAS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_ENTITIES,
    CONF_EXCLUDED_INTEGRATIONS,
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
    SIGNAL_LQI_DANGER_FACTOR,
    SIGNAL_RSSI_DANGER_OFFSET,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
    DATA_DEVICES,
    DATA_FIRST_INSTALLED,
    DATA_SETUP_COUNT,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    SIGNAL_NAME_TERMS,
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
    TODO_UID,
)

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
        DEV_BATTERY_LOW: False,
        DEV_BATTERY_SINCE: None,
        DEV_BATTERY_VALUE: None,
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
                record.setdefault(DEV_BATTERY_LOW, False)
                record.setdefault(DEV_BATTERY_SINCE, None)
                record.setdefault(DEV_BATTERY_VALUE, None)
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
                record.setdefault(DEV_BATTERY_LOW, False)
                record.setdefault(DEV_BATTERY_SINCE, None)
                record.setdefault(DEV_BATTERY_VALUE, None)
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
        excluded_entity_ids = set(
            options.get(CONF_EXCLUDED_ENTITIES, [])
        )
        excluded_labels = set(options.get(CONF_EXCLUDED_LABELS, []))
        excluded_areas = set(options.get(CONF_EXCLUDED_AREAS, []))
        excluded_integrations = set(
            options.get(CONF_EXCLUDED_INTEGRATIONS, [])
        )

        watched: dict[str, str] = {}
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
            # Device-level exclusion reasons, first match names it.
            # The integration test uses the primary domain, so an
            # integration exclude catches only devices it owns, never
            # multi-homed hardware it merely sees.
            if device.id in excluded_device_ids:
                excluded_devices[device.id] = "device"
            elif device.area_id and device.area_id in excluded_areas:
                excluded_devices[device.id] = "area"
            elif excluded_labels & set(device.labels or ()):
                excluded_devices[device.id] = "label"
            elif domain in excluded_integrations:
                excluded_devices[device.id] = "integration"

        entity_map: dict[str, tuple[str, str | None]] = {}
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
            if ent.entity_id in excluded_entity_ids:
                excluded_entities[ent.entity_id] = "entity"
            elif excluded_labels & set(ent.labels or ()):
                excluded_entities[ent.entity_id] = "label"
            elif ent.area_id and ent.area_id in excluded_areas:
                excluded_entities[ent.entity_id] = "area"
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
        self._set_aside = set_aside
        self._excluded_devices = excluded_devices
        self._excluded_entities = excluded_entities
        self._entity_map = entity_map
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
                record[DEV_SIGNAL_VALUE] = value
                today_min = record.get(DEV_SIGNAL_TODAY_MIN)
                if today_min is None or value < today_min:
                    record[DEV_SIGNAL_TODAY_MIN] = value

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

    @staticmethod
    def _trimmed_minimum(
        daily_minimum_signals: list[float],
    ) -> float | None:
        """Return the signal floor: the trimmed minimum of the daily
        minima, the exact mirror of the gap rule. The bottom
        TRIM_TOP_K values are set aside as anomalies once
        TRIM_MIN_SAMPLES days exist; below that, the plain minimum.
        One anomalous bad-signal day moves nothing; a recurring drop
        counts as real degradation."""
        if not daily_minimum_signals:
            return None
        if len(daily_minimum_signals) < TRIM_MIN_SAMPLES:
            return min(daily_minimum_signals)
        survivors = sorted(daily_minimum_signals)[TRIM_TOP_K:]
        return min(survivors)

    @staticmethod
    def _signal_family_and_danger(floor: float) -> tuple[str, float]:
        """Classify the unit family by sign and return the candidate
        danger line (preview only, ruled from real data before any
        detection acts on it): LQI-like positives flag below
        floor * factor; dBm negatives flag below floor - offset."""
        if floor >= 0:
            return "LQI", floor * SIGNAL_LQI_DANGER_FACTOR
        return "RSSI", floor - SIGNAL_RSSI_DANGER_OFFSET

    def _fmt_gap(self, seconds: Any) -> str:
        """Format a gap for the report."""
        if seconds is None:
            return "-"
        if seconds >= 3600:
            return f"{seconds / 3600:.2f}h"
        return f"{seconds:.0f}s"

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

    @staticmethod
    def _trimmed_minimum(
        daily_minimum_signals: list[float],
    ) -> float | None:
        """Return the signal floor: the trimmed minimum of the daily
        minima, the exact mirror of the gap rule. The bottom
        TRIM_TOP_K values are set aside as anomalies once
        TRIM_MIN_SAMPLES days exist; below that, the plain minimum.
        One anomalous bad-signal day moves nothing; a recurring drop
        counts as real degradation."""
        if not daily_minimum_signals:
            return None
        if len(daily_minimum_signals) < TRIM_MIN_SAMPLES:
            return min(daily_minimum_signals)
        survivors = sorted(daily_minimum_signals)[TRIM_TOP_K:]
        return min(survivors)

    @staticmethod
    def _signal_family_and_danger(floor: float) -> tuple[str, float]:
        """Classify the unit family by sign and return the candidate
        danger line (preview only, ruled from real data before any
        detection acts on it): LQI-like positives flag below
        floor * factor; dBm negatives flag below floor - offset."""
        if floor >= 0:
            return "LQI", floor * SIGNAL_LQI_DANGER_FACTOR
        return "RSSI", floor - SIGNAL_RSSI_DANGER_OFFSET

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
            f"Signal preview: FLOOR is the trimmed minimum of the "
            f"daily signal minima (same trim rule); DANGER is the "
            f"candidate line, display-only until ruled: LQI flags "
            f"below floor x {SIGNAL_LQI_DANGER_FACTOR:g}, RSSI below "
            f"floor - {SIGNAL_RSSI_DANGER_OFFSET:g} dB; blank until "
            f"a device has {SIGNAL_ARMING_DAYS} signal days.",
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
            "| DEVICE | DAYS | WINDOW BASIS | GAPS (newest first) | "
            "CLOCK | EVENTS | SIGNAL | SIG MIN | FLOOR | FAMILY | "
            "DANGER |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
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
            signal_minimum_candidates = list(
                record.get(DEV_SIGNAL_DAILY_MIN) or []
            )
            if record.get(DEV_SIGNAL_TODAY_MIN) is not None:
                signal_minimum_candidates.append(
                    record[DEV_SIGNAL_TODAY_MIN]
                )
            signal_days = record.get(DEV_SIGNAL_DAILY_MIN) or []
            if len(signal_days) >= SIGNAL_ARMING_DAYS:
                signal_floor = self._trimmed_minimum(signal_days)
                family, danger_line = self._signal_family_and_danger(
                    signal_floor
                )
            else:
                signal_floor, family, danger_line = None, None, None
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
                    record.get(DEV_SIGNAL_VALUE),
                    min(signal_minimum_candidates)
                    if signal_minimum_candidates
                    else None,
                    signal_floor,
                    family,
                    danger_line,
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
            signal_value,
            signal_minimum,
            signal_floor,
            family,
            danger_line,
        ) in rows:
            signal_text = "-" if signal_value is None else f"{signal_value:g}"
            signal_minimum_text = (
                "-" if signal_minimum is None else f"{signal_minimum:g}"
            )
            floor_text = "-" if signal_floor is None else f"{signal_floor:g}"
            family_text = family or "-"
            danger_text = "-" if danger_line is None else f"{danger_line:g}"
            lines.append(
                f"| {device_name} | {day_count} | "
                f"{self._fmt_gap(operative)} | {maxima_cell} | "
                f"{clock_source} | {event_count} | {signal_text} | "
                f"{signal_minimum_text} | {floor_text} | {family_text} | "
                f"{danger_text} |"
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
            if (
                device_id in self._excluded_devices
                or entity_id in self._excluded_entities
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
            and (self.data[DATA_DEVICES].get(device_id) or {}).get(
                DEV_BATTERY_LOW
            )
        )

    async def async_enable_signal_entities(self) -> dict[str, int]:
        """Enable integration-disabled last_seen and signal entities.

        User-disabled entities are respected and only counted. Home
        Assistant reloads the owning config entries automatically a
        short delay after enabling.
        """
        ent_reg = er.async_get(self.hass)
        enabled_last_seen = 0
        enabled_signal = 0
        skipped_user = 0
        for ent in list(ent_reg.entities.values()):
            if ent.device_id not in self._watched:
                continue
            is_ls = self._is_last_seen(ent)
            is_sig = self._is_signal(ent)
            if not (is_ls or is_sig):
                continue
            if ent.disabled_by is None:
                continue
            if ent.disabled_by is er.RegistryEntryDisabler.USER:
                skipped_user += 1
                continue
            ent_reg.async_update_entity(ent.entity_id, disabled_by=None)
            if is_ls:
                enabled_last_seen += 1
            else:
                enabled_signal += 1
        LOGGER.info(
            "Enable assist: enabled %d last_seen and %d signal "
            "entities; %d left alone because a user disabled them. "
            "Home Assistant reloads the owning integrations shortly",
            enabled_last_seen,
            enabled_signal,
            skipped_user,
        )
        return {
            "last_seen": enabled_last_seen,
            "signal": enabled_signal,
            "skipped_user": skipped_user,
        }

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
