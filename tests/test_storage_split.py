# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_split.py, Version: 0.11.8 (2026-08-04)

"""The two files: the shadow, the merge, and the stamps.

One of the files split out of test_storage.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""



from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DEV_BATTERY_DAILY,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    EPOCH_KEPT,
    INCIDENT_OPENED,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_COALESCE_SECONDS,
    STORAGE_KEY,
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
                )
        self._real_delay(data_func, delay)


def _clocks(hass_storage):
    """The shadow as the harness stored it; storage is mocked here."""
    return hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]


def _hot(hass_storage, clocks, saved_at):
    """Put a hot file on disk with the given clocks and stamp."""
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "data": {DATA_SAVED_AT: saved_at, "clocks": clocks},
    }


def _cold(hass_storage, devices, saved_at):
    """Put a main storage file on disk with the given devices.

    Marked as a clean stop, because these tests are about which file
    supplies the clocks and not about what an unclean stop does to
    them. Without the marker the load would take the #163 path and
    reset every clock the merge had just restored, which is correct
    behaviour and would tell us nothing about the merge.
    """
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: devices,
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: saved_at,
            DATA_CLEAN_STOP: True,
        },
    }


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
    verify a release (0.8.8).

    The phase is read from the flag that gates the strip rather than
    written down, after the string said Phase B for eleven releases
    following Phase C shipping (ruling #205). Setup takes the backup
    the strip waits on, so a healthy install reports C, and the
    string moves with the flag rather than being a constant wearing a
    different value.
    """
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _register(hass, "sd1", "Diag Sensor")
    entry = await setup_entry(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    split = diag["split"]
    assert split["phase"].startswith("C:")
    # And it moves with the flag rather than being a constant.
    entry.runtime_data._strip_clocks = False
    later = await async_get_config_entry_diagnostics(hass, entry)
    assert later["split"]["phase"].startswith("B:")
    assert set(split["clock_fields"]) == set(CLOCK_FIELDS)
    assert split["clock_devices"] >= 1


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
    """The reason the stamp exists, and the phase C tripwire.

    This asserts the invariant rather than the mechanism: a load
    reconstructs the newest clocks available to it. When the hot
    file is refused, the main file is what supplies them, which
    holds only while the main file still carries clock fields.
    Phase C stops writing them there, so this test is expected to
    fail on the day phase C lands, and that failure is the point.

    The reason the stamp exists. The main file is written first
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


async def test_a_cold_change_takes_the_main_file_along(
    hass: HomeAssistant, freezer
):
    """The interval write carries both files when the flag is set.

    A cold change used to schedule its own write on its own debounce,
    and two schedules against one pair of files is the race that let
    the main file lead the clocks file. Now it sets a flag, and the
    one scheduler writes both at the interval, main file first, so
    the hot stamp is always the newer of the pair (#165).
    """
    device, _eid = _register(hass, "pair1", "Paired Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    coord._record_incident(
        device_id=device.id,
        name="Paired Device",
        kind="unavailable",
        event=INCIDENT_OPENED,
    )
    assert coord._cold_dirty is True

    cold = _StoreSpy(coord._store)
    hot = _StoreSpy(coord._clock_store)
    # Nothing was scheduled by the change itself.
    assert cold.delays == 0 and hot.delays == 0

    # Force the window closed and tick.
    coord._next_routine_save = 0.0
    coord._dirty = True
    await coord._on_render_tick(None)

    assert cold.saves == 1, "the main file was left behind"
    assert hot.saves == 1
    assert coord._cold_dirty is False


async def test_a_dirty_tick_inside_the_window_moves_nothing(
    hass: HomeAssistant, freezer
):
    """One deadline, owned here, that later dirty ticks cannot push.

    The old fault class: Home Assistant's delayed-save machinery kept
    the nearer of two deadlines but recorded the further one, and
    deferred to it when the timer fired, so a dirty tick could drag a
    scheduled write out from under a cold change. The deadline is now
    a plain float on the coordinator, and a dirty tick inside the
    window neither writes nor moves it."""
    device, eid = _register(hass, "pair2", "Ticking Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()

    # Open the window with a first write.
    await coord._save_now()
    deadline = coord._next_routine_save
    assert deadline > 0.0

    coord._record_incident(
        device_id=device.id,
        name="Ticking Device",
        kind="unavailable",
        event=INCIDENT_OPENED,
    )
    hot = _StoreSpy(coord._clock_store)
    cold = _StoreSpy(coord._store)

    coord._dirty = True
    await coord._on_render_tick(None)

    assert hot.saves == 0 and hot.delays == 0
    assert cold.saves == 0 and cold.delays == 0
    assert coord._next_routine_save == deadline
    assert coord._cold_dirty is True, "the flag must wait for the window"


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
    """The ordering the merge depends on: a merge running after the
    wipe would hand the wiped fields straight back.

    Narrowed in 0.11.8. The epoch wipes the rhythm and the verdict
    drawn from it, six fields, and keeps everything else, because
    there is no raw layer to rebuild a wiped series from and the
    signal and battery histories are soaks in progress (ruling #204).
    So the taint flag is reset here and the signal reading is not.
    """
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
    assert record[DEV_TAINTED] is False
    assert record[DEV_DAILY_MAX] == []
    # Kept, and the reason the wipe was narrowed: a wiped series
    # cannot be rebuilt, because the readings behind it are never
    # stored.
    assert record[DEV_SIGNAL_VALUE] == 42.0


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


async def test_the_main_file_never_leads_the_clocks_file(
    hass: HomeAssistant, freezer, hass_storage
):
    """The invariant the whole 0.10.9 cadence exists for (#165).

    Cold changes arrive at every offset inside the interval, critical
    saves land mid-window, and churn runs throughout. After every
    single write, the main file's stamp is never newer than the
    clocks file's, because the one scheduler writes cold first and
    hot second and nothing else writes at all. This is the state the
    final phase of the split cannot survive, held down structurally.
    """
    from custom_components.device_sentinel.const import (
        DATA_SAVED_AT,
        STORAGE_CLOCKS_KEY,
        STORAGE_KEY,
    )

    device, eid = _register(hass, "inv1", "Invariant Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord._save_now()

    def check(moment):
        big = ((hass_storage.get(STORAGE_KEY) or {}).get("data") or {}
               ).get(DATA_SAVED_AT)
        small = ((hass_storage.get(STORAGE_CLOCKS_KEY) or {}).get("data")
                 or {}).get(DATA_SAVED_AT)
        assert small >= big, (
            f"main file leads by {big - small:.3f}s {moment}"
        )

    value = 0
    for minute in range(40):
        value += 1
        hass.states.async_set(eid, str(value))
        await hass.async_block_till_done()
        # A cold change at every third minute: every offset in the
        # window gets exercised across the run.
        if minute % 3 == 0:
            coord._record_incident(
                device_id=device.id,
                name="Invariant Device",
                kind="unavailable",
                event=INCIDENT_OPENED,
            )
        # A critical save mid-run, as an acknowledgment would.
        if minute == 17:
            coord._critical = True
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        check(f"at minute {minute}")

    # And a clean stop on top, which must hold the same order.
    freezer.tick(timedelta(seconds=30))
    await coord._on_hass_stop(None)
    check("after the stop")


async def test_the_interval_write_puts_the_main_file_first(
    hass: HomeAssistant, freezer
):
    """Within a carried write the main file goes first (#165).

    The stamps cannot prove the order under test, because both files
    stamp with the same frozen clock, so this watches the calls. If
    the pair is ever torn mid-write, the survivor must be the main
    file, whose own clocks are then the newer source; a torn pair
    the other way round leaves a hot file the merge trusts over a
    main file that never landed.
    """
    device, _eid = _register(hass, "ord1", "Ordered Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord._save_now()

    order: list[str] = []
    real_big = coord._store.async_save
    real_small = coord._clock_store.async_save

    async def big(data):
        order.append("main")
        await real_big(data)

    async def small(data):
        order.append("clocks")
        await real_small(data)

    coord._store.async_save = big
    coord._clock_store.async_save = small

    coord._record_incident(
        device_id=device.id,
        name="Ordered Device",
        kind="unavailable",
        event=INCIDENT_OPENED,
    )
    coord._next_routine_save = 0.0
    coord._dirty = True
    await coord._on_render_tick(None)

    assert order == ["main", "clocks"]


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


async def test_an_older_record_gains_the_fields_this_version_adds(
    hass: HomeAssistant, hass_storage
):
    """End to end through the load path (ruling #189).

    A stored record from a version before the signal statistics
    existed, with a stale statistics epoch so it takes the wipe
    branch, which is precisely the branch whose hand-maintained
    backfill had drifted and never set them. Every schema field is
    present after setup, whichever branch the load took.
    """
    device, _eid = _register(hass, "older1", "Older Device")
    stored = _new_device_record("2026-07-01T00:00:00+00:00", 1000.0)
    for key in (
        "signal_sum",
        "signal_sum_sq",
        "signal_count",
        "signal_today_max",
        "signal_daily_mean",
        "signal_daily_sd",
        "signal_daily_max",
    ):
        del stored[key]
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device.id: stored},
            DATA_STATS_EPOCH: "0.0.1",
        },
    }

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    assert set(record.keys()) == set(_new_device_record("", None))


async def test_an_epoch_wipe_keeps_what_cannot_be_rebuilt(
    hass: HomeAssistant, hass_storage
):
    """Ruling #204. There is no raw layer under these records: a
    reading is folded into a daily figure as it arrives and the
    reading itself is never stored, so a wiped series is gone with
    nothing to rebuild it from.

    The epoch exists to relearn the rhythm, which its own log line
    has always said. It wipes six fields and keeps the rest, so a
    signal soak measured in weeks and a battery soak measured in
    months both survive a rhythm rule changing.
    """
    device, _eid = _register(hass, "ep2", "Soaking Device")
    stale = _new_device_record("2026-07-11T00:00:00+00:00", 1000.0)
    stale[DEV_DAILY_MAX] = [600.0, 700.0]
    stale[DEV_SIGNAL_DAILY_MIN] = [120.0, 116.0]
    stale[DEV_SIGNAL_DAILY_MEAN] = [147.7]
    stale[DEV_SIGNAL_DAILY_SD] = [7.5]
    stale[DEV_BATTERY_DAILY] = [32.0, 31.5]
    stale[DEV_SIGNAL_DWELL_DAILY] = [4.0, 96.7]
    stale[DEV_FROZEN_CATEGORY] = "frozen"
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device.id: stale},
            DATA_STATS_EPOCH: "an-older-epoch",
            DATA_SAVED_AT: 1000.0,
        },
    }

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    # The rhythm, and the verdicts drawn from it, are gone. Dwell
    # counts as a verdict: it was accrued against a line the rule
    # change moved, and nothing survives to recompute it from.
    assert record[DEV_DAILY_MAX] == []
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_SIGNAL_DWELL_DAILY] == []
    # Both soaks survive.
    assert record[DEV_SIGNAL_DAILY_MIN] == [120.0, 116.0]
    assert record[DEV_SIGNAL_DAILY_MEAN] == [147.7]
    assert record[DEV_SIGNAL_DAILY_SD] == [7.5]
    assert record[DEV_BATTERY_DAILY] == [32.0, 31.5]


def test_the_kept_set_and_the_wipe_partition_the_schema():
    """The half that keeps this honest as fields are added.

    A count that has to be maintained by hand drifts, which is the
    fault #189 exists for. Here the wipe is derived, so what needs
    pinning is that every schema field is either kept on purpose or
    wiped on purpose, and none is in neither or both.
    """
    schema = set(_new_device_record("", None))
    kept = set(EPOCH_KEPT)
    assert kept <= schema, sorted(kept - schema)
    wiped = schema - kept
    assert len(wiped) == 7, sorted(wiped)
    assert wiped == {
        "daily_max",
        "today_max",
        "event_count",
        "tainted",
        "frozen_category",
        "frozen_since",
        # A verdict rather than a measurement: accrued against a line
        # that a rule change moves, and not recomputable afterwards
        # because the readings behind it are gone.
        "signal_dwell_daily_pct",
    }


async def test_nothing_is_wiped_without_a_backup(
    hass: HomeAssistant, hass_storage
):
    """A wipe cannot be undone, so a backup that will not take is a
    stop rather than a warning (ruling #204)."""
    device, _eid = _register(hass, "ep3", "Guarded Device")
    stale = _new_device_record("2026-07-11T00:00:00+00:00", 1000.0)
    stale[DEV_DAILY_MAX] = [600.0]
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device.id: stale},
            DATA_STATS_EPOCH: "an-older-epoch",
            DATA_SAVED_AT: 1000.0,
        },
    }

    async def _refuse(hass, data, suffix):
        return False

    with patch(
        "custom_components.device_sentinel.coordinator.async_take_backup",
        _refuse,
    ):
        entry = await setup_entry(hass)

    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_DAILY_MAX] == [600.0]
    # And the epoch is not marked done, so the next start tries again.
    assert entry.runtime_data.data[DATA_STATS_EPOCH] == "an-older-epoch"
