# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage.py, Version: 0.10.3 (2026-07-28)

"""Persistence: the write cadence, the split shadow, and retention.

Per-device statistics survive a reload: a device driven through the
coordinator writes its record to the store and reads it back intact
across a restart. Two tiers of write keep the store honest without
thrashing it. Routine
activity-clock churn coalesces into one delayed save on the coalesce
window; anything a reboot must not lose (a verdict, a battery flip, an
acknowledgment) saves immediately. The delayed write has to actually
fire rather than reschedule itself forever under continuous churn. The
storage split writes a clocks shadow on the same triggers and never
reads it, which is the whole safety argument, alongside a one-time
pre-split backup that copies and never overwrites. Retention bounds the
records that are supposed to forget (briefs, episodes, incidents) and
lets the user choose how long the long series are kept, and the rule
that makes every length safe is that no verdict depends on retention:
the freeze rhythm and the signal floor read only the most recent
fortnight however much is stored. This file holds the two-tier writes,
the coalesce firing, the split shadow and backup, and retention.
"""

import glob
import os

from datetime import timedelta
from unittest.mock import patch

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    BRIEF_KEEP_DAYS,
    CLOCK_FIELDS,
    COLD_WRITE_CAP_SECONDS,
    COLD_WRITE_DEBOUNCE_SECONDS,
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    CONF_RETENTION_DAYS,
    CONF_SETTLE_SHARE,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DEFAULT_RETENTION_DAYS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_TODAY_MAX,
    EP_ENDED,
    EPISODE_ENDED_RESUMED,
    EPISODE_OPEN_SHARE,
    EPISODE_KEEP_DAYS,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NOT_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    INC_WHEN,
    REPORT_BRIEF_PREFIX,
    REPORT_DIAGNOSTIC_DIR,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    RETENTION_DAYS_STEP,
    STARTUP_GRACE_SECONDS,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_COALESCE_SECONDS,
    STORAGE_KEY,
    TODO_KIND_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
    TODO_KIND_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
)

from custom_components.device_sentinel.coordinator import (
    _new_device_record,
)

from tests.helpers import setup_entry

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


class _StoreSpy:
    """Counts immediate saves and delayed schedules on a real store."""

    def __init__(self, store):
        self.saves = 0
        self.delays = 0
        self.last_delay = None
        self._real_save = store.async_save
        self._real_delay = store.async_delay_save
        store.async_save = self._save
        store.async_delay_save = self._delay

    async def _save(self, data):
        self.saves += 1
        await self._real_save(data)

    def _delay(self, data_func, delay):
        self.delays += 1
        self.last_delay = delay
        # Two legitimate windows from 0.10.1: the coalesce window a
        # routine clock write uses, and the shorter cold debounce the
        # main file uses. Anything else means a delay was passed by
        # accident rather than chosen.
        assert delay in (
            STORAGE_COALESCE_SECONDS,
            COLD_WRITE_DEBOUNCE_SECONDS,
        )
        self._real_delay(data_func, delay)


def _episode(coord, days_ago, ended=EPISODE_ENDED_RESUMED, lag=None):
    when = dt_util.utcnow().timestamp() - days_ago * 86400.0
    coord.data[DATA_EPISODES].append(
        {
            "device_id": f"d{days_ago}",
            "name": f"Device {days_ago}",
            "since": when,
            "basis": 3600.0,
            "window": 7200.0,
            "ended": ended,
            "at": when + 60 if ended else None,
            "lag": lag,
            "learned": "yes" if ended else None,
        }
    )


def _clocks(hass_storage):
    """The shadow as the harness stored it; storage is mocked here."""
    return hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]


# ==================================================================
# Two-tier persistence: churn coalesces, the critical saves at once.
# ==================================================================

async def test_routine_churn_coalesces(hass: HomeAssistant, freezer):
    """Activity alone schedules a delayed write; nothing saves
    immediately on the tick."""
    device, entity_id = _register(hass, "r1", "Routine Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    cold = _StoreSpy(coord._store)
    hot = _StoreSpy(coord._clock_store)

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hot.delays >= 1
    assert hot.saves == 0
    # Phase B: churn never touches the main file, which is the saving.
    assert cold.delays == 0
    assert cold.saves == 0


async def test_verdict_flip_saves_immediately(
    hass: HomeAssistant, freezer
):
    """A freeze verdict on the tick takes the immediate tier, the
    exact pre-0.6.5 behavior for anything that matters."""
    device, entity_id = _register(hass, "v1", "Verdict Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)

    spy = _StoreSpy(coord._store)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    saves_before = spy.saves

    freezer.tick(timedelta(hours=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.saves > saves_before  # the flip forced a real write
    assert coord._critical is False


async def test_acknowledgment_saves_immediately(hass: HomeAssistant):
    """The checkbox writes through at once, never waiting for a tick
    or a window."""
    device, entity_id = _register(hass, "a1", "Acked Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 8 * 3600
    coord._judge_all_devices()
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]

    spy = _StoreSpy(coord._store)
    await coord.async_todo_update(uid=uid, status="completed")
    assert spy.saves == 1


async def test_delayed_save_serializes_live_data(hass: HomeAssistant):
    """The delayed write reads the state at write time, not at
    schedule time."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert coord._data_to_save() is coord.data


async def test_shutdown_flushes_pending(hass: HomeAssistant):
    """A clean unload writes through whatever tier was pending."""
    device, entity_id = _register(hass, "s1", "Flush Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    coord._dirty = True  # simulate pending routine churn

    with patch.object(
        coord._store, "async_save", wraps=coord._store.async_save
    ) as saved:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert saved.call_count >= 1
    assert coord._dirty is False


# ==================================================================
# The coalesced write actually fires.
# ==================================================================

async def test_dirty_ticks_schedule_once_and_the_write_fires(
    hass: HomeAssistant, freezer
):
    """Continuous churn: one schedule per window, and the delayed
    write really executes when the window elapses. This is the test
    0.6.5 shipped without."""
    device, entity_id = _register(hass, "c1", "Churn Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._clock_store)
    cold = _StoreSpy(coord._store)

    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Ten dirty ticks inside one window: activity each minute.
    value = 0
    for _ in range(10):
        value += 1
        hass.states.async_set(entity_id, str(value))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.delays == 1          # scheduled once, never rescheduled
    assert spy.saves == 0           # nothing immediate for churn
    assert cold.delays == 0         # and the main file stays put
    assert cold.saves == 0
    assert coord._delay_pending is True

    # The window elapses: the delayed write fires for real. The
    # store's delayed path writes internally rather than through
    # async_save, so the firing proof is the pending flag clearing,
    # which only _clocks_to_save does, and it runs exactly when the
    # store serializes the delayed write. spy.saves staying at zero
    # proves no immediate save could have cleared it instead.
    freezer.tick(
        timedelta(seconds=STORAGE_COALESCE_SECONDS + 30)
    )
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.saves == 0
    assert coord._delay_pending is False

    # More churn after the fire: a fresh window schedules again.
    value += 1
    hass.states.async_set(entity_id, str(value))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spy.delays == 2


async def test_immediate_save_clears_the_pending_window(
    hass: HomeAssistant, freezer
):
    """A critical save mid-window resets the pending flag, so the
    next churn schedules a clean new window instead of assuming one
    is still coming."""
    device, entity_id = _register(hass, "c2", "Reset Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._clock_store)

    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coord._delay_pending is True

    # An acknowledged-style direct save mid-window.
    await coord._save_now()
    assert coord._delay_pending is False
    saves_after_direct = spy.saves

    # New churn: a fresh window schedules.
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coord._delay_pending is True
    assert spy.delays == 2
    assert spy.saves == saves_after_direct  # churn stayed routine


# ==================================================================
# The storage split, phase A: the shadow and the backup.
# ==================================================================

async def test_the_clocks_file_is_written(
    hass: HomeAssistant, hass_storage
):
    device, entity_id = _register(hass, "cl1", "Clock Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    await coord._save_now()

    assert STORAGE_CLOCKS_KEY in hass_storage
    clocks = _clocks(hass_storage)
    assert device.id in clocks
    assert set(clocks[device.id]) == set(CLOCK_FIELDS)


async def test_the_shadow_agrees_with_storage(
    hass: HomeAssistant, hass_storage
):
    """What the rig will check daily, asserted here once."""
    device, entity_id = _register(hass, "cl2", "Agreeing Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    await coord._save_now()

    clocks = _clocks(hass_storage)
    for device_id, record in coord.data[DATA_DEVICES].items():
        for field in CLOCK_FIELDS:
            assert clocks[device_id][field] == record.get(field), (
                device_id,
                field,
            )


async def test_the_shadow_carries_only_the_hot_fields(
    hass: HomeAssistant, hass_storage
):
    """Cold data stays cold: a shadow carrying the learned series
    would save nothing at cutover."""
    device, entity_id = _register(hass, "cl3", "Cold Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] = [1.0, 2.0]
    await coord._save_now()
    assert DEV_DAILY_MAX not in _clocks(hass_storage)[device.id]


async def test_nothing_reads_the_shadow(
    hass: HomeAssistant, hass_storage
):
    """The safety argument for the whole phase: corrupt the shadow
    completely, restart, and the system is unaffected because it
    still loads everything from storage."""
    device, entity_id = _register(hass, "cl4", "Ignored Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = 1234.0
    await coord._save_now()

    hass_storage[STORAGE_CLOCKS_KEY]["data"] = {"clocks": "nonsense"}

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data
    assert reloaded.data[DATA_DEVICES][device.id][
        DEV_LAST_ACTIVITY
    ] == 1234.0


async def test_the_shadow_exists_from_the_first_moment(
    hass: HomeAssistant, hass_storage
):
    """0.8.8: setup writes storage directly rather than through
    _save_now, so without an explicit write here the clocks file did
    not appear until the first coalesced save up to a window later,
    and a system restarting inside that window never produced one.

    It mirrors whatever storage held at that instant, so on a fresh
    install it is legitimately empty and on an existing one it
    carries every device from the first moment.
    """
    _register(hass, "sh1", "Immediate Sensor")
    entry = await setup_entry(hass)
    assert STORAGE_CLOCKS_KEY in hass_storage
    assert "clocks" in hass_storage[STORAGE_CLOCKS_KEY]["data"]

    # Once devices are known, the next save carries them.
    await entry.runtime_data._save_now()
    assert hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]


async def test_the_split_state_reaches_diagnostics(
    hass: HomeAssistant,
):
    """It was confirmable only from a terminal, which is no way to
    verify a release (0.8.8)."""
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _register(hass, "sd1", "Diag Sensor")
    entry = await setup_entry(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    split = diag["split"]
    assert split["phase"].startswith("B:")
    assert set(split["clock_fields"]) == set(CLOCK_FIELDS)
    assert split["clock_devices"] >= 1


# ==================================================================
# Retention: the records that are supposed to forget.
# ==================================================================

async def test_only_the_newest_briefs_are_kept(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    directory = hass.config.path("device_sentinel")
    os.makedirs(directory, exist_ok=True)
    # Setup writes today's brief, so start from a known count.
    for path in glob.glob(os.path.join(directory, "daily_brief_*.md")):
        os.remove(path)
    for day in range(1, BRIEF_KEEP_DAYS + 7):
        name = f"{REPORT_BRIEF_PREFIX}2026-06-{day:02d}.md"
        with open(os.path.join(directory, name), "w") as handle:
            handle.write("stale\n")
    assert len(glob.glob(os.path.join(directory, "daily_brief_*.md"))) == (
        BRIEF_KEEP_DAYS + 6
    )

    coord._trim_briefs(directory)
    left = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(directory, "daily_brief_*.md"))
    )
    assert len(left) == BRIEF_KEEP_DAYS
    # The newest survive: the oldest six dates are gone.
    assert left[0] == f"{REPORT_BRIEF_PREFIX}2026-06-07.md"


async def test_trimming_briefs_is_safe_when_there_are_few(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    directory = hass.config.path("device_sentinel")
    before = glob.glob(os.path.join(directory, "daily_brief_*.md"))
    coord._trim_briefs(directory)
    assert len(glob.glob(os.path.join(directory, "daily_brief_*.md"))) == (
        len(before)
    )


async def test_old_episodes_are_dropped(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 6)
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 1)
    _episode(coord, days_ago=2)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    assert len(coord.data[DATA_EPISODES]) == 1
    assert coord.data[DATA_EPISODES][0]["name"] == "Device 2"


async def test_an_unfinished_episode_survives_the_boundary(
    hass: HomeAssistant,
):
    """An episode still waiting on its lag is an unfinished story, not
    old news, so age alone does not remove it."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9, ended=None)
    _episode(
        coord,
        days_ago=EPISODE_KEEP_DAYS + 9,
        ended="intervention (restart)",
        lag=None,
    )
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    survivors = [row["ended"] for row in coord.data[DATA_EPISODES]]
    assert len(survivors) == 2
    assert EPISODE_ENDED_RESUMED not in survivors


async def test_old_incidents_are_dropped_as_new_ones_arrive(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_INCIDENTS].clear()
    stale = dt_util.utcnow().timestamp() - (INCIDENT_KEEP_DAYS + 3) * 86400
    coord.data[DATA_INCIDENTS].append(
        {
            "device_id": "old",
            "name": "Ancient History",
            "kind": TODO_KIND_FROZEN,
            "event": INCIDENT_OPENED,
            INC_WHEN: stale,
            "cause": None,
            "duration": None,
        }
    )
    coord._record_incident("new", "Fresh", TODO_KIND_FROZEN, INCIDENT_OPENED)
    names = [row["name"] for row in coord.data[DATA_INCIDENTS]]
    assert names == ["Fresh"]


async def test_freeze_kinds_alias_their_verdicts(hass: HomeAssistant):
    """The sync passes a freeze verdict straight through as a kind, so
    the two names must be the same string, defined once."""
    assert TODO_KIND_FROZEN == FREEZE_CATEGORY_FROZEN
    assert TODO_KIND_UNAVAILABLE == FREEZE_CATEGORY_UNAVAILABLE
    assert TODO_KIND_UNKNOWN == FREEZE_CATEGORY_UNKNOWN
    assert TODO_KIND_NOT_REPORTED == FREEZE_CATEGORY_NOT_REPORTED


async def test_every_kind_has_words_for_both_shapes(
    hass: HomeAssistant,
):
    """The guard the literals could not give: if a kind is ever renamed
    and a table is missed, this fails rather than a raw kind name
    reaching a person's brief."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    kinds = (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NOT_REPORTED,
        TODO_KIND_BATTERY,
        TODO_KIND_SIGNAL,
    )
    for kind in kinds:
        assert kind in coord._KIND_SEVERITY, kind
    for kind in (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_SIGNAL,
    ):
        assert kind in coord._EVENT_WORDING, kind
        assert kind in coord._STATE_TEMPLATE, kind


# ==================================================================
# Ninety days kept, a fortnight judged.
# ==================================================================

async def test_the_floor_ignores_history_beyond_a_fortnight(
    hass: HomeAssistant,
):
    """The guard that matters. The floor is the third lowest reading
    it can see, and the third lowest of ninety days is lower than the
    third lowest of fourteen, so reading the whole series would
    quietly slacken every floor on the fleet."""
    device, _ = _register(hass, "fl1", "Floor Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    fortnight = [100.0 - n for n in range(DAILY_MAX_KEEP)]
    record[DEV_SIGNAL_DAILY_MIN] = list(fortnight)
    with_a_fortnight = coord._danger_line(record)

    # The same fortnight, preceded by far worse older days.
    record[DEV_SIGNAL_DAILY_MIN] = [10.0] * 40 + list(fortnight)
    with_a_season = coord._danger_line(record)

    assert with_a_season == with_a_fortnight
    assert 10.0 not in coord._signal_history(record)


async def test_the_signal_series_keeps_ninety_days(
    hass: HomeAssistant,
):
    device, _ = _register(hass, "se1", "Series Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [float(n) for n in range(200)]
    # The trim happens when a day is appended, so roll one.
    record[DEV_SIGNAL_TODAY_MIN] = 42.0
    await coord._on_midnight(None)
    assert len(record[DEV_SIGNAL_DAILY_MIN]) == DEFAULT_RETENTION_DAYS
    assert record[DEV_SIGNAL_DAILY_MIN][-1] == 42.0


async def test_the_columns_show_the_same_fortnight_as_before(
    hass: HomeAssistant,
):
    """A season of history must not widen the report's columns."""
    device, _ = _register(hass, "co1", "Column Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [50.0 + n for n in range(DEFAULT_RETENTION_DAYS)]
    cell = coord._format_signal_lows_cell(record)
    assert len(cell.split()) == DAILY_MAX_KEEP


async def test_the_maintainer_files_live_in_a_subfolder(
    hass: HomeAssistant,
):
    """The folder a person opens holds the briefs and nothing else."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports, "test")
    top = hass.config.path("device_sentinel")
    below = os.path.join(top, REPORT_DIAGNOSTIC_DIR)
    for name in (
        "device_telemetry.md",
        "classification.md",
        "silence_episodes.md",
    ):
        assert os.path.isfile(os.path.join(below, name)), name
        assert not os.path.isfile(os.path.join(top, name)), name
    assert any(
        name.startswith("daily_brief_") for name in os.listdir(top)
    )


# ==================================================================
# How much is kept, and what is judged.
# ==================================================================

async def test_the_rhythm_reads_only_the_judgment_window(
    hass: HomeAssistant,
):
    """The hazard this release had to avoid. The trimmed maximum of
    ninety days is higher than of fourteen, because more days mean
    more chances at a long gap, so reading the whole series would
    quietly widen every freeze window on the fleet."""
    device, _ = _register(hass, "jd1", "Judged Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    fortnight = [600.0 + n for n in range(DAILY_MAX_KEEP)]
    record[DEV_DAILY_MAX] = list(fortnight)
    with_a_fortnight = coord._freeze_window(record)

    # The same fortnight, preceded by far longer gaps months ago.
    record[DEV_DAILY_MAX] = [50000.0] * 60 + list(fortnight)
    with_a_season = coord._freeze_window(record)

    assert with_a_season == with_a_fortnight


async def test_the_rhythm_is_the_same_at_every_setting(
    hass: HomeAssistant,
):
    """A Pi keeping thirty days detects what a fast machine keeping a
    year detects."""
    device, _ = _register(hass, "jd2", "Same Sensor")
    series = [50000.0] * 60 + [600.0 + n for n in range(DAILY_MAX_KEEP)]
    seen = set()
    for days in (RETENTION_DAYS_MIN, DEFAULT_RETENTION_DAYS,
                 RETENTION_DAYS_MAX):
        entry = await setup_entry(hass, {CONF_RETENTION_DAYS: days})
        coord = entry.runtime_data
        record = coord.data["devices"][device.id]
        record[DEV_DAILY_MAX] = list(series)
        seen.add(coord._freeze_window(record))
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert len(seen) == 1


async def test_the_report_cell_still_shows_a_fortnight(
    hass: HomeAssistant,
):
    device, _ = _register(hass, "jd3", "Cell Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [600.0 + n for n in range(120)]
    assert len(coord._format_maxima_cell(record[DEV_DAILY_MAX]).split(", ")) == (
        DAILY_MAX_KEEP
    )


async def test_gaps_are_kept_for_the_chosen_length(
    hass: HomeAssistant,
):
    """Reporting gaps join the long series, so three months of them
    can eventually be used to question the fourteen-day window."""
    device, _ = _register(hass, "ke1", "Kept Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 30})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(200)]
    record[DEV_TODAY_MAX] = 999.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30
    assert record[DEV_DAILY_MAX][-1] == 999.0


async def test_the_setting_is_clamped_to_its_band(
    hass: HomeAssistant,
):
    """The floor of thirty is what makes the slider safe: no choice
    can starve a fourteen-day judgment window."""
    for asked, expected in (
        (5, RETENTION_DAYS_MIN),
        (900, RETENTION_DAYS_MAX),
        (60, 60),
    ):
        entry = await setup_entry(hass, {CONF_RETENTION_DAYS: asked})
        assert entry.runtime_data.retention_days == expected
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_reducing_the_setting_waits_for_midnight(
    hass: HomeAssistant,
):
    """A settings dialog should not destroy three months of history
    the instant a slider moves; the trim happens where every other
    trim happens."""
    device, _ = _register(hass, "ke2", "Patient Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 90})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(90)]

    hass.config_entries.async_update_entry(
        entry, options={CONF_RETENTION_DAYS: 30}
    )
    await coord.async_options_updated()
    assert len(record[DEV_DAILY_MAX]) == 90     # untouched for now

    record[DEV_TODAY_MAX] = 1.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30     # trimmed at the roll


async def test_the_slider_reaches_the_advanced_screen(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SETTLE_SHARE: 30,
            CONF_EPISODE_SHARE: 50,
            CONF_COALESCE_MINUTES: 15,
            CONF_RETENTION_DAYS: 180,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RETENTION_DAYS] == 180
    assert entry.runtime_data.retention_days == 180
    assert RETENTION_DAYS_STEP == 30


async def test_the_report_states_the_retention_in_force(
    hass: HomeAssistant,
):
    """The tunables line said "keep 14 days" after retention became a
    setting, telling a reader it kept a fortnight while keeping three
    months (0.8.10)."""
    _register(hass, "tu1", "Tunable Sensor")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 180})
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports, "test")
    with open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()
    assert f"judge on {DAILY_MAX_KEEP} days, keep 180 days." in text


async def test_storage_roundtrip_with_devices(hass: HomeAssistant, hass_storage):
    """Per-device statistics survive a reload."""
    device, eid = _register(hass, "roundtrip", "Roundtrip Device")

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    await coord._store.async_save(coord.data)

    assert device.id in hass_storage[STORAGE_KEY]["data"][DATA_DEVICES]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert device.id in coord2.data[DATA_DEVICES]
    assert coord2.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT] == 1


async def test_a_stored_outbox_is_dropped_on_load(
    hass: HomeAssistant, hass_storage
):
    """The dry-run outbox was retired at 0.9.11. An install that
    carried one sheds it on the next load rather than paying for a
    dead key in every write."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {},
            "outbox": [{"text": "a line from the dry run"}],
        },
    }
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert "outbox" not in coord.data

    await coord._save_now()
    assert "outbox" not in hass_storage[STORAGE_KEY]["data"]


# ==================================================================
# The storage split, phase B: the hot file is read back.
# ==================================================================

def _hot(hass_storage, clocks, saved_at):
    """Put a hot file on disk with the given clocks and stamp."""
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "data": {DATA_SAVED_AT: saved_at, "clocks": clocks},
    }


def _cold(hass_storage, devices, saved_at):
    """Put a main storage file on disk with the given devices."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: devices,
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: saved_at,
        },
    }


async def test_the_hot_file_supplies_the_clocks(
    hass: HomeAssistant, hass_storage
):
    """Phase B: a routine save wrote the clocks here and nowhere
    else, so the load has to take them from here or lose them."""
    device, _eid = _register(hass, "hot1", "Hot Device")
    _cold(hass_storage, {device.id: _new_device_record(
        "2026-07-11T00:00:00+00:00", 1000.0)}, saved_at=1000.0)
    _hot(hass_storage, {device.id: {
        DEV_LAST_ACTIVITY: 9000.0, DEV_EVENT_COUNT: 42,
    }}, saved_at=9000.0)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_LAST_ACTIVITY] == 9000.0
    assert record[DEV_EVENT_COUNT] == 42


async def test_an_older_hot_file_is_refused(
    hass: HomeAssistant, hass_storage
):
    """The reason the stamp exists. The main file is written first
    and the hot file second, so a failure between them leaves a stale
    hot file. Merging it would drag a device's last activity
    backwards, which reads as silence and earns a freeze it never
    deserved."""
    device, _eid = _register(hass, "hot2", "Stale Hot Device")
    fresh = _new_device_record("2026-07-11T00:00:00+00:00", 1000.0)
    fresh[DEV_LAST_ACTIVITY] = 9000.0
    fresh[DEV_EVENT_COUNT] = 42
    _cold(hass_storage, {device.id: fresh}, saved_at=9000.0)
    _hot(hass_storage, {device.id: {
        DEV_LAST_ACTIVITY: 1000.0, DEV_EVENT_COUNT: 1,
    }}, saved_at=1000.0)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_LAST_ACTIVITY] == 9000.0
    assert record[DEV_EVENT_COUNT] == 42


async def test_an_unstamped_pair_is_left_alone(
    hass: HomeAssistant, hass_storage
):
    """Every install's first load after upgrading. Before 0.10.0 both
    files were written together, so the main file is already current
    and a merge it cannot date is a merge it should not make."""
    device, _eid = _register(hass, "hot3", "Unstamped Device")
    old = _new_device_record("2026-07-11T00:00:00+00:00", 1000.0)
    old[DEV_LAST_ACTIVITY] = 5000.0
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {DATA_DEVICES: {device.id: old},
                 DATA_STATS_EPOCH: STATS_EPOCH},
    }
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "data": {"clocks": {device.id: {DEV_LAST_ACTIVITY: 1.0}}},
    }

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_LAST_ACTIVITY] == 5000.0


async def test_a_device_only_the_hot_file_knows_is_skipped(
    hass: HomeAssistant, hass_storage
):
    """Nine fields cannot rebuild a record, so a device the main file
    has never heard of is not invented here."""
    device, _eid = _register(hass, "hot4", "Known Device")
    _cold(hass_storage, {device.id: _new_device_record(
        "2026-07-11T00:00:00+00:00", 1000.0)}, saved_at=1000.0)
    _hot(hass_storage, {
        device.id: {DEV_LAST_ACTIVITY: 9000.0},
        "a-device-that-is-not-in-the-main-file": {DEV_LAST_ACTIVITY: 9000.0},
    }, saved_at=9000.0)

    entry = await setup_entry(hass)
    devices = entry.runtime_data.data[DATA_DEVICES]
    assert devices[device.id][DEV_LAST_ACTIVITY] == 9000.0
    assert "a-device-that-is-not-in-the-main-file" not in devices


async def test_the_epoch_wipe_still_has_the_last_word(
    hass: HomeAssistant, hass_storage
):
    """The ordering the merge depends on. Six of the nine clock
    fields are exactly what a statistics epoch wipes, so a merge that
    ran afterwards would hand them straight back and a declared epoch
    would quietly fail to take."""
    device, _eid = _register(hass, "hot5", "Epoch Device")
    stale = _new_device_record("2026-07-11T00:00:00+00:00", 1000.0)
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device.id: stale},
            DATA_STATS_EPOCH: "an-older-epoch",
            DATA_SAVED_AT: 1000.0,
        },
    }
    _hot(hass_storage, {device.id: {
        DEV_SIGNAL_VALUE: 42.0, DEV_TAINTED: True,
    }}, saved_at=9000.0)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_SIGNAL_VALUE] is None
    assert record[DEV_TAINTED] is False


async def test_shutdown_writes_the_pair_whatever_the_flags_say(
    hass: HomeAssistant, hass_storage
):
    """A routine save writes the hot file alone and clears the dirty
    flag, so a stop that waited on a flag would leave the main file
    behind. Writing both here is what makes going back to an older
    version safe."""
    _register(hass, "hot6", "Shutdown Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._dirty = False
    coord._critical = False
    cold = _StoreSpy(coord._store)
    hot = _StoreSpy(coord._clock_store)

    await coord.async_shutdown()
    assert cold.saves == 1
    assert hot.saves == 1


async def test_setup_stamps_both_files_at_once(
    hass: HomeAssistant, hass_storage
):
    """An unstamped main file beside a stamped hot one is a pair the
    merge cannot compare, so it declines. Setup writes storage
    directly rather than through the immediate-save path, so if it
    left the stamp off, every clock written between the first load
    and the first critical save would be dropped at the next
    restart."""
    await setup_entry(hass)
    cold = hass_storage[STORAGE_KEY]["data"]
    hot = hass_storage[STORAGE_CLOCKS_KEY]["data"]
    assert cold.get(DATA_SAVED_AT) is not None
    assert hot.get(DATA_SAVED_AT) is not None


# ==================================================================
# The cold write: everything the hot file does not carry.
# ==================================================================

async def test_an_incident_schedules_the_main_file(
    hass: HomeAssistant, freezer
):
    """Phase B left an incident with no write of its own, so it waited
    for an unrelated critical change. It gets one now, on the shorter
    cold window rather than the routine one.

    Renamed in 0.10.3: this exercises the incident recorder, which is
    what it always did. Its old name promised episode coverage that
    its body never gave, and the two episode paths went unwired for
    three releases behind that promise. The episode tests below are
    the coverage the old name implied.
    """
    device, _eid = _register(hass, "cw1", "Cold Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    # Through the real path, not by calling the marker directly, so
    # this fails if the wiring is ever undone rather than only if the
    # marker itself breaks.
    coord._record_incident(
        device_id=device.id,
        name="Cold Device",
        kind="unavailable",
        event=INCIDENT_OPENED,
    )

    assert spy.delays == 1
    assert spy.last_delay == COLD_WRITE_DEBOUNCE_SECONDS


def _armed_and_silent(coord, device_id, basis_hours, share):
    """Arm a device and backdate it to a point inside its window.

    share is where to sit between the episode threshold and the freeze
    line, so a caller can open an episode without also tripping a
    verdict. A verdict would resolve an incident on recovery, and that
    incident marks the main file cold by itself, which would let a
    broken episode path pass on somebody else's write.
    """
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [basis_hours * 3600.0] * (
        FREEZE_ARMING_DAYS + 2
    )
    window = coord._freeze_window(record)
    basis = basis_hours * 3600.0
    opens_at = basis + EPISODE_OPEN_SHARE * (window - basis)
    silence = opens_at + share * (window - opens_at)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - silence
    return record


async def test_opening_an_episode_schedules_the_main_file(
    hass: HomeAssistant, freezer
):
    """An episode exists only in the main file, so opening one has to
    schedule that file.

    Before 0.10.3 it raised the routine flag instead, which writes the
    clocks file, and the clocks file carries no episodes. The flag was
    then cleared by that write, so nothing anywhere remembered the row
    was unwritten and it waited on an unrelated cold change. This is
    the split's own regression: _dirty meant write everything before
    Phase B and means write the clocks after it, and this call site
    was not moved up with its neighbours.
    """
    device, eid = _register(hass, "ep1", "Episode Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()

    coord._grace_until = 0.0
    _armed_and_silent(coord, device.id, 3.7, 0.5)

    spy = _StoreSpy(coord._store)
    coord._judge_all_devices()

    assert coord.data.get(DATA_EPISODES), "no episode opened"
    assert coord.data[DATA_DEVICES][device.id].get(
        DEV_FROZEN_SINCE
    ) is None, "the silence tripped a verdict, so this proves nothing"
    assert spy.delays == 1
    assert spy.last_delay == COLD_WRITE_DEBOUNCE_SECONDS


async def test_closing_an_episode_schedules_the_main_file(
    hass: HomeAssistant, freezer
):
    """The close carries the ending, the lag, and whether the gap was
    learned, and all three live only in the main file.

    The device recovers on its own with no verdict behind it, which is
    the exposed case: no incident resolves, no stamp is taken, and
    nothing else would have scheduled the write.
    """
    device, eid = _register(hass, "ep2", "Closing Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()

    coord._grace_until = 0.0
    _armed_and_silent(coord, device.id, 3.7, 0.5)
    coord._judge_all_devices()
    assert coord.data.get(DATA_EPISODES), "no episode opened"

    spy = _StoreSpy(coord._store)
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    closed = [
        ep
        for ep in coord.data[DATA_EPISODES]
        if ep[EP_ENDED] == EPISODE_ENDED_RESUMED
    ]
    assert closed, "the episode never closed"
    assert spy.delays >= 1
    assert spy.last_delay == COLD_WRITE_DEBOUNCE_SECONDS


async def test_a_wave_of_cold_changes_costs_one_write(
    hass: HomeAssistant, freezer
):
    """A bridge reconnect opens an episode on every device at once.
    Sixty full writes in ninety seconds would give back the saving
    the split exists for, so each change pushes the write out and the
    wave costs one."""
    _register(hass, "cw2", "Wave Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    for _ in range(60):
        coord._mark_cold_dirty()
        freezer.tick(timedelta(seconds=1))

    # Sixty schedules, but the store coalesces them: the write itself
    # has not fired, and the burst is still one pending window.
    assert spy.delays == 60
    assert spy.saves == 0


async def test_the_cap_stops_a_burst_deferring_for_ever(
    hass: HomeAssistant, freezer
):
    """Each change pushing the write out is the point, until it is
    not: a stream that never pauses would defer the write
    indefinitely, so past the cap it happens regardless."""
    _register(hass, "cw3", "Capped Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    coord._mark_cold_dirty()
    assert spy.saves == 0
    # Still inside the cap: the window is pushed out, not written.
    freezer.tick(timedelta(seconds=COLD_WRITE_CAP_SECONDS - 5))
    coord._mark_cold_dirty()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spy.saves == 0

    # Past it: the write happens rather than being deferred again.
    freezer.tick(timedelta(seconds=10))
    coord._mark_cold_dirty()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spy.saves == 1
    assert coord._cold_since is None


async def test_a_freeze_stamp_is_critical_not_merely_cold(
    hass: HomeAssistant, freezer
):
    """The stamp starts the unavailable debounce and its clear is the
    0.9.12 fix. A crash between one reaching disk and the other not
    is how a device comes back reported down for hours, so neither
    waits on a window."""
    device, entity_id = _register(hass, "cw4", "Stamp Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 10
    coord._critical = False

    hass.states.async_set(entity_id, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    coord._apply_freeze_verdict(
        device.id, record, dt_util.utcnow().timestamp()
    )
    assert record[DEV_FROZEN_SINCE] is not None
    assert coord._critical is True
