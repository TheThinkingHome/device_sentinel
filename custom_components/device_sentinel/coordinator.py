# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: coordinator.py, Version: 0.12.5 (2026-08-06)

"""Coordinator for the Device Sentinel integration.

The class itself, and the parts nothing else can be split away from:
setup and shutdown, the registry view of what is watched, the event
bus handlers that record activity, the schedulers, and the entity
properties the sensors read.

Everything with a subject of its own lives beside this file and is
mixed in (ruling #201). Six modules, chosen by measuring which
methods call which rather than by taste: detect_signal, detect_battery
and detect_freeze for the three detectors, problem_list for the single
memory every channel renders, store for the two files and the merge,
and interventions for bridge state, pairing windows and storms. Four
more predate them: reports, narrative, messenger and notifier.

A file split rather than a boundary. Every one of those modules is a
mixin reading this class's state freely, so a method moves between
them without changing how it runs, and none of them can be
instantiated or tested alone.

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
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_REPORTED,
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

from .messenger import MessengerMixin
from .notifier import NotifierMixin
from .journal import JournalMixin
from .narrative import NarrativeMixin
from .reports import ReportWritingMixin
from .detect_battery import BatteryMixin
from .detect_freeze import FreezeMixin
from .detect_signal import SignalMixin
from .interventions import InterventionMixin
from .problem_list import ProblemListMixin
from .records import BAD_STATES, _new_device_record, _span
from .stacks import detect as detect_stack
from .stacks import device_key
from .store import StorageMixin
from .backup import async_take_backup
from .const import (
    BACKUP_SUFFIX_PREPHASE_C,
    BRIEF_TRIGGER,
    CONF_EPISODE_SHARE,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    DATA_BRIDGE_SEEN,
    DATA_BROKER_SEEN,
    DATA_STORMS,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_INCIDENTS,
    DATA_SETUP_COUNT,
    DATA_STATS_EPOCH,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    DEFAULT_EPISODE_SHARE_PCT,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EPOCH_KEPT,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    LEARNED_PAIRING,
    LEARNING_MIN_DAYS,
    LEGACY_CAUSE_UNOBSERVED,
    LOGGER,
    RECOVERY_CAUSE_UNOBSERVED,
    RENDER_TICK_SECONDS,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    STARTUP_GRACE_SECONDS,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_CLOCKS_VERSION,
    STORAGE_KEY,
    STORAGE_VERSION,
    SYS_EPOCH_RESET,
    SYS_OPTIONS_CHANGED,
    SYS_RESTART,
    SYS_UNCLEAN_RESTART,
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TODO_ACKED_AT,
    TODO_DEVICE_ID,
    TODO_KINDS,
)


class DeviceSentinelCoordinator(
    ReportWritingMixin,
    NarrativeMixin,
    JournalMixin,
    MessengerMixin,
    NotifierMixin,
    SignalMixin,
    BatteryMixin,
    FreezeMixin,
    ProblemListMixin,
    StorageMixin,
    InterventionMixin,
):
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
        # The hot half of the storage split (ruling #101). A routine save
        # writes this file alone; the store above is written when
        # something changes that a restart must not lose, and on
        # every clean stop. The load merges the two, taking the
        # clocks from here when this file's stamp proves it newer.
        self._clock_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_CLOCKS_VERSION, STORAGE_CLOCKS_KEY
        )
        self.data: dict[str, Any] = {}
        self.storage_healthy: bool = False
        self._dirty: bool = False
        # Two-tier persistence, which came out of an earlier analysis
        # of how often storage was being rewritten (ruling #100).
        # _dirty
        # alone is routine churn (activity clocks) and coalesces into
        # a delayed save; _critical marks a change a reboot must not
        # lose (a verdict, a battery flip, a problem-list change) and
        # forces the immediate save the tick used to do for
        # everything. Acknowledgments and options changes keep their
        # own direct awaited saves and never wait for a tick.
        self._critical: bool = False
        # Cold data (episodes, incidents, system events, registry
        # changes) waiting for the next interval write to carry the
        # main file (ruling #165). Set by _mark_cold_dirty, cleared inside
        # _data_to_save so every main-file write satisfies it, and
        # read only by the render tick's scheduler.
        self._cold_dirty: bool = False
        # The one routine-save deadline, on the loop's monotonic
        # clock (ruling #165). Zero means no window has started, so the
        # first dirty tick writes at once rather than waiting a full
        # interval. _save_now restarts it, making a critical save
        # also the start of a fresh window.
        self._next_routine_save: float = 0.0
        # Devices whose item a person deleted while the fault was
        # still standing. The next sync re-adds them, and this is
        # how it knows to call that a re-add rather than a fresh
        # detection. Deliberately not persisted: a restart inside
        # the minute between the two loses only the distinction,
        # and the row still appears.
        self._hand_deleted: set[str] = set()

        # Registry view, rebuilt on registry changes.
        self._entity_map: dict[str, tuple[str, str | None]] = {}
        self._watched: dict[str, str] = {}  # device_id -> integration domain
        # Which coordinator stacks this house runs, derived from the
        # registry rather than asked (ruling #143).
        self._stacks: set[str] = set()
        # device_id -> (stack, the key that stack knows it by).
        # Derived on every registry rebuild and never stored.
        self._stack_keys: dict[str, tuple[str, str]] = {}
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
        self._device_entries: dict[str, set[str]] = {}
        self._signal_entities: set[str] = set()
        self._signal_devices: set[str] = set()
        # device_id -> (entity_id, is_binary). Election prefers the
        # percentage entity; the binary low flag is the fallback.
        self._battery_entity: dict[str, tuple[str, bool]] = {}
        # entity_id -> device_id, the reverse index the intake uses.
        self._battery_entity_reverse: dict[str, str] = {}
        self._pending_unavailable: dict[str, tuple[float, str]] = {}
        self._taint_consumed_at: dict[str, float] = {}
        # The unavailable duration that set each device's live
        # taint, held until the recovery stamp writes it onto the
        # episode (ruling #137). Transient, not persisted on the record.
        self._taint_duration: dict[str, float] = {}
        self.deviceless_count: int = 0

        # Grace and storm state.
        self._grace_until: float = 0.0
        self._grace_stamps: int = 0
        self._grace_devices: set[str] = set()
        self._grace_taints: set[str] = set()
        # Family events collected during a sync, fired after it settles
        # (ruling #479). Each is (family, event_line, recovery). Cleared on
        # every dispatch so a later sync starts clean.
        self._pending_events: list[tuple[str, str, bool]] = []
        self._storm_feed_q: dict[str, deque[tuple[float, str]]] = {}
        self._storm_active: dict[str, dict[str, Any]] = {}
        # The polling exemption used to live here as a set and a
        # history of storm times, both in memory alone, so the rule
        # that spots a synchronized poller could only ever count the
        # storms of one uptime and reset at every nightly reboot. It
        # is read from the stored storm series now (ruling #227).

        self._listeners: list[Any] = []
        self._unsubs: list[Any] = []
        # Faults waiting out their notification debounce, keyed
        # by (device_id, kind). A hold is cancelled by its own
        # recovery, so anything still here is still true.
        self._held_events: dict[tuple[str, str], Any] = {}
        # When the current burst of cold changes began, so the
        # debounce can be capped rather than pushed out for ever.
        # What the system could actually watch (ruling #160). Both storage
        # files carry the time they were written, so the newer of the
        # two is the last moment anything was observed, and the gap
        # from there to this start is time no device can be blamed
        # for: it went on reporting to its bridge with nobody there
        # to hear it.
        self._last_alive: float | None = None
        self._downtime: float = 0.0
        # The moment this run began listening, which is
        # what the restart event is stamped with.
        self._started_at: float | None = None
        # The broker underneath every MQTT stack. One reader for the
        # whole house rather than one per stack, because there is one
        # broker and a bridge reader cannot see it fail (ruling #224).
        self._broker_reader: Any | None = None
        self._brief_unsub: Any | None = None
        # One bridge reader per detected coordinator stack that can
        # report its own liveness and pairing state (ruling #145). Populated in
        # async_setup after the registry view has found the stacks. Z2M
        # is the only reader today; ZHA and Z-Wave reach their state
        # through different doors and are added later.
        self._bridge_readers: dict[str, Any] = {}
        # The last bridge state and pairing flag seen per
        # stack, so the tick can tell a transition from a
        # steady reading. Nothing polls the reader
        # otherwise: its state is read on demand, so a
        # bridge could come and go unrecorded.
        self._bridge_seen: dict[str, str] = {}
        self._pairing_seen: dict[str, bool] = {}
        self._bridge_down_at: dict[str, float] = {}
        self._pairing_open_at: dict[str, float] = {}
        self._pending_epoch_wipe: int | None = None
        # True only once the backup taken before the clock fields
        # were stripped out of the main file is on disk (rulings
        # #101 and #130). That copy is what a rollback would need,
        # so nothing strips until it exists, and every main-file
        # save consults this. False means the main file keeps
        # carrying the clock copies, which is the harmless
        # direction: nothing is lost, the split simply is not
        # finished yet on this install.
        self._strip_clocks = False
        # Rulings #163 and #167. The first is how many devices this
        # boot reset after an unclean stop, held until setup
        # succeeds so the system event is written beside the
        # restart it explains. The rest is what the integrity count
        # found, kept for the diagnostics rather than acted on.
        self._pending_unclean: int | None = None
        self._orphan_episodes: dict[str, Any] = {}
        self._options_seen: dict[str, Any] = dict(entry.options)

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
        loaded.setdefault(DATA_TODO_JOURNAL, [])
        loaded.setdefault(DATA_EPISODES, [])
        loaded.setdefault(DATA_INCIDENTS, [])
        loaded.setdefault(DATA_SYSTEM_EVENTS, [])
        loaded.setdefault(DATA_BRIDGE_SEEN, {})
        loaded.setdefault(DATA_BROKER_SEEN, {})
        loaded.setdefault(DATA_STORMS, [])
        # The dry-run outbox was retired once the
        # notifications it previewed had been sending for
        # several releases. Drop what an older install stored,
        # so nobody carries a dead key or its bytes.
        loaded.pop("outbox", None)
        # An earlier release renamed the cause an unobserved recovery
        # carries, and
        # the entries already stored kept the old wording, which the
        # composer then failed to recognize and rendered as "revived
        # by a on its own". Rewritten here so the fleet's history
        # speaks one vocabulary rather than two.
        for entry in loaded.get(DATA_INCIDENTS) or []:
            if entry.get(INC_CAUSE) == LEGACY_CAUSE_UNOBSERVED:
                entry[INC_CAUSE] = RECOVERY_CAUSE_UNOBSERVED
        # The list is engine-owned. Anything stored without a
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
        # The hot file is merged here, and the position is
        # deliberate. Three of the thirteen clock fields are among
        # what the statistics epoch below wipes, so merging after it
        # would hand those fields straight back and a declared epoch
        # would quietly fail to take. Merging first means the wipe
        # still has the last word.
        #
        # The count was six of nine when this was written and neither
        # number was updated as clock fields were added or as the
        # wipe was narrowed (ruling #207). The ordering it argues for
        # was correct throughout and still is: one field overlapping
        # would be reason enough.
        hot_payload = await self._clock_store.async_load()
        merged = self._merge_clocks(loaded, hot_payload)
        self._note_downtime(loaded, hot_payload)
        if merged:
            LOGGER.debug(
                "Merged activity clocks for %d device(s) from %s",
                merged,
                STORAGE_CLOCKS_KEY,
            )
        if loaded.get(DATA_STATS_EPOCH) != STATS_EPOCH:
            # A copy of both files before anything is destroyed. An
            # epoch bump is the one operation in the integration that
            # deletes learned data with nothing behind it, and there
            # is no raw layer to rebuild from: readings are folded
            # into a daily figure as they arrive and never stored. So
            # it gets the same protection the clock strip has
            # (ruling #204, on the mechanism of #130).
            # False means it could not copy, and a caller about to
            # delete must treat that as a stop: doing nothing is
            # harmless, wiping without a copy cannot be undone. The
            # suffix carries the epoch so a later bump takes its own
            # copy rather than finding the first one's marker and
            # skipping.
            safe = not loaded[DATA_DEVICES] or await async_take_backup(
                self.hass, loaded, f"pre-epoch-{STATS_EPOCH}"
            )
            wiped = 0
            fresh = _new_device_record(
                dt_util.utcnow().isoformat(), None
            )
            if safe:
                for record in loaded[DATA_DEVICES].values():
                    # The kept set is declared; the wipe is everything
                    # else in the schema, so a field added later is
                    # wiped by default rather than surviving unnoticed
                    # (ruling #204).
                    for field, value in fresh.items():
                        if field not in EPOCH_KEPT:
                            record[field] = value
                    wiped += 1
                loaded[DATA_STATS_EPOCH] = STATS_EPOCH
            else:
                LOGGER.warning(
                    "Statistics epoch %s: the pre-wipe backup could "
                    "not be taken, so nothing was reset. The rhythm "
                    "stays as it is and the epoch will be tried "
                    "again on the next start",
                    STATS_EPOCH,
                )
            # Only when it actually wiped something. A fresh
            # install sets the epoch with no devices to reset, which
            # is an install rather than an event.
            self._pending_epoch_wipe = wiped or None
            LOGGER.info(
                "Statistics epoch %s: the learned rhythm reset for %d "
                "devices so it is relearned under the final rule set; "
                "clocks, identity, signal and battery history kept",
                STATS_EPOCH,
                wiped,
            )
        # Reconcile every stored record against the schema, both
        # directions. There used to be a prune here and a
        # hand-maintained list of setdefault calls above it, so a
        # field leaving the schema was removed automatically while a
        # field joining it reached an existing record only if
        # somebody remembered the other place. The list had already
        # drifted (ruling #189).
        # The two backup markers were written by earlier releases,
        # whose one-shot copies have long since been taken. Dropping
        # them here keeps a retired key from riding every save.
        loaded.pop("pre_split_backup_taken", None)
        loaded.pop("phase_b_backup_taken", None)
        removed, filled = self._reconcile_records(
            loaded[DATA_DEVICES], dt_util.utcnow().isoformat()
        )
        if removed:
            LOGGER.info(
                "Storage prune: removed %d legacy field(s) no longer "
                "in the record schema",
                removed,
            )
        if filled:
            LOGGER.info(
                "Storage upgrade: filled %d field(s) this version "
                "adds to the record schema",
                filled,
            )
        # The clean-stop marker is read and cleared in one breath
        # (ruling #163), so a crash before the next clean stop is detected
        # again rather than inheriting this boot's verdict. Read after
        # the merge, because the arithmetic below needs the clocks the
        # merge restored, and after the epoch wipe, because a wipe
        # that has just emptied the statistics leaves nothing to
        # protect.
        clean_stop = bool(loaded.pop(DATA_CLEAN_STOP, False))
        if not clean_stop:
            self._handle_unclean_restart(loaded)
        self._orphan_episodes = self._count_orphan_episodes(loaded)
        converted = self._coerce_taint_reasons(loaded[DATA_DEVICES])
        if converted:
            LOGGER.info(
                "Storage upgrade: %d taint(s) carried forward as "
                "unavailable, the only reason the flag could have "
                "meant before this version",
                converted,
            )

        self.data = loaded
        # The gate on stripping the clock fields out of the main file
        # (ruling #130), at the one moment it can be honest:
        # after the load, before the first save of this session. The
        # copy taken here is the file as the previous version left it,
        # clocks and all, which is exactly what a rollback needs. The
        # backup module takes it once and remembers; on every later
        # boot this returns immediately. A failure means the strip
        # simply does not happen: the save below and every save after
        # it keeps writing the clock copies into the main file, which
        # is the pre-C behaviour and loses nothing.
        self._strip_clocks = await async_take_backup(
            self.hass, self.data, BACKUP_SUFFIX_PREPHASE_C
        )
        if not self._strip_clocks:
            LOGGER.error(
                "The pre-strip storage backup could not be taken, so "
                "the main file keeps carrying the activity clocks. "
                "Nothing is lost; the storage split is not finished on "
                "this install until the backup succeeds"
            )
        # Both stamped, and stamped here rather than at the first
        # later save. Setup writes storage directly rather than
        # through _save_now, and an unstamped main file beside a
        # stamped hot one is a pair the merge cannot compare, so it
        # would decline and every clock written between this moment
        # and the first critical save would be dropped at the next
        # restart. Writing the stamp now closes that window to
        # nothing.
        await self._store.async_save(self._data_to_save())
        # The hot file is written here too, not only on later
        # saves, or it did not exist until the first coalesced write
        # up to a window later and a system restarting inside that
        # window would never produce one at all.
        await self._clock_store.async_save(self._clocks_to_save())
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
        self._schedule_brief()
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

        # Start a bridge reader for each detected stack that can report
        # its own state. This is separate from the sensors that display
        # it: the reader (and later the pairing detector that consumes
        # it) runs whether or not a user ever enables the sensor, so
        # detection never depends on a display choice.
        await self._start_bridge_readers()
        await self._start_broker_reader()
        # Before the first sample, so a bridge that went down
        # and came back across this restart still closes
        # (ruling #222).
        self._restore_bridge_state()

        # The house's own record of what happened to it. Written here
        # rather than at load, so a start that failed halfway leaves
        # no claim that the system came back.
        self._record_system_event(
            SYS_RESTART,
            duration=self._downtime if self._downtime > 0.0 else None,
            when=self._started_at,
        )
        if self._pending_unclean is not None:
            # Nothing about ruling #163 ships without this row. A reader
            # months later meeting a fleet whose clocks all restart at
            # one moment needs the reason sitting above them, or the
            # reset is exactly the kind of unexplained jump this
            # project exists to catch in other people's software.
            self._record_system_event(
                SYS_UNCLEAN_RESTART,
                detail=f"{self._pending_unclean} devices reset",
                duration=self._downtime if self._downtime > 0.0 else None,
                when=self._started_at,
            )
            self._pending_unclean = None
        if self._pending_epoch_wipe is not None:
            self._record_system_event(
                SYS_EPOCH_RESET,
                detail=f"{self._pending_epoch_wipe} devices",
            )
            self._pending_epoch_wipe = None

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
        if self._broker_reader is not None:
            self._broker_reader.async_stop()
            self._broker_reader = None
        for reader in self._bridge_readers.values():
            reader.async_stop()
        self._bridge_readers.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # A held fault has a live timer; dropping the coordinator
        # without cancelling it would fire into a dead entry.
        for cancel in self._held_events.values():
            cancel()
        self._held_events.clear()
        # The brief schedule is held separately so a changed brief
        # time can re-arm it without disturbing the others, which
        # also means it has to be cancelled by name here.
        if self._brief_unsub is not None:
            self._brief_unsub()
            self._brief_unsub = None
        # The clean-stop marker belongs here as much as on the stop
        # event (ruling #163). An entry unload is every orderly ending that
        # is not a shutdown: a settings change, a reload, a HACS
        # update, the integration being disabled. None of those fires
        # EVENT_HOMEASSISTANT_STOP, so a marker written only there
        # would make an options change read as a power cut on the
        # next load and reset the whole fleet's clocks. What the flag
        # records is that the integration was asked to stop, not which
        # door it left by.
        self.data[DATA_CLEAN_STOP] = True
        # Unconditional. A routine save writes the hot
        # file alone and clears the dirty flag, so a stop that waited
        # for a flag would leave the main file behind by however long
        # since the last critical change. Writing the pair here bounds
        # that to one session and means a clean stop always leaves two
        # files that agree, which is what makes going back to an older
        # version safe.
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
        stacks: set[str] = set()
        stack_keys: dict[str, tuple[str, str]] = {}
        for device in dev_reg.devices.values():
            domain = self._primary_domain(device)
            name = device.name_by_user or device.name or device.id
            # Which coordinator stacks the house runs, read from the
            # same walk (ruling #143). Which device proves which stack
            # is each stack file's own question and is asked through
            # the registry, so this walk names no stack (ruling #218).
            stack = detect_stack(domain, device)
            if stack is not None:
                stacks.add(stack)
            if device.entry_type is dr.DeviceEntryType.SERVICE:
                set_aside[device.id] = (name, domain)
                continue
            watched[device.id] = domain
            # What the owning stack calls this device, where it can
            # say. Read on the same walk for the same reason stack
            # presence is (ruling #143), and asked through the
            # registry so this file still names no stack.
            owner = device_key(domain, device)
            if owner is not None:
                stack_keys[device.id] = owner
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
        device_entries: dict[str, set[str]] = {}
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
            if ent.config_entry_id is not None:
                device_entries.setdefault(ent.device_id, set()).add(
                    ent.config_entry_id
                )
            entity_labels[ent.entity_id] = frozenset(ent.labels or ())
            if excluded_labels & set(ent.labels or ()):
                # An entity carrying an excluded label does not feed
                # its device's judgment. This is the label axis, not a
                # per-entity exclude: the explicit entity exclude was
                # removed as residue from
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
        self._stacks = stacks
        self._stack_keys = stack_keys
        self._device_names = device_names
        self._device_labels = device_labels
        self._set_aside = set_aside
        self._excluded_devices = excluded_devices
        self._excluded_entities = excluded_entities
        self._entity_map = entity_map
        self._entity_labels = entity_labels
        self._last_seen_entity = last_seen_entity
        self._device_entries = device_entries
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
                self._mark_cold_dirty()
        for device_id in list(devices):
            if device_id not in watched:
                del devices[device_id]
                self._mark_cold_dirty()

        if audit and set_aside:
            LOGGER.info(
                "Set aside %d service devices from telemetry",
                len(set_aside),
            )
            LOGGER.debug(
                "Service devices set aside: %s",
                "; ".join(
                    f"{name} ({domain})"
                    for name, domain in sorted(set_aside.values())
                ),
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


    def _contact_stamp(self, device_id: str, now: float) -> float | None:
        """Return when this device was last actually heard, or None.

        Protocol truth where the integration publishes it (ruling #124). The
        value is the coordinator's own record of contact, and a
        republish carries it unchanged, so a replayed payload cannot
        advance the clock and the gap keeps accumulating with no
        exclusion rule involved. That is the whole point: the data is
        honest without being filtered into honesty.

        None means we have such a clock and it has not moved, or the
        entity itself is unavailable, which is information rather
        than a missing value: Door Master's read unavailable for the
        ten hours it was wedged, and falling back to arrival time
        there would have erased the evidence.

        A device with no such entity falls back to arrival time
        (ruling #125), because the moment we heard something is then the
        only evidence there is.
        """
        entity_id = self._last_seen_entity.get(device_id)
        if entity_id is None:
            return now
        state = self.hass.states.get(entity_id)
        if state is None or state.state in BAD_STATES:
            return None
        parsed = dt_util.parse_datetime(state.state)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        # Never ahead of now: a device clock running fast would
        # otherwise push our clock into the future and suppress every
        # gap behind it.
        return min(parsed.timestamp(), now)

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
            record = self.data[DATA_DEVICES].get(device_id)
            debounce = (
                self._taint_debounce(record)
                if record is not None
                else DEFAULT_TAINT_FLOOR_MINUTES * 60.0
            )
            if gone >= debounce and not same_episode:
                if record is not None and not record[DEV_TAINTED]:
                    # The reason, not a flag (ruling #164). The state is
                    # already in hand here and was previously spent
                    # on the log line below, which is why every
                    # excluded gap read "unavailable" whatever the
                    # device had actually done.
                    record[DEV_TAINTED] = (
                        TAINT_UNKNOWN
                        if bad_state == STATE_UNKNOWN
                        else TAINT_UNAVAILABLE
                    )
                    self._taint_duration[device_id] = gone
                    self._dirty = True
                    if dt_util.utcnow().timestamp() < self._grace_until:
                        self._grace_taints.add(device_id)
                    else:
                        LOGGER.debug(
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
        if grace:
            self._grace_stamps += 1
            self._grace_devices.add(device_id)
        if storm is not None:
            storm["stamps"] += 1
            storm["devices"].add(device_id)

        last = record[DEV_LAST_ACTIVITY]
        stamp = self._contact_stamp(device_id, now)
        if stamp is None or (last is not None and stamp <= last):
            # The protocol clock has not moved, so this event carries
            # no evidence that the device spoke: a republish, a
            # restored state, or an entity of ours reacting to
            # something else. Count it as seen and change nothing
            # about liveness. The silence keeps running, which is
            # what makes the exclusion rules unnecessary here.
            record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
            self._dirty = True
            return

        # A taint is consumed by a stamp the protocol vouches for:
        # the outage ended here, and the spanning gap is excluded
        # because it covers time we could not observe.
        tainted = record[DEV_TAINTED]
        taint_seconds = None
        if tainted:
            record[DEV_TAINTED] = False
            taint_seconds = self._taint_duration.pop(device_id, None)
            self._taint_consumed_at[device_id] = now
            if last is not None:
                LOGGER.debug(
                    "Completed gap of %.0f s on a tainted device excluded "
                    "from learning (spanned an unavailable stretch)",
                    stamp - last,
                )
        capped_note: str | None = None
        learned_gap: float | None = None
        if not tainted and last is not None:
            gap = stamp - last
            learned_gap = gap
            # The resurrection cap (ruling #166): a gap completing while the
            # device stands convicted of a freeze may be a hand-fix
            # nothing can see, so it teaches at most rhythm plus the
            # ratchet allowance. Judgment and every human-facing
            # surface keep the true duration; only what learning
            # stores is capped. Several recoveries in one day each cap
            # independently, and the comparison below keeps only the
            # largest.
            if record.get(DEV_FROZEN_CATEGORY) == FREEZE_CATEGORY_FROZEN:
                cap = self._resurrection_cap(record)
                if cap is not None and gap > cap:
                    learned_gap = cap
                    capped_note = (
                        f"capped ({_span(gap)} -> {_span(cap)})"
                    )
                    LOGGER.debug(
                        "Convicted device's completed gap of %.0f s "
                        "learned as %.0f s under the resurrection cap",
                        gap,
                        cap,
                    )
            if (
                record[DEV_TODAY_MAX] is None
                or learned_gap > record[DEV_TODAY_MAX]
            ):
                record[DEV_TODAY_MAX] = learned_gap

        # Taint is the only surviving exclusion (rulings #124 and #125). Grace
        # and storm are gone: for a device with a protocol clock they
        # were never needed, since a replayed payload cannot advance
        # it, and for a device without one they were discarding the
        # only evidence there was, which is what kept the quiet
        # devices' baselines describing half a night.
        learned = f"no ({tainted})" if tainted else (capped_note or "yes")
        # A recovery during a pairing window is a hand re-pair, not a
        # self-recovery, so its gap is discarded whatever the taint
        # decided (ruling #145). This overrides the debounce because pairing
        # is a stronger, more specific signal than duration. Guarded so
        # that if no reader, no bridge, or any failure, the taint
        # decision above stands and nothing is made worse (ruling #147).
        if self._recovered_during_pairing(device_id, now):
            learned = LEARNED_PAIRING
            if not tainted and learned_gap is not None:
                # Undo the daily-max update this gap just made, so a
                # pairing gap never widens the learned rhythm. The
                # retraction uses what was actually learned, which is
                # the capped value when the cap bit (ruling #166).
                self._retract_today_max(record, learned_gap)
            LOGGER.debug(
                "Device %s recovered during a Z2M pairing window; gap "
                "discarded as a pairing intervention",
                device_id,
            )
        self._close_episode(device_id, stamp, learned, taint_seconds)

        record[DEV_LAST_ACTIVITY] = stamp
        record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
        self._dirty = True

        # Recovery is live: a device the protocol has heard from is
        # alive, so any standing freeze verdict clears the instant it
        # speaks. A republish no longer clears one, which is the
        # behaviour that let a four-second bridge blip erase a
        # nine-hour silence.
        self._clear_freeze_verdict(device_id, record)

    # ----------------------------------------------------------- storms


    # ------------------------------------------------------------ timers


    def _schedule_brief(self) -> None:
        """Arm the daily write that closes the brief's window.

        Ruling 116 specified a write at the brief hour and no caller
        ever made one, so every brief ever written said "in progress"
        and no window was finished before its file was replaced. The
        schedule is separate from the rest because the brief time is
        a live option: changing it re-arms here rather than waiting
        for a restart.
        """
        if self._brief_unsub is not None:
            self._brief_unsub()
            self._brief_unsub = None
        hour, minute = self._brief_hour_minute()
        self._brief_unsub = async_track_time_change(
            self.hass,
            self._on_brief_time,
            hour=hour,
            minute=minute,
            second=0,
        )
        LOGGER.debug(
            "Daily brief will be written at %02d:%02d local", hour, minute
        )

    async def _on_brief_time(self, _now: Any) -> None:
        """Close the day's brief, start a new window, and send it.

        The send hangs off this one caller rather than the writer,
        because this is the only write that closes a window (ruling #135):
        a regenerate or a midnight rewrite produces an in-progress
        document, and mailing one of those would deliver the same
        day several times, each incomplete.
        """
        text = await self.hass.async_add_executor_job(
            self._write_reports, BRIEF_TRIGGER
        )
        await self.async_send_brief(text)

    async def _on_midnight(self, _now: Any) -> None:
        """Roll today's maxima into the bounded daily set."""
        now = dt_util.utcnow().timestamp()
        pushed = 0
        for record in self.data[DATA_DEVICES].values():
            if record[DEV_TODAY_MAX] is not None:
                record[DEV_DAILY_MAX].append(record[DEV_TODAY_MAX])
                del record[DEV_DAILY_MAX][:-self.retention_days]
                record[DEV_TODAY_MAX] = None
                pushed += 1
            if record.get(DEV_SIGNAL_TODAY_MIN) is not None:
                record[DEV_SIGNAL_DAILY_MIN].append(
                    record[DEV_SIGNAL_TODAY_MIN]
                )
                del record[DEV_SIGNAL_DAILY_MIN][:-self.retention_days]
                record[DEV_SIGNAL_TODAY_MIN] = None
            self._roll_dwell(record, now)
            self._roll_battery(record)
        # The roll is what confirms a rail (three daily lows at the
        # fill value), so the sync runs here and the item appears
        # with the rollover rather than a minute behind it.
        self._sync_problem_list()
        if pushed or self._dirty or self._critical:
            await self._save_now()
        LOGGER.debug(
            "Day rollover: pushed daily maxima for %d of %d watched devices",
            pushed,
            len(self.data[DATA_DEVICES]),
        )
        await self.hass.async_add_executor_job(self._write_reports)


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


    # ------------------------------------------------ silence episodes


    def _device_name(self, device_id: str) -> str:
        """Return a device's display name for logging and the report."""
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id)
        if device is not None and (device.name_by_user or device.name):
            return device.name_by_user or device.name
        return device_id

    @property
    def episode_share(self) -> float:
        """Return the configured episode-opening share, as a fraction.

        Live from options (ruling #117): a silence opens an episode once it
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
        self._sample_bridges()
        self._judge_all_devices()
        # The sync follows the sweep every tick, so a freeze the
        # sweep just fired, a battery level that drifted, or a rail
        # the midnight roll confirmed reaches the list within the
        # same minute it was detected. Idempotent and cheap: a clean
        # pass changes nothing and writes nothing.
        self._sync_problem_list()
        if self._critical:
            # Something a reboot must not lose changed this tick:
            # save now. _save_now writes both files and restarts the
            # interval, so a pending cold flag rides along for free.
            await self._save_now()
        elif self._dirty:
            # Routine churn coalesces on one clock (ruling #165): this tick
            # is the only scheduler, and the deadline is a plain float
            # here rather than state inside two Store objects. The old
            # arrangement gave the cold data its own delayed schedule,
            # and two schedules against one pair of files is the race
            # that let the main file come out newer than the clocks
            # file, the state the final phase of the split cannot
            # survive. A deadline of zero is the first dirty tick of a
            # session and writes immediately, which keeps the first
            # window from silently starting a full interval long.
            now_mono = self.hass.loop.time()
            if now_mono >= self._next_routine_save:
                self._next_routine_save = now_mono + self.coalesce_seconds
                if self._cold_dirty:
                    # A forensic row is waiting (an episode, an
                    # incident, a system event, a registry change), so
                    # the main file goes too, first, keeping the hot
                    # stamp the newer of the pair. Anything
                    # judgment-bearing never reaches this branch: it
                    # is critical and wrote both files within the tick
                    # that detected it (ruling #100).
                    await self._store.async_save(self._data_to_save())
                # The split (ruling #101): routine churn is nine
                # fields per
                # device, so the ordinary window writes the hot file
                # alone, 45 KB rather than 335 KB on this fleet, which
                # is the whole point of the split. The main file then
                # lacks only clocks, and the next load merges them
                # back from here.
                await self._clock_store.async_save(self._clocks_to_save())
            self._dirty = False
        self._notify()


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


    # ------------------------------------------- the problem-list sync


    async def async_options_updated(self) -> None:
        """Re-judge the fleet under new options, live, no restart."""
        # Home Assistant has already replaced the entry's options by
        # the time this runs, so the comparison is against a copy
        # taken when they were last applied rather than against the
        # entry itself, which would compare the new options with
        # themselves and find nothing.
        before = self._options_seen
        after = dict(self.entry.options)
        self._options_seen = after
        self._rebuild_registry_view()
        moved = sorted(
            key for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        )
        if moved:
            # Which setting moved, not merely that one did. A row
            # saying something changed cannot answer, months later,
            # why a device started being reported when nothing in the
            # house had altered.
            self._record_system_event(
                SYS_OPTIONS_CHANGED, detail=", ".join(moved)
            )
        LOGGER.debug(
            "Options updated: low threshold now %s, %d devices and %d "
            "entities excluded; re-evaluating",
            self.low_threshold,
            len(self._excluded_devices),
            len(self._excluded_entities),
        )
        self._schedule_brief()
        self._evaluate_all_batteries()
        # Exclusions changed here remove verdicts at the source, so
        # the sync sees the shrunken lists and deletes the items of
        # anything the person just excluded, immediately.
        self._sync_problem_list()
        if self._dirty or self._critical:
            await self._save_now()
        self._notify()


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
        """Judge every device now, then rewrite every report.

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
