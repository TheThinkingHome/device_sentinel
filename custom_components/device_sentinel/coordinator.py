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
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_FIRST_INSTALLED,
    DATA_SETUP_COUNT,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
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
        self._set_aside: dict[str, tuple[str, str]] = {}  # id -> (name, domain)
        self._last_seen_entity: dict[str, str] = {}  # device_id -> entity_id
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

        watched: dict[str, str] = {}
        set_aside: dict[str, tuple[str, str]] = {}
        for device in dev_reg.devices.values():
            domain = self._primary_domain(device)
            name = device.name_by_user or device.name or device.id
            if device.entry_type is dr.DeviceEntryType.SERVICE:
                set_aside[device.id] = (name, domain)
            else:
                watched[device.id] = domain

        entity_map: dict[str, tuple[str, str | None]] = {}
        last_seen_entity: dict[str, str] = {}
        deviceless = 0
        for ent in ent_reg.entities.values():
            if ent.device_id is None:
                deviceless += 1
                continue
            if ent.device_id not in watched:
                continue
            entity_map[ent.entity_id] = (ent.device_id, ent.config_entry_id)
            if ent.entity_id.endswith("_last_seen"):
                last_seen_entity[ent.device_id] = ent.entity_id

        self._watched = watched
        self._set_aside = set_aside
        self._entity_map = entity_map
        self._last_seen_entity = last_seen_entity
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
            record = self.data[DATA_DEVICES].get(device_id)
            if record is not None and not record[DEV_TAINTED]:
                record[DEV_TAINTED] = True
                self._dirty = True
                if dt_util.utcnow().timestamp() < self._grace_until:
                    self._grace_taints.add(device_id)
                else:
                    LOGGER.info(
                        "Device tainted by %s going %s; its next "
                        "completed gap will not feed learning",
                        entity_id,
                        new_state.state,
                    )
            return
        self._record_activity(device_id, entry_id)

    @callback
    def _on_state_reported(self, event: Event) -> None:
        """Handle a same-value report for a watched device's entity."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in BAD_STATES:
            return
        entity_id = event.data["entity_id"]
        device_id, entry_id = self._entity_map[entity_id]
        self._record_activity(device_id, entry_id)

    @callback
    def _record_activity(self, device_id: str, entry_id: str | None) -> None:
        """Stamp the device clock, completing a gap for learning if clean."""
        now = dt_util.utcnow().timestamp()
        record = self.data[DATA_DEVICES].get(device_id)
        if record is None:
            record = _new_device_record(dt_util.utcnow().isoformat(), None)
            self.data[DATA_DEVICES][device_id] = record

        storm = self._storm_feed(entry_id, device_id, now)
        grace = now < self._grace_until

        # A taint is consumed by any real-value stamp: the outage ended
        # here, and the spanning gap is excluded by whichever rule
        # applies. Exclusions are independent, not exclusive.
        tainted = record[DEV_TAINTED]
        if tainted:
            record[DEV_TAINTED] = False

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
        if pushed:
            self._dirty = True
        LOGGER.info(
            "Day rollover: pushed daily maxima for %d of %d watched devices",
            pushed,
            len(self.data[DATA_DEVICES]),
        )

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
            "without_by_integration": without_by_domain,
        }
