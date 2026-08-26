# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: coordinator.py, Version: 0.18.2 (2026-08-26)

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
- The startup grace and the storm detector count the bursts a
  restart or a reconnect produces. Neither mutes anything from
  learning: an echo carries no evidence that the device spoke,
  because the protocol clock behind it has not moved, and for a
  device without one the muting rules were discarding the only
  evidence there was (rulings #124 and #125).
- The taint rule: a gap that spans an unavailable stretch is an
  outage, not normal silence, and never feeds statistics.
- Daily maxima roll at local midnight into a bounded per-device set.
"""

from __future__ import annotations

from collections import Counter, deque
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
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import trim
from .normalise import (
    check_clocks,
    check_records,
    check_storage,
    fault_id,
)
from .repairs import async_evaluate
from .backup import (
    async_copy_evidence,
    async_last_good_taken,
    async_prune_backups,
    async_refresh_last_good,
    async_take_backup,
    async_restore_main_file,
    describe_restore_loss,
)
from .const import (
    DEFAULT_RETENTION_DAYS,
    CONF_RETENTION_DAYS,
    REPAIR_MOMENT_BRIEF,
    SYS_STORAGE_SHAPE,
    SYS_STORAGE_REPAIR,
    AREA_BATTERY,
    AREA_FREEZE,
    AREA_SIGNAL,
    BACKUP_SUFFIX_PREPHASE_C,
    BACKUP_TAKEN_KEY,
    BATTERY_SLOPE_DAYS,
    BRIEF_TRIGGER,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EPISODE_SHARE,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_MAINTENANCE_MINUTES,
    CONF_SIGNAL_MUTED_DEVICES,
    DAILY_MAX_KEEP,
    DATA_BRIDGE_SEEN,
    DATA_BROKER_SEEN,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_EPISODES,
    INC_DEVICE_ID,
    EP_DEVICE_ID,
    DATA_FIRST_INSTALLED,
    DATA_INCIDENTS,
    DATA_SERIES_STAMPS,
    DATA_SETUP_COUNT,
    DATA_SIGNAL_DAY_REPAIR,
    DATA_SIGNAL_WEIGHTING,
    DATA_LAST_VERSION,
    CONF_TRIM_DEVICES,
    CONF_TRIM_INTEGRATIONS,
    DATA_STATS_EPOCH,
    DATA_STORM_DAYS,
    DATA_STORMS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    DEFAULT_EPISODE_SHARE_PCT,
    DEFAULT_MAINTENANCE_MINUTES,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_ALT,
    RETIRED_SIGNAL_KEYS,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_TODAY_MIN,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EPOCH_KEPT,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    LEARNED_DISABLED,
    LEARNED_MAINTENANCE,
    LEARNED_PAIRING,
    LEARNING_MIN_DAYS,
    LEGACY_CAUSE_UNOBSERVED,
    LOGGER,
    MAINTENANCE_MINUTES_MAX,
    MAINTENANCE_MINUTES_MIN,
    RECOVERY_CAUSE_UNOBSERVED,
    RENDER_TICK_SECONDS,
    SERIES_BATTERY,
    SERIES_FREEZE,
    SERIES_SIGNAL,
    SET_ASIDE_DISABLED,
    SET_ASIDE_EXCLUDED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    SIGNAL_ARMING_DAYS,
    SIGNAL_DAY_REPAIR_MARK,
    SIGNAL_DAYS_KEEP,
    SIGNAL_WEIGHTING_MARK,
    STARTUP_GRACE_SECONDS,
    TRIM_BACKUP_DIR,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_CLOCKS_VERSION,
    STORAGE_KEY,
    STORAGE_VERSION,
    SYS_EPOCH_RESET,
    SYS_KIND,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_OPTIONS_CHANGED,
    SYS_RESTART,
    SYS_TRIMMED,
    SYS_UNCLEAN_RESTART,
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TODO_ACKED_AT,
    TODO_DEVICE_ID,
    TODO_KINDS,
)
from .detect_battery import BatteryMixin
from .detect_freeze import FreezeMixin
from .detect_signal import SignalMixin, _entity_unit, _is_percentage
from .events import EventMixin
from .interventions import InterventionMixin
from .journal import JournalMixin
from .messenger import MessengerMixin
from .narrative import NarrativeMixin
from .notifier import NotifierMixin
from .problem_list import ProblemListMixin
from .records import BAD_STATES, _new_device_record, _reset_signal_day, _span
from .reports import ReportWritingMixin
from .stacks import detect as detect_stack
from .stacks import device_key
from .store import StorageMixin


class DeviceSentinelCoordinator(
    EventMixin,
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
        # device_id -> the name a person is shown, which carries
        # the integration where the plain name is not unique.
        self._display_names: dict[str, str] = {}
        self._device_labels: dict[str, frozenset[str]] = {}
        # Muting suppresses judgment, not observation: these sets
        # gate reporting only. Clocks, statistics, and vouching keep
        # running for everything in them, so undo is instant and the
        # rhythm history carries no holes.
        self._muted_devices: dict[str, str] = {}  # device_id -> reason
        self._muted_entities: dict[str, str] = {}  # entity_id -> reason
        # id -> (name, domain, reason). The reason is one of the
        # SET_ASIDE_* constants and has been the third element since
        # 0.13.3, when a device disabled by Home Assistant joined
        # service devices as a thing to set aside (ruling #257).
        self._set_aside: dict[str, tuple[str, str, str]] = {}
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

        self._grace_until: float = 0.0
        self._grace_stamps: int = 0
        self._grace_devices: set[str] = set()
        self._grace_taints: set[str] = set()
        # Family events collected during a sync, fired after it settles
        # (ruling #151). Each is (family, event_line, recovery). Cleared on
        # every dispatch so a later sync starts clean.
        self._pending_events: list[tuple[str, str, bool]] = []
        # The maintenance window (rulings #225 and #238): epoch seconds
        # of the declared end while a window is open, else None, and
        # when it was opened for the closing row's duration. In memory
        # only: a window does not survive a restart, and building
        # storage for a ten-minute declaration would be storage
        # without a reader.
        self._maintenance_until: float | None = None
        self._maintenance_opened_at: float | None = None
        self._storm_feed_q: dict[str, deque[tuple[float, str]]] = {}
        self._storm_active: dict[str, dict[str, Any]] = {}
        # The day's closed storms per domain, memory only, folded
        # into DATA_STORM_DAYS at midnight (ruling #320).
        self._storm_day: dict[str, list[tuple[float, int, float]]] = {}
        # The clocks file as loaded, for the shape check (ruling
        # #332). Set at load, read once, cleared.
        self._clocks_seen: dict[str, Any] | None = None
        # Which integrations have been announced as pollers this
        # session. Log-only, so losing it at a restart costs one
        # repeated debug line (ruling #230).
        self._storm_announced: set[str] = set()
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
        self._last_alive = None
        self._downtime = 0.0
        # The moment this run began listening, which is
        # what the restart event is stamped with.
        self._started_at = None
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
        # When the broker went down, or None while it is up. The
        # reporting layer reads it through upstream_down_since
        # (ruling #264).
        self._broker_down_at: float | None = None
        # The upstream outages already announced, and the moment each
        # was first seen, so the first push sounds and later ones do
        # not (ruling #265).
        self._upstream_announced: dict[str, float] = {}
        self._pairing_open_at: dict[str, float] = {}
        self._pending_epoch_wipe: int | None = None
        # Rulings #163 and #167. The first is how many devices this
        # boot reset after an unclean stop, held until setup
        # succeeds so the system event is written beside the
        # restart it explains. The rest is what the integrity count
        # found, kept for the diagnostics rather than acted on.
        self._pending_unclean = None
        self._orphan_episodes: dict[str, Any] = {}
        self._options_seen: dict[str, Any] = dict(entry.options)
        # What the last shape check found, held for the Repairs pass
        # because the load check runs inside the grace and the issue
        # is raised when the grace closes (ruling #300).
        self._shape_faults: list[tuple[str, str, str]] = []
        # The latch (ruling #341): set when a load verifies faulty or
        # a fold produces a fault, cleared only by a restart that
        # loads clean, which is a new coordinator.
        self._load_faulty: bool = False
        self._repairs_at_load: int = 0
        self._last_good_taken: float | None = None
        # The signal census is a fact about the fleet, not an event
        # (ruling #344): held so it is said only when it changes.
        self._signal_census_said: tuple | None = None
        # Restore (ruling #345): the copy's timestamp and the evidence
        # stamp, held until grace close so the notice can be sent when
        # the notify platform actually exists.
        self._restored_from: float | None = None
        self._restore_evidence: str | None = None
        self._restore_told: str | None = None
        # Whether this start is running a different version from the
        # one that last wrote storage (ruling #303). Set at load.
        self._version_changed = False

    # ------------------------------------------------------------- setup


    async def async_setup(self) -> None:
        """Load storage, build the registry view, and start listening.

        A file Home Assistant cannot parse used to leave a traceback
        in the log and a config entry in an error state that named no
        cause (ruling #327). It is now stated: setup stops with a
        sentence a person can act on, and stops permanently rather
        than retrying, because a corrupt file does not repair itself
        between attempts. The last-good copy beside it is untouched
        and is what the Restore flow will read when it ships.
        """
        try:
            loaded = await self._store.async_load()
        except (HomeAssistantError, ValueError) as err:
            # Restore (ruling #345). The alternative to replacing an
            # unreadable file is not running at all, so nobody is
            # asked. Evidence first: all four files, raw, before
            # anything is overwritten (#340).
            stamp = await async_copy_evidence(self.hass)
            restored, taken = await async_restore_main_file(self.hass)
            if restored:
                LOGGER.warning(
                    "Device Sentinel could not read %s (%s), so it was "
                    "replaced from the last-good copy and startup "
                    "continued. Copies of both files and both backups "
                    "were written to %s as %s",
                    STORAGE_KEY,
                    err,
                    TRIM_BACKUP_DIR,
                    stamp or "unstamped",
                )
                loaded = await self._store.async_load()
                self._restored_from = taken
                self._restore_evidence = stamp
                # A restored session is not a clean read (#341): the
                # latch stands, so Status reports it, the repair issue
                # opens, and the copy this came from is never
                # overwritten by the file it produced (#339).
                self._load_faulty = True
            else:
                LOGGER.error(
                    "Device Sentinel cannot read %s and will not start: "
                    "%s. The last-good copy could not be used either. "
                    "Nothing has been changed or deleted; copies of what "
                    "exists were written to %s as %s. Move that file "
                    "aside to begin recording again, or restore it from "
                    "a Home Assistant backup to keep what was learned",
                    STORAGE_KEY,
                    err,
                    TRIM_BACKUP_DIR,
                    stamp or "unstamped",
                )
                raise ConfigEntryError(
                    f"Device Sentinel cannot read {STORAGE_KEY} and its "
                    f"last-good copy could not be used. Nothing has "
                    f"been changed. Move that file aside to start "
                    f"fresh, or restore it from a backup to keep what "
                    f"was learned."
                ) from err
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
        loaded.setdefault(DATA_STORM_DAYS, [])
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
        # And the same treatment for the four kinds renamed at 0.15.8,
        # for the same reason one release later (ruling #299).
        self._rename_stored_kinds(loaded)
        # And the option keys those four kinds' neighbour carries:
        # a settings-changed row names keys, and the brief resolves
        # each to its screen label (ruling #316).
        self._rename_stored_option_keys(loaded)
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
        # The marker the retired one-time backup wrote (ruling #241). It
        # named a copy this version never takes, so it is dropped
        # rather than carried forever in every save. Any epoch
        # markers beside it stay: #204 still uses that mechanism.
        taken = loaded.get(BACKUP_TAKEN_KEY)
        if isinstance(taken, list) and BACKUP_SUFFIX_PREPHASE_C in taken:
            remaining = [
                suffix
                for suffix in taken
                if suffix != BACKUP_SUFFIX_PREPHASE_C
            ]
            if remaining:
                loaded[BACKUP_TAKEN_KEY] = remaining
            else:
                del loaded[BACKUP_TAKEN_KEY]
            LOGGER.debug(
                "Dropped the retired pre-strip backup marker from "
                "storage"
            )

        # The clocks file is the small companion, and losing it costs
        # one interval of live counters rather than the record
        # (ruling #327). An unreadable one is a warning and a fresh
        # start for those fields, not a refusal to run: the main file
        # is intact and the merge already handles a missing companion.
        try:
            hot_payload = await self._clock_store.async_load()
        except (HomeAssistantError, ValueError) as err:
            LOGGER.warning(
                "Device Sentinel cannot read %s, so this start uses "
                "the clocks held in %s instead. Nothing learned is "
                "lost; live counters resume from here (%s)",
                STORAGE_CLOCKS_KEY,
                STORAGE_KEY,
                err,
            )
            hot_payload = None
        # Held for the shape check, which runs a few lines later and
        # must see the file as it came off disk rather than the merge
        # of it (ruling #332). Cleared there.
        self._clocks_seen = (hot_payload or {}).get("clocks")
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
                # The wipe destroys the series themselves, and the
                # depth is read from the series (ruling #258), so the
                # stamps an older version left behind are pruned here
                # and nothing replaces them.
                loaded.pop(DATA_SERIES_STAMPS, None)
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
        # Before the reconciler, which is the last moment the legacy
        # signal accumulators exist: it removes any key the schema
        # has dropped (ruling #256).
        repair = loaded.get(DATA_SIGNAL_DAY_REPAIR) != SIGNAL_DAY_REPAIR_MARK
        converted, day_reset = self._migrate_signal_accumulators(
            loaded[DATA_DEVICES], repair
        )
        loaded[DATA_SIGNAL_DAY_REPAIR] = SIGNAL_DAY_REPAIR_MARK
        # A history holding two scales at once cannot be separated
        # after the fact, so it goes (ruling #282). Judged on the
        # data rather than on a version, so a device that grows a
        # second signal entity next month is treated the same.
        mixed = self._clear_mixed_signal(loaded[DATA_DEVICES])
        if mixed:
            LOGGER.warning(
                "Signal history discarded for %d device(s) whose "
                "recorded readings held two different measurements at "
                "once, RSSI in dBm and LQI on 0 to 255. The two are "
                "recorded apart from now on and nothing says which "
                "past reading came from which sensor: %s",
                len(mixed),
                ", ".join(self._device_name(d) for d in mixed[:20]),
            )
        if converted:
            LOGGER.info(
                "Signal statistics: converted the day in progress for "
                "%d device(s) to the stable accumulator",
                converted,
            )
        if day_reset:
            LOGGER.warning(
                "Signal statistics: the day in progress was unusable "
                "for %d device(s) after an earlier release restarted "
                "the running mean without its history, so today's "
                "signal mean and deviation start from now. Nothing "
                "already recorded is affected",
                day_reset,
            )
        # The depth is read from the series now (ruling #258), so the
        # stamps an older version wrote are dead weight. Pruned on
        # every load rather than only inside the epoch branch, which
        # does not run on an ordinary start and left the key in place
        # indefinitely (ruling #261).
        loaded.pop(DATA_SERIES_STAMPS, None)
        self._clear_reading_weighted_series(loaded)
        removed, filled = self._reconcile_records(
            loaded[DATA_DEVICES], dt_util.utcnow().isoformat()
        )
        # The reconciler reads top-level keys only, so the erased
        # signal fields (ruling #322) are swept from second-scale
        # blocks here: a dual-scale device carries its own copies
        # inside signal_alt, which the schema sees as one key.
        alt_swept = 0
        for record in loaded[DATA_DEVICES].values():
            alt = record.get(DEV_SIGNAL_ALT)
            if isinstance(alt, dict):
                for key in RETIRED_SIGNAL_KEYS:
                    if key in alt:
                        del alt[key]
                        alt_swept += 1
        if alt_swept:
            LOGGER.info(
                "Signal erasure (ruling #322): removed %d retired "
                "field(s) from second-scale blocks",
                alt_swept,
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
        # Is this start an upgrade? Read before the marker is moved
        # on, because the answer is the difference between what the
        # file says and what is running. An integration that has just
        # updated is the moment new diagnostics arrive turned off,
        # which is the one condition the disabled-entities Repair is
        # written for (ruling #303).
        self._version_changed = (
            loaded.get(DATA_LAST_VERSION) != self.version
        )
        if self._version_changed:
            LOGGER.info(
                "Device Sentinel is running %s where storage was last "
                "written by %s",
                self.version,
                loaded.get(DATA_LAST_VERSION) or "an earlier version",
            )
        loaded[DATA_LAST_VERSION] = self.version
        await self._check_storage_shape("load")
        # The clock fields are the hot file's alone and the main file
        # never carries copies. The one-time backup that guarded the
        # transition, and the gate that kept writing copies where it
        # failed, are gone (ruling #241): every install creates both files
        # in this shape, so the pre-split state cannot occur. The
        # marker that recorded the copy is pruned above.
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
        # The stamp survives restarts by living on the file rather
        # than in memory (ruling #341): the age a person sees is the
        # pair's real age, not this process's.
        self._last_good_taken = await async_last_good_taken(self.hass)

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

        # A maintenance window that was open when the process stopped
        # died with it, correctly, since the window is deliberately
        # in-memory (ruling #238). But its opening row is persisted, and
        # an events log where every other pair closes must not carry
        # one open forever, so the close is written here, before this
        # session's restart row, stamped at the restart because the
        # stop is when the declaration actually ended. Duration is
        # left unknown: the wall time between the press and the stop
        # is not how long the window stood if the machine was off.
        if self._started_at is not None:
            self._close_dangling_maintenance(self._started_at)

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
        await self._write_reports_guarded("setup")


    async def _write_reports_guarded(
        self, trigger: str | None = None
    ) -> str | None:
        """Write the reports, and survive a directory that is not there.

        Every write runs in the executor, and an executor job handles
        nothing: an OSError raised inside one escapes into Home
        Assistant's task machinery and lands in a person's log as an
        unretrieved task exception. The writer's own docstring said
        failure was the caller's to handle and no caller handled it
        (ruling #234).

        A report that cannot be written is a worse report rather than
        a broken integration, so the failure is logged with its path
        and the tick carries on. The path this most affects is the
        midnight rollover, where an unguarded raise abandons the rest
        of the job.
        """
        try:
            if trigger is None:
                return await self.hass.async_add_executor_job(
                    self._write_reports
                )
            return await self.hass.async_add_executor_job(
                self._write_reports, trigger
            )
        except OSError as err:
            LOGGER.warning(
                "Device Sentinel could not write its reports (%s): %s",
                trigger or "midnight",
                err,
            )
            return None

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
        muted_device_ids = set(
            options.get(CONF_MUTED_DEVICES, [])
        )
        muted_labels = set(options.get(CONF_MUTED_LABELS, []))
        muted_integrations = set(
            options.get(CONF_MUTED_INTEGRATIONS, [])
        )
        excluded_integrations = self.excluded_integrations

        watched: dict[str, str] = {}
        device_names: dict[str, str] = {}
        device_labels: dict[str, frozenset[str]] = {}
        # Name, domain and reason: the reason joined the tuple when
        # #257 split disabled from service, and the annotation did
        # not follow it (ruling #331).
        set_aside: dict[str, tuple[str, str, str]] = {}
        muted_devices: dict[str, str] = {}
        muted_entities: dict[str, str] = {}
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
            if domain in excluded_integrations:
                # The person asked for this integration never to be
                # watched, so their reason is the one recorded even
                # where another would also fit. Everything else on
                # this ladder is a fact about the device; this is a
                # decision about it, and a decision outranks a fact
                # when the question is why you cannot see something.
                set_aside[device.id] = (name, domain, SET_ASIDE_EXCLUDED)
                continue
            if device.entry_type is dr.DeviceEntryType.SERVICE:
                set_aside[device.id] = (name, domain, SET_ASIDE_SERVICE)
                continue
            if device.disabled_by is not None:
                # Disabled by a person, by its integration, or by a
                # disabled config entry. It cannot report, so judging
                # its silence is noise, and reporting it is the
                # false negative issue #1 describes (ruling #257).
                set_aside[device.id] = (name, domain, SET_ASIDE_DISABLED)
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
            # Device-level muting reasons, named broadest first
            # so the reason recorded is the one that would survive a
            # prune. The integration test uses the primary domain, so
            # an integration mute catches only devices it owns,
            # never multi-homed hardware it merely sees.
            if domain in muted_integrations:
                muted_devices[device.id] = "integration"
            elif muted_labels & set(device.labels or ()):
                muted_devices[device.id] = "label"
            elif device.id in muted_device_ids:
                muted_devices[device.id] = "device"

        entity_map: dict[str, tuple[str, str | None]] = {}
        last_seen_entity: dict[str, str] = {}
        device_entries: dict[str, set[str]] = {}
        signal_entities: set[str] = set()
        signal_units: Counter[str] = Counter()
        per_device_signals: Counter[str] = Counter()
        refused_signals: list[str] = []
        signal_devices: set[str] = set()
        battery_entity: dict[str, tuple[str, bool]] = {}
        deviceless = 0
        with_entities: set[str] = set()
        for ent in ent_reg.entities.values():
            if ent.device_id is None:
                deviceless += 1
                continue
            if ent.device_id not in watched:
                continue
            entity_map[ent.entity_id] = (ent.device_id, ent.config_entry_id)
            with_entities.add(ent.device_id)
            if ent.config_entry_id is not None:
                device_entries.setdefault(ent.device_id, set()).add(
                    ent.config_entry_id
                )
            if muted_labels & set(ent.labels or ()):
                # An entity carrying a muted label does not feed
                # its device's judgment. This is the label axis, not a
                # per-entity mute: the explicit entity mute was
                # removed as residue from
                # the entity-level Entity Sentinel blueprint.
                muted_entities[ent.entity_id] = "label"
            if self._is_last_seen(ent):
                last_seen_entity[ent.device_id] = ent.entity_id
            if self._is_signal(ent):
                if ent.disabled_by is None:
                    signal_entities.add(ent.entity_id)
                    signal_devices.add(ent.device_id)
                    signal_units[_entity_unit(ent) or "(none)"] += 1
                    per_device_signals[ent.device_id] += 1
            elif ent.disabled_by is None and _is_percentage(ent):
                # Refused by #283, and counted rather than dropped in
                # silence: a refusal nobody can see is the same
                # mistake as a check that only reports when it is
                # quiet.
                refused_signals.append(ent.entity_id)
            if ent.disabled_by is None and self._is_battery(ent):
                is_binary = ent.entity_id.startswith("binary_sensor.")
                current = battery_entity.get(ent.device_id)
                # Percentage beats binary; among equals, first wins.
                if current is None or (current[1] and not is_binary):
                    battery_entity[ent.device_id] = (
                        ent.entity_id,
                        is_binary,
                    )

        in_grace = dt_util.utcnow().timestamp() < self._grace_until
        for device_id in [d for d in watched if d not in with_entities]:
            if in_grace:
                # Integrations register their entities as they load,
                # so during the startup window a device with none is
                # usually one whose owner has not finished, not one
                # that will never speak. Setting it aside then and
                # bringing it back a second later cost eighteen
                # devices their first gap on every restart, discarded
                # as administrative by the rule that exists for a
                # disabling (ruling #260). The window is what it is
                # for: things are still arriving.
                continue
            # No entities at all: nothing exists that could ever
            # report, and nothing a person could switch on, so its
            # silence says nothing (ruling #257). A device whose
            # entities are all disabled is a different case and stays
            # watched: those entities exist, the never-reported row
            # is the prompt, and the person can enable them or
            # mute the device.
            set_aside[device_id] = (
                device_names.get(device_id, device_id),
                watched.pop(device_id),
                SET_ASIDE_NO_ENTITIES,
            )
            device_names.pop(device_id, None)

        # A name shared by more than one watched device cannot be
        # acted on: the reports print the name alone, so three
        # registry devices called Bluetooth Proxy 2d8900 produce one
        # row a person cannot find. The integration is appended to
        # those and to no others, because a parenthetical on every
        # row is decoration where the name is already unique.
        seen: dict[str, int] = {}
        for shared_name in device_names.values():
            seen[shared_name] = seen.get(shared_name, 0) + 1
        display_names = {
            device_id: (
                f"{plain} ({watched[device_id]})"
                if seen.get(plain, 0) > 1
                else plain
            )
            for device_id, plain in device_names.items()
        }

        self._display_names = display_names
        self._watched = watched
        self._stacks = stacks
        self._stack_keys = stack_keys
        self._device_names = device_names
        self._device_labels = device_labels
        self._set_aside = set_aside
        self._muted_devices = muted_devices
        self._muted_entities = muted_entities
        self._entity_map = entity_map
        self._last_seen_entity = last_seen_entity
        self._device_entries = device_entries
        self._signal_entities = signal_entities
        self._log_signal_census(
            signal_units, per_device_signals, refused_signals
        )
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
        now_stamp = dt_util.utcnow().timestamp()
        for device_id in list(devices):
            if device_id in watched:
                continue
            if device_id in set_aside:
                # Set aside, not gone: a person disabling an
                # integration for an afternoon must not lose what the
                # house spent weeks learning (ruling #257). The record
                # is kept untouched and unjudged, and the stamp lets
                # the gap that spans the absence be refused on return.
                if devices[device_id].get(DEV_SET_ASIDE_SINCE) is None:
                    devices[device_id][DEV_SET_ASIDE_SINCE] = now_stamp
                    self._mark_cold_dirty()
                continue
            del devices[device_id]
            self._mark_cold_dirty()

        if audit and set_aside:
            # Named by reason: service devices are furniture, but a
            # disabled one is a person's choice and a device with
            # nothing enabled may be an accident, and a person
            # looking for a missing device needs to tell them apart.
            counts: dict[str, int] = {}
            for _name, _domain, reason in set_aside.values():
                counts[reason] = counts.get(reason, 0) + 1
            LOGGER.info(
                "Set aside %d device(s) from judgment: %s",
                len(set_aside),
                ", ".join(
                    f"{count} {reason}"
                    for reason, count in sorted(counts.items())
                ),
            )
            LOGGER.debug(
                "Devices set aside: %s",
                "; ".join(
                    f"{name} ({domain}, {reason})"
                    for name, domain, reason in sorted(set_aside.values())
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
        muting rule involved. That is the whole point: the data is
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
    def _on_registry_updated(self, event: Event[Any]) -> None:
        """Rebuild the registry view when devices or entities change."""
        if event.data.get("action") == "remove":
            self._log_removed_muting(event.data.get("device_id"))
        self._rebuild_registry_view()
        self._notify()

    @callback
    def _log_removed_muting(self, device_id: str | None) -> None:
        """Name a departing device that carries a muting pick.

        The pick is pruned the next time its screen is saved, and by
        then the device is gone from the registry and only its id
        remains, which tells a person nothing. This is the last
        moment its name exists, so the name is written down here.
        """
        if device_id is None or device_id not in self._device_names:
            return
        keys = (
            CONF_MUTED_DEVICES,
            CONF_BATTERY_MUTED_DEVICES,
            CONF_FREEZE_MUTED_DEVICES,
            CONF_SIGNAL_MUTED_DEVICES,
        )
        options = self.entry.options
        if not any(device_id in options.get(key, []) for key in keys):
            return
        LOGGER.info(
            "%s (%s) has been removed from Home Assistant and carried a "
            "Device Sentinel muting; the setting is dropped the next "
            "time its screen is saved",
            self._device_names.get(device_id, device_id),
            device_id,
        )

    # ---------------------------------------------------------- intake

    @callback
    def _event_filter(self, event_data: Any) -> bool:
        """Fast pre-filter: only entities mapped to watched devices."""
        return event_data.get("entity_id") in self._entity_map

    @callback
    def _taint_after_absence(
        self,
        device_id: str,
        entity_id: str,
        pending: tuple[float, str],
    ) -> None:
        """Taint a device whose absence outlasted its debounce.

        Called when the device speaks again, because the length of
        the absence is only known then. A short absence is a mesh
        blip and the silence around it is still learned; a long one
        is real downtime and the completed gap is discarded. A second
        absence inside a gap the taint was already spent on changes
        nothing, and neither does an absence on a device already
        tainted.

        The taint carries the reason rather than a flag (ruling
        #164): the state is in hand here and was previously spent on
        the log line alone, which is why every muted gap once read
        unavailable whatever the device had actually done. A taint
        raised inside the startup grace window is held in the grace
        set instead of logged, so the grace release can tell the two
        apart.
        """
        began, bad_state = pending
        gone = dt_util.utcnow().timestamp() - began
        if began <= self._taint_consumed_at.get(device_id, 0.0):
            return
        record = self.data[DATA_DEVICES].get(device_id)
        debounce = (
            self._taint_debounce(record)
            if record is not None
            else DEFAULT_TAINT_FLOOR_MINUTES * 60.0
        )
        if gone < debounce:
            return
        if record is None or record[DEV_TAINTED]:
            return
        record[DEV_TAINTED] = (
            TAINT_UNKNOWN
            if bad_state == STATE_UNKNOWN
            else TAINT_UNAVAILABLE
        )
        self._taint_duration[device_id] = gone
        self._dirty = True
        if dt_util.utcnow().timestamp() < self._grace_until:
            self._grace_taints.add(device_id)
            return
        LOGGER.debug(
            "Device tainted: %s was %s for %.0f s; its next completed "
            "gap will not feed learning",
            entity_id,
            bad_state,
            gone,
        )

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
            self._taint_after_absence(device_id, entity_id, pending)
        self._record_activity(
            device_id, entry_id, entity_id, new_state.state
        )
        if entity_id in self._battery_entity_reverse:
            self._evaluate_battery(
                self._battery_entity_reverse[entity_id],
                notify_on_change=True,
            )

    @callback
    def _on_state_reported(self, event: Event[Any]) -> None:
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
            # what makes the muting rules unnecessary here.
            record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
            self._dirty = True
            return

        # A taint is consumed by a stamp the protocol vouches for:
        # the outage ended here, and the spanning gap is muted
        # because it covers time we could not observe.
        tainted = record[DEV_TAINTED]
        taint_seconds = None
        if tainted:
            record[DEV_TAINTED] = False
            taint_seconds = self._taint_duration.pop(device_id, None)
            self._taint_consumed_at[device_id] = now
            if last is not None:
                LOGGER.debug(
                    "Completed gap of %.0f s on a tainted device muted "
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

        # Taint is the only surviving muting (rulings #124 and #125). Grace
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
        elif record.get(DEV_SET_ASIDE_SINCE) is not None:
            # The device was set aside for part of this gap, so the
            # silence is a disabled entity or integration rather than
            # the device's own rhythm (ruling #257). Same treatment as
            # pairing and maintenance: refused and retracted, so a
            # fortnight switched off cannot teach a fortnight-long
            # window. The stamp is cleared by the registry rebuild
            # that brought the device back.
            learned = LEARNED_DISABLED
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap)
            LOGGER.debug(
                "Device %s returned from being set aside; gap "
                "discarded as administrative",
                device_id,
            )
        elif self._recovered_during_maintenance(now):
            # A recovery inside a declared maintenance window is the
            # person's hands, not the device's own rhythm (rulings #225
            # and #238). Pairing takes precedence where both windows are
            # open, because it is the more specific signal: it names
            # the stack, where maintenance names only the person. Same
            # retraction as pairing (ruling #166); detections are untouched,
            # since a device going down during maintenance is not an
            # intervention.
            learned = LEARNED_MAINTENANCE
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap)
            LOGGER.debug(
                "Device %s recovered during a maintenance window; gap "
                "discarded as a hand fix",
                device_id,
            )
        self._close_episode(device_id, stamp, learned, taint_seconds)

        record[DEV_LAST_ACTIVITY] = stamp
        record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
        if record.get(DEV_SET_ASIDE_SINCE) is not None:
            # Spent: the gap spanning the absence has been judged
            # above, and the next silence is the device's own again.
            # Cleared here rather than when the registry brought it
            # back, which happens before it speaks (ruling #257).
            record[DEV_SET_ASIDE_SINCE] = None
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
        text = await self._write_reports_guarded(BRIEF_TRIGGER)
        if text is not None:
            await self.async_send_brief(text)
        # After the send, not before it, so a Repair raised here
        # cannot delay or fail the delivery it travels beside
        # (ruling #309). The fold keeps the storage shape check,
        # the copy, and the heal; only the judging moved.
        self._evaluate_repairs(REPAIR_MOMENT_BRIEF)

    @property
    def _excluded_device_ids(self) -> set[str]:
        """Return the devices set aside because their integration is
        excluded.

        Read by the record discard and the episode cleanup. The
        enable buttons no longer need it: they reach watched devices
        only (ruling #302), and every excluded device is set aside, so
        the narrower filter already covers what this used to mute
        from them.
        """
        return {
            device_id
            for device_id, (_name, _domain, reason) in self._set_aside.items()
            if reason == SET_ASIDE_EXCLUDED
        }

    async def _check_storage_shape(self, moment: str) -> None:
        """Check the whole file, protect the evidence, and refresh
        the last-good copy only when nothing needed doing.

        Two moments call this (ruling #278): after load, and after
        the midnight fold once its records are folded and saved.

        The refresh rule changed in 0.18.0 (ruling #339): the copy
        refreshes only in a session whose load was clean the first
        time, and never after any repair, automatic or human. A
        repaired file checks clean by construction, because the check
        judges shapes and a field just written is in the right shape
        whatever value it holds. Refreshing after a repair would turn
        the last-good pair from the last file that was born clean
        into the last file patched until it looked clean, and the
        whole ladder rests on the first guarantee. Verify has
        produced one false positive already, the tainted field in
        0.15.3, so none of this is hypothetical.

        A load that verifies faulty latches (ruling #341): Status
        reads `problem` for the whole session and only a restart that
        loads clean clears it. A repair does not clear it, because a
        repaired file is not a good read.
        """
        faults = self._gather_shape_faults(moment)
        if faults and moment == "load":
            # The evidence copy comes before anything else touches
            # disk (ruling #340): the first save re-serializes the
            # file after migrations have handled it, so without this
            # copy the original of what went wrong is destroyed by
            # the process that found it.
            stamp = await async_copy_evidence(self.hass)
            if stamp:
                LOGGER.warning(
                    "Storage evidence copied to trim_backups as %s "
                    "before anything writes",
                    stamp,
                )
            repaired = self._bank_damaged_clocks(faults)
            if repaired:
                # Verify again (the load path's step 4): the repair
                # list is what remains, and the session stays dirty
                # however clean it now checks.
                faults = self._gather_shape_faults(moment)
            self._load_faulty = True
        if moment == "fold" and faults:
            self._load_faulty = True
        # Kept for the Repairs pass, which runs at grace close rather
        # than here. The load check fires inside the startup grace,
        # where nothing is announced (ruling #291), so the result has
        # to survive the wait rather than the issue being raised from
        # inside the window. Each fault carries a stable identity
        # (ruling #338) naming file, holder and field, so a later
        # release can act on one fault rather than on a list.
        self._shape_faults = faults
        if not faults and not self._load_faulty:
            if await async_refresh_last_good(self.hass):
                self._last_good_taken = dt_util.utcnow().timestamp()
            return
        if not faults:
            # Clean now, but the session is latched: the load needed
            # repair, so the copy is withheld and the latch stands
            # until a restart loads clean (ruling #341).
            LOGGER.warning(
                "Storage checks clean at %s, but this session's load "
                "was not: the last-good copy is withheld and Status "
                "stays a problem until a restart loads clean",
                moment,
            )
            return
        source = "the fold produced" if moment == "fold" else "storage holds"
        for fault in faults[:50]:
            LOGGER.warning(
                "Storage shape: %s a record that does not fit: %s: %s. "
                "Nothing was changed.",
                source,
                fault_id(fault),
                fault[2],
            )
        if len(faults) > 50:
            LOGGER.warning(
                "Storage shape: %d further fault(s) not listed", len(faults) - 50
            )
        fields = sorted({field for _d, field, _w in faults})
        self._record_system_event(
            SYS_STORAGE_SHAPE,
            detail=f"{moment}: {len(faults)} fault(s) in "
            f"{len({d for d, _f, _w in faults})} record(s): "
            + ", ".join(fields[:8])
            + (", ..." if len(fields) > 8 else ""),
            devices=len({d for d, _f, _w in faults}),
        )

    def _gather_shape_faults(
        self, moment: str
    ) -> list[tuple[str, str, str]]:
        """Run all three checks for one moment and return the union.

        At load the clocks subject is the file as it arrived; at the
        fold it is what this process is about to write, the same
        distinction the record check draws between a fault storage
        holds and one the fold produced (ruling #332).
        """
        faults = check_records(self.data.get(DATA_DEVICES))
        faults += check_storage(self.data)
        if moment == "fold":
            faults += check_clocks(self._clocks_to_save().get("clocks"))
        else:
            faults += check_clocks(self._clocks_seen)
            self._clocks_seen = None
        return faults

    def _bank_damaged_clocks(
        self, faults: list[tuple[str, str, str]]
    ) -> int:
        """Repair damaged activity clocks by banking, not by reading.

        A damaged `last_activity` cannot be reconstructed: the entity
        registry's idea of last-changed is the restart moment for
        anything that has not spoken since, so reading it would write
        "reported just now" over a dead device's clock and make the
        one fault this integration exists to catch invisible
        (ruling #338, retiring the reconstruct rung).

        Instead the clock restarts honestly, the path an unclean
        restart already takes: set to now, taint cleared because the
        gap that taint was waiting to mute no longer exists. No
        silence is banked into today's maximum, because a value that
        carries no information gives nothing to measure the silence
        from; the difference from the unclean-restart path is that
        there the old stamp was true and here it is noise.

        Each repair is recorded as a system event (ruling #342): a
        repair nobody can see afterwards is a repair that did not
        happen as far as the person is concerned.
        """
        devices = self.data.get(DATA_DEVICES) or {}
        now = dt_util.utcnow().timestamp()
        repaired = 0
        seen: set[str] = set()
        for holder, field, _why in faults:
            if field != DEV_LAST_ACTIVITY:
                continue
            # The same damaged clock is reported by the record check
            # and by the clocks check, one holder in two files. One
            # repair, one event: found by the first test written
            # against this, which counted two.
            if holder in seen:
                continue
            seen.add(holder)
            record = devices.get(holder)
            if not isinstance(record, dict):
                continue
            record[DEV_LAST_ACTIVITY] = now
            record[DEV_TAINTED] = False
            repaired += 1
            self._record_system_event(
                SYS_STORAGE_REPAIR,
                detail=(
                    f"banked a damaged activity clock on {holder}: "
                    "set to now, taint cleared, nothing banked from "
                    "a value carrying no information"
                ),
            )
        if repaired:
            self._repairs_at_load += repaired
            LOGGER.warning(
                "Storage repair: %d damaged activity clock(s) "
                "restarted by banking",
                repaired,
            )
        return repaired

    @callback
    def _evaluate_repairs(self, moment: str) -> None:
        """Reconcile the Repairs panel against how things stand now.

        Two moments and no tick (ruling #300): the startup grace
        closing, and the midnight fold. Nothing is announced inside
        the grace (ruling #291), which is why the load-time shape
        check stores its result rather than raising from where it
        runs, and why this is the first chance a fault found at load
        has to reach a person.

        Every reading is taken here and handed over, so repairs.py
        holds the rules and the coordinator holds the measurements.
        The registry walk behind the awaiting counts is the expensive
        part, and running it twice a day rather than on a tick is the
        reason there is no tick.
        """
        days_installed: float | None = None
        first = self.first_installed
        if first:
            try:
                installed = dt_util.parse_datetime(first)
            except (TypeError, ValueError):
                installed = None
            if installed is not None:
                days_installed = (
                    dt_util.utcnow() - installed
                ).total_seconds() / 86400.0
        async_evaluate(
            self.hass,
            self.entry,
            moment,
            shape_faults=self._shape_faults,
            awaiting=self.awaiting_enable_counts(),
            days_installed=days_installed,
            version_changed=self._version_changed,
            namer=self._device_name,
        )

    def _discard_excluded_records(self) -> None:
        """Drop what an excluded integration recorded before it was.

        Here rather than on the save that excluded it, because this is
        the fold, and the fold is already the one place the record
        changes size: lowering how much history to keep does not
        delete anything when the slider moves either, it shortens the
        series at the next rollover. So a person who excludes an
        integration by mistake has until midnight to take it back with
        nothing lost, and record-shrinking stays in one place instead
        of two.

        Set aside for any other reason keeps its record untouched
        (ruling #257): a disabling is Home Assistant's doing and may
        last an afternoon, while this is a person saying the data is
        not worth keeping.
        """
        excluded = self._excluded_device_ids
        if not excluded:
            return
        devices = self.data.get(DATA_DEVICES) or {}
        dropped = [device_id for device_id in excluded if device_id in devices]
        for device_id in dropped:
            del devices[device_id]

        # The episodes and incidents go with the record, and an open
        # episode is the reason this cannot be left to the age prune.
        # An episode is completed by its device speaking again, and an
        # excluded device is no longer walked, so one still open when
        # the integration was excluded can never be closed by anything.
        # It would then be counted as an orphan at every boot, which
        # is the one diagnostic that exists to catch a closing that
        # never reached disk (ruling #167), and a permanent false
        # positive there costs more than the rows are worth. They are
        # dropped rather than stamped because the promise is that an
        # excluded integration is never recorded, and an episode is a
        # record.
        episodes = self.data.get(DATA_EPISODES) or []
        kept_episodes = [
            episode
            for episode in episodes
            if episode.get(EP_DEVICE_ID) not in excluded
        ]
        incidents = self.data.get(DATA_INCIDENTS) or []
        kept_incidents = [
            row for row in incidents if row.get(INC_DEVICE_ID) not in excluded
        ]
        shed_episodes = len(episodes) - len(kept_episodes)
        shed_incidents = len(incidents) - len(kept_incidents)
        if shed_episodes:
            self.data[DATA_EPISODES] = kept_episodes
        if shed_incidents:
            self.data[DATA_INCIDENTS] = kept_incidents

        if dropped or shed_episodes or shed_incidents:
            self._mark_cold_dirty()
            LOGGER.info(
                "Excluded integrations: discarded %d device record(s), "
                "%d episode(s) and %d incident(s) at the fold",
                len(dropped),
                shed_episodes,
                shed_incidents,
            )

    async def _on_midnight(self, _now: Any) -> None:
        """Roll today's maxima into the bounded daily set."""
        now = dt_util.utcnow().timestamp()
        self._discard_excluded_records()
        pushed = 0
        for record in self.data[DATA_DEVICES].values():
            if record[DEV_TODAY_MAX] is not None:
                record[DEV_DAILY_MAX].append(record[DEV_TODAY_MAX])
                del record[DEV_DAILY_MAX][:-self.retention_days]
                record[DEV_TODAY_MAX] = None
                pushed += 1
            # The day's low, for the primary and for a second scale
            # if the device has one (ruling #285).
            for bucket in (record, record.get(DEV_SIGNAL_ALT)):
                if bucket is None:
                    continue
                # The daily-minimum series is erased (ruling #322);
                # today's minimum stays live for the telemetry
                # report and resets with the day.
                bucket[DEV_SIGNAL_TODAY_MIN] = None
            self._roll_dwell(record, now)
            self._roll_battery(record)
        # The day's storm tally, one row per domain (ruling #320),
        # written before the save that carries it.
        self._fold_storm_days(dt_util.now().date().isoformat())
        # The roll is what confirms a rail (three consecutive days
        # of nothing but the fill value), so the sync runs here and
        # the item appears with the rollover rather than a minute
        # behind it.
        self._sync_problem_list()
        if pushed or self._dirty or self._critical:
            await self._save_now()
        await self._check_storage_shape("fold")
        # The evidence directory is bounded by the same retention
        # setting as every daily series, one retention idea rather
        # than two (ruling #343). No file is special: a copy older
        # than the window describes a fleet state older than anything
        # the integration still remembers.
        pruned = await async_prune_backups(
            self.hass,
            int(
                self.entry.options.get(
                    CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                )
            ),
        )
        if pruned:
            LOGGER.info(
                "Trim backups: pruned %d file(s) past the retention "
                "window",
                pruned,
            )
        LOGGER.debug(
            "Day rollover: pushed daily maxima for %d of %d watched devices",
            pushed,
            len(self.data[DATA_DEVICES]),
        )
        await self._write_reports_guarded()


    # ------------------------------------------------ device-down judgment

    def _has_registered_entities(self, device_id: str) -> bool:
        """Return whether the registry holds any entity for a device.

        The companion to _live_entity_states: that one answers what
        can be read now, this one answers whether anything is meant
        to be readable at all. Together they separate a device that
        has not loaded yet from a device with nothing to load.
        """
        return any(
            owner == device_id for owner, _ in self._entity_map.values()
        )

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
        if device is not None:
            named = device.name_by_user or device.name
            if named:
                return named
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


    async def _routine_save(self) -> None:
        """Write the coalesced routine save, if its window has come.

        Routine churn coalesces on one clock (ruling #165): the render
        tick is the only scheduler, and the deadline is a plain float
        here rather than state inside two Store objects. The old
        arrangement gave the cold data its own delayed schedule, and
        two schedules against one pair of files is the race that let
        the main file come out newer than the clocks file, the state
        the final phase of the split cannot survive. A deadline of
        zero is the first dirty tick of a session and writes
        immediately, which keeps the first window from silently
        starting a full interval long.

        The split (ruling #101): routine churn is nine fields per
        device, so the ordinary window writes the hot file alone, 45
        KB rather than 335 KB on this fleet. The main file goes first
        and only when a forensic row is waiting (an episode, an
        incident, a system event, a registry change), which keeps the
        hot stamp the newer of the pair. Anything judgment-bearing
        never reaches here: it is critical and wrote both files
        within the tick that detected it (ruling #100).
        """
        now_mono = self.hass.loop.time()
        if now_mono >= self._next_routine_save:
            self._next_routine_save = now_mono + self.coalesce_seconds
            if self._cold_dirty:
                await self._store.async_save(self._data_to_save())
            await self._clock_store.async_save(self._clocks_to_save())
        self._dirty = False

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
        self._expire_maintenance(dt_util.utcnow().timestamp())
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
            await self._routine_save()
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

    def _clear_reading_weighted_series(
        self, loaded: dict[str, Any]
    ) -> None:
        """Drop the mean and deviation days recorded by reading count.

        Ruling #259 moved both onto the minute clock the percentiles
        already used. The two weightings answer different questions,
        so a series holding some of each could not be separated by
        any later analysis, and the September formula work reads
        exactly these series. Cleared once, under a marker, so a
        restart cannot throw away days recorded since. Nothing else
        goes: the minima, the percentiles, the dwell, and the lines
        mean today what they meant yesterday.
        """
        if loaded.get(DATA_SIGNAL_WEIGHTING) == SIGNAL_WEIGHTING_MARK:
            return
        cleared = 0
        for record in loaded.get(DATA_DEVICES, {}).values():
            if record.get(DEV_SIGNAL_DAILY_MEAN) or record.get(
                DEV_SIGNAL_DAILY_SD
            ):
                record[DEV_SIGNAL_DAILY_MEAN] = []
                record[DEV_SIGNAL_DAILY_SD] = []
                cleared += 1
            # The day in progress too (ruling #260). Its accumulator
            # was built by counting readings and would carry on by
            # counting minutes, so the first row folded after the
            # upgrade would mix both weightings: the one row the
            # clearing exists to prevent. The cost is the hours since
            # midnight on the day of the upgrade.
            _reset_signal_day(record)
        loaded[DATA_SIGNAL_WEIGHTING] = SIGNAL_WEIGHTING_MARK
        if cleared:
            LOGGER.info(
                "Signal mean and deviation now weigh minutes rather "
                "than readings, so the recorded days for %d device(s) "
                "were cleared: the two are not comparable and a mixed "
                "series could not be separated later. Minima, "
                "percentiles, dwell, and every other recording are "
                "untouched",
                cleared,
            )

    @property
    def recording_depth(self) -> dict[str, dict[str, Any]]:
        """Return each area's recording depth, read from the series.

        Ruling #258: the count is the record itself rather than a
        stamp beside it. For one device, an area's complete days is
        the length of its shortest series, since a set that gained a
        series yesterday has one day of complete history however deep
        its older members run; fleet-wide it is the highest of those,
        because the question is how long this system has recorded the
        area, not whether every device is mature.

        Two faults go with the stamp that carried this before. It
        counted whole 24-hour blocks from the moment a version first
        ran, so the number ticked at whatever hour that happened to
        be and read zero for a day on a system recording for months.
        And it had to be told when a recording set changed, by a hand
        edit to a version constant that a release could forget. The
        series cannot forget: add one and it is empty, so it is the
        shortest, so the area reads zero on its own.

        device_days is the fleet's total volume in the area, which is
        the number a person has otherwise had to read out of
        diagnostics.
        """
        devices = list(self.data.get(DATA_DEVICES, {}).values())
        out: dict[str, dict[str, Any]] = {}
        for area, series, arming, learned in (
            (AREA_FREEZE, SERIES_FREEZE, FREEZE_ARMING_DAYS, DAILY_MAX_KEEP),
            (AREA_BATTERY, SERIES_BATTERY, BATTERY_SLOPE_DAYS, None),
            (AREA_SIGNAL, SERIES_SIGNAL, SIGNAL_ARMING_DAYS, SIGNAL_DAYS_KEEP),
        ):
            days = 0
            device_days = 0
            for record in devices:
                lengths = [len(record.get(field) or []) for field in series]
                device_days += sum(lengths)
                if max(lengths, default=0) == 0:
                    # Nothing recorded in this area for this device,
                    # so it is silent on the question rather than an
                    # answer of zero.
                    continue
                days = max(days, min(lengths))
            days = min(days, self.retention_days)
            out[area] = {
                "complete_days": days,
                "armed": days >= arming,
                "arming_days": arming,
                "learned_days": learned,
                "series": list(series),
                "device_days": device_days,
                "retention_days": self.retention_days,
            }
        return out

    async def _announce_restore(self) -> None:
        """Say that a restore happened, once, at grace close.

        Ruling #345. Everything here is knowable: the copy's
        timestamp, how old it was, how many local midnights it
        crossed, where the evidence went, and that the integration is
        running, which is provable by the fact that this code is
        executing. What the corrupt file held is not knowable, so
        nothing here counts events or readings.
        """
        taken = self._restored_from
        if taken is None:
            return
        self._restored_from = None
        loss = describe_restore_loss(taken, dt_util.utcnow().timestamp())
        headline = (
            "Device Sentinel could not read its storage file, so it "
            "replaced the file from its last known-good backup and "
            "started normally. It is running now."
        )
        where = (
            f"Copies of the unreadable file, the clocks file and both "
            f"backups were saved in {TRIM_BACKUP_DIR} under the stamp "
            f"{self._restore_evidence}."
            if self._restore_evidence
            else "The unreadable file could not be copied aside."
        )
        self._record_system_event(
            SYS_STORAGE_REPAIR,
            detail=f"restored from the last-good copy: {loss}",
        )
        self._restore_told = f"{headline} {loss}"
        await self.async_announce_restore(headline, f"{loss}\n\n{where}")

    @property
    def restore_told(self) -> str | None:
        """The restore sentence for the brief, or None (#345)."""
        return getattr(self, "_restore_told", None)

    @property
    def storage_load_faulty(self) -> bool:
        """Whether this session's load verified faulty (ruling #341)."""
        return self._load_faulty

    @property
    def repairs_at_load(self) -> int:
        """How many fields this session's load repaired."""
        return self._repairs_at_load

    @property
    def last_good_taken(self) -> float | None:
        """When the last-good pair was last refreshed, from the file."""
        return self._last_good_taken

    @property
    def shape_faults(self) -> list[tuple[str, str, str]]:
        """The standing faults, each addressable via fault_id (#338)."""
        return list(self._shape_faults)

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
        for _name, domain, _reason in self._set_aside.values():
            breakdown.setdefault(
                domain, {"watched": 0, "set_aside": 0}
            )["set_aside"] += 1
        return breakdown


    # ------------------------------------------- the problem-list sync


    def _trim_name(self, device_id: str) -> str:
        """Return a name for a device the trim event can carry.

        Three maps, because the trim reaches wider than anything else
        does. The display names cover watched devices; the set-aside
        map carries its own name in its tuple; and the registry
        answers for a device that is in neither, which is how a
        picked id that has since gone still reads as something.

        Found on the first live trim: an excluded television was
        erased and the brief recorded a thirty-two character hex id,
        because the lookup read the watched map alone (ruling #307
        widened the picker to every detected device and this reader
        had not been widened with it). An event naming a device by
        id answers nothing a month later, which is the reason the
        ruling says the event names devices rather than counting
        them.
        """
        name = self._display_names.get(device_id)
        if name:
            return name
        aside = self._set_aside.get(device_id)
        if aside:
            return aside[0]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            return device.name_by_user or device.name or device_id
        return device_id

    async def _apply_trim_selection(
        self, options: dict[str, Any]
    ) -> None:
        """Erase what the two Advanced pickers name, then empty them.

        An action wearing an option's clothes (ruling #307). Saving
        the screen is what performs it, which is the one place in
        this flow where a save has a side effect beyond storing what
        it was given, so the pickers are cleared here: without that,
        every later save and every reload would delete again, and the
        person would never be able to change another setting without
        re-erasing the device they trimmed last week.

        Order matters and is the safety property. The copy is taken
        first and the deletion only proceeds if it landed, because
        the copy is the only way back. Then the deletion, then the
        pickers are emptied, then storage is written at once rather
        than at the next interval, so a restart in the seconds after
        a trim cannot resurrect what was just erased or, worse, lose
        the emptied pickers and run the deletion a second time.

        Idempotent on purpose: a device with nothing left to delete
        is a valid pick and produces an event saying nothing was
        recorded. A faulty record can read as empty and that is
        exactly the device a person will be told to choose.
        """
        domains = list(options.get(CONF_TRIM_INTEGRATIONS) or [])
        device_ids = list(options.get(CONF_TRIM_DEVICES) or [])
        if not domains and not device_ids:
            return

        targets = set(device_ids)
        if domains:
            wanted = set(domains)
            targets |= {
                device_id
                for device_id, domain in self._watched.items()
                if domain in wanted
            }
            targets |= {
                device_id
                for device_id, (
                    _name,
                    domain,
                    _reason,
                ) in self._set_aside.items()
                if domain in wanted
            }
        names = [self._trim_name(device_id) for device_id in targets]

        try:
            stamp = await self.hass.async_add_executor_job(
                trim.write_backup,
                self.hass.config.path(TRIM_BACKUP_DIR),
                dt_util.now(),
                self._data_to_save(),
                self._clocks_to_save(),
            )
        except OSError as error:
            # Nothing is deleted. The pickers keep their selection so
            # the person can see what did not happen and try again.
            LOGGER.error(
                "Trim abandoned: the storage copy could not be "
                "written to %s (%s). Nothing was deleted",
                self.hass.config.path(TRIM_BACKUP_DIR),
                error,
            )
            return

        # The clock file is derived from the records at save time
        # rather than held separately, so deleting the record deletes
        # the clock entry with it and the next save writes a clock
        # file that no longer names the device.
        removed = trim.trim_devices(self.data, targets)
        trim.log_result(stamp, removed, names)
        self._record_system_event(
            SYS_TRIMMED,
            detail=trim.describe(removed, names, domains),
            devices=len(targets) or None,
        )
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **options,
                CONF_TRIM_INTEGRATIONS: [],
                CONF_TRIM_DEVICES: [],
            },
        )
        self._options_seen = dict(self.entry.options)
        await self._save_now()

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
        # The trim runs before anything re-judges, so the rest of
        # this method sees the fleet as it is after the deletion
        # rather than judging records that are about to vanish
        # (ruling #307).
        await self._apply_trim_selection(after)
        self._rebuild_registry_view()
        moved = sorted(
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
            # The trim pickers are an action rather than a setting,
            # and they move twice per trim: once when a person picks
            # something and once when the save empties them again.
            # The trim writes its own event, so naming them here put
            # three rows in the brief for one deed and told a reader
            # that a setting had changed when none had (ruling #307).
            and key not in (CONF_TRIM_DEVICES, CONF_TRIM_INTEGRATIONS)
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
            "entities muted; re-evaluating",
            self.low_threshold,
            len(self._muted_devices),
            len(self._muted_entities),
        )
        self._schedule_brief()
        self._evaluate_all_batteries()
        # Muting changed here remove verdicts at the source, so
        # the sync sees the shrunken lists and deletes the items of
        # anything the person just muted, immediately.
        self._sync_problem_list()
        if self._dirty or self._critical:
            await self._save_now()
        self._notify()


    @property
    def trimmable_device_rows(self) -> list[dict[str, Any]]:
        """Return every device the integration knows, for the trim
        pickers.

        Wider than watched_device_rows on purpose (ruling #307).
        Nothing is filtered: watched, muted, excluded and
        set-aside devices are all offered, and so is a device that
        currently holds no record at all. The muting pickers can
        narrow to what a muting would change, because offering a
        pointless muting is only clutter. A trim picker cannot,
        because a faulty record can read as empty and the
        empty-looking device is exactly the one a person will be
        told to choose; a filter keyed on holding a record would
        hide the case the feature exists for.

        The integration is shown beside the name because a fleet can
        carry the same name on two registry devices, and the person
        being walked through this over email has to pick the right
        one first time.
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
        rows += [
            {
                "device_id": device_id,
                "name": name,
                "integration": domain,
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, (
                name,
                domain,
                _reason,
            ) in self._set_aside.items()
        ]
        rows.sort(key=lambda row: (row["name"] or "").lower())
        return rows

    @property
    def watched_device_rows(self) -> list[dict[str, Any]]:
        """Return every watched device, for the muting picker.

        Service-type devices are absent because they were never
        watched, so the list cannot offer a muting that would do
        nothing. Muted devices are present: the list is what is
        being judged, and a muted device is still a device you
        may want to un-mute.
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
        """Enable every disabled entity a matcher recognizes.

        On a watched device, whoever disabled the entity (ruling
        #302). A person pressing Enable Battery is asking for the
        battery entities to come on: declining part of the job
        because they turned one off themselves reads as the tool
        second-guessing them, and they would then have to go and do
        by hand exactly what they just asked for. A muted device
        is watched and still learns, so it is reached like any other;
        muting suppresses judgment and reporting, never learning.

        A set-aside device is not reached, which corrects the third
        consequence of #257. Its entities cannot be usefully turned
        on: Home Assistant re-disables the entities of a disabled
        device at the next registry write, so the sweep enabled them,
        the registry put them back, and the count never reached zero.
        An excluded integration is set aside too, and a person who
        asked for a phone never to be watched is not waiting for its
        battery sensor to be switched on. Home Assistant reloads the
        owning config entries a short delay after.

        Split by kind (signals, last_seen, battery) so a user can
        enable exactly the diagnostic they want without turning on the
        others. Each kind is its own button, its own press.
        """
        ent_reg = er.async_get(self.hass)
        enabled = 0
        enabled_ids: list[str] = []
        by_hand = 0
        for ent in list(ent_reg.entities.values()):
            if ent.device_id not in self._watched:
                continue
            if not matches(ent):
                continue
            if ent.disabled_by is None:
                continue
            if ent.disabled_by is er.RegistryEntryDisabler.USER:
                # Counted as well as enabled, because a sweep that
                # reverses a person's own choice should say how often
                # it did so.
                by_hand += 1
            ent_reg.async_update_entity(ent.entity_id, disabled_by=None)
            enabled += 1
            enabled_ids.append(ent.entity_id)
        LOGGER.info(
            "Enable %s: enabled %d entities, %d of them disabled by "
            "hand. Home Assistant reloads the owning integrations "
            "shortly",
            kind,
            enabled,
            by_hand,
        )
        if enabled_ids:
            # Named, so a person who wonders where a count on the
            # Status sensor came from (ruling #237 keeps the attribute a
            # bare number) finds the answer where the press left it.
            LOGGER.info(
                "Enable %s turned on: %s", kind, ", ".join(enabled_ids)
            )
        return {"enabled": enabled, "by_hand": by_hand}

    @callback
    def _in_startup_grace(self) -> bool:
        """Is the integration still inside its startup grace?

        Everything reports at once on a restart and none of it is
        news, which is why the integration already refuses to judge
        inside the grace. The bus follows the same rule: a fault
        still true when grace ends is announced then, once
        (ruling #291).
        """
        return dt_util.utcnow().timestamp() < self._grace_until

    def _log_signal_census(
        self,
        units: Counter,
        per_device: Counter,
        refused: list[str],
    ) -> None:
        """Say what signal units this fleet actually publishes.

        Written because the next release has to classify the two
        scales apart, and nothing anywhere records what unit a
        Zigbee2MQTT linkquality entity carries or a ZHA LQI sensor
        carries. Guessing was the alternative and #283 rejected it.

        The second line is the count that matters more: a device with
        more than one accepted signal entity is a device whose series
        is a mixture of two measurements (ruling #282). On a
        Zigbee2MQTT fleet it is zero, which is why the fault was
        invisible for the life of the project.

        Once per session, and only when the census changes
        (ruling #344). The docstring said one line per start and the
        call site said otherwise: this runs on every registry
        rebuild, so the reference fleet's log carried 133 copies of
        both lines on 26 August, 38 of them inside one second, each
        with a 1.5 KB entity list attached. A census is a fact about
        the fleet, not an event, so it is said when it is new.

        The lists themselves are debug. A person reading an info log
        wants the counts; a person hunting a specific entity turns
        debug on and gets the whole list rather than the first
        twenty.
        """
        if not units:
            return
        spread = ", ".join(
            f"{unit} x{count}" for unit, count in sorted(units.items())
        )
        doubled = sorted(
            device for device, count in per_device.items() if count > 1
        )
        census = (spread, tuple(doubled), len(refused))
        if census == self._signal_census_said:
            return
        self._signal_census_said = census
        LOGGER.info("Signal units in use: %s", spread)
        if doubled:
            LOGGER.info(
                "%d device(s) report more than one signal entity, so "
                "their signal series mixes two measurements",
                len(doubled),
            )
            LOGGER.debug(
                "Devices with more than one signal entity: %s",
                ", ".join(self._device_name(d) for d in doubled),
            )
        if refused:
            LOGGER.info(
                "%d signal entity(s) refused as a percentage rather "
                "than a measurement",
                len(refused),
            )
            LOGGER.debug(
                "Signal entities refused as a percentage: %s",
                ", ".join(sorted(refused)),
            )

    async def async_enable_signal_entities(self) -> dict[str, int]:
        """Enable every disabled signal-strength entity (ruling #257)."""
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
        await self._write_reports_guarded("manual")
        return {"regenerated": 2}

    async def async_enable_last_seen_entities(self) -> dict[str, int]:
        """Enable every disabled last_seen entity (ruling #257)."""
        return self._enable_matching_entities(
            self._is_last_seen, "last_seen"
        )

    async def async_enable_battery_entities(self) -> dict[str, int]:
        """Enable every disabled battery-percentage entity (ruling #257).

        Percentage batteries only (the sensor, not the binary low
        flag): the percentage is what the discharge series records,
        and the low flag is caught by the battery threshold whether
        or not this entity is on.
        """
        return self._enable_matching_entities(
            self._is_battery_percentage, "battery"
        )

    def awaiting_enable_counts(self) -> dict[str, int]:
        """Return how many entities each enable button would turn on.

        One registry pass, three counters (ruling #237). The filter is
        the buttons' own, so a non-zero count is exactly a press that
        would do something and zero means the button can hide. On a
        watched device every disabled entity is counted, whoever
        disabled it, because the buttons enable every one of them; a
        set-aside device is counted by neither (ruling #302).
        """
        ent_reg = er.async_get(self.hass)
        signal = last_seen = battery = 0
        for ent in list(ent_reg.entities.values()):
            if ent.device_id not in self._watched:
                continue
            if ent.disabled_by is None:
                continue
            if self._is_signal(ent):
                signal += 1
            if self._is_last_seen(ent):
                last_seen += 1
            if self._is_battery_percentage(ent):
                battery += 1
        return {
            "signal": signal,
            "last_seen": last_seen,
            "battery": battery,
        }

    # ----------------------------------------------- maintenance mode

    @property
    def maintenance_until(self) -> float | None:
        """Return when the open maintenance window ends, or None."""
        return self._maintenance_until

    @property
    def maintenance_minutes(self) -> int:
        """Return the configured window length, clamped to its band."""
        raw = self.entry.options.get(
            CONF_MAINTENANCE_MINUTES, DEFAULT_MAINTENANCE_MINUTES
        )
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            minutes = DEFAULT_MAINTENANCE_MINUTES
        return max(
            MAINTENANCE_MINUTES_MIN, min(MAINTENANCE_MINUTES_MAX, minutes)
        )

    async def async_toggle_maintenance(self) -> dict[str, Any]:
        """Open the maintenance window, or close it early (rulings #225
        and #238).

        One button, two meanings: pressed while closed it declares
        that a person is working on the hardware for the configured
        minutes, pressed while open it ends the declaration now. Both
        edges are recorded as system events, so the events log
        explains any discarded recoveries between them. Sensors are
        refreshed at once rather than waiting for the tick, so the
        timer flips under the finger that pressed it.
        """
        now = dt_util.utcnow().timestamp()
        if self._maintenance_until is not None and now < self._maintenance_until:
            opened = self._maintenance_opened_at
            self._close_maintenance(now, "ended by hand", opened)
            self._notify()
            return {"maintenance": "closed"}
        minutes = self.maintenance_minutes
        self._maintenance_until = now + minutes * 60.0
        self._maintenance_opened_at = now
        self._record_system_event(
            SYS_MAINTENANCE_OPEN,
            detail=f"{minutes} minute window",
            when=now,
        )
        LOGGER.info(
            "Maintenance mode opened for %d minutes; recoveries in "
            "this window are attributed to the person and not learned",
            minutes,
        )
        self._notify()
        return {"maintenance": "opened", "minutes": minutes}

    def _close_maintenance(
        self, when: float, detail: str, opened: float | None
    ) -> None:
        """Record the closing edge and clear the window."""
        duration = when - opened if opened is not None else None
        self._maintenance_until = None
        self._maintenance_opened_at = None
        self._record_system_event(
            SYS_MAINTENANCE_CLOSED,
            detail=detail,
            duration=duration,
            when=when,
        )
        LOGGER.info("Maintenance mode closed (%s)", detail)

    def _expire_maintenance(self, now: float) -> None:
        """Close a window whose declared end has passed.

        Lazy, on the render tick, so the closing row can be up to a
        tick late but is stamped at the declared end rather than at
        the tick that noticed (the same honesty the system events log
        keeps everywhere: when it happened, not when it was written).
        """
        if self._maintenance_until is None:
            return
        if now < self._maintenance_until:
            return
        self._close_maintenance(
            self._maintenance_until, "expired", self._maintenance_opened_at
        )

    def _close_dangling_maintenance(self, restart_at: float) -> None:
        """Write the close a restart denied the previous window.

        Called once at setup. The newest maintenance row still being
        an open means the process stopped mid-window; the pair is
        completed with detail "ended by restart" and no duration,
        because how long the declaration actually stood cannot be
        known from here.
        """
        newest: str | None = None
        for row in self.data.get(DATA_SYSTEM_EVENTS) or []:
            if row.get(SYS_KIND) in (
                SYS_MAINTENANCE_OPEN,
                SYS_MAINTENANCE_CLOSED,
            ):
                newest = row.get(SYS_KIND)
        if newest != SYS_MAINTENANCE_OPEN:
            return
        self._record_system_event(
            SYS_MAINTENANCE_CLOSED,
            detail="ended by restart",
            when=restart_at,
        )
        LOGGER.info(
            "A maintenance window was open at the last stop; its "
            "closing row is recorded at this restart"
        )

    def _recovered_during_maintenance(self, now: float) -> bool:
        """Return whether a maintenance window is open at this moment.

        Fleet-wide by design (ruling #238): the button is global, and the
        cost of the width is one discarded learning sample for a
        genuine self-recovery that lands inside the person's ten
        minutes, the same conservative trade pairing already makes.
        No grace tail, unlike pairing: the window's end is declared
        rather than observed late, so it is exact.
        """
        self._expire_maintenance(now)
        return self._maintenance_until is not None


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
