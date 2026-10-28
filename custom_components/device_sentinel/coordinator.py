# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: coordinator.py, Version: 0.27.10 (2026-10-27)

"""Coordinator for the Device Sentinel integration.

The class itself, and the parts nothing else can be split away from:
setup and shutdown, the registry view of what is watched, the event
bus handlers that record activity, the schedulers, and the entity
properties the sensors read.

Everything with a subject of its own lives beside this file and is
mixed in, split by measuring which methods call which rather than by
taste (rule CODE-11): detect_signal, detect_battery and detect_freeze
for the three detectors, problem_list for the single memory every
channel renders, store for the files and the merge, interventions for
the upstreams and a person's hand, and the reports, narrative,
messenger, notifier, journal, events, flapping, router_ties, wifi,
study, model_groups and dashboard modules among others.

A file split rather than a boundary. Every one of those modules is a
mixin reading this class's state freely, so a method moves between
them without changing how it runs, and none of them can be
instantiated or tested alone.

Core rules carried out here:
- A device with nothing to watch, a service device among them, is
  set aside: never judged or reported, and named in a startup audit
  log. It keeps what it had learned, so being watched again costs
  nothing (rule WATCH-03).
- The completed-gap principle: learning ingests only finished gaps
  (rule FRZ-12).
- The startup grace and the storm detector count the bursts a
  restart or a reconnect produces. Neither mutes anything from
  learning, because an echo carries no evidence that the device
  spoke. A restart's republished values are not reports, so a
  restart does not end a silence (rules FRZ-11, UP-06).
- The taint rule: a gap that spans an unavailable stretch is an
  outage, not normal silence, and never feeds statistics (rule
  FRZ-14).
- Daily maxima roll at local midnight into a bounded per-device set.
"""

from __future__ import annotations

import asyncio
import copy
import math
import threading
import time
from collections import Counter, deque
from datetime import date, timedelta
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_CALL_SERVICE,
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_REPORTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import trim
from .normalise import (
    damaged_rows,
    fill_missing_row_fields,
    check_clocks,
    check_containers,
    check_records,
    drop_damaged_held_values,
    fault_id,
    repair_containers,
    repair_tables,
)
from .repairs import (
    _english_list,
    async_clear_home_assistant_corruption,
    async_evaluate,
    async_raise_restored,
)
from .backup import (
    async_copy_evidence,
    async_last_good_taken,
    async_prune_backups,
    async_take_backup,
    async_delete_clocks_last_good,
    read_last_good_raw,
    read_main_file_raw,
    async_restore_main_file,
    describe_restore_loss,
    async_diagnose_empty_load,
    async_copy_corrupt_evidence,
    _last_good_holds_devices,
)
from .rhythm_rules import lognormal_days, slowed_down
from .daily_dates import (
    FAMILY_BATTERY,
    FAMILY_BATTERY_PREVIOUS,
    FAMILY_GAP,
    FAMILY_SIGNAL,
    day_appended,
    entry_removed,
    trimmed_to,
    FAMILY_SIGNAL_ALT,
)
from .device_actions import DeviceActionsMixin
from .power_source import PowerMixin
from .device_type import TypeMixin
from .answers_store import AnswersMixin
from .device_recommendations import DeviceRecommendationsMixin
from .battery_evidence import BatteryEvidenceMixin
from .battery_forecasts import BatteryForecastMixin
from .battery_replacement import BatteryReplacementMixin
from .history_file import fold_line
from .store import _version_tuple as _store_version_tuple
from .const import (
    CONF_EXCLUDED_INTEGRATIONS,
    ACTIVE_REPORT_SECONDS,
    SET_ASIDE_NOTICES_ONLY,
    NOTICE_DOMAINS,
    EVENT_RESTING,
    DATA_HISTORY_LINE,
    CLIP_MAX_DAYS,
    DEV_LOGNORMAL_DAYS,
    RULE_TRIMMED,
    SLOWDOWN_DAYS,
    DAILY_SERIES_FIELDS,
    COMMANDED_RECOVERY_SECONDS,
    FETCHING_INTEGRATIONS,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    DEFAULT_RETENTION_DAYS,
    CONF_RETENTION_DAYS,
    CLOCK_RESET_THRESHOLD_SECONDS,
    REPAIR_MOMENT_BRIEF,
    REPAIR_MOMENT_GRACE,
    SYS_STORAGE_SHAPE,
    SYS_STORAGE_REPAIR,
    AREA_BATTERY,
    AREA_FREEZE,
    AREA_SIGNAL,
    BACKUP_SUFFIX_PREPHASE_C,
    BACKUP_TAKEN_KEY,
    BATTERY_ARMING_DAYS,
    BRIEF_TRIGGER,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_MAINTENANCE_MINUTES,
    CONF_SIGNAL_MUTED_DEVICES,
    DAILY_MAX_KEEP,
    DATA_BRIDGE_SEEN,
    DATA_ROUTERS_SEEN,
    DATA_ASIDE_SEEN,
    DATA_WIFI_MEDIUM,
    DATA_WIFI_MEDIUM_REJECTED,
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
    DATA_SAVED_AT,
    DATA_SIGNAL_DAY_REPAIR,
    DATA_SIGNAL_WEIGHTING,
    DATA_BRIEF_CLOSED_DAY,
    DATA_LAST_VERSION,
    CONF_TRIM_DEVICES,
    CONF_TRIM_INTEGRATIONS,
    DATA_STATS_EPOCH,
    DATA_STORM_DAYS,
    DATA_STORMS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    EPISODE_SHARE_PCT,
    DEFAULT_MAINTENANCE_MINUTES,
    TAINT_FLOOR_MINUTES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_DOWN_BEGAN_AS,
    DEV_HELD_VALUES,
    HELD_VALUE_LENGTH,
    UNHELD_DEVICE_CLASSES,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_DOWN_SINCE,
    NODE_DEAD_STATE,
    DEV_WATCHED_FROM,
    DEV_REMOVED_NAME,
    DEV_BATTERY_VALUE,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_LOW,
    DEV_FLAP_BACK,
    DEV_FLAP_SINCE,
    DEV_FLAP_DROPS,
    DEV_REMOVED_SINCE,
    REMOVED_HOLD_DAYS,
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
    FREEZE_CATEGORY_PRIORITY,
    INC_CAUSE,
    LEARNED_DISABLED,
    LEARNED_COMMANDED,
    LEARNED_MAINTENANCE,
    LEARNED_HANDLED,
    LEARNED_DOWNTIME_OUT,
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
    SET_ASIDE_COPY,
    SET_ASIDE_DUPLICATE_COORDINATOR,
    SET_ASIDE_EXCLUDED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
    SIGNAL_ARMING_DAYS,
    SIGNAL_DAY_REPAIR_MARK,
    SIGNAL_DAYS_KEEP,
    SIGNAL_LQI_HIGHEST,
    SIGNAL_RSSI_LOWEST,
    SIGNAL_WEIGHTING_MARK,
    STARTUP_GRACE_SECONDS,
    FREEZE_UNAVAILABLE_DEBOUNCE,
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
    SYS_CLOCK_RESET,
    SYS_RESTART,
    SYS_TRIMMED,
    SYS_UNCLEAN_RESTART,
    SYS_CLOCKS_LOST,
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TODO_ACKED_AT,
    TODO_DEVICE_ID,
    TODO_KINDS,
    REGISTRY_REBUILD_COOLDOWN_SECONDS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_DAILY_DATES,
    PAIRING_GRACE_SECONDS_DEFAULT,
)
from .detect_battery import BatteryMixin, mark_raw_battery, raw_battery_history
from .flapping import FlapMixin
from .model_groups import ModelGroupMixin
from .detect_freeze import FreezeMixin
from .detect_signal import SignalMixin
from .device_fields import child_devices, device_field
from .events import EventMixin
from .hubs import HUB_BUTTON_EVENTS, HUB_READERS, HubMixin
from .interventions import InterventionMixin
from .hardware_copies import choose_copies, find_groups, rank_of
from .naming import display_name
from .router_ties import RouterTiesMixin
from .study import StudyMixin
from .wifi import WifiScanMixin
from .dashboard import (
    BriefViewMixin,
    DashboardMixin,
    DeviceViewMixin,
    IntegrationViewMixin,
    TrendsViewMixin,
)
from .journal import JournalMixin
from .messenger import MessengerMixin
from .narrative import NarrativeMixin
from .notifier import NotifierMixin
from .problem_list import ProblemListMixin
from .records import (
    BAD_STATES,
    _new_device_record,
    _reset_signal_day,
    _shift,
    forget_signal_history,
)
from .reports import ReportWritingMixin
from .stacks import detect as detect_stack
from .stacks import device_key, is_plumbing, radio_owner
from .stacks import is_node_status, node_dead, node_heard, node_up
from .stacks import reader_for_domain
from .stacks import last_heard as stack_last_heard
from .store import StorageMixin, _watched_seconds


def _plain(name: object, limit: int = 120) -> str:
    """A name fit for one log line: control characters as spaces, cut
    to a readable length, because a device may name itself (rule
    GEN-10)."""
    text = "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(name))
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"



# Entities that read unknown until first used: an event entity until
# its next event after every restart, a button until it is first
# pressed. At rest they hold, as a kept value does, and say nothing
# about the device (rule UNAV-04). A command button is never the
# device at all (NOTICE_DOMAINS), so the entities that decide skip it
# first (rule WATCH-04).
RESTING_DOMAINS = frozenset({"event", "button"})


def _resting(entity_id: str, state: str) -> bool:
    """Whether an entity reads unknown only because it is at rest."""
    return state == STATE_UNKNOWN and entity_id.split(".", 1)[0] in RESTING_DOMAINS


def _forget_hold_verdicts(record: dict[str, Any]) -> None:
    """What a removed device's held record must not carry back: a flap
    in progress and a low battery verdict with the level it was read
    from. Each is formed again from what the device says when it
    returns. Its histories stay (rule WATCH-07)."""
    fresh = _new_device_record("", None)
    for field in (
        DEV_FLAP_DROPS, DEV_FLAP_SINCE, DEV_FLAP_BACK,
        DEV_BATTERY_LOW, DEV_BATTERY_SINCE, DEV_BATTERY_VALUE,
    ):
        record[field] = fresh[field]


class DeviceSentinelCoordinator(
    HubMixin,
    DeviceActionsMixin,
    PowerMixin,
    TypeMixin,
    AnswersMixin,
    DeviceRecommendationsMixin,
    BatteryReplacementMixin,
    BatteryForecastMixin,
    BatteryEvidenceMixin,
    EventMixin,
    ReportWritingMixin,
    NarrativeMixin,
    JournalMixin,
    MessengerMixin,
    NotifierMixin,
    SignalMixin,
    BatteryMixin,
    FreezeMixin,
    FlapMixin,
    ModelGroupMixin,
    ProblemListMixin,
    StorageMixin,
    InterventionMixin,
    RouterTiesMixin,
    WifiScanMixin,
    StudyMixin,
    DashboardMixin,
    IntegrationViewMixin,
    DeviceViewMixin,
    BriefViewMixin,
    TrendsViewMixin,
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
        # The hot half of the storage split (rule STOR-01). A routine save
        # writes this file alone; the store above is written when
        # something changes that a restart must not lose, and on
        # every clean stop. The load merges the two, taking the
        # clocks from here when this file's stamp proves it newer.
        self._clock_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_CLOCKS_VERSION, STORAGE_CLOCKS_KEY
        )
        # The history file: the digest of the older part last written
        # or joined, the generation the main file pairs with, the
        # highest generation seen on disk, and what the load found,
        # for the diagnostics (rule STOR-03).
        self._history_digest: str | None = None
        self._history_generation: int | None = None
        self._history_generation_high = 0
        self._history_state: dict[str, Any] = {}
        self._history_writes = 0
        self._history_body: dict[str, Any] = {}
        # What powers each device: the owner's entries, in a store of
        # their own, and the shipped Battery Notes library (rule DEV-06).
        self._power_entries: dict[str, dict[str, Any]] = {}
        # Entries that cover a whole model, keyed by model (rule DEV-06).
        self._power_models: dict[str, dict[str, Any]] = {}
        # Set as the stop begins. A minute check is a
        # background task that cancelling its timer does not stop; one
        # already running finishes after the stop, and must not write.
        self._stopped = False
        # One save at a time, so the stop's final save is the last.
        self._save_lock = asyncio.Lock()
        self.data: dict[str, Any] = {}
        self.storage_healthy: bool = False
        self._dirty: bool = False
        # Two-tier persistence, so storage is not rewritten on every
        # tick. _dirty alone is routine churn (activity clocks) and
        # coalesces into a delayed save; _critical marks a change a
        # reboot must not lose (a verdict, a battery flip, a
        # problem-list change) and forces an immediate save.
        # Acknowledgments and options changes keep their own direct
        # awaited saves and never wait for a tick (rule STOR-02).
        self._critical: bool = False
        # Cold data (episodes, incidents, system events, registry
        # changes) waiting for the next interval write to carry the
        # main file (rule STOR-02). Set by _mark_cold_dirty, cleared inside
        # _data_to_save so every main-file write satisfies it, and
        # read only by the render tick's scheduler.
        self._cold_dirty: bool = False
        # The one routine-save deadline, on the loop's monotonic
        # clock (rule STOR-02). Zero means no window has started, so the
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
        # Each watched device's own entities, from the same rebuild, so
        # reading one device's states does not walk every entity in
        # the house (rule GEN-05).
        self._own_entities: dict[str, list[str]] = {}
        # Each device's main entities, the ones Home Assistant puts in no
        # category: they decide whether the device is down (rule
        # UNAV-01).
        self._main_entities: dict[str, set[str]] = {}
        # Devices whose verdict a mute took away while they were still
        # down, so their item leaves silently; cleared when the device
        # reports or is judged down again (rule MUTE-07).
        self._muted_down: set[str] = set()
        # Outages an unavailable mute hid after they had lasted past
        # the debounce, by device, keyed to the saved outage start
        # (rules UNAV-02, UNAV-04).
        self._unavailable_under_mute: dict[str, float] = {}
        # Options a device-page mute just wrote: the update listener
        # leaves them out of its "Settings changed" row, since the act
        # records its own (rule BRIEF-07).
        self._page_option_keys: set[str] = set()
        # The day a fold is folding, and the one a catch-up fold sets
        # for it: the daily histories' new entries take it (rule
        # STOR-17).
        self._folding_day: date | None = None
        self._fold_day_override: date | None = None
        # Rebuilds the registry view at most once per cooldown during a
        # burst of registry changes; made in setup (rule WATCH-11).
        self._registry_debouncer: Debouncer[None] | None = None
        # Every watched device that owns at least one registered
        # entity, disabled or not. A device with none has nothing
        # that could report (rule WATCH-03).
        self._devices_with_entities: set[str] = set()
        # Devices with an entity of their own switched on that is not a
        # firmware notice or a command button (rule WATCH-04).
        self._devices_enabled_real: set[str] = set()
        self._foreign_entities: set[str] = set()
        self._foreign_by_device: dict[str, Counter[str]] = {}
        self._foreign_ids: dict[str, dict[str, list[str]]] = {}
        self._no_hardware_integrations: set[str] = set()
        # The one notice the repair raises: what was repaired and where
        # the originals are. None when nothing this session repaired
        # anything; self-clears on a clean load (rule STOR-09).
        self._repair_notice: dict[str, str] | None = None
        # The container check's own notice, kept apart because the two
        # checks answer different questions (rules STOR-05, STOR-12).
        self._container_notice: dict[str, str] | None = None
        # Whether the live file on disk was last written clean, so
        # the next clean save may rotate it to last-good (rule STOR-04).
        self._rotation_armed: bool = False
        # Devices whose registry entry could not be read, warned of once
        # per start so the log is not flooded.
        self._odd_devices: set[str] = set()
        self._watched: dict[str, str] = {}  # device_id -> integration domain
        # Which coordinator stacks this house runs, derived from the
        # registry rather than asked (rule STACK-01).
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
        # Label id to its name, read on the registry walk so the
        # Classification rows can name a label without the report
        # writer, which runs off the loop, opening a registry.
        self._label_names: dict[str, str] = {}
        # Muting suppresses judgment, not observation: these sets
        # gate reporting only. Clocks, statistics, and vouching keep
        # running for everything in them, so undo is instant and the
        # rhythm history carries no holes.
        self._muted_devices: dict[str, str] = {}  # device_id -> reason
        # id -> (name, domain, reason). The reason is one of the
        # SET_ASIDE_* constants, because a service device and one
        # Home Assistant disabled are set aside for different reasons
        # (rule WATCH-03).
        self._set_aside: dict[str, tuple[str, str, str]] = {}
        # One piece of hardware, several devices: each copy set aside,
        # mapped to the copy kept watched, and every group found (rule
        # WATCH-06).
        self._copy_of: dict[str, str] = {}
        self._hardware_groups: list[set[str]] = []
        self._via_parents: set[str] = set()
        self._bluetooth_parents: set[str] = set()
        self._last_seen_entity: dict[str, str] = {}  # device_id -> entity_id
        # Each watched device's node status sensor, where its stack
        # keeps one, and the set of the entity ids that are the stack's
        # word on a node: those sensors and the Hue bridge's Zigbee
        # connectivity sensors (rules STACK-05, WATCH-04).
        self._node_status_entity: dict[str, str] = {}
        self._node_status_ids: set[str] = set()
        # Devices whose stack last called their node dead, held while
        # the status cannot be read (a reload, a restart), so cached
        # values coming back first are not taken for the device
        # (rule STACK-05).
        self._dead_nodes: set[str] = set()
        # Each ESPHome device's connection as last seen by the sweep, so
        # a reconnect is noticed as the device speaking (rule STACK-07).
        self._esphome_was_connected: dict[str, bool] = {}
        # When each device last spoke in this run, because a device
        # actively reporting is not unavailable (rule UNAV-01).
        self._reported_at: dict[str, float] = {}
        self._device_entries: dict[str, set[str]] = {}
        self._signal_entities: set[str] = set()
        self._signal_devices: set[str] = set()
        # device_id -> (entity_id, is_binary). Election prefers the
        # percentage entity; the binary low flag is the fallback.
        self._battery_entity: dict[str, tuple[str, bool]] = {}
        # Whether each elected reading came from the device's own
        # integration (rule WATCH-02).
        self._battery_own: dict[str, bool] = {}
        self._last_seen_own: dict[str, bool] = {}
        self._signal_own_entities: set[str] = set()
        # entity_id -> device_id, the reverse index the intake uses.
        self._battery_entity_reverse: dict[str, str] = {}
        self._taint_consumed_at: dict[str, float] = {}
        # The unavailable duration that set each device's live
        # taint, held until the recovery stamp writes it onto the
        # episode (rule FRZ-14). Transient, not persisted on the record.
        self._taint_duration: dict[str, float] = {}
        self.deviceless_count: int = 0

        self._grace_until: float = 0.0
        self._grace_stamps: int = 0
        self._grace_devices: set[str] = set()
        self._grace_taints: set[str] = set()
        # Family events collected during a sync, fired after it settles
        # (rule NOTE-03). Each is (family, event_line, recovery). Cleared on
        # every dispatch so a later sync starts clean.
        self._pending_events: list[tuple[str, str, bool]] = []
        # The maintenance window (rule FRZ-18): epoch seconds
        # of the declared end while a window is open, else None, and
        # when it was opened for the closing row's duration. In memory
        # only: a window does not survive a restart, and building
        # storage for a ten-minute declaration would be storage
        # without a reader.
        self._maintenance_until: float | None = None
        self._maintenance_opened_at: float | None = None
        # The saved-at stamp the file carried at load (rule STOR-17).
        self._loaded_saved_at: float | None = None
        # Whether the statistics epoch wiped every rhythm at this
        # load, which suppresses the missed-day fold (rule STOR-17).
        self._epoch_wiped: bool = False
        self._storm_feed_q: dict[str, deque[tuple[float, str]]] = {}
        self._storm_feed_counts: dict[str, dict[str, int]] = {}
        self._storm_active: dict[str, dict[str, Any]] = {}
        # The day's closed storms per domain, memory only, folded
        # into DATA_STORM_DAYS at midnight (rule UP-17).
        self._storm_day: dict[str, list[tuple[float, int, float]]] = {}
        # The clocks file as loaded, for the shape check (rule
        # STOR-05). Set at load, read once, cleared.
        self._clocks_seen: dict[str, Any] | None = None
        # Which integrations have been announced as pollers this
        # session. Log-only, so losing it at a restart costs one
        # repeated debug line (rule UP-17).
        self._storm_announced: set[str] = set()
        # The polling exemption is read from the stored storm series,
        # not held here, so a synchronized poller is still spotted
        # across a restart (rule UP-17).

        self._listeners: list[Any] = []
        self._unsubs: list[Any] = []
        # Faults waiting out their notification debounce, keyed
        # by (device_id, kind). A hold is cancelled by its own
        # recovery, so anything still here is still true.
        self._held_events: dict[tuple[str, str], Any] = {}
        # Items whose last problem cleared, kept on the list for a
        # minute before they leave (rule LIST-06): when it cleared, and
        # the timer that comes back to retire them.
        self._parked: dict[str, float] = {}
        # Set at load; see store.default_exclusions (rule MUTE-02).
        self._pin_before_0277 = False
        # Faults whose debounce ended while their device waited its
        # minute, kept until the minute decides.
        self._matured_in_park: dict[tuple[str, str], tuple[str, str]] = {}
        self._park_timer: Callable[[], None] | None = None
        # What the system could actually watch (rule FRZ-10). Both storage
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
        # broker and a bridge reader cannot see it fail (rule UP-02).
        self._broker_reader: Any | None = None
        # The persistent card's last message, so an unchanged one is
        # not written again. Memory only: every setup writes once.
        self._card_written: str | None = None
        # The dashboard's change marker and whoever is subscribed to it.
        self._change_marker = 0
        self._change_listeners: list[Any] = []
        self._brief_unsub: Any | None = None
        # Report writes take turns. Each report is saved through a
        # temporary file of a fixed name, so two writes at once would
        # share it and one report would be lost.
        self._report_lock = asyncio.Lock()
        # One bridge reader per detected stack that has one, Zigbee2MQTT
        # and ZHA; Z-Wave and Matter have none (rule STACK-03). Filled
        # in at setup, once the registry view has found the stacks.
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
        # (rule UP-05).
        self._broker_down_at: float | None = None
        # The upstream outages already announced, and the moment each
        # was first seen, so the first push sounds and later ones do
        # not (rule UP-09).
        self._upstream_announced: dict[str, float] = {}
        # The bus pair, kept apart from the push map above because
        # they answer different questions: that one is whether a
        # person has been pushed at, this one is whether the bus was
        # told. Held is what the startup grace swallowed and owes an
        # announcement; said is what has been announced and is
        # therefore owed a recovery (rule UP-10).
        # Keyed by the outage, which for an integration is its config
        # entry: several plugs of one integration can each be down at
        # once, and each is owed its own recovery.
        # Held carries the name the bus is told last.
        self._upstream_held: dict[
            str, tuple[str, str | None, float, int | None, str]
        ] = {}
        self._upstream_said: dict[
            str, tuple[str, str | None, float, int | None]
        ] = {}
        # Which config entry owns each device, rebuilt on every
        # registry walk, and when each entry was first seen in any
        # state other than loaded. An integration is called down only
        # once that has outlived the dwell.
        self._entry_of_device: dict[str, str] = {}
        # The moment of the last command to each device's entities,
        # read from the bus, in memory only (rule FRZ-19).
        self._commanded_at: dict[str, float] = {}
        # When each device's latest closed silence began (rule UNAV-07).
        self._silence_began: dict[str, float] = {}
        # Whether each device's latest report came while it was judged
        # down (rule UNAV-07).
        self._report_ends_down: dict[str, tuple[str, Any] | None] = {}
        # Entities just renamed, whose first state under the new id is
        # Home Assistant moving the old one across, not the device
        # (rule UNAV-04).
        self._renamed_entities: set[str] = set()
        # The values a device's own entities last held (rule WATCH-12):
        # each voting entity's registry id against its entity id, the
        # last good value of each (by registry id), heard from both
        # state handlers and read from the state machine at setup, and,
        # per device, the registry ids on watch after a restart, a
        # reload or an entity added again. Own entities that never vote
        # (timestamp and duration sensors) are kept apart, so they
        # cannot speak for a device on watch either.
        self._held_keys: dict[str, str] = {}
        self._unheld_own: set[str] = set()
        self._last_good: dict[str, str] = {}
        self._on_watch: dict[str, set[str]] = {}
        # The devices set aside at the last registry rebuild, so a
        # return and a new stretch are each seen once, as they happen
        # (rule WATCH-08). None before the first rebuild, which reads
        # the saved set; a file from a release that kept none dates no
        # return.
        self._aside_seen: set[str] | None = None
        # The ESPHome entries whose deep-sleep flag could not be read,
        # warned of once, in memory only (rule STACK-08).
        self._deep_sleep_unreadable: set[str] = set()
        # Which devices are hubs, which they control, and whether each
        # hub's connection is up (rules STACK-09, STACK-10).
        self._init_hubs()
        self._entry_down_at: dict[str, float] = {}
        self._integration_told: set[str] = set()
        # Entry outages by entry: each one's detail, the one
        # device an entry carries, and whether the open outages in the
        # events log have been taken back this run.
        self._integration_detail: dict[str, str] = {}
        # How many watched devices each failed entry carried when it was
        # announced, so its recovery says the same (rule UP-10).
        self._integration_behind: dict[str, int] = {}
        # Each announced entry's integration, so an entry deleted while
        # down can still be closed under its name.
        self._integration_domain: dict[str, str] = {}
        # Outages announced before this run, whose recovery is owed even
        # inside the startup grace (rule NOTE-12).
        self._upstream_owed: set[str] = set()
        # Recoveries from inside the startup grace, fired when it closes
        # (rule WATCH-10).
        self._held_recoveries: list[dict[str, Any]] = []
        self._entry_only_device: dict[str, str] = {}
        self._integration_resumed = False
        self._entry_seen_loaded: set[str] = set()
        # The Wi-Fi outage. Ties resolve at registry rebuild.
        # An outage open across a restart is resumed once a run, from
        # when it went down (rule UP-04).
        self._wifi_resumed = False
        self._wifi_resume_seed = False
        # A resumed outage listens to its stored fallen trackers by
        # entity id, apart from the ties (rule UP-16).
        self._wifi_fallen_unsub: Any = None
        # When each fallen tracker was first found without a usable
        # state, and when the tie retry stops (rule UP-16).
        self._wifi_fallen_unusable_since: dict[str, float] = {}
        self._wifi_retry_until: float | None = None
        self._wifi_ties: dict[str, str] = {}
        # A wireless adapter nothing is watching with, read before
        # each report write for the brief's recommendations.
        self._wifi_adapter_unused: str | None = None
        self._wifi_device_of: dict[str, str] = {}
        self._wifi_not_home: dict[str, float] = {}
        self._wifi_burst: list[float] = []
        self._wifi_hold_since: float | None = None
        self._wifi_first_fall: float | None = None
        # The recovery state (rule UP-16). The
        # fallen set is the trackers that went away during this
        # outage, so anything already away when it began is absent
        # and never votes against recovery. A member that returns
        # joins _wifi_returned and stays there: coming home ends the
        # outage for that device, and leaving again later is a new
        # event rather than the old one continuing.
        self._wifi_fallen: dict[str, float] = {}
        self._wifi_returned: set[str] = set()
        self._wifi_announced = False
        self._wifi_peak_back = 0
        self._wifi_quiet_ticks = 0
        self._wifi_settle_losses = 0
        # When the recovery began: the network was heard again, or a
        # share of the fallen set returned (rule UP-16). Separate
        # from the close, because a person watching the problem list
        # should be told the network is back while the settle is
        # still holding its casualties off the list.
        self._wifi_recovering_at: float | None = None
        # device_id -> (outage start, when it was handed back), for
        # devices still down when an outage closed (rule UP-08).
        self._wifi_handback: dict[str, tuple[float, float]] = {}
        # The phase each upstream was last announced in: "down",
        # "recovering", or absent once it is over (rule UP-09).
        self._upstream_phase: dict[str, str] = {}
        # stack -> (outage start, when the bridge came back), and the
        # recovery being watched behind it (rule UP-08).
        self._bridge_handback: dict[str, tuple[float, float]] = {}
        self._bridge_recovering_at: dict[str, float] = {}
        self._bridge_fell: dict[str, int] = {}
        # The same three for an integration that came back: the window
        # is held per config entry, the recovery per domain, which is
        # the name its row carries (rule UP-08).
        self._integration_handback: dict[str, tuple[float, float]] = {}
        self._integration_recovering_at: dict[str, float] = {}
        self._integration_fell: dict[str, int] = {}
        # The most devices each standing outage has had down at once,
        # by the name its problem list row carries (rule UP-11).
        self._upstream_peak: dict[str, int] = {}
        # Upstreams whose standing outage is dated from the start of
        # this run, because they never loaded in it. Nothing in the
        # run happened before such an outage (rule UP-04).
        self._upstream_from_start: set[str] = set()
        # Seconds from this run's start to each upstream's first load
        # for the diagnostics download (rule UP-04).
        self.upstreams_loaded_after: dict[str, float] = {}
        # Which device each name in the brief belongs to, kept while
        # one brief is composed so its page can link them (rule BRIEF-13).
        self._brief_devices: dict[str, list[str | None]] = {}
        self._brief_cursor: dict[str, int] = {}
        # Devices a radio stack owns (rule UP-15), rebuilt with the
        # registry view. Empty until the first rebuild, which is the
        # same moment `_watched` is populated.
        self._radio_owned: set[str] = set()
        self._wifi_down_at: float | None = None
        # When the outage was first dated, before any device that
        # noticed earlier moved it back (rule UP-15).
        self._wifi_declared_from: float | None = None
        self._wifi_unsub = None
        self._wifi_retry_pending = False
        self._wifi_medium_census: dict[str, int] = {}
        self._wifi_wired_skipped: list[str] = []
        # The last_updated stamp last counted per tracker, so a
        # reading is scored once per state update rather than once
        # per look at the state.
        self._wifi_medium_stamp: dict[str, float] = {}
        # WiFi detection from the host's own radio (rule UP-12).
        # Absent until a network is chosen and an adapter is found.
        self._wifi_scan_interface: str | None = None
        self._wifi_scan_gone_at: float | None = None
        self._wifi_scan_down_at: float | None = None
        self._wifi_heard: set[str] = set()
        # Volunteered hardware study (rule STACK-11). Empty unless a toggle is
        # on, and dropped at the fold when one goes off.
        self._study_shapes: dict[str, dict[str, dict]] = {}
        # What each studied stack's nodes last said, so a line is
        # written when that changes (rule STACK-12).
        self._probe_last: dict[tuple[str, str], tuple[str, str]] = {}
        # When each node was first seen in its state, each Hue light's
        # last on or off, and each bridge's or cloud's recent state
        # changes. Rebuilt each minute from what was read.
        self._probe_since: dict[tuple[str, str], tuple[str, float]] = {}
        self._probe_light: dict[tuple[str, str], bool] = {}
        self._probe_changes: dict[tuple[str, str], deque[float]] = {}
        # Probe lines rendered and waiting for the next flush, and the
        # lock that keeps two flushes from rolling the file at once
        # (rule STACK-12).
        self._probe_pending: list[str] = []
        # The last lines this session wrote, for the diagnostics and
        # for a test to read without waiting on the file.
        self._probe_recent: deque[str] = deque(maxlen=500)
        # Each stack and kind of error the probe has already warned of
        # this start, and whether the file has refused a write.
        self._probe_failed: set[str] = set()
        self._probe_write_failed = False
        self._probe_lock = threading.Lock()
        self._init_rule_counts()
        # Whether Device Sentinel's Wi-Fi outage was open at the last
        # probe tick; None until the first tick (rule STACK-12).
        self._probe_wifi_down: bool | None = None
        # Z-Wave node event subscriptions, each controller's counters
        # at the last fold, and the Thread border routers (rule STACK-12).
        self._zwave_listeners: dict[tuple[int, str], list[Any]] = {}
        self._zwave_counters: dict[str, dict[str, int]] = {}
        self._thread_discovery: Any = None
        self._thread_starting = False
        self._thread_failed = False
        self._thread_routers: dict[str, tuple[str, str, str]] = {}
        self._meshcop_names: dict[str, str] = {}
        # Firmware versions seen but not yet held ten minutes, by
        # device, with the time each first appeared. Memory only, so
        # a restart forgets a version that never held (rule DEV-15).
        self._firmware_candidates: dict[str, tuple[str, float]] = {}
        self._firmware_unflickered = False
        self._study_capped: dict[str, bool] = {}
        self._study_unsub = None
        self._study_watching: dict[str, str] = {}
        self._pairing_open_at: dict[str, float] = {}
        self._pending_epoch_wipe: int | None = None
        # The first is how many devices this boot reset after an
        # unclean stop, held until setup succeeds so the system event
        # is written beside the restart it explains (rule FRZ-20). The
        # rest is what the integrity count found, kept for the
        # diagnostics rather than acted on (rule STOR-18).
        self._pending_unclean = None
        # When this start restarted the clocks of a lost clocks file,
        # and how many, for the brief's row written at setup (rule
        # LIST-12).
        self._clocks_reset_at: float | None = None
        self._clocks_reset_count = 0
        # The last minute check's wall clock and a clock nobody can
        # set, and the reset the two last disagreed on (rule FRZ-21).
        self._tick_wall: float | None = None
        self._tick_mono: float | None = None
        self._clock_reset: tuple[float, float] | None = None
        # The last clock step, as (the last minute check before it, in
        # the old clock; the moment it was noticed, in the new one).
        # Time across a step is unknown, so a moment from before it
        # counts from the step (rule FRZ-21).
        self._clock_step: tuple[float, float] | None = None
        self._orphan_episodes: dict[str, Any] = {}
        self._options_seen: dict[str, Any] = dict(entry.options)
        # What the last shape check found, held for the Repairs pass
        # because the load check runs inside the grace and the issue
        # is raised when the grace closes (rule REP-07).
        # The latch: set when a load verifies faulty or a fold
        # produces a fault, cleared only by a restart that loads
        # clean, which is a new coordinator (rule STOR-12).
        self._load_faulty: bool = False
        # The faults a discarded clocks file carried (rule STOR-10), kept for
        # the load report; they never reach the card.
        self._clocks_discarded: list[tuple[str, str, str]] = []
        # The join observers (rule FRZ-17). A stack that can
        # say when a person handled a device reports it here, and
        # the recovery that follows is attributed rather than
        # learned. Empty on a house whose stacks have none, and
        # stopped with the readers at shutdown.
        self._join_observers: dict[str, Any] = {}
        # Registry id -> when that device was last reported handled,
        # so the same handling's several messages make one event.
        self._handled_at: dict[str, float] = {}
        self._repairs_at_load: int = 0
        self._last_good_taken: float | None = None
        # Restore: the copy's timestamp and the evidence stamp, held
        # until grace close so the notice can be sent when the notify
        # platform actually exists (rule STOR-08).
        self._restored_from: float | None = None
        self._restore_evidence: str | None = None
        self._restore_told: str | None = None
        self._restore_told_at: float | None = None
        # Why the load came back empty: corrupt, missing, or
        # unreadable. Carried into the notice so a person is told
        # which of the three happened to them (rule STOR-08).
        self._restore_reason: str = "unreadable"
        # What the evidence copy actually wrote (rule STOR-11), so the
        # notice names files that exist rather than four by habit.
        self._restore_copied: list[str] = []
        # The names Home Assistant renamed aside, kept so its own
        # issue can be cleared after a successful restore (rule REP-08).
        self._restore_corrupt_names: list[str] = []
        # Whether this start is running a different version from the
        # one that last wrote storage. Set at load.
        self._version_changed = False

    # ------------------------------------------------------------- setup


    async def async_setup(self) -> None:
        """Load storage, build the registry view, and start listening.

        A file Home Assistant cannot parse stops setup with a sentence
        a person can act on, and stops it permanently rather than
        retrying, because a corrupt file does not repair itself
        between attempts. Before stopping, setup restores the
        last-good copy beside it and starts from that; it stops only
        where there is no copy, or the copy will not load either
        (rule STOR-08).
        """
        # What powers each device, read first so the first reports of
        # this start already carry it, then the answers owners set on
        # device pages. Neither can stop a start: each says why in the
        # log and is treated as empty (rule STOR-20).
        await self.async_load_power()
        await self.async_load_answers()
        try:
            loaded = await self._store.async_load()
        except (HomeAssistantError, ValueError) as err:
            # Restore. The alternative to replacing an unreadable file
            # is not running at all, so nobody is asked (rule STOR-08).
            # Evidence first: all four files, raw, before anything is
            # overwritten (rule STOR-11).
            stamp, copied = await async_copy_evidence(self.hass)
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
                try:
                    loaded = await self._store.async_load()
                except (HomeAssistantError, ValueError) as second:
                    # The restored file will not load either, so the
                    # fault is not the file. Without this the second
                    # failure would escape uncaught and a person would
                    # get a traceback instead of a sentence (rule
                    # STOR-08).
                    LOGGER.error(
                        "Device Sentinel restored %s from its "
                        "last-good copy and still cannot read it: "
                        "%s. Nothing further has been changed; copies "
                        "were written to %s as %s",
                        STORAGE_KEY,
                        second,
                        TRIM_BACKUP_DIR,
                        stamp or "unstamped",
                    )
                    raise ConfigEntryError(
                        f"Device Sentinel restored {STORAGE_KEY} from "
                        f"its last-good copy and still cannot read "
                        f"it. Nothing further has been changed."
                    ) from second
                self._restored_from = taken
                self._restore_evidence = stamp
                self._restore_copied = copied
                # A restored session is not a clean read: the latch
                # stands, so Status reports it, the repair issue opens,
                # and the copy this came from is never overwritten by
                # the file it produced (rules STOR-12, STOR-04).
                self._load_faulty = True
                # A restore is a repair the load made (rule STOR-12).
                self._repairs_at_load += 1
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
        if loaded is None and self._restored_from is None:
            # The trigger that matters. Corruption never reaches the
            # except block above: Home Assistant's own Store catches
            # every JSONDecodeError, renames the file to
            # `.corrupt.<isotime>`, raises its own repair issue and
            # returns None. So the common case arrives here, looking
            # exactly like a first install. Treated as one, it would
            # start empty and refresh the last-good copy from the
            # empty document, destroying the only usable history
            # (rule STOR-08).
            reason, corrupt = await async_diagnose_empty_load(self.hass)
            if reason != "fresh":
                stamp, copied = await async_copy_evidence(self.hass)
                if corrupt and stamp:
                    await async_copy_corrupt_evidence(
                        self.hass, corrupt, stamp
                    )
                restored, taken = await async_restore_main_file(self.hass)
                if restored:
                    LOGGER.warning(
                        "Device Sentinel found %s %s, so it was "
                        "replaced from the last-good copy and startup "
                        "continued. Copies of what existed were "
                        "written to %s as %s",
                        STORAGE_KEY,
                        (
                            "unreadable and renamed aside by Home "
                            "Assistant"
                            if reason == "corrupt"
                            else "missing"
                        ),
                        TRIM_BACKUP_DIR,
                        stamp or "unstamped",
                    )
                    loaded = await self._store.async_load()
                    self._restored_from = taken
                    self._restore_evidence = stamp
                    self._restore_copied = copied
                    self._restore_corrupt_names = corrupt
                    self._restore_reason = reason
                    self._load_faulty = True
                    self._repairs_at_load += 1
                else:
                    # The copy could not be used after all. Fall
                    # through to first install, which is what would
                    # have happened anyway, but never refresh the
                    # last-good copy from it (rule STOR-04).
                    LOGGER.error(
                        "Device Sentinel found %s empty and its "
                        "last-good copy could not be used. Starting "
                        "fresh. The copy has not been touched",
                        STORAGE_KEY,
                    )
                    self._load_faulty = True
                    self._repairs_at_load += 1
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
        # The two gates, with the restore retry (rules STOR-05, STOR-09).
        # Gate 1 checks the containers, the load-time steps run, gate
        # 2 checks everything, and a faulty document with a usable
        # last-good is answered by restoring the file and running
        # this section once more on the restored copy. The second
        # pass repairs in place instead, so the loop always ends with
        # a document both gates vouch for. Per-pass state resets at
        # the top so a retry never reads the first pass's verdict.
        malformed: dict[str, Any] = {}
        gate_restored = False
        for _load_attempt in (1, 2):
            self._clocks_discarded = []
            self._clocks_seen = None
            # Gate 1, before the first load-time step. Those steps walk
            # the data raw, because the full check cannot run ahead of
            # the clocks merge without faulting the fields the main
            # file does not carry. A container of the wrong kind stops
            # setup there, so the containers are made containers first
            # (rule STOR-05). The main document only: the clocks file
            # has its own guard a few lines below, which discards a
            # damaged one whole before the merge reads it (rule
            # STOR-10). Silent on a healthy file.
            container_faults = check_containers(loaded)
            if container_faults:
                # Gate 1 owes this as much as gate 2 does: damage with a
                # usable last-good is answered by restoring, not by
                # repairing. Repair here empties a `devices` map that
                # arrived as a string, losing every record, when the
                # copy one save back holds them all. The copy is checked
                # with gate 1's own check before the restore, because a
                # copy carrying the same fault is not worth restoring to
                # (rule STOR-09).
                copy_data = None
                if not gate_restored and self._restored_from is None:
                    copy_data = await self.hass.async_add_executor_job(
                        read_last_good_raw, self.hass
                    )
                    if copy_data is not None and (
                        check_containers(copy_data)
                        or not copy_data.get(DATA_DEVICES)
                    ):
                        # Same fault, or a copy holding no records at
                        # all, which is never promoted over a genuine
                        # first install (rule STOR-08).
                        copy_data = None
                if copy_data is not None:
                    stamp, copied = await async_copy_evidence(self.hass)
                    restored, taken = await async_restore_main_file(self.hass)
                    fresh = None
                    if restored:
                        fresh = await self.hass.async_add_executor_job(
                            read_main_file_raw, self.hass
                        )
                    if fresh is not None:
                        LOGGER.warning(
                            "Storage held %d container fault(s), so the "
                            "file was replaced from the last-good copy "
                            "and the load ran again on the copy. The "
                            "originals are in %s as %s",
                            len(container_faults),
                            TRIM_BACKUP_DIR,
                            stamp or "unstamped",
                        )
                        loaded = fresh
                        malformed = {}
                        self._restored_from = taken
                        self._restore_evidence = stamp
                        self._restore_copied = copied
                        self._restore_reason = "damaged"
                        self._load_faulty = True
                        self._repairs_at_load += 1
                        gate_restored = True
                        continue
                    LOGGER.warning(
                        "Storage held %d container fault(s) and the "
                        "last-good copy could not be used; repairing "
                        "in place instead",
                        len(container_faults),
                    )
                await self._repair_containers_at_load(
                    loaded, container_faults
                )
            loaded.setdefault(DATA_FIRST_INSTALLED, dt_util.utcnow().isoformat())
            loaded.setdefault(DATA_DEVICES, {})
            loaded.setdefault(DATA_TODO_ITEMS, [])
            loaded.setdefault(DATA_TODO_JOURNAL, [])
            loaded.setdefault(DATA_EPISODES, [])
            loaded.setdefault(DATA_INCIDENTS, [])
            loaded.setdefault(DATA_SYSTEM_EVENTS, [])
            loaded.setdefault(DATA_BRIDGE_SEEN, {})
            loaded.setdefault(DATA_BROKER_SEEN, {})
            loaded.setdefault(DATA_ROUTERS_SEEN, [])
            loaded.setdefault(DATA_WIFI_MEDIUM, {})
            loaded.setdefault(DATA_WIFI_MEDIUM_REJECTED, {})
            loaded.setdefault(DATA_STORMS, [])
            loaded.setdefault(DATA_STORM_DAYS, [])
            # The history file joins here, once for each document this
            # load settles on, so every load-time step and both gates
            # see the whole record (rule STOR-03). A restore below
            # replaces the document and the next pass joins its pair.
            await self._join_history_at_load(loaded)
            # Rows cross into the history file at a line set at each
            # fold; a file from before the history file has none until
            # now (rule STOR-19).
            if not isinstance(loaded.get(DATA_HISTORY_LINE), (int, float)):
                loaded[DATA_HISTORY_LINE] = fold_line()
            # The dry-run outbox is a retired key: dropped, so no save
            # carries it (rule STOR-19).
            loaded.pop("outbox", None)
            # Incidents stored with the old name for an unobserved
            # recovery take the current one, since the composer knows
            # only the current name (rule STOR-19).
            for entry in loaded.get(DATA_INCIDENTS) or []:
                if not isinstance(entry, dict):
                    # Damage, which the gate repairs after the
                    # migrations. A migration that raised on it would
                    # stop setup at the one moment nothing can yet hold
                    # it (rule STOR-09).
                    continue
                if entry.get(INC_CAUSE) == LEGACY_CAUSE_UNOBSERVED:
                    entry[INC_CAUSE] = RECOVERY_CAUSE_UNOBSERVED
            # And the same treatment for the four kinds renamed later,
            # for the same reason (rule LIST-02).
            self._rename_stored_kinds(loaded)
            # And the renamed option keys: a settings-changed row names
            # keys, and the brief resolves each to its screen label
            # (rule BRIEF-07).
            self._rename_stored_option_keys(loaded)
            # Device Sentinel owns the list. An item stored without a
            # device id was typed by hand and is removed, so the list
            # holds only what the detections write; the rest gain any
            # missing fields in place (rule LIST-01).
            engine_items = [
                record
                for record in loaded[DATA_TODO_ITEMS]
                # A row that is not a row has no device id either, so it
                # is purged by the same rule rather than raising and
                # stopping setup (rule STOR-09).
                if isinstance(record, dict) and record.get(TODO_DEVICE_ID)
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
            # The clocks file is merged before the statistics epoch,
            # because three clock fields are among what the epoch wipes:
            # merged after it, they would come straight back and the
            # wipe would not take (rule STOR-19).
            # The marker the retired one-time backup wrote. It names a
            # copy this version never takes, so it is dropped rather than
            # carried forever in every save. Any epoch markers beside it
            # stay, because the statistics epoch still uses them (rule
            # STOR-19).
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

            # A record corrupted to something that is not a dict would
            # crash the first migration loop that writes into it, so it
            # comes out before the merge: a string record raises a
            # TypeError from the clocks merge. This is gate damage: the
            # record is dropped here, the gate that follows counts it
            # into the repair, and the evidence copy preserves the
            # original (rule STOR-09).
            malformed = {
                device_id: record
                for device_id, record in (loaded.get(DATA_DEVICES) or {}).items()
                if not isinstance(record, dict)
            }
            if malformed:
                for device_id in malformed:
                    del loaded[DATA_DEVICES][device_id]
                LOGGER.warning(
                    "Storage holds %d record(s) that are not records at "
                    "all (%s). The gate repairs them",
                    len(malformed),
                    ", ".join(sorted(malformed)[:5]),
                )

            # The clocks file is the small companion, and losing it costs
            # one interval of live counters rather than the record
            # (rule STOR-10). An unreadable one is a warning and a fresh
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
            # A clocks file that holds damage is discarded whole before
            # the merge, never healed (rule STOR-10): it rebuilds itself
            # within a day, so a damaged one is treated exactly like a
            # missing one. Damage means a value of the wrong shape or a
            # record that is not a record; a missing field is not damage,
            # because that is how an upgrade adding a clock field looks
            # on its first start, and discarding the file for it would
            # restart every device's clock at each upgrade. A missing
            # field is latched and reported, never a reason to discard.
            clock_faults = check_clocks((hot_payload or {}).get("clocks"))
            # A damaged saved outage start is that one field's loss, not
            # the file's: it is cleared, and the device's next outage
            # starts afresh, because discarding the whole file for it
            # would restart every device's clock (rule STOR-10).
            for device_id, field, why in list(clock_faults):
                if field == DEV_DOWN_SINCE and why != "missing":
                    row = ((hot_payload or {}).get("clocks") or {}).get(device_id)
                    if isinstance(row, dict):
                        row[field] = None
                    clock_faults.remove((device_id, field, why))
            clock_damage = [f for f in clock_faults if f[2] != "missing"]
            if clock_damage:
                LOGGER.warning(
                    "The activity clocks file failed its shape check with "
                    "%d damaged value(s), so it is discarded and rebuilds "
                    "from this boot. First: %s: %s",
                    len(clock_damage),
                    fault_id(clock_damage[0]),
                    clock_damage[0][2],
                )
                self._clocks_discarded = clock_damage
                hot_payload = None
            # Held for the shape check, which runs a few lines later and
            # must see the file as it came off disk rather than the merge
            # of it (rule STOR-05). Cleared there.
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
                # epoch change deletes learned data with nothing to
                # rebuild it from, since readings are folded into a daily
                # figure as they arrive and never stored (rule STOR-19).
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
                        # (rule STOR-19).
                        for field, value in fresh.items():
                            if field not in EPOCH_KEPT:
                                record[field] = value
                        # The gap history was just cleared, so its dates
                        # go with it; the battery and signal histories
                        # survive the wipe with theirs (rule STOR-16).
                        blocks = record.get(DEV_DAILY_DATES)
                        if isinstance(blocks, dict):
                            blocks.pop(FAMILY_GAP, None)
                            if not blocks:
                                record[DEV_DAILY_DATES] = None
                        wiped += 1
                    loaded[DATA_STATS_EPOCH] = STATS_EPOCH
                    # A wiped house has no missed day to fold: the
                    # day's longest gap so far, which the fold would append, belongs to
                    # the rhythm this wipe just declared invalid, and
                    # appending it hands back what the wipe removed
                    # (rule STOR-17).
                    self._epoch_wiped = True
                    # The wipe destroys the series themselves, and the
                    # depth is read from the series, so the stamps an
                    # older version left behind are pruned here and
                    # nothing replaces them.
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
                # Logged only when learned data went, which is when a
                # fault report needs it (rule GEN-10).
                if wiped:
                    LOGGER.info(
                        "Statistics epoch %s: the learned rhythm reset for %d "
                        "devices so it is relearned under the final rule set; "
                        "clocks, identity, signal and battery history kept",
                        STATS_EPOCH,
                        wiped,
                    )
            # Reconcile every stored record against the schema, both
            # directions, so a field joining the schema reaches every
            # existing record as surely as a leaving one is removed
            # (rule STOR-19).
            # Two retired backup markers are dropped, so no save carries
            # them.
            loaded.pop("pre_split_backup_taken", None)
            loaded.pop("phase_b_backup_taken", None)
            # Before the reconciler, which is the last moment the legacy
            # signal accumulators exist: it removes the retired fields,
            # these among them (RETIRED_DEVICE_FIELDS, rule STOR-19).
            repair = loaded.get(DATA_SIGNAL_DAY_REPAIR) != SIGNAL_DAY_REPAIR_MARK
            converted, day_reset = self._migrate_signal_accumulators(
                loaded[DATA_DEVICES], repair
            )
            loaded[DATA_SIGNAL_DAY_REPAIR] = SIGNAL_DAY_REPAIR_MARK
            # A history holding two scales at once cannot be separated
            # after the fact, so it goes (rule SIG-03). Judged on the
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
            # The depth is read from the series, so the stamps an older
            # version wrote are dead weight. Pruned on every load rather
            # than only inside the epoch branch, which does not run on an
            # ordinary start (rule STOR-19).
            loaded.pop(DATA_SERIES_STAMPS, None)
            self._clear_reading_weighted_series(loaded)
            removed, filled = self._reconcile_records(
                loaded[DATA_DEVICES], dt_util.utcnow().isoformat()
            )
            # The reconciler reads top-level keys only, so the erased
            # signal fields (rule SIG-13) are swept from second-scale
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
                    "Signal erasure: removed %d retired "
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

            # Values a real device or a longer retention can explain,
            # brought into range before the boundary rather than
            # called damage by it: a device on Zigbee's raw battery
            # scale has its history halved, and a gap longer than this
            # house's retention is learned as the retention (rules
            # BAT-02, FRZ-13). Only then is what is left held to the
            # possible (rule STOR-07).
            raw = self._convert_raw_batteries(loaded.get(DATA_DEVICES) or {})
            if raw:
                LOGGER.info(
                    "%d device(s) report Zigbee's raw battery scale of 0 "
                    "to 200; their stored levels were halved to percent"
                    ": %s",
                    len(raw),
                    ", ".join(raw[:5]),
                )
            held = self._cap_gaps_at_retention(loaded.get(DATA_DEVICES) or {})
            if held:
                LOGGER.info(
                    "%d learned gap(s) were longer than the %d days kept "
                    "and are held at %d days",
                    held,
                    self.retention_days,
                    self.retention_days,
                )

            # The boundary (rule STOR-05), placed here on purpose:
            # after every migration, which may still repair a legacy
            # shape, and before the first reader. From this line on
            # no reader in the process meets a record or a table row
            # the check would not vouch for.
            # A damaged held value costs only its own entity's watch: it
            # is dropped here, the sound ones kept (rule WATCH-12).
            dropped_held = drop_damaged_held_values(loaded.get(DATA_DEVICES))
            if dropped_held:
                LOGGER.info(
                    "Storage load: %d damaged held value(s) dropped",
                    dropped_held,
                )
            filled = fill_missing_row_fields(loaded)
            if filled:
                LOGGER.info(
                    "Storage load: %d missing nullable field(s) "
                    "filled with None on table rows, as the record "
                    "reconciler does for devices",
                    filled,
                )
            gate_faults = check_records(loaded.get(DATA_DEVICES))
            gate_faults += [
                (table, str(index), "damaged row")
                for table, indexes in damaged_rows(loaded).items()
                for index in indexes
            ]
            for device_id in malformed:
                gate_faults.append((device_id, "*", "not a record"))
            if not gate_faults and not self._clocks_discarded:
                break
            # Evidence before anything else touches disk: the first
            # save re-serializes the file after migrations have handled
            # it, so without this copy the original of what went wrong
            # is destroyed by the process that found it. A discarded
            # clocks file is preserved by the same copy (rule STOR-11).
            stamp, copied = await async_copy_evidence(self.hass)
            if stamp:
                LOGGER.warning(
                    "Storage evidence copied to trim_backups as %s "
                    "before anything writes: %s",
                    stamp,
                    ", ".join(copied),
                )
            if self._clocks_discarded:
                self.data = loaded
                self._record_system_event(
                    SYS_STORAGE_REPAIR,
                    detail=(
                        "the activity clocks file failed its shape "
                        f"check with {len(self._clocks_discarded)} "
                        "fault(s) and was discarded. It rebuilds "
                        "itself; the day's counters start over"
                    ),
                )
                self._load_faulty = True
                # Counted once: after a restore the load runs again and
                # finds the same clocks file (rule STOR-12).
                if not gate_restored:
                    self._repairs_at_load += 1
            if not gate_faults:
                break
            self._load_faulty = True
            if (
                not gate_restored
                and self._restored_from is None
                and await self.hass.async_add_executor_job(
                    _last_good_holds_devices, self.hass
                )
            ):
                # Rule: damage at load with a usable last-good
                # restores from last-good, which under the rotation
                # is one write interval old (rule STOR-09). The store
                # object caches its first parse, so the restored file
                # is read directly.
                restored, taken = await async_restore_main_file(self.hass)
                fresh = None
                if restored:
                    fresh = await self.hass.async_add_executor_job(
                        read_main_file_raw, self.hass
                    )
                if fresh is not None:
                    LOGGER.warning(
                        "Storage loaded with %d fault(s), so the file "
                        "was replaced from the last-good copy and the "
                        "load ran again on the copy. The originals "
                        "are in %s as %s",
                        len(gate_faults),
                        TRIM_BACKUP_DIR,
                        stamp or "unstamped",
                    )
                    loaded = fresh
                    loaded.setdefault(DATA_DEVICES, {})
                    loaded.setdefault(DATA_TODO_ITEMS, [])
                    loaded.setdefault(DATA_TODO_JOURNAL, [])
                    loaded.setdefault(DATA_EPISODES, [])
                    loaded.setdefault(DATA_INCIDENTS, [])
                    loaded.setdefault(DATA_SYSTEM_EVENTS, [])
                    loaded.setdefault(DATA_BRIDGE_SEEN, {})
                    loaded.setdefault(DATA_BROKER_SEEN, {})
                    loaded.setdefault(DATA_ROUTERS_SEEN, [])
                    loaded.setdefault(DATA_WIFI_MEDIUM, {})
                    loaded.setdefault(DATA_WIFI_MEDIUM_REJECTED, {})
                    loaded.setdefault(DATA_STORMS, [])
                    loaded.setdefault(DATA_STORM_DAYS, [])
                    malformed = {}
                    self._restored_from = taken
                    self._restore_evidence = stamp
                    self._restore_copied = copied
                    self._restore_reason = "damaged"
                    self._repairs_at_load += 1
                    gate_restored = True
                    continue
                LOGGER.warning(
                    "Storage loaded with %d fault(s) and the "
                    "last-good copy could not be used; repairing in "
                    "place instead",
                    len(gate_faults),
                )
            # Rule: damage with no usable last-good is repaired in
            # place, damaged table rows dropped and a damaged record
            # field reset to its default, the rest of the record
            # kept. The clocks bank first, so a damaged activity clock
            # restarts honestly at now rather than being reset to a
            # fresh record's None (rule STOR-09).
            self.data = loaded
            await self._repair_in_place("load", gate_faults, stamp)
            break
        loaded[DATA_SETUP_COUNT] = int(loaded.get(DATA_SETUP_COUNT, 0)) + 1
        # The clean-stop marker is read and cleared in one breath
        # (rule FRZ-20), so a crash before the next clean stop is detected
        # again rather than inheriting this boot's verdict. Read after
        # the merge, because the arithmetic below needs the clocks the
        # merge restored, and after the epoch wipe, because a wipe
        # that has just emptied the statistics leaves nothing to
        # protect.
        # The on-disk stamp, captured before anything can move it: a
        # save during setup rewrites DATA_SAVED_AT to now, and the
        # missed-day fold needs the moment the file was last current
        # (rule STOR-17).
        stamp = loaded.get(DATA_SAVED_AT)
        self._loaded_saved_at = (
            float(stamp) if isinstance(stamp, (int, float)) else None
        )
        clean_stop = bool(loaded.pop(DATA_CLEAN_STOP, False))
        if not clean_stop:
            self._handle_unclean_restart(loaded)
        # Every load, not only a repair: a gap wider than the watch is
        # a finite number and passes the shape check, so the shape
        # repair never sees it (rule FRZ-13).
        capped = self._cap_gap_series(loaded.get(DATA_DEVICES) or {}, loaded)
        if capped[0]:
            LOGGER.info(
                "%d learned gap(s) on %d device(s) exceeded the time the "
                "device has been watched and were forgotten",
                capped[0], capped[1],
            )
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
        # Whether this start is an upgrade, read before the stamp moves
        # on, so the log can name the version that last wrote storage
        # (rule GEN-10).
        self._version_changed = (
            loaded.get(DATA_LAST_VERSION) != self.version
        )
        # A first start has no earlier version to name (rule GEN-10).
        if self._version_changed and (
            loaded.get(DATA_LAST_VERSION) or loaded.get(DATA_DEVICES)
        ):
            LOGGER.info(
                "Device Sentinel is running %s where storage was last "
                "written by %s",
                self.version,
                loaded.get(DATA_LAST_VERSION) or "an earlier version",
            )
        # A house last written before 0.27.7 that never saved its
        # exclusion list keeps the default it had: read here, before
        # the stamp moves on (rule MUTE-02).
        came_from = loaded.get(DATA_LAST_VERSION)
        self._pin_before_0277 = (
            isinstance(came_from, str)
            and _store_version_tuple(came_from) < (0, 27, 7)
            and CONF_EXCLUDED_INTEGRATIONS not in self.entry.options
        )
        loaded[DATA_LAST_VERSION] = self.version
        # The rotation arms only when the live file on disk is one
        # this process knows to be clean (rule STOR-04). A load that
        # restored or repaired leaves the damaged original or the
        # copy in place, so the first save writes without rotating
        # and the file it writes arms the one after.
        self._rotation_armed = (
            not self._load_faulty and self._restored_from is None
        )
        # The clocks last-good file is retired: the clocks file's
        # contents are derived and a restore deletes it rather than
        # restoring it. An install upgraded from an older release may
        # still carry one; removed here (rule STOR-19).
        await async_delete_clocks_last_good(self.hass)
        # Both files are stamped now, through the same checked save as
        # every later one (rule STOR-06), because an unstamped main file
        # beside a stamped clocks file is a pair the merge cannot
        # compare, and the clocks written before the first critical
        # save would be lost at the next restart.
        await self._save_main()
        # The clocks file is written now too, so a restart inside the
        # first write interval still finds one (rule STOR-02).
        await self._clock_store.async_save(self._clocks_to_save())
        self.storage_healthy = True
        # The stamp survives restarts by living on the file rather
        # than in memory (rule STOR-12): the age a person sees is the
        # copy's real age, not this process's.
        self._last_good_taken = await async_last_good_taken(self.hass)

        self._grace_until = (
            dt_util.utcnow().timestamp() + STARTUP_GRACE_SECONDS
        )

        self._rebuild_registry_view(audit=True)
        # Battery Last Replaced entries are stored first, so a catch-up
        # fold cannot detect a new cell over a replacement not yet
        # stored (rule BAT-07).
        self._settle_battery_entries()
        await self._fold_if_a_midnight_was_missed()
        # A router integration seen for the first time, or Music
        # Assistant or a television integration, is excluded on a new
        # install and offered on the Recommendations tab on a house that
        # already exists, once, ever. It runs after the registry view,
        # which it reads, and before the readers start, so an exclusion
        # holds for this session; and after the catch-up fold, so a
        # restart across midnight does not discard the newly excluded
        # devices' history at once (rule MUTE-02).
        await self._sight_router_integrations()

        # The recoveries held inside the last run's grace come back
        # before this run listens for reports: one held while setup
        # still waits would otherwise write the stored list with only
        # itself, and the earlier ones would be lost (rule WATCH-10).
        self._restore_held_recoveries()
        # This start is a restart or a reload: each device with held
        # values has its entities put on watch before the first state
        # is heard (rule WATCH-12).
        self._arm_held_watches()
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
        # A command to a watched device's entity, from a device card,
        # a script or an automation: a report that follows one clears a
        # freeze verdict and teaches nothing (rule FRZ-19).
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_CALL_SERVICE,
                self._on_call_service,
                event_filter=self._command_filter,
            )
        )
        # A press on a Pico, which has no entity that would say so, is
        # the Pico reporting (rule STACK-09).
        for event_type in HUB_BUTTON_EVENTS:
            self._unsubs.append(
                self.hass.bus.async_listen(
                    event_type,
                    self._on_hub_button,
                    event_filter=self._hub_button_filter,
                )
            )
        # One rebuild for a burst of registry changes, not one per
        # change: at once when none ran in the last cooldown, otherwise
        # once when it ends (rule WATCH-11). Shut down with the listeners, so
        # no rebuild runs after the entry is gone.
        self._registry_debouncer = Debouncer(
            self.hass,
            LOGGER,
            cooldown=REGISTRY_REBUILD_COOLDOWN_SECONDS,
            immediate=True,
            function=self._rebuild_and_notify,
        )
        self._unsubs.append(self._registry_debouncer.async_shutdown)
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
        # A renamed label changes what Classification says about every
        # device it mutes, and nothing in the device or entity
        # registry moves when it happens (rule MUTE-05).
        self._unsubs.append(
            self.hass.bus.async_listen(
                lr.EVENT_LABEL_REGISTRY_UPDATED, self._on_registry_updated
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
        # sync against not-yet-judged lists would read as a house-wide
        # recovery and empty the list at every start. The write
        # itself waits a few lines, until the readers are up and the
        # remembered upstream state is back (rule UP-04).

        # Start a bridge reader for each detected stack that can report
        # its own state. This is separate from the sensors that display
        # it: the reader (and later the pairing detector that consumes
        # it) runs whether or not a user ever enables the sensor, so
        # detection never depends on a display choice.
        await self._start_bridge_readers()
        await self._start_broker_reader()
        # Before the first sample, so a bridge that went down
        # and came back across this restart still closes
        # (rule UP-04).
        self._restore_bridge_state()
        # A Wi-Fi outage remembered from before the restart is back
        # before the Problem List is first written (rule UP-04).
        self._resume_wifi_outage(dt_util.utcnow().timestamp())

        # The first write of the problem list, now that a device can
        # be matched to its bridge and a remembered outage is back.
        # Written before this, it would list every device behind a
        # bridge that was already down as its own problem, one row
        # per device, replaced by the single bridge row a tick later
        # (rule UP-04).
        self._sync_problem_list()

        # A maintenance window open at the stop ended with it, since the
        # window lives in memory, but its opening row is stored, so its
        # closing row is written here, before the restart row and dated
        # at the restart. Its length is left unknown, because the host
        # may have been off for part of it (rule FRZ-18).
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
            # Every clock restarting at one moment needs its reason
            # beside it, or the reset reads as an unexplained jump
            # (rule FRZ-20).
            self._record_system_event(
                SYS_UNCLEAN_RESTART,
                detail=f"{self._pending_unclean} devices reset",
                duration=self._downtime if self._downtime > 0.0 else None,
                when=self._started_at,
            )
            self._pending_unclean = None
        if self._clocks_reset_at is not None:
            # A lost or damaged clocks file is told in the brief rather
            # than on a Repairs card, so the repair is never silent
            # (rules LIST-12, STOR-12).
            self._record_system_event(
                SYS_CLOCKS_LOST,
                detail=f"{self._clocks_reset_count} clocks restarted",
                when=self._clocks_reset_at,
            )
            self._clocks_reset_at = None
        if self._pending_epoch_wipe is not None:
            self._record_system_event(
                SYS_EPOCH_RESET,
                detail=f"{self._pending_epoch_wipe} devices",
            )
            self._pending_epoch_wipe = None
        # Answers set on device pages that were left out or restored at
        # load, read before the events log existed this session (rule
        # STOR-20).
        notes = self.answers_notes()
        # The history file that matched nothing, so the start used the
        # storage file's own days (rule STOR-12): a repair, told and
        # counted as one.
        dropped = getattr(self, "_history_drop_note", None)
        if dropped:
            self._history_drop_note = None
            self._record_system_event(SYS_STORAGE_REPAIR, detail=dropped)
            self._load_faulty = True
            self._repairs_at_load += 1
        for note in notes:
            self._record_system_event(SYS_STORAGE_REPAIR, detail=note)
        if notes:
            # A restore or repair of the answers is a repair at the
            # start too: Status reads Problem (rule STOR-12).
            self._load_faulty = True
            self._repairs_at_load += len(notes)
            # The repair is written back once, so the next start does
            # not find the same damage, copy it again and say so again.
            # Rotation is off after a repair, so the last good file
            # stays as it was; a move from the old power file in the
            # same load armed it, so it is turned off here. Every write
            # arms it again (rule STOR-20).
            self._answers_rotation_armed = False
            self._answers_save()

        LOGGER.debug(
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
        # A replacement no Battery Last Replaced entry carries yet, from
        # an older release or after a downgrade, is dated once and
        # stored (rule BAT-07).
        self._settle_battery_entries()
        await self._write_reports_guarded("setup")


    async def _write_reports_guarded(
        self, trigger: str | None = None
    ) -> str | None:
        """Write the reports, and survive a directory that is not there.

        Every write runs in the executor, and an executor job handles
        nothing: an OSError raised inside one escapes into Home
        Assistant's task machinery and lands in a person's log as an
        unretrieved task exception (rule CODE-06).

        A report that cannot be written is a worse report rather than
        a broken integration, so the failure is logged with its path
        and the tick carries on. The path this most affects is the
        midnight rollover, where an unguarded raise abandons the rest
        of the job.
        """
        await self.async_check_unused_adapter()
        try:
            async with self._report_lock:
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
        except Exception:  # noqa: BLE001 - a report is never worth the tick
            # Each report is already guarded on its own (rule CODE-06); this is
            # the brief, or the writer around them. The midnight fold and
            # the brief's send carry on without it.
            LOGGER.exception(
                "Device Sentinel could not write its reports (%s); the "
                "tick carries on",
                trigger or "midnight",
            )
            return None

    async def _on_hass_stop(self, _event: Event) -> None:
        """Home Assistant is stopping: store the open Wi-Fi outage first.

        A restart does not unload the integration, so this is the only
        write it gets; the outage is stored as it stands now, its push
        and worst count included, before the stop's save, so the next
        start resumes it whole (rule UP-04).
        """
        self._remember_wifi_outage()
        # A broker that restarted since the last minute check is told
        # now, while the last message before it is still known (rule
        # UP-02): the next start would see only its start time move,
        # and give the restart no length.
        if getattr(self, "_broker_reader", None) is not None:
            try:
                self._sample_broker(dt_util.utcnow().timestamp())
            except Exception:  # noqa: BLE001 - the stop's save comes first
                LOGGER.exception("Device Sentinel could not check the broker as Home Assistant stopped")
        await super()._on_hass_stop(_event)

    async def async_shutdown(self) -> None:
        """Stop listening and flush storage."""
        # First, so a minute check still running writes nothing from
        # here on; the final save below is the session's last.
        self._stopped = True
        if self._broker_reader is not None:
            self._broker_reader.async_stop()
            self._broker_reader = None
        for observer in self._join_observers.values():
            observer.async_stop()
        self._join_observers.clear()
        for reader in self._bridge_readers.values():
            reader.async_stop()
        self._bridge_readers.clear()
        if self._wifi_unsub is not None:
            self._wifi_unsub()
            self._wifi_unsub = None
        self._stop_wifi_fallen_listener()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # A held fault has a live timer; dropping the coordinator
        # without cancelling it would fire into a dead entry.
        for cancel in self._held_events.values():
            cancel()
        self._held_events.clear()
        if self._park_timer is not None:
            self._park_timer()
            self._park_timer = None
        # The probe's lines wait a minute for the next tick; a stop has
        # none, so they are written here (rule STACK-12).
        await self.async_probe_stop()
        # The brief schedule is held separately so a changed brief
        # time can re-arm it without disturbing the others, which
        # also means it has to be cancelled by name here.
        if self._brief_unsub is not None:
            self._brief_unsub()
            self._brief_unsub = None
        # The clean-stop marker is written here as well as on the stop
        # event, because an unload (a settings change, a reload, an
        # update, the integration disabled) fires no
        # EVENT_HOMEASSISTANT_STOP, and would otherwise read as an
        # unclean stop and restart every device's clock (rule FRZ-20).
        self.data[DATA_CLEAN_STOP] = True
        # A Wi-Fi outage still open is stored as it stands at the stop,
        # its worst count and announcements included, so the next start
        # resumes it whole (rule UP-04).
        self._remember_wifi_outage()
        # Unconditional. A routine save writes the clocks file alone and
        # clears the dirty flag, so a stop that waited for the flag
        # would leave the main file behind; writing both here means a
        # clean stop always leaves two files that agree (rule STOR-02).
        # A restore happens at load,
        # before the session reads anything, and the session runs on
        # the restored copy, so its save is the right one (rule
        # STOR-09).
        await self._save_now(final=True)
        # A pencil answer still inside its one-second wait (rule STOR-20).
        await self.async_flush_answers()

    # ---------------------------------------------------- registry view

    @staticmethod
    def _owner_candidates(device: dr.DeviceEntry) -> list[str]:
        """Return the config entry ids that may own a device, owner first.

        Home Assistant 2026.8 gave every device a single config entry,
        named by `config_entry_id`, and 2026.10 reports any read of
        the two attributes it replaced, `primary_config_entry` and
        `config_entries`, as deprecated. Where `config_entry_id`
        exists it is the whole answer, and the old attributes are
        never touched, so nothing is reported. Where it does not,
        Home Assistant 2026.5 to 2026.7, the old order stands: the
        primary first, then every entry sorted, so the pick is
        deterministic. On 2026.8 and later the two give the same
        owner, because there the old primary is `config_entry_id`.

        One exception keeps the old order on new versions: a restored
        composite, the stand-in Home Assistant builds when asked for a
        device id from before the 2026.8 split. It can still list
        several entries, its old attributes report nothing, and the
        old order lets it fall back to another entry when its owner's
        has gone.
        """
        owner = getattr(device, "config_entry_id", None)
        if owner is not None and not getattr(device, "is_composite_device", False):
            return [owner]
        candidates: list[str] = []
        primary = getattr(device, "primary_config_entry", None)
        if primary is not None:
            candidates.append(primary)
        candidates.extend(sorted(getattr(device, "config_entries", ()) or ()))
        return candidates

    def _primary_entry(self, device: dr.DeviceEntry) -> str | None:
        """Return the config entry id that owns this device.

        The same order the domain is read in, so the entry whose state
        is watched is the entry whose domain the device is filed
        under. The owner Home Assistant names, `config_entry_id` from
        2026.8 or the primary before it, is returned as it stands;
        only a device with neither, before 2026.8, is answered by the
        first of its entries that still exists.
        """
        owner = getattr(device, "config_entry_id", None)
        if owner is not None:
            return owner
        primary = getattr(device, "primary_config_entry", None)
        if primary is not None:
            return primary
        for entry_id in sorted(getattr(device, "config_entries", ()) or ()):
            if self.hass.config_entries.async_get_entry(entry_id):
                return entry_id
        return None

    def _primary_domain(self, device: dr.DeviceEntry) -> str:
        """Return the integration domain owning a device.

        The owner is the registry's own: `config_entry_id` from Home
        Assistant 2026.8, and before that a multi-homed device (known
        to its own integration and to a network tracker at once) is
        filed under its primary entry, the one that created it, with
        a sorted fallback so the pick is deterministic either way.
        """
        for entry_id in self._owner_candidates(device):
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                return entry.domain
        return "unknown"

    def _registry_devices(
        self, dev_reg: dr.DeviceRegistry
    ) -> list[Any]:
        """Return every registry device once, walked by config entry.

        Child devices (Home Assistant 2026.9) are asked for separately,
        because the lookup by config entry returns ordinary devices
        only: a boiler's pump filed under the boiler was never watched,
        and a watched device an integration converted into a child after
        a restart dropped out of watch with its history left unused. A
        conversion keeps the id, so the device keeps its record.

        Home Assistant 2026.9 deprecated reading `devices` as a mapping,
        and iterating it yields device entries only from 2026.9; on
        2026.5 to 2026.8 it yields ids. The lookup by config entry reads
        the same on every supported release and never warns (rule
        GEN-04). Below 2026.8 a device can belong to several entries, so
        a device already reached is skipped. A device whose config
        entry no longer exists is not reached; Home Assistant removes
        such a device at startup.
        """
        seen: set[str] = set()
        devices: list[dr.DeviceEntry] = []
        for entry in self.hass.config_entries.async_entries():
            for device in [
                *dr.async_entries_for_config_entry(dev_reg, entry.entry_id),
                *child_devices(dev_reg, entry.entry_id),
            ]:
                if device.id not in seen:
                    seen.add(device.id)
                    devices.append(device)
        return devices

    def _ask_registry(
        self, question: Any, domain: str, device: Any, name: str
    ) -> Any:
        """Ask a stack question of one device, never letting it stop setup.

        One device's registry entry, written by another integration,
        must not stop Device Sentinel starting for the whole house: an
        identifier of an unexpected shape would otherwise leave it in
        setup_error. A device whose entry cannot be read is answered
        None for that question, stays watched, and is named in one
        warning per start.
        """
        try:
            return question(domain, device)
        except Exception as err:  # noqa: BLE001 - another integration's data
            self._note_odd_device(device, name, err)
            return None

    def _note_odd_device(self, device: Any, name: str, err: Exception) -> None:
        """Say once per start that a device's registry entry was unreadable."""
        key = str(getattr(device, "id", name))
        if key in self._odd_devices:
            return
        self._odd_devices.add(key)
        LOGGER.warning(
            "Device Sentinel could not read part of %s's registry entry "
            "(%s: %s). It is still watched. Said once per start.",
            name,
            type(err).__name__,
            err,
        )

    def _find_hardware_copies(
        self, devices: list[Any], watched: dict[str, str], ent_reg: Any
    ) -> dict[str, str]:
        """Copies of one device among the watched devices, each mapped to
        the copy kept watched (hardware_copies.py, rule WATCH-06)."""
        try:
            groups = find_groups(devices, self._primary_domain)
        except Exception as err:  # noqa: BLE001 - never stops a rebuild
            LOGGER.warning("Device Sentinel could not group hardware copies: %s", err)
            self._hardware_groups = []
            return {}
        self._hardware_groups = groups

        ranks: dict[str, tuple[int, int, int, int, int, int]] = {}
        by_id = {device.id: device for device in devices}
        for members in groups:
            for device_id in members:
                if device_id not in watched:
                    continue
                domain = watched[device_id]
                # Enabled entities only: UniFi registers a client speed
                # sensor disabled, and counting it would rank a tracker
                # over the device (rule WATCH-06).
                own = [
                    e for e in er.async_entries_for_device(ent_reg, device_id)
                    if e.platform == domain and e.disabled_by is None
                ]
                # Firmware notices and command buttons are never the
                # device, so a copy holding only those ranks as one with
                # nothing, never kept over one that reports (rule
                # WATCH-04). Beside a real entity they still count in
                # choosing between two real copies. An ESPHome device's
                # connection is something it reports, so a Bluetooth
                # proxy with only notices switched on is still the
                # device its adapter copies (rule WATCH-06).
                if domain != "esphome" and all(e.domain in NOTICE_DOMAINS for e in own):
                    own = []
                ranks[device_id] = rank_of(
                    self.iot_class_of(domain),  # type: ignore[attr-defined]
                    {e.domain for e in own},
                    len(own),
                    battery=any(
                        (e.device_class or e.original_device_class) == "battery" for e in own
                    ),
                    # An address of its own (rule WATCH-06).
                    addressed=bool(device_field(by_id.get(device_id), "connections", set())),
                )
        # Only a device with entities of its own can be a copy or the
        # one kept. One with none keeps its own reason (no entities, or
        # watched through restart grace while its integration loads),
        # so a device whose main integration is still starting is never
        # set aside in favor of a copy for that minute (rule WATCH-06).
        candidates = {d: watched[d] for d, r in ranks.items() if r[0]}
        return choose_copies(groups, candidates, ranks.__getitem__)

    def _rebuild_registry_view(self, audit: bool = False) -> None:
        """Classify devices and rebuild the entity-to-device map."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        # The names the last rebuild knew, for a device removed since:
        # its record is held under the name it had (rule WATCH-07).
        previous_names = {
            device_id: held[0] for device_id, held in self._set_aside.items()
        }
        # Which devices were set aside as excluded before this walk, so
        # one removed from Home Assistant can be told apart below.
        previously_excluded = {
            device_id for device_id, held in self._set_aside.items()
            if held[2] == SET_ASIDE_EXCLUDED
        }
        previous_names.update(self._device_names)
        self._label_names = {
            label.label_id: label.name
            for label in lr.async_get(self.hass).async_list_labels()
        }

        options = self.entry.options
        muted_device_ids = set(
            options.get(CONF_MUTED_DEVICES, [])
        )
        muted_labels = set(options.get(CONF_MUTED_LABELS, []))
        muted_integrations = set(
            options.get(CONF_MUTED_INTEGRATIONS, [])
        )
        excluded_integrations = self.excluded_integrations
        # One device excluded on its own (rule MUTE-03).
        excluded_devices = self.excluded_devices

        watched: dict[str, str] = {}
        radio_owned: set[str] = set()
        device_names: dict[str, str] = {}
        device_labels: dict[str, frozenset[str]] = {}
        # Name, domain and reason, because a disabled device and a
        # service device are set aside for different reasons (rule
        # WATCH-03).
        set_aside: dict[str, tuple[str, str, str]] = {}
        muted_devices: dict[str, str] = {}
        stacks: set[str] = set()
        owning_domains: set[str] = set()
        stack_keys: dict[str, tuple[str, str]] = {}
        entry_of: dict[str, str] = {}
        all_devices = self._registry_devices(dev_reg)
        for device in all_devices:
            domain = self._primary_domain(device)
            entry_id = self._primary_entry(device)
            if entry_id is not None:
                entry_of[device.id] = entry_id
            name = display_name(device, domain, device.id)
            owning_domains.add(domain)
            # Which coordinator stacks the house runs, read from the
            # same walk. Which device proves which stack is each stack
            # file's own question and is asked through the registry, so
            # this walk names no stack (rule STACK-01).
            stack = self._ask_registry(detect_stack, domain, device, name)
            if stack is not None:
                stacks.add(stack)
            if domain in excluded_integrations or device.id in excluded_devices:
                # The person asked for this integration, or this one
                # device, not to be watched, so that reason is recorded
                # even where another would also fit: a person's decision
                # outranks a fact about the device (rule WATCH-03).
                set_aside[device.id] = (name, domain, SET_ASIDE_EXCLUDED)
                continue
            if device_field(device, "entry_type") is dr.DeviceEntryType.SERVICE:
                set_aside[device.id] = (name, domain, SET_ASIDE_SERVICE)
                continue
            if device.disabled_by is not None:
                # Disabled by a person, by its integration, or by a
                # disabled config entry. It cannot report, so judging
                # its silence is noise, and reporting it is a false
                # alarm (rule WATCH-03).
                set_aside[device.id] = (name, domain, SET_ASIDE_DISABLED)
                continue
            if is_plumbing(domain, device):
                # A coordinator reaching the registry a second time as
                # an ordinary device (rule WATCH-05). It is already
                # watched properly by its own bridge sensor, which
                # reads the stack directly. Judged as hardware it
                # learns a rhythm from the intervals between unrelated
                # events and is eventually convicted frozen while that
                # sensor reads running. Last on the fact ladder so a
                # person's exclusion, a service device and a disabled
                # device all keep their own reason.
                set_aside[device.id] = (
                    name, domain, SET_ASIDE_DUPLICATE_COORDINATOR
                )
                continue
            watched[device.id] = domain
            # What the owning stack calls this device, where it can
            # say. Read on the same walk for the same reason stack
            # presence is, and asked through the registry so this file
            # still names no stack (rule STACK-01).
            owner = self._ask_registry(device_key, domain, device, name)
            if owner is not None:
                stack_keys[device.id] = owner
            # Whether a radio stack owns this device (rule UP-15). A
            # Wi-Fi outage does not explain Zigbee, Z-Wave or Matter
            # hardware: it has its own bridge rung and its own medium.
            # Asked on the same walk, and deliberately not read from
            # `stack_keys`, which ZHA, Z-Wave and Matter leave empty
            # because their identifiers are unverified.
            if self._ask_registry(radio_owner, domain, device, name) is not None:
                radio_owned.add(device.id)
            device_names[device.id] = name
            device_labels[device.id] = frozenset(device.labels or ())
            # Device-level muting reasons, named broadest first
            # so the reason recorded is the one that would survive a
            # prune. The integration test uses the primary domain, so
            # an integration mute catches only devices it owns,
            # never multi-homed hardware it merely sees. A muted label
            # mutes the device that carries it, never an entity, since
            # Device Sentinel judges devices (rule MUTE-05).
            if domain in muted_integrations:
                muted_devices[device.id] = "integration"
            elif muted_labels & set(device.labels or ()):
                muted_devices[device.id] = "label"
            elif device.id in muted_device_ids:
                muted_devices[device.id] = "device"

        # What other devices hang from, for the Type row: a device
        # others reach Home Assistant through is a hub, and an ESPHome
        # device with a Bluetooth adapter of its own registered under
        # it is a Bluetooth proxy (rule DEV-10).
        self._via_parents = {
            via for d in all_devices if (via := device_field(d, "via_device_id"))
        }
        self._bluetooth_parents = {
            via for d in all_devices
            if (via := device_field(d, "via_device_id")) and self._primary_domain(d) == "bluetooth"
        }
        # One piece of hardware shown as several devices: every watched
        # copy but the one that reaches the hardware most directly is
        # set aside, so it is judged once (rule WATCH-06).
        copy_of =self._find_hardware_copies(all_devices, watched, ent_reg)
        for copy_id, kept in copy_of.items():
            set_aside[copy_id] = (
                device_names.pop(copy_id, copy_id),
                watched.pop(copy_id),
                SET_ASIDE_COPY,
            )
            device_labels.pop(copy_id, None)
            muted_devices.pop(copy_id, None)
            stack_keys.pop(copy_id, None)
            radio_owned.discard(copy_id)
        self._copy_of = copy_of

        entity_map: dict[str, tuple[str, str | None]] = {}
        # Entities another integration added to a watched device. They
        # are still mapped, so a reading the device publishes nowhere
        # else can still be taken from one, but they never count as the
        # device speaking (rule WATCH-02).
        foreign_entities: set[str] = set()
        foreign_by_device: dict[str, Counter[str]] = {}
        # The same, by name: device -> integration -> its entity ids,
        # so a page can name them (rule WATCH-02).
        foreign_ids: dict[str, dict[str, list[str]]] = {}
        last_seen_entity: dict[str, str] = {}
        node_status_entity: dict[str, str] = {}
        device_entries: dict[str, set[str]] = {}
        signal_entities: set[str] = set()
        signal_devices: set[str] = set()
        battery_entity: dict[str, tuple[str, bool]] = {}
        # Which readings came from the device's own integration. An
        # entity another integration added is a second-hand reading: it
        # took the original and did something to it, and nobody can
        # know what, so it is used only where the device publishes
        # nothing of its own (rule BAT-01).
        battery_own: dict[str, bool] = {}
        last_seen_own: dict[str, bool] = {}
        signal_own_entities: set[str] = set()
        signal_device_of: dict[str, str] = {}
        deviceless = 0
        with_entities: set[str] = set()
        stack_words: set[str] = set()
        main_entities: dict[str, set[str]] = {}
        # Devices with an enabled entity of their own that can report, and
        # devices with an enabled firmware notice or command button.
        enabled_real: set[str] = set()
        enabled_notice: set[str] = set()
        held_keys: dict[str, str] = {}
        unheld_own: set[str] = set()
        for ent in ent_reg.entities.values():
            if ent.device_id is None:
                deviceless += 1
                continue
            if ent.device_id not in watched:
                continue
            entity_map[ent.entity_id] = (ent.device_id, ent.config_entry_id)
            if (
                ent.entity_category is None
                and ent.domain not in NOTICE_DOMAINS
                and ent.disabled_by is None
            ):
                # A main entity: what the device is for, not a setting,
                # a diagnostic or a firmware notice, which Home Assistant
                # or the coordinator can hold for a device that is gone.
                main_entities.setdefault(ent.device_id, set()).add(ent.entity_id)
            if ent.platform == "hue" and getattr(ent, "translation_key", None) == "zigbee_connectivity":
                stack_words.add(ent.entity_id)
            if is_node_status(watched.get(ent.device_id), ent):
                # The stack's own word on the node: read for the
                # dead-node check, never as the device speaking (rule
                # STACK-05).
                node_status_entity[ent.device_id] = ent.entity_id
            # The device's own integration published this entity, as
            # opposed to an integration that enriches somebody else's
            # devices (rule WATCH-02). The registry records the author,
            # so no list of such integrations is maintained and the
            # rule holds for ones that do not exist yet.
            own = ent.platform == watched.get(ent.device_id)
            if not own:
                # Battery Notes refreshes its entities about every 26
                # minutes, so on a device with no Last Seen clock each
                # refresh would stamp the device as heard and keep a
                # dead sensor looking alive. A foreign entity is not the
                # device speaking, so it neither counts as the device
                # having entities, nor ties the device to its
                # integration's reloads (rule WATCH-02).
                foreign_entities.add(ent.entity_id)
                foreign_by_device.setdefault(ent.device_id, Counter())[
                    ent.platform
                ] += 1
                foreign_ids.setdefault(ent.device_id, {}).setdefault(
                    ent.platform, []
                ).append(ent.entity_id)
            else:
                # A firmware notice or a command button is never the
                # device, so it does not count as the device having
                # something that could report; an ESPHome device's
                # connection does, and so does the hub that speaks for a
                # Lutron Pico, whose only entities are its buttons
                # (rules WATCH-04, STACK-09).
                if (
                    ent.domain not in NOTICE_DOMAINS
                    or watched.get(ent.device_id) == "esphome"
                    or watched.get(ent.device_id) in HUB_READERS
                ):
                    with_entities.add(ent.device_id)
                if ent.disabled_by is None:
                    # The Hue bridge's word on a light is no more the
                    # device than a firmware notice is: a device with
                    # nothing else switched on is set aside the same way
                    # (rule WATCH-04).
                    if ent.domain in NOTICE_DOMAINS or ent.entity_id in stack_words:
                        enabled_notice.add(ent.device_id)
                    else:
                        enabled_real.add(ent.device_id)
                if ent.config_entry_id is not None:
                    device_entries.setdefault(ent.device_id, set()).add(
                        ent.config_entry_id
                    )
                # Which of its own entities can hold a value for a
                # device with a verdict: never a firmware notice, a
                # button or another command, nor the stack's own word
                # on the node, and never a timestamp or duration sensor,
                # whose value is worked out again at each start (rule
                # WATCH-12).
                if (
                    ent.domain not in NOTICE_DOMAINS
                    and ent.entity_id not in stack_words
                    and node_status_entity.get(ent.device_id) != ent.entity_id
                ):
                    device_class = ent.device_class or ent.original_device_class
                    if device_class in UNHELD_DEVICE_CLASSES:
                        unheld_own.add(ent.entity_id)
                    else:
                        held_keys[ent.entity_id] = ent.id
            # A switched-off Last Seen has no state, so it is not the
            # clock: the device is timed by when its reports arrive, and
            # the Last Seen Sensor Switched Off card still finds it in
            # the registry (rule WATCH-01).
            if ent.disabled_by is None and self._is_last_seen(ent):
                if last_seen_entity.get(ent.device_id) is None or (
                    own and not last_seen_own.get(ent.device_id, False)
                ):
                    last_seen_entity[ent.device_id] = ent.entity_id
                    last_seen_own[ent.device_id] = own
            if self._is_signal(ent):
                if ent.disabled_by is None:
                    signal_entities.add(ent.entity_id)
                    signal_devices.add(ent.device_id)
                    signal_device_of[ent.entity_id] = ent.device_id
                    if own:
                        signal_own_entities.add(ent.entity_id)
            if ent.disabled_by is None and self._is_battery(ent):
                is_binary = ent.entity_id.startswith("binary_sensor.")
                current = battery_entity.get(ent.device_id)
                # Percentage beats binary, then the device's own
                # beats one another integration added, then the
                # lower entity id wins. Every rung is a comparison
                # rather than an arrival order, so a device carrying two
                # percentages, as Battery Notes often gives one, reads
                # the same sensor after every restart (rule BAT-01).
                if current is None:
                    better = True
                else:
                    was_own = battery_own.get(ent.device_id, False)
                    better = (current[1], not was_own, current[0]) > (
                        is_binary, not own, ent.entity_id
                    )
                if better:
                    battery_entity[ent.device_id] = (
                        ent.entity_id,
                        is_binary,
                    )
                    battery_own[ent.device_id] = own

        # A device whose only entities switched on are firmware notices or
        # command buttons has nothing that can report, whatever it has
        # switched off: set aside with a reason of its own (rule
        # WATCH-04). An infrared light's buttons are Home Assistant
        # sending, never the light answering. An ESPHome device and a
        # hub-judged one keep their own voice.
        for device_id in enabled_notice - enabled_real:
            if watched.get(device_id) == "esphome" or watched.get(device_id) in HUB_READERS:
                continue
            with_entities.discard(device_id)
        in_grace = dt_util.utcnow().timestamp() < self._grace_until
        for device_id in [d for d in watched if d not in with_entities]:
            if in_grace and not self._integration_finished_loading(
                watched.get(device_id)
            ):
                # Integrations register their entities as they load,
                # so during the startup window a device with none is
                # usually one whose owner has not finished, not one
                # that will never speak. Setting it aside then and
                # bringing it back a second later would cost such
                # devices their first gap on every restart (rule
                # WATCH-10).
                #
                # The clock alone is too blunt. An integration whose
                # config entry has finished loading has registered
                # what it is going to register, so a device of its
                # own that still has no entities has none to come.
                # The ZHA coordinator is exactly that, so it is set
                # aside at once rather than watched through the grace
                # (rule WATCH-03).
                continue
            # No entities at all: nothing exists that could ever
            # report, and nothing a person could switch on, so its
            # silence says nothing (rule WATCH-03). A device whose
            # entities are all disabled is a different case and stays
            # watched: those entities exist, the never-reported row
            # is the prompt, and the person can enable them or
            # mute the device. One with nothing but firmware notices or
            # command buttons switched on is set aside with its own
            # words, since switching another entity on brings it back
            # (rule WATCH-04).
            set_aside[device_id] = (
                device_names.get(device_id, device_id),
                watched.pop(device_id),
                SET_ASIDE_NOTICES_ONLY if device_id in enabled_notice else SET_ASIDE_NO_ENTITIES,
            )
            device_names.pop(device_id, None)

        # The name the brief and the railed-signal rows print is the
        # plain name; the integration is added on the Settings lists
        # alone (rule DEV-04).
        display_names = dict(device_names)

        self._display_names = display_names
        self._watched = watched
        # Kept rather than discarded with the rebuild: the judge needs
        # to know whether a device has any entity at all, and that is
        # the only place the registry has been walked (rule FRZ-09).
        self._devices_with_entities = with_entities
        self._devices_enabled_real = enabled_real
        self._clear_verdicts_for_set_aside(set_aside)
        self._stacks = stacks
        self._stack_keys = stack_keys
        self._radio_owned = radio_owned
        self._entry_of_device = entry_of
        # Each device a hub controls, from the same walk (rule STACK-09).
        self._rebuild_hubs(all_devices)
        # A hub muted from everything mutes the devices it controls
        # with it. Derived here, never saved, so unmuting the hub
        # unmutes them, and a device's own mute stands (rule STACK-09).
        for member, hub in self._hub_of.items():
            if hub in muted_devices and hub in watched:
                muted_devices.setdefault(member, "hub")
        self._device_names = device_names
        self._device_labels = device_labels
        self._set_aside = set_aside
        self._muted_devices = muted_devices
        self._entity_map = entity_map
        self._foreign_entities = foreign_entities
        own_entities: dict[str, list[str]] = {}
        for entity_id, (owner, _) in entity_map.items():
            if entity_id not in foreign_entities:
                own_entities.setdefault(owner, []).append(entity_id)
        self._own_entities = own_entities
        # The entities that hold a value for a device with a verdict,
        # and the last good values of only those (rule WATCH-12).
        self._held_keys = held_keys
        self._unheld_own = unheld_own
        live_keys = set(held_keys.values())
        self._last_good = {
            key: value for key, value in self._last_good.items() if key in live_keys
        }
        # A device watched again, or new, starts from what it shows now.
        self._seed_last_good()
        self._main_entities = {
            device_id: {e for e in entities if e not in foreign_entities}
            for device_id, entities in main_entities.items()
        }
        self._foreign_by_device = foreign_by_device
        self._foreign_ids = foreign_ids
        # An integration whose entities all sit on devices other
        # integrations own, and which owns no device itself, has no
        # hardware of its own, as Battery Notes has none (rule
        # WATCH-02).
        self._no_hardware_integrations = {
            platform
            for counts in foreign_by_device.values()
            for platform in counts
        } - owning_domains
        self._last_seen_entity = last_seen_entity
        self._node_status_entity = node_status_entity
        # The stack's word on a node is never the device speaking:
        # Z-Wave's node status, and the Hue bridge's Zigbee connectivity
        # sensor, which the bridge writes when it loses a light (rule
        # WATCH-04).
        self._node_status_ids = set(node_status_entity.values()) | stack_words
        self._device_entries = device_entries
        # Another integration's signal reading is used only where the
        # device has none of its own, since feeding both into one series
        # would mix two scales in one day (rule WATCH-02).
        with_own = {signal_device_of[e] for e in signal_own_entities if e in signal_device_of}
        signal_entities = {
            e for e in signal_entities
            if e in signal_own_entities or signal_device_of.get(e) not in with_own
        }
        self._signal_entities = signal_entities
        self._signal_devices = signal_devices
        self._battery_entity = battery_entity
        # Kept so the diagnostics can say which reading each device
        # is using and whether it is the device's own, so a series that
        # changed source can be told from a cell that was changed (rule
        # WATCH-02).
        self._battery_own = battery_own
        self._last_seen_own = last_seen_own
        self._signal_own_entities = signal_own_entities
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
        # Each watched device's firmware, at every start and every
        # registry change, since the registry keeps only the current
        # version (rule DEV-15).
        if not self._firmware_unflickered:
            self._unflicker_firmware()
            self._firmware_unflickered = True
        self._note_firmware(watched)
        now_stamp = dt_util.utcnow().timestamp()
        held_now: list[str] = []
        returned: list[str] = []
        excluded_gone: list[str] = []
        aside_before = self._aside_seen
        if aside_before is None:
            # The first rebuild reads the saved set, so a return made
            # while Device Sentinel was reloading or disabled is dated
            # (rule WATCH-08). None from a file that has none, as an
            # older release's.
            stored = self.data.get(DATA_ASIDE_SEEN)
            if isinstance(stored, list) and all(isinstance(x, str) for x in stored):
                aside_before = set(stored)
        # Watched at the last rebuild, so being set aside or removed
        # now starts a new stretch; before the first rebuild nothing
        # is known, and a stamp already saved is kept.
        aside_now: set[str] = set()
        for device_id in list(devices):
            record = devices[device_id]
            fresh_stretch = aside_before is not None and device_id not in aside_before
            if device_id in watched or device_id in set_aside:
                came_back = False
                if isinstance(record, dict) and record.get(DEV_REMOVED_SINCE) is not None:
                    returned.append(device_id)
                    self._welcome_back(device_id, record, watched.get(device_id))
                    came_back = True
                if device_id in watched:
                    returning = (
                        isinstance(record, dict)
                        and record.get(DEV_SET_ASIDE_SINCE) is not None
                        and (came_back or (aside_before is not None and device_id in aside_before))
                    )
                    if returning and self._past_window_when_set_aside(record):
                        # Down before anyone stopped watching it: judged
                        # from its last report, so an earlier return no
                        # longer dates its silence (rule WATCH-08).
                        if record.get(DEV_WATCHED_FROM) is not None:
                            record[DEV_WATCHED_FROM] = None
                            self._mark_cold_dirty()
                    elif returning:
                        # Back from being set aside, excluded or
                        # removed: judged from now, since the time
                        # nobody watched it is not its silence.
                        # Dated once, as it comes back: a later
                        # settings change, a restart or the upgrade
                        # from a release that kept no return never
                        # re-dates it, so none can clear a standing
                        # freeze (rule WATCH-08).
                        record[DEV_WATCHED_FROM] = now_stamp
                        # In the main file, written at once: a lost
                        # clocks file must not make a restart look like
                        # the return (rule WATCH-08).
                        self._mark_cold_dirty()
                        self._critical = True
                    continue
                aside_now.add(device_id)
                # Unwatched, its outage is not followed: the return
                # reads it afresh (rule WATCH-08).
                if isinstance(record, dict) and record.get(DEV_DOWN_SINCE) is not None:
                    record[DEV_DOWN_SINCE] = None
                    self._dirty = True
                # Set aside, not gone: a person disabling an
                # integration for an afternoon must not lose what the
                # house spent weeks learning (rule WATCH-03). The record
                # is kept untouched and unjudged, and the stamp lets
                # the gap that spans the absence be refused on return.
                # Each stretch dates its own start, so the return reads
                # this stretch, not an earlier one (rule WATCH-08).
                if isinstance(record, dict) and (
                    record.get(DEV_SET_ASIDE_SINCE) is None or fresh_stretch
                ):
                    record[DEV_SET_ASIDE_SINCE] = now_stamp
                    self._mark_cold_dirty()
                continue
            if not isinstance(record, dict):
                del devices[device_id]
                self._mark_cold_dirty()
                continue
            if record.get(DEV_REMOVED_SINCE) is not None:
                aside_now.add(device_id)
                continue
            if device_id in previously_excluded or device_id in self.excluded_devices:
                # Excluded, then removed (rule WATCH-07):
                # the person already asked for its record to go, so it
                # is not held for a return. It goes now, with what it
                # recorded, as the fold would have taken it at midnight.
                excluded_gone.append(device_id)
                continue
            # Gone from Home Assistant: held, not dropped (rule WATCH-07).
            # Home Assistant keeps a removed device's id and gives it
            # back when the same hardware is added again, so for
            # REMOVED_HOLD_DAYS the rhythm, answers and mutes wait for
            # it, unjudged. The set-aside stamp refuses the gap that
            # spans the absence, as it does for a disabling. The fold
            # purges a hold that has run its time.
            record[DEV_REMOVED_SINCE] = now_stamp
            record[DEV_REMOVED_NAME] = previous_names.get(device_id)
            if record.get(DEV_SET_ASIDE_SINCE) is None or fresh_stretch:
                record[DEV_SET_ASIDE_SINCE] = now_stamp
            record[DEV_DOWN_SINCE] = None
            held_now.append(device_id)
            aside_now.add(device_id)
            self._mark_cold_dirty()
        self._aside_seen = aside_now
        if self.data.get(DATA_ASIDE_SEEN) != sorted(aside_now):
            self.data[DATA_ASIDE_SEEN] = sorted(aside_now)
            self._mark_cold_dirty()
            self._critical = True
        if excluded_gone:
            self._drop_excluded_and_removed(excluded_gone)
        if held_now:
            self._clear_verdicts_for_set_aside(dict.fromkeys(held_now))
            for device_id in held_now:
                _forget_hold_verdicts(devices[device_id])
            # The Problem List drops the row now, not at the next minute
            # (rule LIST-09).
            self._held_unsynced = True
            # Said once rather than silently. On an ordinary restart
            # this is a device a person removed. On a restore to a
            # fresh Home Assistant install it is every record the
            # house ever learned, because registry ids are minted per
            # install, and a person reading "watching 0 of 0" with no
            # explanation has no way to know which happened.
            LOGGER.info(
                "%d stored record(s) belong to device ids this registry "
                "does not know; each is held %d days in case the device "
                "comes back, then deleted: %s",
                len(held_now),
                REMOVED_HOLD_DAYS,
                ", ".join(
                    _plain(devices[d].get(DEV_REMOVED_NAME) or d) for d in sorted(held_now)[:10]
                ),
            )
        if returned:
            LOGGER.info(
                "%d removed device(s) came back and kept their records: %s",
                len(returned),
                ", ".join(_plain(display_names.get(d) or set_aside.get(d, (d,))[0]) for d in sorted(returned)[:10]),
            )

        if audit and set_aside:
            # Named by reason: service devices are furniture, but a
            # disabled one is a person's choice and a device with
            # nothing enabled may be an accident, and a person
            # looking for a missing device needs to tell them apart.
            LOGGER.debug(
                "Devices set aside: %s",
                "; ".join(
                    f"{name} ({domain}, {reason})"
                    for name, domain, reason in sorted(set_aside.values())
                ),
            )

        # The Wi-Fi tie ladder follows every rebuild: a tracker that
        # appeared, a device that gained a MAC, or a dissolved tie is
        # picked up here, and where no ties exist this is a no-op
        # that subscribes to nothing.
        self._rebuild_wifi_ties()
        self.resubscribe_study()

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

        Protocol truth where the integration publishes it. The value is
        the coordinator's own record of contact, and a republish carries
        it unchanged, so a replayed payload cannot advance the clock and
        the gap keeps accumulating with no muting rule involved (rule
        FRZ-11).

        None means the device has such a clock and it has not moved, or
        the entity itself is unavailable, which is information rather
        than a missing value: a hung device's Last Seen reads
        unavailable, and falling back to arrival time there would erase
        the evidence.

        A device with no such entity falls back to arrival time,
        because the moment Device Sentinel heard something is then the
        only evidence there is. A value the stack republishes through a
        restart or an outage never arrives here as speech (rule UP-06).
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
        # otherwise push the device's clock into the future and hide
        # every gap behind it (rule FRZ-11).
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
        """Rebuild the registry view when devices, entities or labels change.

        Through the debouncer (rule WATCH-11): at once when no rebuild ran in the
        last cooldown, otherwise once when it ends, so a burst of changes
        costs two rebuilds rather than one each. Naming a removed device
        that carried a muting stays immediate, because its name exists
        only until the removal completes.
        """
        old_id = event.data.get("old_entity_id")
        new_id = event.data.get("entity_id")
        if isinstance(old_id, str) and isinstance(new_id, str) and old_id != new_id:
            self._entity_renamed(old_id, new_id)
        if event.data.get("action") == "remove":
            device_id = event.data.get("device_id")
            # A device with a record is held 30 days, and its power and
            # type answers wait with it; a model answer it set still
            # passes to another device of the model now. One with no
            # record takes its answers with it (rule WATCH-07).
            held = isinstance(device_id, str) and device_id in (self.data.get(DATA_DEVICES) or {})
            # An excluded device is not held (rule WATCH-07): its answers
            # go with it.
            if held and (
                device_id in self.excluded_devices
                or (self._set_aside.get(device_id) or (None, None, None))[2] == SET_ASIDE_EXCLUDED
            ):
                held = False
            self._log_removed_muting(device_id, held)
            self._power_forget(device_id, hold=held)
            self._type_forget(device_id, hold=held)
        if self._registry_debouncer is None:
            self._rebuild_and_notify()
            return
        self._registry_debouncer.async_schedule_call()

    @callback
    def _rebuild_and_notify(self) -> None:
        """Rebuild the registry view, then tell the entities."""
        self._rebuild_registry_view()
        # An integration added while running is sighted within the
        # debounce, before it can raise a false alarm (rule MUTE-02).
        if not self._stopped:
            self.hass.async_create_task(
                self._sight_router_integrations(), "device_sentinel first-seen exclusions"
            )
        if getattr(self, "_held_unsynced", False):
            self._held_unsynced = False
            self._sync_problem_list()
        self._notify()

    @callback
    def _log_removed_muting(self, device_id: str | None, held: bool = False) -> None:
        """Name a departing device that carries a muting pick.

        The pick is pruned the next time its screen is saved, and by
        then the device is gone from the registry and only its id
        remains, which tells a person nothing. This is the last
        moment its name exists, so the name is written down here.
        A device whose record is held keeps its mutes while the hold
        lasts (rule WATCH-07).
        """
        if device_id is None:
            return
        # On Home Assistant 2026.5 its entities' removal arrives first
        # and the rebuild it runs already holds the record, so its name
        # is looked for there too (rule WATCH-11).
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id)
        name = (
            self._device_names.get(device_id)
            or (self._set_aside.get(device_id) or (None,))[0]
            or (record.get(DEV_REMOVED_NAME) if isinstance(record, dict) else None)
        )
        if name is None:
            return
        keys = (
            CONF_MUTED_DEVICES,
            CONF_BATTERY_MUTED_DEVICES,
            CONF_FREEZE_MUTED_DEVICES,
            CONF_SIGNAL_MUTED_DEVICES,
            CONF_UNAVAILABLE_MUTED_DEVICES,
        )
        options = self.entry.options
        if not any(device_id in options.get(key, []) for key in keys):
            return
        # Kept in the log: nothing else keeps a removed device's name,
        # so it is the only trace when a muting is asked about later
        # (rules WATCH-11, GEN-10).
        if held:
            LOGGER.info(
                "%s (%s) has been removed from Home Assistant and carried a "
                "Device Sentinel muting; the muting is kept %d days in case "
                "the device comes back",
                _plain(name),
                device_id,
                REMOVED_HOLD_DAYS,
            )
            return
        LOGGER.info(
            "%s (%s) has been removed from Home Assistant and carried a "
            "Device Sentinel muting; the setting is dropped the next "
            "time its screen is saved",
            _plain(name),
            device_id,
        )

    # ---------------------------------------------------------- intake

    @callback
    def _event_filter(self, event_data: Any) -> bool:
        """Fast pre-filter: only entities mapped to watched devices."""
        return event_data.get("entity_id") in self._entity_map

    def _past_window_when_set_aside(self, record: dict[str, Any]) -> bool:
        """Whether the device was already silent past its window when set aside.

        Such a device was down before anyone stopped watching it, so it
        is judged from its last report on its return, and reads frozen
        again at once rather than a window later (rule WATCH-08).
        """
        last = record.get(DEV_LAST_ACTIVITY)
        aside = record.get(DEV_SET_ASIDE_SINCE)
        if not isinstance(last, (int, float)) or not isinstance(aside, (int, float)):
            return False
        if isinstance(last, bool) or isinstance(aside, bool):
            return False
        # Silence counts from an earlier return, if it came after the
        # last report and before this stretch, so an earlier stretch
        # set aside is not read as this one's silence (rule WATCH-08).
        back = record.get(DEV_WATCHED_FROM)
        if (
            isinstance(back, (int, float))
            and not isinstance(back, bool)
            and last < back <= aside
        ):
            last = back
        window = self._freeze_window(record)
        return window is not None and aside - last >= window

    # ------------------------------------------ values handed back

    def _holds_values(self, device_id: str) -> bool:
        """Whether this device keeps its last good values while a
        verdict stands (rule WATCH-12).

        Not a device with a Last Seen entity, which is the stack's own
        record of hearing it; not one whose stack keeps that clock for
        it, as ZHA does, asked of the stack itself so this file names
        none; and not one on an integration that fetches its readings
        from the device, whose reading is the device answering. A stack
        clock that cannot be read leaves the device judged as one
        without (rule STACK-04).
        """
        domain = self._watched.get(device_id)
        return (
            domain is not None
            and device_id not in self._last_seen_entity
            and domain not in FETCHING_INTEGRATIONS
            and stack_last_heard(self.hass, domain, device_id) is None
        )

    def _held_entities(self, device_id: str) -> dict[str, str]:
        """The device's entities that can hold a value, each with its
        registry id (rule WATCH-12)."""
        return {
            entity_id: self._held_keys[entity_id]
            for entity_id in self._own_entities.get(device_id, ())
            if entity_id in self._held_keys
        }

    @staticmethod
    def _good_value(state: str) -> bool:
        """Whether a state is a value that can be held and compared
        (rule WATCH-12). Unavailable and unknown are never values, nor
        is the empty text an action sensor rests at after a press."""
        return state not in BAD_STATES and 0 < len(state) <= HELD_VALUE_LENGTH

    def _note_good(self, entity_id: str, state: str) -> None:
        """Remember an entity's latest good value, for the moment a
        verdict starts (rule WATCH-12)."""
        key = self._held_keys.get(entity_id)
        if key is not None and self._good_value(state):
            self._last_good[key] = state

    def _seed_last_good(self) -> None:
        """Take each entity's value from the state machine at each
        registry rebuild, setup's included, so a verdict starting before
        its next change still has it (rule WATCH-12)."""
        for entity_id in self._held_keys:
            state = self.hass.states.get(entity_id)
            if state is not None:
                self._note_good(entity_id, state.state)

    def _hold_values(self, device_id: str, record: dict[str, Any]) -> None:
        """Keep the device's last good values as its verdict starts, in
        the verdict's own save (rule WATCH-12)."""
        held = (
            {
                key: self._last_good[key]
                for key in self._held_entities(device_id).values()
                if key in self._last_good
            }
            if self._holds_values(device_id)
            else {}
        )
        record[DEV_HELD_VALUES] = held or None
        self._dirty = True

    def _release_values(self, device_id: str, record: dict[str, Any]) -> None:
        """Forget the held values and end the watch: the verdict is over,
        or the device has spoken, or it is no longer watched (rule
        WATCH-12)."""
        self._on_watch.pop(device_id, None)
        if record.get(DEV_HELD_VALUES) is not None:
            record[DEV_HELD_VALUES] = None
            self._dirty = True

    def _arm_held_watches(self) -> None:
        """Put each held entity on watch at setup, which follows a
        restart or a reload (rule WATCH-12). Held values with no verdict
        behind them, or on a device that no longer keeps them, go."""
        self._on_watch = {}
        records = self.data.get(DATA_DEVICES) or {}
        for device_id, record in records.items():
            if not isinstance(record, dict) or record.get(DEV_HELD_VALUES) is None:
                continue
            held = record[DEV_HELD_VALUES]
            if device_id not in self._watched:
                continue
            if record.get(DEV_FROZEN_CATEGORY) is None or not self._holds_values(device_id):
                self._release_values(device_id, record)
                continue
            entities = {
                entity_id: key
                for entity_id, key in self._held_entities(device_id).items()
                if key in held
            }
            if any(
                (state := self.hass.states.get(entity_id)) is not None
                and self._good_value(state.state)
                and not self._same_value(held[key], state.state)
                for entity_id, key in entities.items()
            ):
                # Already showing a value other than the one it held: the
                # device spoke while nobody was listening, so it is judged
                # on what it shows now (rule WATCH-12).
                self._release_values(device_id, record)
                continue
            if entities:
                self._on_watch[device_id] = set(entities.values())

    def _arm_entity_watch(self, entity_id: str) -> None:
        """Put one entity on watch when it is removed, or Home Assistant
        writes its placeholder as an integration reloads: the value
        coming next is the one it held (rule WATCH-12)."""
        mapped = self._entity_map.get(entity_id)
        key = self._held_keys.get(entity_id)
        if mapped is None or key is None:
            return
        device_id = mapped[0]
        record = self.data.get(DATA_DEVICES, {}).get(device_id)
        if not isinstance(record, dict) or record.get(DEV_FROZEN_CATEGORY) is None:
            return
        held = record.get(DEV_HELD_VALUES)
        if isinstance(held, dict) and key in held and self._holds_values(device_id):
            self._on_watch.setdefault(device_id, set()).add(key)

    @staticmethod
    def _same_value(held: str, state: str) -> bool:
        """Whether a value is the one held: as numbers when both read as
        numbers, so 21.5 is 21.50, and otherwise as text without case
        (rule WATCH-12)."""
        try:
            first, second = float(held), float(state)
        except ValueError:
            pass
        else:
            if math.isfinite(first) and math.isfinite(second):
                return first == second
        return held.casefold() == state.casefold()

    def _read_on_watch(
        self, device_id: str, entity_id: str, state: str
    ) -> str | None:
        """What a state change means for a device on watch (rule WATCH-12).

        "cache" when it is the held value handed back, or an own entity
        that never votes; "spoke" when a held entity reads a different
        value, which ends the watch and the held values; None when it is
        read as it always was, as an absence is.
        """
        watch = self._on_watch.get(device_id)
        if not watch:
            return None
        key = self._held_keys.get(entity_id)
        if key is None:
            return "cache" if entity_id in self._unheld_own else None
        if key not in watch or not self._good_value(state):
            return None
        record = self.data[DATA_DEVICES].get(device_id)
        held = record.get(DEV_HELD_VALUES) if isinstance(record, dict) else None
        stored = held.get(key) if isinstance(held, dict) else None
        if stored is None:
            return None
        if self._same_value(stored, state):
            return "cache"
        if isinstance(record, dict):
            self._release_values(device_id, record)
        return "spoke"

    def _held_reading(self, entity_id: str, state: Any) -> str | None:
        """An entity's state as the down readers take it (rule WATCH-12).

        For a device on watch whose verdict is unavailable or unknown,
        a held entity reads unknown, not yet known, so a value handed
        back cannot end the verdict, nor its stack calling it available;
        an own entity that never votes is not read at all. None means
        skipped. A frozen or never reported device is read as it is: its
        clock keeps it, and reading unknown would start an outage.
        """
        mapped = self._entity_map.get(entity_id)
        if mapped is None:
            return str(state.state)
        device_id = mapped[0]
        watch = self._on_watch.get(device_id)
        if not watch:
            return str(state.state)
        record = self.data.get(DATA_DEVICES, {}).get(device_id)
        if not isinstance(record, dict) or record.get(DEV_FROZEN_CATEGORY) not in (
            FREEZE_CATEGORY_UNAVAILABLE,
            FREEZE_CATEGORY_UNKNOWN,
        ):
            return str(state.state)
        if entity_id in self._unheld_own:
            return None
        if self._held_keys.get(entity_id) not in watch:
            return str(state.state)
        if state.state == STATE_UNAVAILABLE and state.attributes.get("restored") is not True:
            return STATE_UNAVAILABLE
        return STATE_UNKNOWN

    def held_diagnostics(self) -> dict[str, int]:
        """How many devices hold values and how many entities are on
        watch, for the download (rule WATCH-12)."""
        records = self.data.get(DATA_DEVICES) or {}
        return {
            "devices_with_held_values": sum(
                1
                for record in records.values()
                if isinstance(record, dict) and record.get(DEV_HELD_VALUES)
            ),
            "entities_on_watch": sum(len(keys) for keys in self._on_watch.values()),
        }

    def _entity_renamed(self, old_id: str, new_id: str) -> None:
        """Note a renamed entity, whose first write is not a report.

        Home Assistant removes the old state and writes the same value
        under the new id. That write is not the device speaking. The
        outage start is the device's, not the entity's, so a rename
        carries nothing (rule UNAV-04).
        """
        self._renamed_entities.add(new_id)

    def _down_now(self, device_id: str) -> str | None:
        """The state the device as a whole is down in now, "" if up.

        Down means its ESPHome connection has dropped (rule STACK-07),
        its stack calls its node dead (rule STACK-05), or every one of the
        entities that decide (_live_entity_states) reads unavailable or
        unknown. A foreign entity is not read, and an event entity at
        rest holds, as a kept value does. None when nothing can be
        read yet, as while its integration loads after a restart: an
        outage neither starts nor ends on that (rule UNAV-04).
        """
        if self._dropped_esphome(device_id):
            return STATE_UNAVAILABLE
        if self._dead_node(device_id):
            # Saved with the outage start, so the dead word outlives a
            # restart (rule STACK-05).
            return NODE_DEAD_STATE
        states = self._live_entity_states(device_id)
        if not states:
            if self._connection_only(device_id) and self._awake_esphome(device_id):
                # A device whose connection is its only report is up
                # while connected (rule STACK-07).
                return ""
            return None
        # For learning and for the outage start, unknown still counts as
        # gone: a spell with nothing but unknown is not a gap the device
        # made (rule UNAV-04). Judging is another matter, where unknown
        # counts as nothing (rule UNAV-02; _device_down_category).
        if any(state not in BAD_STATES for state in states):
            return ""
        if self._reporting_through_others(device_id):
            # Main entities unavailable while another of its own reports:
            # alive (rule UNAV-01).
            return ""
        if (
            self._main_entities.get(device_id)
            and all(state in (STATE_UNKNOWN, EVENT_RESTING) for state in states)
            and any(
                state not in BAD_STATES
                for state in self._states_of(self._own_entities.get(device_id, ()))
            )
        ):
            # Main entities saying nothing while another of its own holds
            # a value: for the outage start the device is up, so a
            # remote whose action reads unknown while its link quality
            # reports is not down for days (rule UNAV-04). Judging still
            # reads the main entities (_live_entity_states).
            return ""
        return STATE_UNAVAILABLE if STATE_UNAVAILABLE in states else STATE_UNKNOWN

    def _reporting_through_others(self, device_id: str) -> bool:
        """Whether the device has reported since its main entities went
        unavailable: a device whose main entity
        is unavailable is still alive while any entity of its own is
        actively reporting. Read from its last report, which only the
        device moves (not a held value, a firmware notice, a command
        button or another integration's entity), against the
        moment the last of its main entities became unavailable. Only a
        report heard in this run counts: a clock step moves the clock
        without the device speaking (rule UNAV-01)."""
        last = self._reported_at.get(device_id)
        if last is None:
            return False
        # For as long as its freeze window, or an hour while it is still
        # learning: one old report does not keep a dead device alive
        # (rule UNAV-01).
        record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
        window = self._freeze_window(record) if record else None
        if dt_util.utcnow().timestamp() - last > (window or ACTIVE_REPORT_SECONDS):
            return False
        main = self._main_entities.get(device_id)
        if not main:
            return False
        # And something of its own still holds a value: a device whose
        # every entity has since gone unavailable is not reporting,
        # whatever it said before (rule UNAV-01).
        others = [e for e in self._own_entities.get(device_id, ()) if e not in main]
        if not any(state not in BAD_STATES for state in self._states_of(others)):
            return False
        gone_at = None
        for entity_id in main:
            state = self.hass.states.get(entity_id)
            if state is None or state.state != STATE_UNAVAILABLE:
                continue
            changed = state.last_changed.timestamp()
            gone_at = changed if gone_at is None else max(gone_at, changed)
        return gone_at is not None and float(last) > gone_at

    def _node_heard_now(self, device_id: str) -> bool:
        """Whether the node status sensor reads that the node was heard (rule STACK-05)."""
        entity_id = self._node_status_entity.get(device_id)
        if entity_id is None:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and node_heard(self._watched.get(device_id), state.state)

    def _node_reads_up(self, device_id: str) -> bool:
        """Whether the device's node status sensor says the node is up (rule STACK-05)."""
        entity_id = self._node_status_entity.get(device_id)
        if entity_id is None:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and node_up(self._watched.get(device_id), state.state)

    def _gone_as_unavailable(self, record: dict[str, Any]) -> bool:
        """Whether the device's saved outage began with it unavailable or
        dead, rather than reading unknown (rule UNAV-04)."""
        saved = self._saved_down_since(record)
        return saved is not None and saved[1] in (STATE_UNAVAILABLE, NODE_DEAD_STATE)

    @staticmethod
    def _saved_down_since(record: dict[str, Any]) -> tuple[float, str] | None:
        """The record's saved outage start, if it holds a sound one."""
        saved = record.get(DEV_DOWN_SINCE)
        if (
            isinstance(saved, list)
            and len(saved) == 2
            and isinstance(saved[0], (int, float))
            and not isinstance(saved[0], bool)
            and math.isfinite(saved[0])
            and isinstance(saved[1], str)
        ):
            return float(saved[0]), saved[1]
        return None

    @staticmethod
    def _verdict_start(record: dict[str, Any]) -> tuple[float, str] | None:
        """When a standing unavailable or unknown verdict began, if one does."""
        category = record.get(DEV_FROZEN_CATEGORY)
        since = record.get(DEV_FROZEN_SINCE)
        if (
            category in (FREEZE_CATEGORY_UNAVAILABLE, FREEZE_CATEGORY_UNKNOWN)
            and isinstance(since, (int, float))
            and not isinstance(since, bool)
            and math.isfinite(since)
        ):
            return float(since), str(category)
        return None

    def _settle_down(self, device_id: str, entity_id: str | None) -> bool:
        """Start or end the device's outage, from what it reads now.

        One moment per device (rule UNAV-04): saved when the device goes
        down as a whole, and taken when it comes back, whichever entity
        it comes back through. An entity that goes bad alone while
        another still holds a value is not the device's outage and
        starts nothing. Kept with the record, so a restart inside an
        outage cannot lose its start, and free of entity ids, so a
        rename or a removal cannot either. With nothing saved, as at
        the upgrade from a release that saved no start or after a
        damaged one was cleared, a standing unavailable or unknown
        verdict gives the start. True when it recorded a node back from
        dead as contact, so the caller does not record it a second time.
        """
        record = self.data[DATA_DEVICES].get(device_id)
        if not isinstance(record, dict):
            return False
        down = self._down_now(device_id)
        saved = self._saved_down_since(record)
        came_back = False
        if (
            down is None
            and saved is not None
            and self._node_reads_up(device_id)
            and (saved[1] == NODE_DEAD_STATE or self._status_only(device_id))
        ):
            # A start saved some other way on a device whose status
            # sensor is now its only enabled entity (switched off while
            # down, or saved by an older release) ends here too, or it
            # would date the node's next death. Only a dead start
            # counts as contact.
            # A device whose only readable entity is its status sensor
            # has nothing else to say it is up: the node being heard
            # ends the outage, and counts as contact as the change to
            # alive would, since it may have come before Device
            # Sentinel was listening (rule STACK-05).
            down = ""
            came_back = saved[1] == NODE_DEAD_STATE and self._node_heard_now(device_id)
            if came_back:
                self._node_came_back(device_id)
        if down is None:
            return False
        if down:
            if saved is None:
                now = dt_util.utcnow().timestamp()
                verdict = self._verdict_start(record)
                began = verdict[0] if verdict is not None and verdict[0] < now else now
                record[DEV_DOWN_SINCE] = [began, down]
                self._dirty = True
            elif down == NODE_DEAD_STATE and saved[1] != NODE_DEAD_STATE:
                # Dead learned after the outage began some other way:
                # keep the moment, mark it dead so it outlives a restart.
                record[DEV_DOWN_SINCE] = [saved[0], NODE_DEAD_STATE]
                self._dirty = True
            return False
        if record.get(DEV_DOWN_SINCE) is not None:
            record[DEV_DOWN_SINCE] = None
            self._dirty = True
        if saved is None:
            saved = self._verdict_start(record)
        if saved is not None:
            self._taint_after_absence(device_id, entity_id or device_id, saved)
        if came_back:
            self._dead_nodes.discard(device_id)
            self._record_activity(
                device_id,
                self._entry_of_device.get(device_id),
                self._node_status_entity.get(device_id),
                "alive",
            )
        return came_back

    def _status_only(self, device_id: str) -> bool:
        """Whether the node status sensor is the device's only enabled
        entity of its own, read from the registry, so an entity still
        loading after a restart does not count as switched off. An
        entity gone from the registry, as in a rename before the
        rebuild maps its new id, is not taken as switched off either
        (rule STACK-05)."""
        ent_reg = er.async_get(self.hass)
        for entity_id in self._own_entities.get(device_id, ()):
            if entity_id in self._node_status_ids or entity_id.split(".", 1)[0] in NOTICE_DOMAINS:
                # A firmware notice is not the device (rule WATCH-04).
                continue
            ent = ent_reg.async_get(entity_id)
            if ent is None or ent.disabled_by is None:
                return False
        return device_id in self._node_status_entity

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

        The taint carries the reason rather than a flag, so a gap set
        aside says what the device actually did (rule FRZ-14). A taint raised
        inside the startup grace window is held in the grace set
        instead of logged, so the grace release can tell the two apart.
        """
        began, bad_state = pending
        now = dt_util.utcnow().timestamp()
        if began > now:
            # A clock set back since the start was saved (rule FRZ-21): how
            # long it lasted is unknown, so the gap is not learned.
            began = now - 86400.0
        # Device Sentinel's own stops inside the absence are not the
        # device's, as for a gap: an entity written unavailable as Home
        # Assistant shuts down and back as it starts is a restart, not
        # an outage (rules UP-06, FRZ-14).
        gone = now - began - self._stopped_within(began, now)
        if began <= self._taint_consumed_at.get(device_id, 0.0):
            return
        record = self.data[DATA_DEVICES].get(device_id)
        debounce = (
            self._taint_debounce(record)
            if record is not None
            else TAINT_FLOOR_MINUTES * 60.0
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

    def _node_came_back(self, device_id: str) -> None:
        """A dead node its stack has heard again ends the outage.

        As a report ending a down verdict does, so the recovery counts
        from when the device went down rather than from the opening,
        which the debounce dates minutes later, even where the device's
        Last Seen clock has not moved yet (rules STACK-05, UNAV-07).
        """
        record = self.data[DATA_DEVICES].get(device_id)
        if not isinstance(record, dict):
            return
        category = record.get(DEV_FROZEN_CATEGORY)
        if category is None:
            return
        began_as = record.get(DEV_DOWN_BEGAN_AS)
        if category == FREEZE_CATEGORY_FROZEN or began_as not in FREEZE_CATEGORY_PRIORITY:
            began_as = category
        self._report_ends_down[device_id] = (began_as, record.get(DEV_FROZEN_SINCE))

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Handle a state change for a watched device's entity."""
        new_state = event.data.get("new_state")
        if new_state is None:
            # An entity removed: added again, its first value is the one
            # it held (rule WATCH-12).
            self._arm_entity_watch(event.data["entity_id"])
            return
        entity_id = event.data["entity_id"]
        if (
            new_state.state == STATE_UNAVAILABLE
            and new_state.attributes.get("restored") is True
        ):
            # Home Assistant's placeholder for an entity whose
            # integration is reloading or still loading: the same
            # (rule WATCH-12).
            self._arm_entity_watch(entity_id)
        # Guarded rather than indexed: the filter has already checked
        # membership, but that safety lives in HA dispatching filter
        # and handler in one loop turn. The guard makes the invariant
        # local, so a future dispatch change cannot raise here.
        mapped = self._entity_map.get(entity_id)
        if mapped is None:
            return
        device_id, entry_id = mapped
        if entity_id in self._node_status_ids:
            # The stack's word on the node (rule STACK-05): it can start
            # or end the device's outage, and it is never the device
            # speaking. A change to "dead" is the controller failing to
            # reach the node, and "alive" can come from the stack before
            # any value does. A Hue bridge's connectivity sensor takes
            # this branch too and only settles the outage (rule WATCH-04).
            old_state = event.data.get("old_state")
            domain = self._watched.get(device_id)
            record = self.data[DATA_DEVICES].get(device_id)
            saved = self._saved_down_since(record) if isinstance(record, dict) else None
            # Back from dead even through a reload or a restart, where
            # the sensor passes through unavailable on the way (rule
            # STACK-05).
            was_dead = (
                (old_state is not None and node_dead(domain, old_state.state))
                or device_id in self._dead_nodes
                or (saved is not None and saved[1] == NODE_DEAD_STATE)
            )
            back = was_dead and node_heard(domain, new_state.state)
            if back:
                self._dead_nodes.discard(device_id)
            if back:
                self._node_came_back(device_id)
            recorded = self._settle_down(device_id, entity_id)
            if back and not recorded:
                # Z-Wave JS calls a dead node alive only once it has
                # heard it, so that change is the device speaking, the
                # one status change that is: a node can come back on
                # "alive" alone, with no value changing, and a device
                # whose only enabled entity is the status sensor has
                # nothing else to come back through (rule STACK-05).
                self._record_activity(device_id, entry_id, entity_id, new_state.state)
            return
        if entity_id in self._renamed_entities:
            self._renamed_entities.discard(entity_id)
            if event.data.get("old_state") is None and new_state.state not in BAD_STATES:
                # The value moved across by a rename, not a report.
                return
        if entity_id in self._foreign_entities:
            # Another integration's entity on this device (rule WATCH-02):
            # its absence says nothing about the device, and its
            # value counts only as a reading the device publishes
            # nowhere else, never as the device speaking.
            if new_state.state not in BAD_STATES:
                self._record_activity(
                    device_id, entry_id, entity_id, new_state.state,
                    foreign=True,
                )
                if entity_id in self._battery_entity_reverse:
                    self._evaluate_battery(
                        self._battery_entity_reverse[entity_id],
                        notify_on_change=True,
                    )
            return
        if entity_id.split(".", 1)[0] in NOTICE_DOMAINS:
            # A firmware notice or a command button is not the device
            # speaking (rule WATCH-04): it never moves the
            # device's clock or ends a verdict. The outage bookkeeping
            # still reads the device.
            self._settle_down(device_id, entity_id)
            return
        # After a restart, a reload or an entity added again, the value
        # an entity held coming back is its integration's cache, by
        # whatever path it comes: no previous state, Home Assistant's
        # placeholder, unknown first, or the integration's own restore.
        # Kept as a reading, as a republish is, with no clock moved and
        # no outage ended. Only a different value is the device
        # speaking (rule WATCH-12).
        reading = self._read_on_watch(device_id, entity_id, new_state.state)
        self._note_good(entity_id, new_state.state)
        if reading == "cache":
            if new_state.state not in BAD_STATES:
                self._record_activity(
                    device_id, entry_id, entity_id, new_state.state, foreign=True
                )
            return
        # The device's outage starts when it goes down as a whole and
        # ends when the entities that decide hold a value again, read
        # through _live_entity_states (rule UNAV-04). An event entity
        # reads unknown until its next event, after every restart: at
        # rest, holding, so an action entity back at unknown as
        # Zigbee2MQTT starts ends the outage at its real length, not
        # after the hours until the next press.
        # Whether the device was gone as a whole before this change, read
        # before the outage start is taken, for the republish check.
        record_before = self.data[DATA_DEVICES].get(device_id)
        # The saved outage, read before the settle clears it.
        was_gone = (
            self._saved_down_since(record_before)
            if isinstance(record_before, dict)
            else None
        )
        self._settle_down(device_id, entity_id)
        if (
            new_state.state in BAD_STATES
            or self._dropped_esphome(device_id)
            or self._dead_node(device_id)
        ):
            # An absence, or an event entity at rest, says nothing
            # new; and a value written while the connection is down,
            # such as the Status sensor turning off, is not the device
            # speaking (rule STACK-07), nor one written while its stack
            # calls the node dead (rule STACK-05): statistics rewritten after a
            # failed command, or cached values handed back by a reload.
            return
        old_state = event.data.get("old_state")
        # A held entity reading a different value is the device speaking,
        # whatever came before it (rule WATCH-12).
        if reading != "spoke" and self._republished(device_id, old_state, was_gone):
            # A value coming back through a restart or an outage is the
            # stack republishing it, not the device speaking (rule
            # UNAV-05). Kept as a reading,
            # as a foreign entity's value is, so a battery or signal
            # figure is not lost; the device's clock does not move.
            self._record_activity(
                device_id, entry_id, entity_id, new_state.state, foreign=True
            )
            return
        self._record_activity(
            device_id, entry_id, entity_id, new_state.state
        )
        if entity_id in self._battery_entity_reverse:
            self._evaluate_battery(
                self._battery_entity_reverse[entity_id],
                notify_on_change=True,
            )

    def _republished(
        self,
        device_id: str,
        old_state: Any,
        was_gone: tuple[float, str] | None = None,
    ) -> bool:
        """Whether a value coming back is the stack republishing it (rule UNAV-05).

        Only a value returning from unavailable or unknown while the
        device's upstream is held, or inside the startup grace after
        Home Assistant's own restart. Three devices are exempt. One with
        a last-seen clock: its clock is the stack's own record of
        hearing it, so a restored old time cannot move it and a new one
        is the device speaking (rule FRZ-11). One on an integration that
        fetches its readings from the device itself (FETCHING_INTEGRATIONS),
        whose reading is the device answering. And one Device Sentinel
        had judged unavailable: its stack now saying it is available is
        a genuine recovery (rule UP-06).
        """
        if old_state is None or old_state.state not in BAD_STATES:
            return False
        if device_id in self._last_seen_entity:
            return False
        if self._watched.get(device_id) in FETCHING_INTEGRATIONS:
            # Fetched from the device, not restored from a cache: the
            # device answering (rule UP-06).
            return False
        record = self.data.get(DATA_DEVICES, {}).get(device_id) or {}
        # The stack's own Last Seen clock, as ZHA keeps (rule STACK-04):
        # a value is the device speaking only if the radio has heard it
        # since its last report. Otherwise the stack, restarted or
        # reloaded, is handing back what it kept, however briefly it
        # was down.
        heard = stack_last_heard(self.hass, self._watched.get(device_id), device_id)
        if heard is not None:
            last = record.get(DEV_LAST_ACTIVITY)
            return (
                isinstance(last, (int, float))
                and not isinstance(last, bool)
                and heard[1] <= last
            )
        if record.get(DEV_FROZEN_CATEGORY) == FREEZE_CATEGORY_UNAVAILABLE:
            return False
        now = dt_util.utcnow().timestamp()
        held = self._held_by_upstream(device_id, now)
        if not (self._in_startup_grace() or held):
            return False
        if was_gone is not None and self._unavailable_muted(device_id):
            # Gone as a whole while muted for unavailable, so judged
            # nothing: its return is the recovery an unavailable verdict
            # would have had. Only an outage that began before the
            # restart or the stack's hold and outlasted the debounce: a
            # restart's own minute of unavailable is not one (rule
            # UNAV-05).
            saved = was_gone
            # Up to when Device Sentinel last listened: on a full
            # restart Zigbee2MQTT stops a second or two before Home
            # Assistant, and the time the system is off is no part of
            # the device's own outage (rule UNAV-05).
            last_alive = getattr(self, "_last_alive", None)
            began = (
                self.upstream_down_since(device_id)[1]  # type: ignore[index]
                if held
                else last_alive
                if isinstance(last_alive, (int, float))
                else self._grace_until - STARTUP_GRACE_SECONDS
            )
            if (
                saved is not None
                and saved[1] in (STATE_UNAVAILABLE, NODE_DEAD_STATE)
                and saved[0] + FREEZE_UNAVAILABLE_DEBOUNCE <= began
            ):
                return False
        return True

    @callback
    def _command_filter(self, event_data: Any) -> bool:
        """Fast pre-filter: commands naming an entity of a watched device."""
        return bool(self._command_entities(event_data))

    def _command_entities(self, event_data: Any) -> list[str]:
        """The watched entities a service call names, if any.

        A call names its targets under `service_data` as one entity
        id or a list of them (rule FRZ-19). Calls aimed at an
        area, a device id or a label are not resolved here: Home
        Assistant expands those inside the call, and the reply the
        device sends is still a reply, so the cost of missing one is
        a learned gap, the direction the rule was already taking.
        """
        try:
            data = event_data.get("service_data") or {}
            ids = data.get(ATTR_ENTITY_ID)
        except AttributeError:
            return []
        # Home Assistant also accepts one string of comma-separated ids
        # and any letter case.
        if isinstance(ids, str):
            ids = ids.split(",")
        if not isinstance(ids, list):
            return []
        named = (i.strip().lower() for i in ids if isinstance(i, str))
        return [i for i in named if i in self._entity_map]

    @callback
    def _on_call_service(self, event: Event[Any]) -> None:
        """Remember when each watched device was last commanded (rule FRZ-19)."""
        now = dt_util.utcnow().timestamp()
        for entity_id in self._command_entities(event.data):
            owner = self._entity_map[entity_id][0]
            if entity_id in self._foreign_entities:
                continue
            self._commanded_at[owner] = now

    def _recovered_after_command(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> bool:
        """Whether this report clears a freeze and follows a command.

        True only while the device stands frozen and a command to one
        of its own entities arrived within COMMANDED_RECOVERY_SECONDS
        (rule FRZ-19). The command is spent once read, so a second
        report after it is the device's own.
        """
        if record.get(DEV_FROZEN_CATEGORY) != FREEZE_CATEGORY_FROZEN:
            return False
        at = self._commanded_at.get(device_id)
        if at is None:
            return False
        # A command stamped after now means the system clock was set
        # back since: it is no reply to anything (rule FRZ-21).
        if not 0.0 <= now - at <= COMMANDED_RECOVERY_SECONDS:
            return False
        self._commanded_at.pop(device_id, None)
        return True

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
        if entity_id in self._node_status_ids or entity_id.split(".", 1)[0] in NOTICE_DOMAINS:
            # Never the device speaking: the stack's word on the node,
            # or a firmware notice or command button rewritten at a
            # refresh (rule WATCH-04).
            self._settle_down(device_id, entity_id)
            return
        foreign = entity_id in self._foreign_entities
        if self._read_on_watch(device_id, entity_id, new_state.state) == "cache":
            # The same value written again never counts while on watch,
            # and nor does an own entity that never votes. A different
            # value, already shown when the watch began, is the device
            # speaking and is recorded as a report below (rule WATCH-12).
            return
        if not foreign:
            self._note_good(entity_id, new_state.state)
            self._settle_down(device_id, entity_id)
            # A same-value write while the connection is down is not
            # the device speaking either (rule STACK-07), nor one while
            # the node is dead (rule STACK-05).
            if self._dropped_esphome(device_id) or self._dead_node(device_id):
                return
        self._record_activity(
            device_id, entry_id, entity_id, new_state.state,
            foreign=foreign,
        )

    @callback
    def _device_is_speaking(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> bool:
        """Whether this reading comes from a device that is speaking.

        A device whose clock is its own Last Seen value cannot be
        revived by a replayed message, because the replay carries the
        old value (rule FRZ-11). Its signal is another matter: at a
        restart the broker hands back every retained payload, and the
        link quality in it would be fed to the statistics as though a
        dead device had just answered.

        A device with no Last Seen clock is heard whenever anything
        arrives, so the question does not arise and the reading
        counts. So does one still learning its rhythm,
        which has no window to be overdue against.
        """
        if device_id not in self._last_seen_entity:
            return True
        window = self._freeze_window(record)
        if window is None:
            return True
        stamp = self._contact_stamp(device_id, now)
        if stamp is None:
            stamp = record.get(DEV_LAST_ACTIVITY)
        if stamp is None:
            return False
        return now - stamp <= window

    @callback
    def _record_activity(
        self,
        device_id: str,
        entry_id: str | None,
        entity_id: str | None = None,
        state: str | None = None,
        foreign: bool = False,
    ) -> None:
        """Stamp the device clock, completing a gap for learning if clean.

        A foreign entity (rule WATCH-02) feeds its reading and stops there:
        it is not the device speaking, so it neither stamps the clock
        nor counts toward an integration's update burst.
        """
        now = dt_util.utcnow().timestamp()
        if not foreign:
            self._muted_down.discard(device_id)
        record = self.data[DATA_DEVICES].get(device_id)
        if record is None:
            record = _new_device_record(dt_util.utcnow().isoformat(), None)
            self.data[DATA_DEVICES][device_id] = record

        if entity_id in self._signal_entities and state is not None:
            try:
                value = float(state)
            except ValueError:
                value = None
            if value is not None and not math.isfinite(value):
                # float() accepts nan, inf, -inf, infinity and 1e999
                # and raises on none of them, and ESPHome and MQTT
                # sensors publish nan for a reading that failed. One
                # such value would reach the day's statistics, and every
                # figure worked out from them would be nan. A reading that is not a
                # finite number is not a reading (rules SIG-04, BAT-02).
                LOGGER.debug(
                    "device_sentinel: %s reported %s, which is not a "
                    "signal reading; ignored",
                    entity_id,
                    state,
                )
                value = None
            if value is not None and not (
                SIGNAL_RSSI_LOWEST <= value <= SIGNAL_LQI_HIGHEST
            ):
                # Finite, and still not a reading: no radio reports
                # it. Ignored, never brought into range (rule SIG-04).
                LOGGER.debug(
                    "device_sentinel: %s reported %s, which is outside "
                    "any signal scale; ignored",
                    entity_id,
                    state,
                )
                value = None
            if value is not None and self._device_is_speaking(
                device_id, record, now
            ):
                self._feed_signal(record, value, now)

        if foreign:
            return
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
            # restored state, or an entity reacting to something
            # else. Count it as seen and change nothing
            # about liveness. The silence keeps running, which is
            # what makes the muting rules unnecessary here.
            record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
            self._dirty = True
            return
        # When the device itself last spoke, past the protocol clock's
        # word that it did, never moved by a clock step or a restart
        # (_reporting_through_others; rule UNAV-01).
        self._reported_at[device_id] = now

        # When the silence this report ends began: a recovery's "down
        # for" counts from here, the device's last report, rather than
        # from the moment its verdict was reached (rule UNAV-07).
        # Not across a stretch the device was set aside, disabled or
        # excluded by a person: that is not the device being down, and
        # the recovery keeps its own opening.
        # A device taken back counts from when it was watched again:
        # the time nobody watched it is not its silence (rule WATCH-08).
        back = record.get(DEV_WATCHED_FROM)
        if last is not None and record.get(DEV_SET_ASIDE_SINCE) is None:
            self._silence_began[device_id] = last
        elif (
            last is not None
            and isinstance(back, (int, float))
            and not isinstance(back, bool)
            and back > last
        ):
            self._silence_began[device_id] = float(back)
        else:
            self._silence_began.pop(device_id, None)
        # Whether this report ends a down verdict, read before the
        # verdict clears below: a recovery that follows it counts from
        # the silence it ended; one with no report counts from the last
        # report. Read from the verdict, not from stamps, which a Last
        # Seen clock or a clock reset can place before the opening.
        # It keeps how the trouble began (rule UNAV-07): a freeze
        # counts from the last report, while a
        # device that went straight to unavailable counts from when it
        # went, so a five-minute drop on a quiet device reads five
        # minutes, not the hours of quiet before it.
        category = record.get(DEV_FROZEN_CATEGORY)
        if category is None:
            self._report_ends_down[device_id] = None
        else:
            # A damaged saved value is not trusted, and a standing
            # freeze can only have begun as a freeze (rule UNAV-07).
            began_as = record.get(DEV_DOWN_BEGAN_AS)
            if category == FREEZE_CATEGORY_FROZEN or began_as not in FREEZE_CATEGORY_PRIORITY:
                began_as = category
            self._report_ends_down[device_id] = (
                began_as,
                record.get(DEV_FROZEN_SINCE),
            )

        # A taint is consumed by a stamp the protocol vouches for:
        # the outage ended here, and the gap across it is set aside
        # because Device Sentinel could not hear all of it (rule FRZ-14).
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
        if not tainted and last is not None:
            # A gap is learned only if Device Sentinel could trust all
            # of it: see `_gap_untrusted` for the rule (rule FRZ-12).
            tainted = self._gap_untrusted(device_id, record, last, stamp)
        downtime_note: str | None = None
        learned_gap: float | None = None
        # Today's longest gap before this one, put back if this gap is
        # discarded below (rule FRZ-15): the day keeps the real gaps it
        # had, rather than losing them with the one set aside.
        today_before = record.get(DEV_TODAY_MAX)
        if not tainted and last is not None:
            gap = stamp - last
            learned_gap = gap
            # Take the downtime out (rule FRZ-12): the stops of Device
            # Sentinel itself inside the gap are not the device's
            # silence, so the gap is learned without them, and the
            # episode says so.
            stopped = self._stopped_within(last, stamp)
            if stopped > 0.0:
                learned_gap = max(0.0, gap - stopped)
                downtime_note = LEARNED_DOWNTIME_OUT
            # No cap on a gap that ends under a freeze verdict: the
            # Trimmed Maximum sets aside its longest day and the
            # Log-Normal Percentile its days far above normal, so one
            # long day cannot stretch the wait in use, and a slow
            # reporter learns the quiet spells it really has (rule
            # FRZ-12). A hand on the device is read below, from the
            # command that preceded the report.
            # Held at the retention (rule FRZ-13): a silence longer
            # than the history kept is learned as the retention and
            # shown as more than it.
            learned_gap = min(learned_gap, self.gap_cap())
            if (
                record[DEV_TODAY_MAX] is None
                or learned_gap > record[DEV_TODAY_MAX]
            ):
                record[DEV_TODAY_MAX] = learned_gap

        # Taint is the only muting of learning. Grace and storm mute
        # nothing: for a device with a protocol clock they are not
        # needed, since a replayed payload cannot advance it, and for
        # a device without one they would discard the only evidence
        # there is (rules FRZ-11, FRZ-14).
        learned = (
            f"no ({tainted})"
            if tainted
            else (downtime_note or "yes")
        )
        # A recovery during a pairing window is a hand re-pair, not a
        # self-recovery, so its gap is discarded whatever the taint
        # decided (rule FRZ-16). This overrides the debounce because pairing
        # is a stronger, more specific signal than duration. Guarded so
        # that if no reader, no bridge, or any failure, the taint
        # decision above stands and nothing is made worse (rule FRZ-15).
        if self._recovered_during_pairing(device_id, now):
            learned = LEARNED_PAIRING
            # A re-pair starts the device's 42-day count again, as a
            # ZHA re-pair does (rule FRZ-05): a device that was down, or
            # silent past its window, and came back while pairing was
            # open. A device reporting on its rhythm while someone pairs
            # another keeps its count.
            window = self._freeze_window(record)
            if category is not None or (
                last is not None
                and window is not None
                and stamp - last > window
            ):
                record[DEV_LOGNORMAL_DAYS] = 0
                self._mark_cold_dirty()
            if not tainted and learned_gap is not None:
                # Undo the daily-max update this gap just made, so a
                # pairing gap never widens the learned rhythm. The
                # retraction uses what was actually learned, the gap
                # with Device Sentinel's own stops taken out (rule FRZ-12).
                self._retract_today_max(record, learned_gap, today_before)
            LOGGER.debug(
                "Device %s recovered during a Z2M pairing window; gap "
                "discarded as a pairing intervention",
                device_id,
            )
        elif record.get(DEV_SET_ASIDE_SINCE) is not None:
            # The device was set aside for part of this gap, so the
            # silence is a disabled entity or integration rather than
            # the device's own rhythm (rule FRZ-15). Same treatment as
            # pairing and maintenance: refused and retracted, so two
            # weeks switched off cannot teach a two-week window of
            # normal silence. The stamp is cleared by the
            # device's own report, below.
            learned = LEARNED_DISABLED
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap, today_before)
            LOGGER.debug(
                "Device %s returned from being set aside; gap "
                "discarded as administrative",
                device_id,
            )
        elif self._handled_recently(device_id, now):
            # ZHA says a person re-paired, reconfigured or removed
            # this device while it was silent, so the gap measures
            # the hand rather than the device (rule FRZ-17). The
            # cause was already recorded as a system event when the
            # message arrived, and attribution names it in the brief
            # and the episode; this is the other half: without the
            # retraction the report says the gap was not learned while
            # the daily maximum says it was.
            #
            # Below pairing and being set aside, above maintenance:
            # a named device on a stack that announced it is more
            # specific than a window a person declared, and less
            # specific than a pairing window that names the stack
            # and the moment both (rule FRZ-15).
            learned = LEARNED_HANDLED
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap, today_before)
            LOGGER.debug(
                "Device %s was handled by a person; gap discarded "
                "rather than learned",
                device_id,
            )
        elif self._recovered_during_maintenance(now):
            # A recovery inside a declared maintenance window is the
            # person's hands, not the device's own rhythm (rule
            # FRZ-18). Pairing takes precedence where both windows are
            # open, because it is the more specific signal: it names
            # the stack, where maintenance names only the person. Same
            # retraction as pairing; detections are untouched,
            # since a device going down during maintenance is not an
            # intervention.
            learned = LEARNED_MAINTENANCE
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap, today_before)
            LOGGER.debug(
                "Device %s recovered during a maintenance window; gap "
                "discarded as a hand fix",
                device_id,
            )
        elif self._recovered_after_command(device_id, record, now):
            # The report that clears a freeze verdict followed a
            # command to the device (rule FRZ-19): a toggle
            # from a device card or an automation. The device answered,
            # so it is reachable and the verdict clears below; the gap
            # measures nobody's hand on the switch rather than the
            # device's own rhythm, so it is discarded as a pairing gap
            # is. Last on the ladder, below every window a stack or a
            # person declared, and read only while a freeze stands:
            # a command on an ordinary day changes nothing.
            learned = LEARNED_COMMANDED
            if not tainted and learned_gap is not None:
                self._retract_today_max(record, learned_gap, today_before)
            LOGGER.debug(
                "Device %s reported after a command to it while frozen; "
                "gap discarded as a commanded recovery",
                device_id,
            )
        self._close_episode(device_id, stamp, learned, taint_seconds)

        record[DEV_LAST_ACTIVITY] = stamp
        record[DEV_EVENT_COUNT] = int(record[DEV_EVENT_COUNT]) + 1
        if record.get(DEV_SET_ASIDE_SINCE) is not None:
            # Spent: the gap spanning the absence has been judged
            # above, and the next silence is the device's own again.
            # Cleared here rather than when the registry brought it
            # back, which happens before it speaks (rule FRZ-15).
            record[DEV_SET_ASIDE_SINCE] = None
        # Heard: its silence runs from this report again (rule WATCH-08).
        if record.get(DEV_WATCHED_FROM) is not None:
            record[DEV_WATCHED_FROM] = None
            self._mark_cold_dirty()
        self._dirty = True

        # Recovery is live: a device the protocol has heard from is
        # alive, so any standing freeze verdict clears the instant it
        # speaks. A republish does not clear one, or a few seconds'
        # bridge blip would erase hours of silence (rule FRZ-11).
        self._clear_freeze_verdict(device_id, record)

    # ------------------------------------------------------------ timers


    def _schedule_brief(self) -> None:
        """Arm the daily write that closes the brief's window.

        Without a write at the brief hour every brief would say "in
        progress" and no window would finish before its file was
        replaced (rule BRIEF-10). The schedule is separate from the
        rest because the brief time is a live option: changing it
        re-arms here rather than waiting for a restart.
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
        because this is the only write that closes a window (rule BRIEF-11):
        a regenerate or a midnight rewrite produces an in-progress
        document, and mailing one of those would deliver the same
        day several times, each incomplete.

        Once a day (rule BRIEF-11): when clocks fall back, a brief time
        inside the repeated hour fires twice, and the second firing
        would close and mail the same day again. The day closed is
        stored, and a firing for that day sends nothing.
        """
        today = dt_util.now().date().isoformat()
        if self.data.get(DATA_BRIEF_CLOSED_DAY) == today:
            LOGGER.info(
                "device_sentinel: the brief for %s was already sent; "
                "a second firing in a repeated hour sends nothing",
                today,
            )
            return
        # Dirty, not critical: the day is read again an hour later at
        # the earliest, in the repeated hour, and a routine save writes
        # it long before then. Forcing a write here would race the
        # minute check's own save when both fall on the brief minute.
        self.data[DATA_BRIEF_CLOSED_DAY] = today
        self._dirty = True
        text = await self._write_reports_guarded(BRIEF_TRIGGER)
        if text is not None:
            await self.async_send_brief(text)
        # After the send, not before it, so a Repair raised here
        # cannot delay or fail the delivery it travels beside
        # (rule REP-07). The fold still runs the storage shape check,
        # the copy and the repair; only the judging is here.
        self._evaluate_repairs(REPAIR_MOMENT_BRIEF)

    @staticmethod
    def _monotonic() -> float:
        """A clock nobody can set, read here so a test can stand in."""
        return time.monotonic()

    async def _detect_clock_reset(self) -> None:
        """Notice the system clock being moved, and restart the clocks.

        A clock reset is a person's act (rule FRZ-21), and a system
        paused or suspended reads the same way, because the monotonic
        clock stops with it: a virtual machine paused for a backup
        comes back with its wall clock ahead. Nobody was watching in
        either case, so both restart the clocks, and the system event
        names both. Between one minute check and the next the wall clock and
        a monotonic clock
        advance together; when they disagree by more than the
        threshold, the wall clock was set. Backward, every report is
        stamped before its device's clock and ignored until real time
        catches up, so a device that dies is invisible for the size of
        the step. Forward, every device looks silent for the size of
        the step, and the first check would list the fast ones frozen.
        So the check comes first, before anything is judged, and every
        device's clock restarts at this moment the way a lost clocks
        file restarts them (rule STOR-10), a frozen device keeping its
        verdict. The time before is
        unwatched, and the next gap each device completes is measured
        from here.
        """
        wall = dt_util.utcnow().timestamp()
        mono = self._monotonic()
        previous_wall, previous_mono = self._tick_wall, self._tick_mono
        self._tick_wall, self._tick_mono = wall, mono
        if previous_wall is None or previous_mono is None:
            return
        drift = (wall - previous_wall) - (mono - previous_mono)
        if abs(drift) < CLOCK_RESET_THRESHOLD_SECONDS:
            return
        restarted = 0
        for record in self.data[DATA_DEVICES].values():
            if not isinstance(record, dict):
                continue
            # An outage's start restarts here, as the device clocks
            # do: which clock it was written in cannot be told, and
            # the time before is unwatched (rule FRZ-21). So does the
            # start of an unavailable or unknown verdict, or of one
            # still being debounced.
            saved = self._saved_down_since(record)
            if saved is not None:
                record[DEV_DOWN_SINCE] = [wall, saved[1]]
            since = record.get(DEV_FROZEN_SINCE)
            if (
                record.get(DEV_FROZEN_CATEGORY)
                in (None, FREEZE_CATEGORY_UNAVAILABLE, FREEZE_CATEGORY_UNKNOWN)
                and isinstance(since, (int, float))
                and not isinstance(since, bool)
            ):
                record[DEV_FROZEN_SINCE] = wall
            # The set-aside stamp moves too, so a clock set back while
            # a device is set aside does not read as silence before it
            # (rule WATCH-08).
            for field in (DEV_WATCHED_FROM, DEV_SET_ASIDE_SINCE):
                moment = record.get(field)
                if isinstance(moment, (int, float)) and not isinstance(moment, bool):
                    record[field] = float(moment) + drift
            if record.get(DEV_LAST_ACTIVITY) is None:
                continue
            since = record.get(DEV_FROZEN_SINCE)
            if record.get(DEV_FROZEN_CATEGORY) == FREEZE_CATEGORY_FROZEN and (
                isinstance(since, (int, float)) and not isinstance(since, bool)
            ):
                # Clearly past its window, so the verdict holds on
                # this check and every one after it (rule FRZ-21).
                record[DEV_LAST_ACTIVITY] = (
                    wall - self._lost_clock_window(record) - 60.0
                )
                record[DEV_FROZEN_SINCE] = min(float(since), wall)
            else:
                record[DEV_LAST_ACTIVITY] = wall
            # An outage running across the step has no known length,
            # so the gap it ends is not learned (rule FRZ-21).
            record[DEV_TAINTED] = (
                False if saved is None
                else TAINT_UNKNOWN if saved[1] == STATE_UNKNOWN
                else TAINT_UNAVAILABLE
            )
            restarted += 1
        self._shift_moments(drift)
        self._clock_reset = (wall, drift)
        self._clock_step = (previous_wall, wall)
        # A report heard before the step cannot be set against a moment
        # after it (rule FRZ-21).
        self._reported_at.clear()
        # A restart's downtime credit was measured in the old clock:
        # with the clocks restarted here it has nothing left to cover,
        # and kept, it would put a frozen device back inside its window
        # (rule FRZ-21).
        self._downtime = 0.0
        self._last_alive = None
        self._record_system_event(
            SYS_CLOCK_RESET,
            detail=f"{_shift(drift)}, {restarted} clocks restarted",
            duration=abs(drift),
        )
        LOGGER.warning(
            "device_sentinel: the system clock moved %s between two "
            "minute checks; %d device clocks restarted and a system "
            "event written",
            _shift(drift),
            restarted,
        )
        self._critical = True
        self._evaluate_repairs(REPAIR_MOMENT_GRACE)

    # The moments the coordinator holds in memory as wall-clock times,
    # each the start or the end of a window still running. A clock
    # reset moves them by its size (rule FRZ-21), so each window keeps
    # the time that really passed: after a backward step of two hours
    # the startup grace would otherwise hold every announcement for up
    # to two hours, and a maintenance window would run two hours long;
    # forward, both would close early. Stored history is not moved.
    _MOMENTS = (
        "_grace_until",
        "_maintenance_until",
        "_maintenance_opened_at",
        "_broker_down_at",
        "_wifi_down_at",
        "_wifi_recovering_at",
        "_wifi_scan_gone_at",
        "_wifi_scan_down_at",
    )
    _MOMENT_MAPS = (
        "_bridge_down_at",
        "_entry_down_at",
        "_bridge_recovering_at",
        "_integration_recovering_at",
        "_pairing_open_at",
        "_handled_at",
        "_taint_consumed_at",
        "_commanded_at",
        "_silence_began",
    )
    _MOMENT_PAIRS = (
        "_bridge_handback",
        "_integration_handback",
        "_wifi_handback",
    )

    def _counted_from(self, moment: float | None) -> float | None:
        """A moment as a duration counts it: from the last clock step
        when it lies before the step, since the time across a step is
        unknown (rule FRZ-21)."""
        step = self._clock_step
        if moment is None or step is None:
            return moment
        before, at = step
        return at if moment <= before else moment

    def _shift_moments(self, drift: float) -> None:
        """Move every in-memory wall-clock moment by a reset's size."""

        def moved(value: Any) -> Any:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return value
            return float(value) + drift

        for name in self._MOMENTS:
            if hasattr(self, name):
                setattr(self, name, moved(getattr(self, name)))
        for name in self._MOMENT_MAPS:
            held = getattr(self, name, None)
            if isinstance(held, dict):
                for key, value in list(held.items()):
                    held[key] = moved(value)
        for name in self._MOMENT_PAIRS:
            held = getattr(self, name, None)
            if isinstance(held, dict):
                for key, value in list(held.items()):
                    if isinstance(value, tuple):
                        held[key] = tuple(moved(v) for v in value)

    async def _close_brief_if_skipped(self) -> None:
        """Send a brief whose time the clock skipped (rule BRIEF-11).

        When clocks spring forward, a brief time inside the skipped
        hour never comes, Home Assistant's tracker never fires, and
        that day's window is never closed or mailed. Read on the
        minute check: when today's brief time does not exist in local
        time, the moment has passed and today is not yet closed, the
        brief closes now. A brief time that exists is left to the
        tracker, so an ordinary day never sends twice and a day the
        system was down at the brief hour is not sent late.
        """
        local_now = dt_util.now()
        hour, minute = self._brief_hour_minute()
        target = local_now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        exists = (
            target.astimezone(dt_util.UTC).astimezone(target.tzinfo)
            == target
        )
        if exists or local_now.timestamp() < target.timestamp():
            return
        if self.data.get(DATA_BRIEF_CLOSED_DAY) == local_now.date().isoformat():
            return
        LOGGER.info(
            "device_sentinel: the brief time %02d:%02d does not exist "
            "today, the clock skipped it; closing the brief now",
            hour,
            minute,
        )
        await self._on_brief_time(None)

    @property
    def _excluded_device_ids(self) -> set[str]:
        """Return the devices set aside because they, or their
        integration, are excluded.

        Read by the record discard and the episode cleanup. The
        enable buttons do not need it: they reach watched devices
        only, and every excluded device is set aside (rule WATCH-03).
        """
        excluded = {
            device_id
            for device_id, (_name, _domain, reason) in self._set_aside.items()
            if reason == SET_ASIDE_EXCLUDED
        }
        # A device excluded on its own and then removed from Home
        # Assistant before midnight is no longer set aside, since the
        # registry no longer names it, and its record would be held
        # for 30 days. The person asked for it to go, so the fold takes
        # it all the same (rule WATCH-07).
        return excluded | (set(self.excluded_devices) - set(self._watched))

    async def _repair_storage(
        self, moment: str, faults: list[tuple[str, str, str]]
    ) -> None:
        """Repair the live document at the point of detection.

        The save seam calls this the moment its check finds a fault:
        evidence copy of everything first (rule STOR-11), then the
        repair in place, then the event and the notice. Nobody is
        asked anything, because no person can judge a damaged row
        (rule STOR-09).
        """
        stamp, copied = await async_copy_evidence(self.hass)
        if stamp:
            LOGGER.warning(
                "Storage evidence copied to trim_backups as %s before "
                "the repair writes: %s",
                stamp,
                ", ".join(copied),
            )
        await self._repair_in_place(moment, faults, stamp)

    async def _repair_in_place(
        self,
        moment: str,
        faults: list[tuple[str, str, str]],
        stamp: str | None,
    ) -> None:
        """Drop what cannot be used, reset what can be, and say so.

        The repair half of the boundary (rule STOR-09): damaged table
        rows are dropped, a record that is not a record is dropped,
        and a damaged record field is reset to its default with the
        rest of the record kept. The activity clocks bank first,
        so a damaged clock restarts honestly at now
        rather than being reset to a fresh record's None. Every
        repair writes a system event and raises the one notice card,
        which names what was repaired and where the originals are
        and asks for nothing.
        """
        banked = self._bank_damaged_clocks(faults)
        dropped_rows = repair_tables(self.data)
        dropped_records, reset_fields = self._repair_records()
        parts: list[str] = []
        for table, count in sorted(dropped_rows.items()):
            parts.append(f"{count} row(s) dropped from {table}")
        if dropped_records:
            parts.append(
                f"{len(dropped_records)} record(s) dropped: "
                + ", ".join(
                    self._device_name(d) for d in dropped_records[:5]
                )
            )
        if banked:
            parts.append(f"{banked} activity clock(s) restarted")
        if reset_fields:
            named = ", ".join(
                f"{self._device_name(d)}.{field}"
                for d, field in reset_fields[:5]
            )
            parts.append(
                f"{len(reset_fields)} field(s) reset to defaults ({named})"
            )
        what = "; ".join(parts) if parts else (
            f"{len(faults)} fault(s) found and nothing needed changing"
        )
        where = (
            f"the originals are in {TRIM_BACKUP_DIR} under {stamp}"
            if stamp
            else "the evidence copy could not be written"
        )
        LOGGER.warning("Storage repaired at %s: %s; %s", moment, what, where)
        self._record_system_event(
            SYS_STORAGE_REPAIR,
            detail=f"{moment}: {what}; {where}",
        )
        self._repair_notice = {"moment": moment, "what": what, "where": where}
        self._load_faulty = True
        if moment == "load":
            # Each repair the load made, not only restarted clocks, and
            # none made at a save (rule STOR-12).
            self._repairs_at_load += max(
                1,
                sum(dropped_rows.values()) + len(dropped_records) + banked + len(reset_fields),
            )

    async def _repair_containers_at_load(
        self,
        loaded: dict[str, Any],
        faults: list[tuple[str, str, str]],
    ) -> None:
        """Gate 1's repair, at the point of detection (rule STOR-05).

        Its own evidence copy and its own notice, because gate 1 and
        gate 2 answer different questions and a person reading one
        card should not have to work out which. The copies are
        stamped to the second and collision-suffixed, so a boot where
        both gates fire keeps the file as it arrived and the state
        gate 1 handed on, which is what says whether gate 1's repair
        caused gate 2's fault or merely preceded it.

        No system event here: the event log is a table this repair
        may be emptying, so writing into it mid-repair would write
        into what is being repaired. Gate 2's event covers the boot,
        and the log carries the detail (rule STOR-12).
        """
        stamp, copied = await async_copy_evidence(self.hass)
        if stamp:
            LOGGER.warning(
                "Storage evidence copied to trim_backups as %s before "
                "the container repair writes: %s",
                stamp,
                ", ".join(copied),
            )
        counts = repair_containers(loaded)
        what = (
            "; ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
            or f"{len(faults)} fault(s) found and nothing needed changing"
        )
        where = (
            f"the originals are in {TRIM_BACKUP_DIR} under {stamp}"
            if stamp
            else "the evidence copy could not be written"
        )
        named = "; ".join(
            f"{holder}.{field}: {why}" for holder, field, why in faults[:5]
        )
        LOGGER.warning(
            "Storage containers repaired before the load-time steps: "
            "%s (%s); %s",
            what,
            named,
            where,
        )
        self._container_notice = {"what": what, "where": where}
        self._load_faulty = True
        # A repair the load made (rule STOR-12).
        self._repairs_at_load += max(1, len(faults))

    def _repair_records(self) -> tuple[list[str], list[tuple[str, str]]]:
        """Repair the device records in place, by the two rules.

        A record that is not a record is dropped; a damaged field is
        reset to the fresh record's default and the rest of the
        record is kept (rule STOR-09). Returns what was
        dropped and what was reset, for the notice.
        """
        devices = self.data.get(DATA_DEVICES)
        if not isinstance(devices, dict):
            self.data[DATA_DEVICES] = devices = {}
        dropped: list[str] = []
        reset: list[tuple[str, str]] = []
        template = _new_device_record(dt_util.utcnow().isoformat(), None)
        for device_id, field, _why in check_records(devices):
            if device_id == "*":
                continue
            record = devices.get(device_id)
            if record is None:
                continue
            if field == "*" or not isinstance(record, dict):
                devices.pop(device_id, None)
                dropped.append(device_id)
                continue
            if field not in template:
                # Only a retired field reaches here (rule STOR-19); its
                # repair is removal, the answer
                # the reconciler gives it too. A newer version's field
                # is never flagged, so never removed.
                record.pop(field, None)
            else:
                # A fresh copy per record, never the template's own
                # object: two records reset in the same pass would
                # otherwise share one list, and a reading written
                # into one would appear in the other. Gate 1 gives its
                # fields a fresh list the same way (rule STOR-09).
                record[field] = copy.deepcopy(template[field])
            reset.append((device_id, field))
        return dropped, reset

    def _convert_raw_batteries(self, devices: dict[str, Any]) -> list[str]:
        """Halve the stored battery history of every device that can
        only be on Zigbee's raw scale (rule BAT-02). Returns the names
        of the devices converted."""
        converted: list[str] = []
        for device_id, record in devices.items():
            if isinstance(record, dict) and raw_battery_history(record):
                mark_raw_battery(record)
                converted.append(str(self._device_name(device_id) or device_id))
        return converted

    def gap_cap(self) -> float:
        """The longest gap this house can learn: its retention (rule FRZ-13)."""
        return float(self.retention_days) * 86400.0

    def _cap_gaps_at_retention(self, devices: dict[str, Any]) -> int:
        """Hold every stored gap at the retention (rule FRZ-13).

        A silence longer than the history kept cannot be learned
        from, and the stored day says so as "more than" the retention
        in every report. Only positive numbers are held; anything else
        is the boundary's to judge.
        """
        cap = self.gap_cap()
        held = 0
        for record in devices.values():
            if not isinstance(record, dict):
                continue
            series = record.get(DEV_DAILY_MAX)
            if isinstance(series, list):
                for i, gap in enumerate(series):
                    if (
                        isinstance(gap, (int, float))
                        and not isinstance(gap, bool)
                        and gap > cap
                    ):
                        series[i] = cap
                        held += 1
            today = record.get(DEV_TODAY_MAX)
            if (
                isinstance(today, (int, float))
                and not isinstance(today, bool)
                and today > cap
            ):
                record[DEV_TODAY_MAX] = cap
                held += 1
        return held

    def _cap_gap_series(
        self, devices: dict[str, Any], loaded: dict[str, Any]
    ) -> tuple[int, int]:
        """Forget every learned gap longer than the device has been watched.

        A daily maximum larger than the time the device has been
        watched cannot be a silence anybody observed, and left in the
        series it becomes a freeze window no silence can ever close
        (rule FRZ-13). It is forgotten, not cut down to the watch: a
        gap is learned only if Device Sentinel could have heard the
        device for all of it, and nobody was listening for the part
        before the watch began (rule FRZ-12). The forgotten day reads
        as skipped in the history's dates. Returns how many elements
        were forgotten and on how many devices.
        """
        installed = loaded.get(DATA_FIRST_INSTALLED)
        now = dt_util.utcnow().timestamp()
        elements = 0
        touched = 0
        for record in devices.values():
            if not isinstance(record, dict):
                continue
            series = record.get(DEV_DAILY_MAX)
            if not isinstance(series, list) or not series:
                continue
            watched = _watched_seconds(record, now, installed)
            if watched is None:
                continue
            over = [i for i, gap in enumerate(series) if gap > watched]
            if not over:
                continue
            end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
            for i in reversed(over):
                entry_removed(record, FAMILY_GAP, len(series), i, end)
                del series[i]
            elements += len(over)
            touched += 1
        return elements, touched

    def _note_writer_fault(self, table: str, why: str) -> None:
        """Record that a writer produced a row the seam refused.

        The row was dropped at the instant it was made (rule STOR-06),
        so no reader and no file ever carried it; there is nothing on
        disk to preserve and no evidence copy. The event and the
        notice say it happened, because a fault in this version's own
        writer is a bug the person should see and report.
        """
        self._record_system_event(
            SYS_STORAGE_SHAPE,
            detail=(
                f"a {table} row written by {self.version} was refused "
                f"by the shape check and dropped ({why}); this is a "
                "fault in the writer, not in the file"
            ),
        )
        self._repair_notice = {
            "moment": "write",
            "what": f"one {table} row this version wrote was refused "
            f"and dropped ({why})",
            "where": "nothing reached the file",
        }

    def _bank_damaged_clocks(
        self, faults: list[tuple[str, str, str]]
    ) -> int:
        """Repair damaged activity clocks by restarting them, not by reading.

        A damaged `last_activity` cannot be reconstructed: the entity
        registry's idea of last-changed is the restart moment for
        anything that has not spoken since, so reading it would write
        "reported just now" over a dead device's clock and make the
        one fault this integration exists to catch invisible (rule
        STOR-09).

        Instead the clock restarts honestly, the path an unclean
        restart already takes: set to now, taint cleared because the
        gap that taint was waiting to set aside no longer exists. No
        silence is banked into today's maximum, because a value that
        carries no information gives nothing to measure the silence
        from; the difference from the unclean-restart path is that
        there the old stamp was true and here it is noise.

        Each repair is recorded as a system event (rule STOR-12): a
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
            # repair, one event (rule STOR-12).
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
                    f"restarted a damaged activity clock on {holder}: "
                    "set to now, taint cleared, nothing learned from "
                    "a value carrying no information"
                ),
            )
        if repaired:
            # Counted by the repair that called this, at load only
            # (rule STOR-12).
            LOGGER.warning(
                "Storage repair: %d damaged activity clock(s) "
                "restarted by banking",
                repaired,
            )
        return repaired

    @callback
    def _evaluate_repairs(self, moment: str) -> None:
        """Reconcile the Repairs panel against how things stand now.

        Two moments and no tick: the startup grace closing, and the
        brief's scheduled send (rule REP-07). Nothing is announced
        inside the grace (rule WATCH-10), which is why the load-time
        shape check stores its result rather than raising from where
        it runs, and why this is the first chance a fault found at
        load has to reach a person. Only what stops Device Sentinel
        working, or reports a repair it made, is a card (rule REP-01).
        """
        async_evaluate(
            self.hass,
            self.entry,
            moment,
            repair_notice=self._repair_notice,
            container_notice=self._container_notice,
        )

    def _integration_finished_loading(self, domain: str | None) -> bool:
        """Return whether this integration has finished setting up.

        A loaded config entry has registered its entities, so a
        device of its own with none has none coming and the startup
        exemption does not apply to it. Anything unreadable, unknown
        or still in progress answers False: the exemption is the safe
        side, since it costs a device five minutes of watching while
        the alternative costs devices their first gap (rule WATCH-10).
        """
        if not domain:
            return False
        try:
            entries = self.hass.config_entries.async_entries(domain)
        except Exception as err:  # noqa: BLE001 - a read never breaks setup
            LOGGER.debug("Entry state unreadable for %s: %s", domain, err)
            return False
        if not entries:
            return False
        return any(
            entry.state is ConfigEntryState.LOADED for entry in entries
        )

    def _clear_verdicts_for_set_aside(
        self, set_aside: dict[str, Any]
    ) -> None:
        """Drop the standing verdict of a device that is no longer
        watched.

        The sweep walks the watched set, so a device that leaves it
        keeps whatever verdict and stamp it had at that moment, for
        as long as it stays away. Nothing reads them while it is set
        aside, but the day it is watched again the verdict already
        matches, so no fresh stamp is taken, and the item raised from
        it is born dated to an absence that ended long ago, and a
        five minute absence is announced as far longer (rule
        LIST-09).

        A set-aside device is one nothing may be said about, so
        holding a verdict for it is holding an opinion that cannot be
        published, cannot be corrected, and outlives the facts it was
        formed from. The record itself is untouched: this clears the
        judgment, never the history.
        """
        records = self.data.get(DATA_DEVICES) or {}
        for device_id in set_aside:
            # A hand deletion is forgotten with the verdict: whatever
            # the person deleted belonged to an incident that ends
            # here, so a return is a fresh problem and not the
            # deleted row coming back (rule LIST-09).
            self._hand_deleted.discard(device_id)
            record = records.get(device_id)
            if not isinstance(record, dict):
                continue
            # Set aside, excluded or removed: nothing is held for it, and
            # nothing is on watch (rule WATCH-12).
            self._release_values(device_id, record)
            if (
                record.get(DEV_FROZEN_CATEGORY) is None
                and record.get(DEV_FROZEN_SINCE) is None
            ):
                continue
            record[DEV_FROZEN_CATEGORY] = None
            record[DEV_FROZEN_SINCE] = None
            record[DEV_DOWN_BEGAN_AS] = None
            self._dirty = True
            self._critical = True

    def _welcome_back(
        self, device_id: str, record: dict[str, Any], domain: str | None = None
    ) -> None:
        """A removed device is back in Home Assistant with its old id.
        The rhythm stays; the set-aside stamp, kept, refuses the gap
        across the absence at its first report. The signal history
        stays only when it comes back before the next midnight: a
        device away longer may have been moved (rule WATCH-07)."""
        since = record.get(DEV_REMOVED_SINCE)
        heard = record.get(DEV_LAST_ACTIVITY)
        # A hold always carries the set-aside stamp, and only the
        # device's own report clears it. A hold without one was carried
        # back by an older release that kept the removal stamp while
        # the device was back and reporting: nothing is reset. Device
        # Sentinel's own clock restarts leave the stamp alone, so they
        # cannot pass for a report (rule WATCH-07).
        carried_back = record.get(DEV_SET_ASIDE_SINCE) is None
        if isinstance(since, (int, float)) and not isinstance(since, bool) and not carried_back:
            left = dt_util.as_local(dt_util.utc_from_timestamp(float(since))).date()
            if dt_util.now().date() != left:
                forget_signal_history(record)
            if isinstance(heard, (int, float)) and not isinstance(heard, bool):
                # Its clock restarts here, as after a lost clocks file:
                # judged on the days it was gone, it would be listed
                # frozen before its first report (rule WATCH-07). The
                # set-aside stamp still refuses that first gap. A device
                # never heard keeps no clock, so it can still be listed
                # as never reported.
                record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
                record[DEV_TAINTED] = False
        record[DEV_REMOVED_SINCE] = None
        record[DEV_REMOVED_NAME] = None
        # Removed and added again while its coordinator's pairing is
        # open: the usual Zigbee2MQTT re-pair, which restarts the
        # 42-day count (rule FRZ-05). Decided here, on its return, since
        # its first report may come after pairing has closed, or carry
        # a Last Seen older than this moment.
        if domain is None:
            # Set aside at its return, as a Zigbee2MQTT device is while
            # its entities are still being made: read from its owner.
            device = dr.async_get(self.hass).async_get(device_id)
            domain = self._primary_domain(device) if device is not None else None  # type: ignore[arg-type]
        for domain in [domain] if domain else []:
            reader = reader_for_domain(self._bridge_readers, domain)
            try:
                pairing = reader is not None and reader.pairing_active_within(
                    PAIRING_GRACE_SECONDS_DEFAULT, dt_util.utcnow().timestamp()
                )
            except Exception:  # noqa: BLE001 - a reader never breaks a rebuild
                pairing = False
            if pairing:
                record[DEV_LOGNORMAL_DAYS] = 0
                break
        self._mark_cold_dirty()

    def held_records(self) -> list[dict[str, Any]]:
        """The records held for removed devices, oldest first (rule WATCH-07)."""
        rows = []
        for device_id, record in (self.data.get(DATA_DEVICES) or {}).items():
            if not isinstance(record, dict):
                continue
            since = record.get(DEV_REMOVED_SINCE)
            if not isinstance(since, (int, float)) or isinstance(since, bool):
                continue
            rows.append({
                "device_id": device_id,
                "name": record.get(DEV_REMOVED_NAME),
                "removed": dt_util.utc_from_timestamp(float(since)).isoformat(),
                "deleted_after": dt_util.utc_from_timestamp(
                    float(since) + REMOVED_HOLD_DAYS * 86400.0
                ).isoformat(),
            })
        rows.sort(key=lambda row: (row["removed"], row["device_id"]))
        return rows

    def is_held(self, device_id: Any) -> bool:
        """Whether a device id is a removed device whose record is held."""
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id) if isinstance(device_id, str) else None
        return isinstance(record, dict) and record.get(DEV_REMOVED_SINCE) is not None

    def _purge_held_records(self, now: float) -> None:
        """Delete each held record whose REMOVED_HOLD_DAYS have passed,
        with its answers (rule WATCH-07). At the fold, where records
        change size. A device back in the registry is never purged:
        the rebuild that brings it back clears its hold."""
        devices = self.data.get(DATA_DEVICES) or {}
        if self._clock_reset is not None and now - self._clock_reset[0] < 2 * 86400.0:
            # The clock was set in the last two days: a step forward
            # would purge every hold, and its answers, for good. The
            # purge waits until the clock has held still (rule FRZ-21).
            return
        limit = REMOVED_HOLD_DAYS * 86400.0
        purged: list[str] = []
        for device_id, record in list(devices.items()):
            if not isinstance(record, dict):
                continue
            since = record.get(DEV_REMOVED_SINCE)
            if not isinstance(since, (int, float)) or isinstance(since, bool):
                continue
            # Present means the registry walk found it. Asking the
            # registry by id answers a device id from before Home
            # Assistant 2026.8's split with a made-up composite
            # device, which would keep such a hold for ever.
            if now - float(since) < limit or device_id in self._watched or device_id in self._set_aside:
                continue
            purged.append(_plain(record.get(DEV_REMOVED_NAME) or device_id))
            del devices[device_id]
            self._power_forget(device_id)
            self._type_forget(device_id)
        if purged:
            self._mark_cold_dirty()
            LOGGER.info(
                "Deleted %d record(s) of devices removed from Home Assistant "
                "more than %d days ago: %s",
                len(purged),
                REMOVED_HOLD_DAYS,
                ", ".join(sorted(purged)[:10]),
            )

    def _drop_excluded_and_removed(self, device_ids: list[str]) -> None:
        """Drop the records of excluded devices removed from Home Assistant.

        Not held (rule WATCH-07): an exclusion already
        said the record should go, and a hold would keep it, and its
        answers, for 30 days against what the person asked. Its
        episodes and incidents go with it, as at the fold.
        """
        devices = self.data.get(DATA_DEVICES) or {}
        gone = set(device_ids)
        for device_id in device_ids:
            devices.pop(device_id, None)
            self._power_forget(device_id)  # type: ignore[attr-defined]
            self._type_forget(device_id)  # type: ignore[attr-defined]
        episodes = self.episode_rows()
        kept = [row for row in episodes if row.get(EP_DEVICE_ID) not in gone]
        if len(kept) != len(episodes):
            self.data[DATA_EPISODES] = kept
        incidents = self.incident_rows()
        kept_incidents = [row for row in incidents if row.get(INC_DEVICE_ID) not in gone]
        if len(kept_incidents) != len(incidents):
            self.data[DATA_INCIDENTS] = kept_incidents
        self._mark_cold_dirty()
        LOGGER.info(
            "Excluded and then removed from Home Assistant, so not held: "
            "deleted %d record(s): %s",
            len(device_ids),
            ", ".join(sorted(device_ids)[:10]),
        )

    def _discard_excluded_records(self) -> None:
        """Drop what an excluded integration or device recorded before it was.

        Here rather than on the save that excluded it, because this is
        the fold, and the fold is already the one place the record
        changes size: lowering how much history to keep does not
        delete anything when the slider moves either, it shortens the
        series at the next rollover. So a person who excludes an
        integration by mistake has until midnight to take it back with
        nothing lost, and record-shrinking stays in one place instead
        of two.

        Set aside for any other reason keeps its record untouched
        (rule WATCH-03): a disabling is Home Assistant's doing and may
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
        # never reached disk (rule STOR-18), and a permanent false
        # positive there costs more than the rows are worth. They are
        # dropped rather than stamped because the promise is that an
        # excluded integration is never recorded, and an episode is a
        # record.
        episodes = self.episode_rows()
        kept_episodes = [
            episode
            for episode in episodes
            if episode.get(EP_DEVICE_ID) not in excluded
        ]
        incidents = self.incident_rows()
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
                "Excluded integrations and devices: discarded %d device record(s), "
                "%d episode(s) and %d incident(s) at the fold",
                len(dropped),
                shed_episodes,
                shed_incidents,
            )

    async def _fold_if_a_midnight_was_missed(self) -> None:
        """Run the fold once for a midnight that passed while down.

        The fold is scheduled with a local-time tracker, so a restart
        that spans 00:00 means it never fires and nothing notices.
        Yesterday's accumulated maximum then merges into today and
        the next fold records one sample spanning both days, no
        battery level is sampled for the missed day, and every device
        loses a day of learning silently. A house that restarts
        nightly at midnight would lose it every night (rule STOR-17).

        Judged on the local date of the last save against today's,
        because the fold is a local-midnight event and the saved-at
        stamp is the only record of when the file was last current.
        Run once however many midnights were missed: the day's
        accumulators hold one day's worth whether the gap was one
        night or a week, so folding twice would append a second
        sample that no day produced.

        Silent when nothing was missed, which is every ordinary
        start.
        """
        if self._epoch_wiped:
            # The statistics epoch changed at this load and every
            # rhythm was wiped (rule STOR-17). There is nothing to fold into
            # and the day's longest gap so far is pre-wipe evidence.
            return
        saved_at = self._loaded_saved_at
        if saved_at is None:
            return
        last = dt_util.as_local(
            dt_util.utc_from_timestamp(float(saved_at))
        ).date()
        today = dt_util.now().date()
        if last >= today:
            return
        LOGGER.info(
            "Storage was last saved on %s and today is %s, so a "
            "midnight passed while Device Sentinel was not running; "
            "folding the missed day once before resuming",
            last.isoformat(),
            today.isoformat(),
        )
        # The missed day is the day of the last save (rule STOR-17).
        self._fold_day_override = last
        await self._on_midnight(None)

    async def _on_midnight(self, _now: Any) -> None:
        """The midnight fold: close the day for every device.

        Today's gaps, signal statistics and battery level join their
        daily series, every series is held to the retention (rule STOR-14),
        the day's storm tally and the daily count of each wait rule
        in use are written, and the reports are rewritten for the new
        day.
        """
        now = dt_util.utcnow().timestamp()
        # The day being folded (rule STOR-16): the day that just
        # ended at midnight, or the day of the last save when a missed
        # midnight is folded at startup. Every daily history's new
        # entry takes this date.
        day = self._fold_day_override or dt_util.as_local(
            dt_util.utcnow() - timedelta(minutes=1)
        ).date()
        self._fold_day_override = None
        self._folding_day = day
        # The line the long-kept rows cross into the history file moves
        # only here, so they cross only at a fold (rule STOR-03).
        self.data[DATA_HISTORY_LINE] = fold_line()
        self._discard_excluded_records()
        self._purge_held_records(dt_util.utcnow().timestamp())
        # Study readings for hardware no longer volunteered go here,
        # with everything else that ages out at the fold (rule STACK-11).
        self.study_fold()
        self.probe_fold(now)
        pushed = 0
        for device_id, record in self.data[DATA_DEVICES].items():
            if record[DEV_TODAY_MAX] is not None:
                before = len(record[DEV_DAILY_MAX])
                record[DEV_DAILY_MAX].append(record[DEV_TODAY_MAX])
                del record[DEV_DAILY_MAX][:-self.retention_days]
                day_appended(
                    record, FAMILY_GAP, before, len(record[DEV_DAILY_MAX]), day, added=True
                )
                record[DEV_TODAY_MAX] = None
                pushed += 1
                # A day since the last reset, for the Log-Normal
                # Percentile. Back to None once it covers every day the
                # rule can read (rule FRZ-05).
                since = record.get(DEV_LOGNORMAL_DAYS)
                if isinstance(since, (int, float)) and not isinstance(since, bool):
                    since = int(since) + 1
                    record[DEV_LOGNORMAL_DAYS] = (
                        None if since >= CLIP_MAX_DAYS else since
                    )
                # Three long days in a row are a new habit, not bad
                # days: the Log-Normal Percentile starts again and the
                # Trimmed Maximum carries the device (rule FRZ-05).
                found = self._freeze_rhythm(record)
                if found is not None and slowed_down(
                    record[DEV_DAILY_MAX], lognormal_days(record), found.get("fit")
                ):
                    record[DEV_LOGNORMAL_DAYS] = 0
                    LOGGER.debug(
                        "%s has reported more slowly for %d days in a row; "
                        "its wait follows the %s until it has 28 new days",
                        self._device_name(device_id),
                        SLOWDOWN_DAYS,
                        RULE_TRIMMED,
                    )
            # The day's low, for the primary and for a second scale
            # if the device has one (rule SIG-03).
            for bucket in (record, record.get(DEV_SIGNAL_ALT)):
                if bucket is None:
                    continue
                # The daily-minimum series is erased (rule SIG-13);
                # today's minimum stays live for the telemetry
                # report and resets with the day.
                bucket[DEV_SIGNAL_TODAY_MIN] = None
            self._roll_dwell(record, now)
            self._roll_battery(record, device_id)
            self._prune_firmware(record, now)
        # Every daily series held to the retention, whether or not the
        # day appended to it, so a device silent all day, or with no
        # battery or signal reading that day, does not keep its old
        # history past a cut in retention until it next learns a day
        # (rule STOR-14).
        keep = self.retention_days
        for record in self.data[DATA_DEVICES].values():
            for bucket in (record, record.get(DEV_SIGNAL_ALT)):
                if not isinstance(bucket, dict):
                    continue
                # Each family's dates are trimmed with the series that
                # carries its length (rule STOR-16).
                for family, anchor in (
                    ((FAMILY_GAP, DEV_DAILY_MAX),
                     (FAMILY_BATTERY, DEV_BATTERY_DAILY),
                     (FAMILY_BATTERY_PREVIOUS, DEV_BATTERY_DAILY_PREVIOUS),
                     (FAMILY_SIGNAL, DEV_SIGNAL_DAILY_COUNT))
                    if bucket is record
                    else ((FAMILY_SIGNAL_ALT, DEV_SIGNAL_DAILY_COUNT),)
                ):
                    series = bucket.get(anchor)
                    if isinstance(series, list) and len(series) > keep:
                        trimmed_to(record, family, len(series), keep, day)
                for field in DAILY_SERIES_FIELDS:
                    series = bucket.get(field)
                    if isinstance(series, list) and len(series) > keep:
                        del series[:-keep]
        # The day's storm tally, one row per domain (rule UP-17),
        # written before the save that carries it. Dated by the day
        # that just ended: the roll runs at local midnight, when today
        # is already the next day, so dating by today would file every
        # storm a day late. The catch-up fold after a missed midnight
        # has nothing to date, since the day's storms live in memory
        # and a restart empties them.
        ended = dt_util.as_local(
            dt_util.utcnow() - timedelta(minutes=1)
        ).date()
        self._fold_storm_days(ended.isoformat())
        # The house events and signal stress rows held to the history
        # length here, not on each write (rule STOR-14).
        self._trim_house_tables(now)
        self.rule_counts_fold(now)
        # Each battery forecast scored, and today's written (rule BAT-15), once
        # every battery history holds the day just closed.
        self.battery_forecasts_fold(day)
        # What a better forecast will need, kept from now (rule BAT-16).
        self.battery_evidence_fold(day)
        # A new day's figures are something the dashboard should offer.
        self._mark_changed()
        # The roll is what confirms a rail (three consecutive days
        # of nothing but the fill value), so the sync runs here and
        # the item appears with the rollover rather than a minute
        # behind it.
        self._sync_problem_list()
        if pushed or self._dirty or self._critical:
            await self._save_now()
        # No midnight verify: every row in memory arrived through the
        # gate or the seam, and the save that just ran checked the
        # whole outgoing document (rule STOR-06).
        # Each copy in trim_backups is deleted 30 days after it was
        # taken, except the newest, which is kept for the full History
        # retention (rule STOR-13).
        pruned = await async_prune_backups(
            self.hass,
            int(
                self.entry.options.get(
                    CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                )
            ),
        )
        if pruned:
            LOGGER.debug(
                "Trim backups: pruned %d file(s) past the retention "
                "window",
                pruned,
            )
        LOGGER.debug(
            "Day rollover: pushed daily maxima for %d of %d watched devices",
            pushed,
            len(self.data[DATA_DEVICES]),
        )
        # Ticks whose device left its card or whose line is gone are
        # forgotten here and only here (rule REC-07): at a real
        # midnight, never at the catch-up fold a start runs, when the
        # readers have not all been heard yet.
        self._settle_battery_entries()
        if _now is not None:
            self.prune_recommendation_acks()
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
            owner == device_id
            and entity_id not in self._foreign_entities
            and entity_id.split(".", 1)[0] not in NOTICE_DOMAINS
            for entity_id, (owner, _) in self._entity_map.items()
        )

    def _live_entity_states(self, device_id: str) -> list[str]:
        """Return the current states of the entities that decide whether
        a device is down. A missing state object means the entity is not
        live and is skipped, so the judgment reads only what a person
        could see reporting. A foreign entity is not read: holding a
        value, it would read the device as up while every entity of its
        own is down (rule WATCH-02).

        The device's main entities decide, so a setting, a diagnostic
        or a firmware notice that Home Assistant or the coordinator
        still holds cannot keep a dead motion or door sensor looking
        alive (rule UNAV-01). A device with no main entity, or whose
        main entities are not loaded, is read on all its own entities.
        One whose main entities all read unknown or rest is read on the
        others only when they say the device is gone. Unknown is
        returned as read; callers count it as neither down nor alive
        (rule UNAV-02).
        """
        main = self._main_entities.get(device_id)
        if main:
            ordered = [e for e in self._own_entities.get(device_id, ()) if e in main]
            states = self._states_of(ordered)
            # A button or an event at rest says nothing either: only a
            # value read decides (rule UNAV-04).
            if any(state not in (STATE_UNKNOWN, EVENT_RESTING) for state in states):
                return states
            if states:
                # Main entities loaded but saying nothing. The others may
                # only tell that the device is gone, never that it is
                # alive: a battery or signal value the stack still holds
                # cannot end an outage. So they are read only when every
                # one that says anything says unavailable (rule UNAV-04).
                others = self._states_of(self._own_entities.get(device_id, ()))
                said = [s for s in others if s not in (STATE_UNKNOWN, EVENT_RESTING)]
                if said and all(s in BAD_STATES for s in said):
                    return others
                return states
        return self._states_of(self._own_entities.get(device_id, ()))

    def _states_of(self, entity_ids: Any) -> list[str]:
        """The states of these entities, as _live_entity_states reads them."""
        states: list[str] = []
        resting = False
        for entity_id in entity_ids:
            if entity_id in self._node_status_ids:
                # The stack's word on the node, not a reading: alive while
                # every reading is unavailable must not hold the device
                # up, and dead is read on its own (rule STACK-05).
                continue
            if entity_id.split(".", 1)[0] in NOTICE_DOMAINS:
                # A firmware notice or a command button is never the
                # device: it can show the device neither alive nor gone
                # (rule WATCH-04).
                continue
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            # A value handed back to a device judged unavailable reads as
            # not known yet (rule WATCH-12).
            value = self._held_reading(entity_id, state) if self._on_watch else state.state
            if value is None:
                continue
            if _resting(entity_id, value):
                resting = True
                continue
            states.append(value)
        if not states and resting:
            states.append(EVENT_RESTING)
        return states


    # ------------------------------------------------ silence episodes


    def _device_name(self, device_id: str) -> str:
        """Return a device's display name for logging and the report."""
        # A removed device whose record is held keeps the name it had
        # (rule WATCH-07).
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id)
        if isinstance(record, dict) and isinstance(record.get(DEV_REMOVED_NAME), str):
            return str(record[DEV_REMOVED_NAME])
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id)
        domain = self._primary_domain(device) if device is not None else None  # type: ignore[arg-type]
        return display_name(device, domain, device_id)

    @property
    def episode_share(self) -> float:
        """Return the episode-opening share, as a fraction.

        A silence opens an episode once it has spent this much of the
        distance from the device's rhythm to its freeze line. A
        constant, not an option, because it shapes one forensic file
        and nothing a person is alerted about (rule FRZ-08).
        """
        return EPISODE_SHARE_PCT / 100.0


    async def _routine_save(self) -> None:
        """Write the coalesced routine save, if its window has come.

        Routine churn coalesces on one clock: the render tick is the
        only scheduler, and the deadline is a plain float here rather
        than state inside two Store objects. Two schedules against one
        pair of files would race, and the main file could come out
        newer than the clocks file. A deadline of zero is the first
        dirty tick of a session and writes immediately, which keeps the
        first window from silently starting a full interval long.

        Routine churn is the clock fields alone (CLOCK_FIELDS), so the
        ordinary window writes the hot file alone, a small fraction of
        the main file's size (rule STOR-01). The main file goes first
        and only when a forensic row is waiting (an episode, an
        incident, a system event, a registry change), which keeps the
        hot stamp the newer of the pair. Anything judgment-bearing never
        reaches here: it is critical and wrote both files within the
        tick that detected it (rule STOR-02).
        """
        if self._stopped:
            return
        now_mono = self.hass.loop.time()
        if now_mono >= self._next_routine_save:
            self._next_routine_save = now_mono + self.coalesce_seconds
            async with self._save_lock:
                if self._stopped:
                    return
                if self._cold_dirty:
                    await self._save_routine_main()
                await self._clock_store.async_save(self._clocks_to_save())
        self._dirty = False

    async def _on_render_tick(self, _now: Any) -> None:
        """Sweep storms, judge freezes, persist if dirty, refresh.

        The freeze sweep runs here rather than on a per-device timer:
        at 60-second granularity a window that closes is caught within
        a minute, which is immaterial against windows of minutes to
        hours, and one sweep is simpler than a scheduled callback per
        device to cancel and re-arm. Detection is still live in the sense
        that matters, a freeze shows on the next tick after its window
        closes, and clears the instant the device reports (that half
        runs in the report path, not here).
        """
        # The radio sweep, where a network was chosen and an adapter
        # found. It reads the Supervisor, so it is awaited here rather
        # than run inside the synchronous judgment below.
        await self._detect_clock_reset()
        await self.async_sweep_wifi()
        self._sweep_storms(dt_util.utcnow().timestamp())
        self.probe_tick(dt_util.utcnow().timestamp())
        # Firmware that has held ten minutes, once the restart's stale
        # registry values have settled (rule DEV-15).
        if not self._in_startup_grace():
            self._confirm_firmware(dt_util.utcnow().timestamp())
        self._expire_maintenance(dt_util.utcnow().timestamp())
        await self._close_brief_if_skipped()
        self._sample_bridges()
        # Each hub's connection, read before the devices are judged
        # (rule STACK-09).
        self._sample_hubs(dt_util.utcnow().timestamp())
        self._judge_all_devices()
        self._wifi_backdate()
        self._note_upstream_peaks()
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
        """Refresh all registered sensors.

        Walks a copy of the list. The Wi-Fi sensor's adder removes
        itself from the list the moment it runs, and removing from the
        list being walked would skip the listener after it, the
        Problem List on a live system, for that one refresh.
        """
        for update_callback in list(self._listeners):
            update_callback()

    # -------------------------------------------------------- properties


    @property
    def watched_count(self) -> int:
        """Return the number of watched devices."""
        return len(self._watched)

    @property
    def set_aside_count(self) -> int:
        """Return the number of devices set aside, for any reason."""
        return len(self._set_aside)

    def _clear_reading_weighted_series(
        self, loaded: dict[str, Any]
    ) -> None:
        """Drop the mean and deviation days recorded by reading count.

        Both are weighted by the minute clock the percentiles use
        (rule SIG-05). The two weightings answer different questions,
        so a series holding some of each could not be separated by
        any later analysis. Cleared once, under a marker, so a
        restart cannot throw away days recorded since. Nothing else
        goes: the percentiles mean today what they meant yesterday.
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
            # The day in progress too (rule SIG-05). Its accumulator
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

        The count is the record itself rather than a stamp beside it.
        For one device, an area's complete days is
        the length of its shortest series, since a set that gained a
        series yesterday has one day of complete history however deep
        its older members run; house-wide it is the highest of those,
        because the question is how long this system has recorded the
        area, not whether every device is mature.

        A stamp would have to be told when a recording set changed,
        and a release could forget. The series cannot forget: add one
        and it is empty, so it is the shortest, so the area reads zero
        on its own.

        device_days is the house's total volume in the area, which a
        person would otherwise have to read out of the diagnostics.
        """
        # Through watched_records, the one-line rule every surface
        # follows (rule WATCH-09), which also holds out a record with a
        # standing shape fault, so a held record whose series is an
        # integer cannot crash this (rule STOR-09).
        devices = [record for _device_id, record in self.watched_records()]
        out: dict[str, dict[str, Any]] = {}
        for area, series, arming, learned in (
            (AREA_FREEZE, SERIES_FREEZE, FREEZE_ARMING_DAYS, DAILY_MAX_KEEP),
            (AREA_BATTERY, SERIES_BATTERY, BATTERY_ARMING_DAYS, None),
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

        Everything here is knowable (rule STOR-08): the copy's
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
        moment = dt_util.utcnow().timestamp()
        loss = describe_restore_loss(taken, moment)
        # The embedded form continues "restored from the last-good
        # backup," so the brief carries one sentence rather than a
        # standalone paragraph spliced in after a colon (rule STOR-08).
        loss_embedded = describe_restore_loss(taken, moment, embedded=True)
        # Which of the three happened is knowable and worth saying:
        # a person who deleted a file, a person whose disk failed, and
        # a person whose file was corrupted have different next steps
        # (rule STOR-08). One name for the backup on every surface:
        # the last-good backup, nothing else.
        cause = {
            "corrupt": (
                "Device Sentinel's storage file was damaged and could "
                "not be read. Home Assistant renamed it aside and "
                "Device Sentinel replaced it from its last-good "
                "backup, then started normally. It is running now."
            ),
            "missing": (
                "Device Sentinel's storage file was missing. It was "
                "replaced from the last-good backup and startup "
                "continued. It is running now."
            ),
        }
        headline = cause.get(
            self._restore_reason,
            "Device Sentinel could not read its storage file, so it "
            "replaced the file from its last-good backup and "
            "started normally. It is running now.",
        )
        # Name what was actually copied. On a missing storage file
        # there is no storage file to copy, so the sentence must not
        # claim one (rule STOR-11).
        if self._restore_evidence and self._restore_copied:
            where = (
                f"Copies of {_english_list(self._restore_copied)} were "
                f"saved in {TRIM_BACKUP_DIR} under the stamp "
                f"{self._restore_evidence}."
            )
        elif self._restore_evidence:
            where = (
                f"Copies were saved in {TRIM_BACKUP_DIR} under the "
                f"stamp {self._restore_evidence}."
            )
        else:
            where = "Nothing could be copied aside."
        self._record_system_event(
            SYS_STORAGE_REPAIR,
            detail=f"restored from the last-good backup, {loss_embedded}",
        )
        self._restore_told = f"{headline} {loss}"
        # When, so only the brief whose window holds it says so (rule
        # BRIEF-02).
        self._restore_told_at = dt_util.utcnow().timestamp()
        # Home Assistant's own critical issue, if it raised one, tells
        # a person to repair the file by hand or restore the whole
        # system from a backup. Both are wrong after a restore (rule
        # REP-08).
        cleared = 0
        if self._restore_corrupt_names:
            cleared = async_clear_home_assistant_corruption(
                self.hass, self._restore_corrupt_names
            )
        if cleared:
            where = (
                f"{where} Home Assistant also reported this file as "
                f"corrupt; that report has been cleared."
            )
        async_raise_restored(
            self.hass,
            self.entry.entry_id,
            headline,
            loss,
            where,
        )
        await self.async_announce_restore(headline, f"{loss}\n\n{where}")

    @property
    def restore_told(self) -> str | None:
        """The restore sentence for the brief, or None (rule STOR-08)."""
        return getattr(self, "_restore_told", None)

    @property
    def storage_load_faulty(self) -> bool:
        """Whether this session's load verified faulty (rule STOR-12)."""
        return self._load_faulty

    @property
    def repairs_at_load(self) -> int:
        """How many repairs this session's load made (rule STOR-12)."""
        return self._repairs_at_load

    @property
    def last_good_taken(self) -> float | None:
        """When the last-good pair was last refreshed, from the file."""
        return self._last_good_taken

    @property
    def learning_buckets(self) -> dict[str, int]:
        """Return counts of devices by learning progress.

        Read through watched_records rather than the raw store,
        which is the one-line rule every surface follows (rule
        WATCH-09), so a damaged record cannot reach the coverage
        sensor and crash it. Such a record is repaired at the gate
        too (rule STOR-09), and the one-line rule still stands here.
        """
        buckets = {"observing": 0, "building": 0, "established": 0}
        for _device_id, record in self.watched_records():
            days = len(record.get(DEV_DAILY_MAX) or [])
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

        The picker reaches every detected device, so reading the
        watched map alone would leave an erased excluded device named
        by a hex id. An event naming a device by id answers nothing a
        month later, which is why the event names devices rather than
        counting them (rule CFG-10).
        """
        name = self._display_names.get(device_id)
        if name:
            return name
        aside = self._set_aside.get(device_id)
        if aside:
            return aside[0]
        # Returns the id when nothing knows this device, which is the
        # signal a caller needs to prefer a historically stored name
        # over anything derived. The naming ladder is applied by the
        # caller, after that check, so a device that departed still
        # reads as what it was called (rule DEV-02).
        return device_id

    async def _apply_trim_selection(
        self, options: dict[str, Any]
    ) -> None:
        """Erase what the two Advanced pickers name, then empty them.

        An action wearing an option's clothes (rule CFG-10). Saving
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
        names = [
            name if name != device_id else self._device_name(device_id)
            for device_id, name in (
                (device_id, self._trim_name(device_id))
                for device_id in targets
            )
        ]

        try:
            stamp = await self.hass.async_add_executor_job(
                trim.write_backup,
                self.hass.config.path(TRIM_BACKUP_DIR),
                dt_util.now(),
                self._trim_backup_storage(),
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
        # A trimmed device's Battery Last Replaced entry goes with its
        # history: a fresh record starts with none (rule CFG-10).
        answers = self._battery_answers()
        dropped = [device_id for device_id in targets if answers.pop(device_id, None) is not None]
        if dropped:
            self._answers_save()
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
        """Re-judge the house under new options, live, no restart."""
        # Home Assistant has already replaced the entry's options by
        # the time this runs, so the comparison is against a copy
        # taken when they were last applied rather than against the
        # entry itself, which would compare the new options with
        # themselves and find nothing.
        before = self._options_seen
        after = dict(self.entry.options)
        self._options_seen = after
        # The trim runs before anything re-judges, so the rest of
        # this method sees the house as it is after the deletion
        # rather than judging records that are about to vanish
        # (rule CFG-10).
        await self._apply_trim_selection(after)
        self._rebuild_registry_view()
        moved = sorted(
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
            # The trim pickers are an action rather than a setting,
            # and they move twice per trim: once when a person picks
            # something and once when the save empties them again.
            # The trim writes its own event, so naming them here would
            # put three rows in the brief for one deed and tell a reader
            # that a setting had changed when none had (rule CFG-10).
            and key not in (CONF_TRIM_DEVICES, CONF_TRIM_INTEGRATIONS)
            # A mute set on a device's page records its own row there.
            and key not in self._page_option_keys
        )
        self._page_option_keys.clear()
        if moved:
            # Which setting moved, not merely that one did. A row
            # saying something changed cannot answer, months later,
            # why a device started being reported when nothing in the
            # house had altered.
            self._record_system_event(
                SYS_OPTIONS_CHANGED, detail=", ".join(moved)
            )
        LOGGER.debug(
            "Options updated: low threshold now %s, %d devices "
            "muted; re-evaluating",
            self.low_threshold,
            len(self._muted_devices),
        )
        self._schedule_brief()
        self._evaluate_all_batteries()
        # A device muted here leaves the down list at once
        # (frozen_devices_list and the held kinds read the mutes), so
        # the sync deletes its items now. Its verdict clears on the next
        # sweep that judges it; one held behind a down upstream keeps
        # it, unshown, until the upstream is back.
        self._sync_problem_list()
        if self._dirty or self._critical:
            await self._save_now()
        self._notify()


    @property
    def trimmable_device_rows(self) -> list[dict[str, Any]]:
        """Return every device the integration knows, for the trim
        pickers.

        Wider than watched_device_rows on purpose (rule CFG-10).
        Nothing is filtered: watched, muted, excluded and
        set-aside devices are all offered, and so is a device that
        currently holds no record at all. The muting pickers can
        narrow to what a muting would change, because offering a
        pointless muting is only clutter. A trim picker cannot,
        because a faulty record can read as empty and the
        empty-looking device is exactly the one a person will be
        told to choose; a filter keyed on holding a record would
        hide the case the feature exists for.

        The integration is shown beside the name because a house can
        carry the same name on two registry devices, and the person
        has to pick the right one first time (rule DEV-04).
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

        Set-aside devices are absent because they are not watched, so the list
        cannot offer a muting that would do nothing. Muted devices are present:
        the list is what is being judged, and a muted device is still a device
        you may want to un-mute.
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

    @callback
    def _in_startup_grace(self) -> bool:
        """Is the integration still inside its startup grace?

        Everything reports at once on a restart and none of it is
        news, which is why the integration already refuses to judge
        inside the grace. The bus follows the same rule: a fault
        still true when grace ends is announced then, once
        (rule WATCH-10).
        """
        return dt_util.utcnow().timestamp() < self._grace_until

    async def async_regenerate_reports(self) -> dict[str, int]:
        """Judge every device now, then rewrite every report.

        For a person hunting a problem: fix a frozen device, press
        this, and the report reflects the fix at once rather than at
        the next tick or the nightly write. Judgment runs first so the
        down-devices section and the verdicts are current, then every
        report is written with a fresh timestamp that confirms the run.
        """
        self._judge_all_devices()
        await self._write_reports_guarded("manual")
        return {"regenerated": 2}

    def _is_node_status_entry(self, ent: er.RegistryEntry) -> bool:
        """Whether this is a watched device's node status sensor (rule STACK-05)."""
        return is_node_status(self._watched.get(ent.device_id or ""), ent)

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

    async def async_toggle_maintenance(
        self, minutes: int | None = None
    ) -> dict[str, Any]:
        """Open the maintenance window, or close it early (rule FRZ-18).

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
        # The dashboard chooses a length per press; the device page's
        # button and a press with none use the setting.
        minutes = minutes or self.maintenance_minutes
        self._maintenance_until = now + minutes * 60.0
        self._maintenance_opened_at = now
        self._record_system_event(
            SYS_MAINTENANCE_OPEN,
            detail=f"{minutes} minute window",
            when=now,
        )
        LOGGER.debug(
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
        LOGGER.debug("Maintenance mode closed (%s)", detail)

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
        LOGGER.debug(
            "A maintenance window was open at the last stop; its "
            "closing row is recorded at this restart"
        )

    def _recovered_during_maintenance(self, now: float) -> bool:
        """Return whether a maintenance window is open at this moment.

        House-wide by design (rule FRZ-18): the button is global, and the
        cost of the width is one discarded learning sample for a
        genuine self-recovery that lands inside the window, the same
        conservative trade pairing makes.
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
