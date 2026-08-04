# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_timing.py, Version: 0.11.8 (2026-08-04)

"""When a save happens: coalescing, and what forces one.

One of the files split out of test_storage.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""



from datetime import timedelta
from unittest.mock import patch

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EP_ENDED,
    EPISODE_ENDED_RESUMED,
    EPISODE_OPEN_SHARE,
    FREEZE_ARMING_DAYS,
    INCIDENT_OPENED,
    STARTUP_GRACE_SECONDS,
    DATA_SAVED_AT,
    STORAGE_COALESCE_SECONDS,
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


async def test_routine_churn_coalesces(hass: HomeAssistant, freezer):
    """The first dirty tick opens the window; churn inside it writes
    nothing; the window closing writes the hot file alone (#165)."""
    device, entity_id = _register(hass, "r1", "Routine Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    # Setup discovers this test's device after its own save, which
    # sets the cold flag legitimately: a new record is a cold change.
    # Baseline it so the assertions below measure churn alone.
    await coord._save_now()
    cold = _StoreSpy(coord._store)
    hot = _StoreSpy(coord._clock_store)

    # The baseline opened the window; a dirty tick past its deadline
    # writes once and starts the next, keeping a session from
    # silently running a full interval unsaved.
    freezer.tick(timedelta(seconds=coord.coalesce_seconds))
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hot.saves == 1
    assert coord._next_routine_save > 0.0

    # Churn inside the window: nothing written.
    for step in range(5):
        hass.states.async_set(entity_id, str(step + 2))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hot.saves == 1

    # The window closes: the hot file goes out alone.
    freezer.tick(timedelta(seconds=coord.coalesce_seconds))
    hass.states.async_set(entity_id, "99")
    await hass.async_block_till_done()
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hot.saves == 2
    # Phase B: churn never touches the main file, which is the saving.
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
    schedule time.

    Under Phase C the serialized view is a filtered copy rather than
    the live object, so identity can no longer be the assertion. What
    the test protects is unchanged: the values written are the values
    at write time. The clock fields are absent from the view by
    design; that behaviour has its own tests in test_clock_strip.py.
    """
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    out = coord._data_to_save()
    assert out[DATA_SAVED_AT] == coord.data[DATA_SAVED_AT]
    assert set(out[DATA_DEVICES]) == set(coord.data[DATA_DEVICES])


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


async def test_dirty_ticks_write_once_per_window(
    hass: HomeAssistant, freezer
):
    """Continuous churn costs one write per interval, no more.

    This is the 0.6.5 lesson restated for the new scheduler: a fleet
    that is always dirty must neither write every tick nor push the
    deadline forward forever. The deadline is a plain float that only
    the write that satisfies it advances."""
    device, entity_id = _register(hass, "c1", "Churn Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    # Baseline: setup discovered this device after its own save, so
    # the cold flag is legitimately set; clear it with one write.
    await coord._save_now()
    spy = _StoreSpy(coord._clock_store)
    cold = _StoreSpy(coord._store)

    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Twenty dirty ticks, one a minute: churn crossing one or two
    # 900 s window boundaries from the baseline write.
    value = 0
    for _ in range(20):
        value += 1
        hass.states.async_set(entity_id, str(value))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    # Twenty-five minutes of churn against a 15 minute window is one
    # or two boundary writes, never twenty.
    assert 1 <= spy.saves <= 2
    assert cold.saves == 0          # and the main file stays put


async def test_immediate_save_restarts_the_window(
    hass: HomeAssistant, freezer
):
    """A critical save mid-window restarts the interval, so churn
    after it waits a fresh full window rather than writing early."""
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
    before = coord._next_routine_save

    # An acknowledgment-style direct save mid-window.
    freezer.tick(timedelta(seconds=60))
    await coord._save_now()
    assert coord._next_routine_save > before
    saves_after_direct = spy.saves

    # Churn right after it: inside the fresh window, nothing written.
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spy.saves == saves_after_direct


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

    assert spy.delays == 0, "a cold change must not schedule (#165)"
    assert coord._cold_dirty is True


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
    assert spy.delays == 0, "a cold change must not schedule (#165)"
    assert coord._cold_dirty is True


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
    assert spy.delays == 0, "a cold change must not schedule (#165)"
    assert coord._cold_dirty is True


async def test_a_wave_of_cold_changes_costs_one_flag(
    hass: HomeAssistant, freezer
):
    """A bridge reconnect opens an episode on every device at once.
    Sixty full writes in ninety seconds would give back the saving
    the split exists for. Sixty changes now set one flag, schedule
    nothing, and the next interval write carries them all (#165)."""
    _register(hass, "cw2", "Wave Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord._save_now()  # baseline: clear setup's registry flag
    spy = _StoreSpy(coord._store)

    for _ in range(60):
        coord._mark_cold_dirty()
        freezer.tick(timedelta(seconds=1))

    assert spy.delays == 0
    assert spy.saves == 0
    assert coord._cold_dirty is True


async def test_a_cold_change_waits_at_most_one_interval(
    hass: HomeAssistant, freezer
):
    """The old cap bounded how long a burst could defer the cold
    write. The bound is now structural: the flag cannot be pushed,
    so the interval write after the change always carries it."""
    _register(hass, "cw3", "Capped Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord._save_now()  # baseline: clear setup's registry flag
    spy = _StoreSpy(coord._store)

    coord._mark_cold_dirty()
    # A burst keeps arriving; nothing defers because nothing schedules.
    for _ in range(10):
        freezer.tick(timedelta(seconds=30))
        coord._mark_cold_dirty()
    assert spy.saves == 0

    # The interval closes: the write happens and the flag clears.
    freezer.tick(timedelta(seconds=coord.coalesce_seconds))
    coord._dirty = True
    await coord._on_render_tick(None)
    assert spy.saves == 1
    assert coord._cold_dirty is False


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
