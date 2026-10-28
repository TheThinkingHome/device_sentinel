# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_esphome_connection.py, Version: 0.27.10 (2026-10-27)

"""An ESPHome device's connection through a drop and a return
(rule STACK-07).

Home Assistant's ESPHome integration sets the connection flag false
before it writes the device's entities unavailable, keeps the Status
sensor available and switches it off, and sets the flag true before
any state arrives on a reconnect. Nothing written while the flag is
false is the device speaking; the device is unavailable for the whole
drop, so the gap spanning it is not learned, whichever entity reports
first on the return.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    STARTUP_GRACE_SECONDS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_MUTED_DEVICES,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import arm, past_grace, walk

PIN = "2026-10-11 15:00:00+00:00"
HOUR = 3600.0


def _dropped(coord, device_id):
    """The saved start of a device's outage, its drop here (rule UNAV-04)."""
    saved = coord.data[DATA_DEVICES][device_id].get("down_since")
    return saved[0] if saved else None


class _Info:
    def __init__(self, deep_sleep):
        self.has_deep_sleep = deep_sleep


class _Runtime:
    def __init__(self, deep_sleep, available=True):
        self.device_info = _Info(deep_sleep)
        self.available = available


def _source(hass, runtime):
    source = MockConfigEntry(domain="esphome")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    source.runtime_data = runtime
    return source


def _esp_device(hass, source, uid, domains):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", uid)}, name=f"Device {uid}")
    eids = []
    for index, domain in enumerate(domains):
        entity = er.async_get(hass).async_get_or_create(
            domain, "esphome", f"{uid}_{index}", device_id=device.id, config_entry=source)
        eids.append(entity.entity_id)
    return device, eids


def _arm(coord, device_id, rhythm=3600.0):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [rhythm] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_TODAY_MAX] = None
    return record


async def _past_grace(hass, freezer):
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _tick(hass, freezer, step=61, n=1):
    for _ in range(n):
        freezer.tick(timedelta(seconds=step))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def _ready(hass, freezer, uid, flag=False, domains=("sensor", "binary_sensor"), values=("21.5", "on")):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(flag))
    device, eids = _esp_device(hass, source, uid, domains)
    coord = await setup_coordinator(hass)
    record = _arm(coord, device.id)
    for eid, value in zip(eids, values):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    await _past_grace(hass, freezer)
    return coord, device, eids, record, source


async def _drop(hass, source, eids, status_index=1):
    source.runtime_data.available = False
    for index, eid in enumerate(eids):
        hass.states.async_set(eid, "off" if index == status_index else "unavailable")
    await hass.async_block_till_done()


async def _reconnect(hass, source, eids, values, order=None):
    source.runtime_data.available = True
    for index in order or range(len(eids)):
        hass.states.async_set(eids[index], values[index])
        await hass.async_block_till_done()


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]



async def test_a_same_value_write_while_dropped_is_not_the_device_speaking(hass: HomeAssistant, freezer):
    """Nothing written while the connection is down is the device
    speaking (rule STACK-07). Home Assistant rewrites an entity with the
    same value (a registry edit, a second device update) as a
    state_reported event, not a state change. The Status sensor
    rewritten "off" while dropped must not move the clock or clear the
    unavailable verdict."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r601")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _drop(hass, source, eids)
    await _tick(hass, freezer, step=600, n=3)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    before = record[DEV_LAST_ACTIVITY]
    hass.states.async_set(eids[1], "off", force_update=False)  # same value: state_reported
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == before, "a same-value write while dropped moved the clock"
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    assert not _mine(recoveries, device.id), recoveries



async def test_the_report_on_reconnect_is_never_lost(hass: HomeAssistant, freezer):
    """True is set before any state on reconnect, so the first state
    after it is a report: the verdict clears at once, one recovery fires,
    and its down_for counts from the drop, since the trouble began as
    unavailable, not as a freeze (rules STACK-07, UNAV-07)."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r602")
    recoveries = record_events(hass, EVENT_RECOVERED)
    last_report = record[DEV_LAST_ACTIVITY]
    dropped_at = dt_util.utcnow().timestamp()
    await _drop(hass, source, eids)
    await _tick(hass, freezer, step=600, n=6)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    await _reconnect(hass, source, eids, ("22.0", "on"))
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_LAST_ACTIVITY] > last_report
    await _tick(hass, freezer)
    mine = _mine(recoveries, device.id)
    assert len(mine) == 1, mine
    expected = record[DEV_LAST_ACTIVITY] - dropped_at
    assert abs(mine[0]["down_for"] - expected) <= 61, (mine[0], expected)



@pytest.mark.parametrize("order", [(1, 0), (0, 1)], ids=["status_first", "sensor_first"])
async def test_the_gap_spanning_a_drop_is_not_learned(hass: HomeAssistant, freezer, order):
    """A device judged unavailable for a two-hour drop has not been
    heard for any of it, so the gap spanning the drop is not learned
    (rules STACK-07, FRZ-14). ESPHome sends binary sensors first on a
    reconnect, so the Status sensor ("on") is normally the first entity
    written. Run both orders."""
    coord, device, eids, record, source = await _ready(hass, freezer, f"r603{order[0]}")
    await _tick(hass, freezer, step=60, n=2)
    record[DEV_TODAY_MAX] = None
    await _drop(hass, source, eids)
    await _tick(hass, freezer, step=600, n=12)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    await _reconnect(hass, source, eids, ("22.0", "on"), order=order)
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, (
        "the two-hour drop was learned as the device's own silence", learned)



async def test_a_status_only_device_does_not_learn_its_drop(hass: HomeAssistant, freezer):
    """The same promise for a device whose only watched entity is its Status
    sensor: the drop writes nothing unavailable, so nothing taints."""
    coord, device, eids, record, source = await _ready(
        hass, freezer, "r604", domains=("binary_sensor",), values=("on",))
    await _tick(hass, freezer, step=60, n=2)
    record[DEV_TODAY_MAX] = None
    await _drop(hass, source, eids, status_index=0)
    await _tick(hass, freezer, step=600, n=12)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    await _reconnect(hass, source, eids, ("on",))
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, ("drop learned", learned)


async def test_dropped_inside_startup_grace_then_judged_after(hass: HomeAssistant, freezer):
    """A device still disconnected when Device Sentinel starts (ESPHome sets
    available False until it connects): nothing judged inside the grace
    (rule WATCH-10), unavailable after it, never frozen; its Status "off"
    written during the grace is not a report."""
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False, available=False))
    device, eids = _esp_device(hass, source, "r605", ("sensor", "binary_sensor"))
    hass.states.async_set(eids[0], "21.5")
    hass.states.async_set(eids[1], "on")
    coord = await setup_coordinator(hass)
    record = _arm(coord, device.id)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 30 * 3600.0
    before = record[DEV_LAST_ACTIVITY]
    hass.states.async_set(eids[0], "unavailable")
    hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == before
    seen = []
    await _past_grace(hass, freezer)
    for _ in range(12):
        await _tick(hass, freezer)
        seen.append(record[DEV_FROZEN_CATEGORY])
    assert FREEZE_CATEGORY_FROZEN not in seen, seen
    assert seen[-1] == FREEZE_CATEGORY_UNAVAILABLE, seen


async def test_runtime_replaced_on_reload_is_read_afresh(hass: HomeAssistant, freezer):
    """ESPHome's reload removes runtime_data (Home Assistant deletes it on
    unload) and sets a new object. While it is missing the device keeps
    the freeze rule; the new object is read, not a cached one, and a
    dropped new runtime is judged unavailable."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r606")
    assert coord._awake_esphome(device.id) is True
    object.__delattr__(source, "runtime_data")
    assert coord._esphome_flags(device.id) == (None, None)
    assert coord._awake_esphome(device.id) is False and coord._dropped_esphome(device.id) is False
    source.runtime_data = _Runtime(False, available=False)
    assert coord._dropped_esphome(device.id) is True
    source.runtime_data.available = True
    assert coord._awake_esphome(device.id) is True


async def test_device_info_none_before_first_connect_then_readable(hass: HomeAssistant, freezer, caplog):
    """A new ESPHome entry has device_info None until its first connect:
    unknown, logged once at info; once device_info arrives the flags are
    read (the log-once set does not pin it to unknown)."""
    caplog.set_level(logging.INFO)
    coord, device, eids, record, source = await _ready(hass, freezer, "r607")
    source.runtime_data.device_info = None
    for _ in range(3):
        assert coord._esphome_flags(device.id) == (None, None)
    source.runtime_data.device_info = _Info(False)
    assert coord._esphome_flags(device.id) == (False, True)
    lines = [r for r in caplog.records if "could not read whether an ESPHome" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO, [r.getMessage() for r in lines]


@pytest.mark.parametrize("deep, avail", [
    (0, True), (False, 1), (False, None), ("False", True), (False, "False"), (1.0, False),
])
async def test_hostile_flags_answer_unknown(hass: HomeAssistant, freezer, deep, avail):
    """Each flag must be a real bool; anything else answers unknown (rule STACK-08)."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r608")
    source.runtime_data = _Runtime(deep, avail)
    assert coord._esphome_flags(device.id) == (None, None)
    assert not coord._dropped_esphome(device.id) and not coord._awake_esphome(device.id)


async def test_raising_property_answers_unknown(hass: HomeAssistant, freezer):
    coord, device, eids, record, source = await _ready(hass, freezer, "r609")

    class Boom:
        @property
        def available(self):
            raise RuntimeError("moved")

        device_info = _Info(False)

    source.runtime_data = Boom()
    assert coord._esphome_flags(device.id) == (None, None)


async def test_several_devices_on_one_entry_drop_together(hass: HomeAssistant, freezer):
    """Several devices on one ESPHome entry (sub-devices): one flag speaks
    for all. All are judged unavailable on a drop, none frozen, and the
    Status sensor on the main device is not a report for any."""
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    devices = [_esp_device(hass, source, f"r610{i}", ("sensor", "binary_sensor")) for i in range(3)]
    coord = await setup_coordinator(hass)
    records = [_arm(coord, d.id) for d, _ in devices]
    for _, eids in devices:
        hass.states.async_set(eids[0], "21.5")
        hass.states.async_set(eids[1], "on")
    await hass.async_block_till_done()
    await _past_grace(hass, freezer)
    records[0][DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    records[0][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 30 * 3600.0
    source.runtime_data.available = False
    for _, eids in devices:
        hass.states.async_set(eids[0], "unavailable")
        hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()
    await _tick(hass, freezer, step=600, n=3)
    assert [r[DEV_FROZEN_CATEGORY] for r in records] == [FREEZE_CATEGORY_UNAVAILABLE] * 3


async def test_deep_sleeper_disconnected_keeps_freeze_rule(hass: HomeAssistant, freezer):
    """Deep sleepers keep the freeze rule: asleep (available False) is not
    dropped, so the freeze window still judges it frozen, not unavailable."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r611", flag=True,
                                                       domains=("sensor",), values=("21.5",))
    source.runtime_data.available = False
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 30 * 3600.0
    await _tick(hass, freezer, n=3)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_drop_and_reconnect_before_debounce_publishes_nothing(hass: HomeAssistant, freezer):
    """A drop shorter than the unavailable debounce publishes nothing and
    announces nothing (the debounce applies to the connection verdict as
    to any unavailable)."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r612")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _drop(hass, source, eids)
    await _tick(hass, freezer, step=20)
    assert record[DEV_FROZEN_CATEGORY] is None
    await _reconnect(hass, source, eids, ("21.6", "on"))
    await _tick(hass, freezer, n=3)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(recoveries, device.id)


async def test_ds_reload_while_dropped_keeps_unavailable(hass: HomeAssistant, freezer):
    """Device Sentinel reloaded while an ESPHome device is dropped: the
    verdict stays unavailable through and after the grace, never cleared
    and never frozen, and no recovery is announced."""
    coord, device, eids, record, source = await _ready(hass, freezer, "r613")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _drop(hass, source, eids)
    await _tick(hass, freezer, step=600, n=3)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    entry = hass.config_entries.async_entries("device_sentinel")[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    seen = [record[DEV_FROZEN_CATEGORY]]
    await _past_grace(hass, freezer)
    for _ in range(5):
        await _tick(hass, freezer)
        seen.append(record[DEV_FROZEN_CATEGORY])
    assert set(seen) == {FREEZE_CATEGORY_UNAVAILABLE}, seen
    assert not _mine(recoveries, device.id), recoveries


# --------------------------------------------------------------- down_for


def _entry(hass):
    return hass.config_entries.async_entries("device_sentinel")[0]


@pytest.mark.parametrize("how", ["reload_mid_drop", "dropped_while_unloaded"])
async def test_a_drop_spanning_a_reload_is_not_learned(hass: HomeAssistant, freezer, how):
    """A Device Sentinel reload, or a Home Assistant restart, during a drop
    forgets when the drop began, and the entities already read unavailable
    and off, so nothing more is written. The minute check notes the drop
    again, so the gap spanning it is still not learned (rule STACK-07)."""
    coord, device, eids, record, source = await _ready(hass, freezer, f"reload{how[0]}")
    await _tick(hass, freezer, step=60, n=2)
    record[DEV_TODAY_MAX] = None
    entry = _entry(hass)
    if how == "reload_mid_drop":
        await _drop(hass, source, eids)
        await _tick(hass, freezer, step=600, n=6)
        assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await _drop(hass, source, eids)
        freezer.tick(timedelta(seconds=120))
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coord = _entry(hass).runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, step=600, n=12)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    await _reconnect(hass, source, eids, ("22.0", "on"), order=(1, 0))
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, (
        "a drop the reload forgot was learned as the device's own silence", learned,
        _dropped(coord, device.id))


# The drop survives a reload, a mute and a clock step.


async def _ready_muted(hass, freezer, uid, options=None):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp_device(hass, source, uid, ("sensor", "binary_sensor"))
    if options is not None:
        options = {k: (v if v != "SELF" else [device.id]) for k, v in options.items()}
    coord = await setup_coordinator(hass, options)
    record = _arm(coord, device.id)
    for eid, value in zip(eids, ("21.5", "on")):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    await _past_grace(hass, freezer)
    return coord, device, eids, record, source


async def _drop_both(hass, source, eids):
    source.runtime_data.available = False
    hass.states.async_set(eids[0], "unavailable")
    hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()


async def _return_status_first(hass, source, eids, values=("22.0", "on")):
    source.runtime_data.available = True
    # ESPHome's Status sensor first, then the values.
    hass.states.async_set(eids[1], values[1])
    await hass.async_block_till_done()
    hass.states.async_set(eids[0], values[0])
    await hass.async_block_till_done()


@pytest.mark.parametrize("mute", [CONF_FREEZE_MUTED_DEVICES, CONF_MUTED_DEVICES])
async def test_a_muted_device_does_not_learn_a_drop_across_a_reload(hass: HomeAssistant, freezer, mute):
    """The drop is noted from the minute check, so it survives a reload,
    and a muted device too (rule STACK-07). Muting suppresses judgment,
    not observation: a muted device keeps learning its rhythm, so a
    dropped, muted device must still be noted after a reload, or the
    three-hour drop would be learned as its own silence and carried into
    judgment once unmuted."""
    coord, device, eids, record, source = await _ready_muted(hass, freezer, f"mute{mute[:4]}", {mute: "SELF"})
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    record[DEV_TODAY_MAX] = None
    await _drop_both(hass, source, eids)
    await _tick(hass, freezer, step=600, n=6)
    assert _dropped(coord, device.id) is not None  # noted from the writes
    assert await hass.config_entries.async_reload(_entry(hass).entry_id)
    await hass.async_block_till_done()
    coord = _entry(hass).runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, step=600, n=12)
    noted = _dropped(coord, device.id)
    await _return_status_first(hass, source, eids)
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, ("muted device learned the drop", learned, noted)


@pytest.mark.parametrize("back_after", [60, STARTUP_GRACE_SECONDS + 120])
async def test_a_return_soon_after_a_reload_mid_drop_is_not_learned(hass: HomeAssistant, freezer, back_after):
    """A three-hour drop; Device Sentinel reloads in its third hour and the
    device returns `back_after` seconds later. Judgment is skipped in the
    startup grace, and once it runs it notes the drop at the moment it
    looks, not when the drop began, so a return soon after reads as a
    drop shorter than the debounce. The gap spans three hours of drop and
    must not be learned."""
    coord, device, eids, record, source = await _ready_muted(hass, freezer, f"back{back_after}")
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    record[DEV_TODAY_MAX] = None
    await _drop_both(hass, source, eids)
    await _tick(hass, freezer, step=600, n=18)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert await hass.config_entries.async_reload(_entry(hass).entry_id)
    await hass.async_block_till_done()
    coord = _entry(hass).runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    await _tick(hass, freezer, step=60, n=back_after // 60)
    noted = _dropped(coord, device.id)
    await _return_status_first(hass, source, eids)
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, ("three-hour drop learned after a reload", learned, noted)


@pytest.mark.parametrize("step_hours", [3, -3])
async def test_a_drop_written_just_after_a_clock_step_is_not_learned(hass: HomeAssistant, freezer, step_hours):
    """The system clock is stepped, and the device drops before the next
    minute check notices the step. The drop is noted from the write in the
    new clock; the check then moves every in-memory moment by the step
    (rule FRZ-21), the saved drop start among them, so the drop's start
    lands `step_hours` away from when it really began. Two hours of drop
    must still taint the gap on return."""
    coord, device, eids, record, source = await _ready_muted(hass, freezer, f"step{step_hours}")
    mono = {"now": coord._monotonic()}
    coord._monotonic = lambda: mono["now"]

    async def tick(seconds):
        freezer.tick(timedelta(seconds=seconds))
        mono["now"] += seconds
        await coord._on_render_tick(None)
        await hass.async_block_till_done()

    await tick(60)
    hass.states.async_set(eids[0], "21.7")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=step_hours))
    await _drop_both(hass, source, eids)
    await tick(30)
    shifted = _dropped(coord, device.id)
    for _ in range(120):
        await tick(60)
    record[DEV_TODAY_MAX] = None
    await _return_status_first(hass, source, eids)
    now = dt_util.utcnow().timestamp()
    learned = record[DEV_TODAY_MAX]
    assert learned is None or learned < 3600.0, learned
    assert shifted is None or shifted <= now - 7000, ("drop start moved off its real moment", shifted, now)


@pytest.mark.parametrize("connected_at_setup", [True, False])
async def test_a_restart_before_esphome_connects_costs_no_gap(hass: HomeAssistant, freezer, connected_at_setup):
    """Home Assistant restarts and ESPHome connects to each device a moment
    after Device Sentinel's first look, so a device that is fine reads as
    not connected for a few seconds. That is not a drop to date from its
    last report: the gap its first report ends, two quiet hours and a
    three-minute restart, is learned with the downtime taken out, whichever
    came first (rule FRZ-12)."""
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp_device(hass, source, f"boot{connected_at_setup}", ("sensor", "binary_sensor"))
    for eid, value in zip(eids, ("21.5", "on")):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    coord = await setup_coordinator(hass)
    await _past_grace(hass, freezer)
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    coord.data[DATA_DEVICES][device.id][DEV_TODAY_MAX] = None
    await _tick(hass, freezer, step=600, n=12)  # two hours quiet, connected
    entry = hass.config_entries.async_entries("device_sentinel")[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # Home Assistant down for three minutes; on start ESPHome's entities
    # read unavailable until it connects.
    freezer.tick(timedelta(minutes=3))
    source.runtime_data.available = connected_at_setup
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=5))
    source.runtime_data.available = True
    hass.states.async_set(eids[1], "on")
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    learned = record[DEV_TODAY_MAX]
    # Two hours quiet and three minutes down: 7,385 s, 7,205 s with the
    # downtime taken out (rule FRZ-12).
    assert learned is not None and 7000 < learned < 7400, learned


# ------------------------------------------ judged by its connection alone


def _esp(hass, source, uid, shape):
    """shape: (domain, enabled, entity_category) per entity."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", uid)}, name=f"Proxy {uid}")
    reg = er.async_get(hass)
    eids = []
    for index, (domain, enabled, category) in enumerate(shape):
        eids.append(reg.async_get_or_create(
            domain, "esphome", f"{uid}_{index}", device_id=device.id, config_entry=source,
            entity_category=category,
            disabled_by=None if enabled else er.RegistryEntryDisabler.INTEGRATION,
        ).entity_id)
    return device, eids


PROXY = (
    ("update", True, er.EntityCategory.CONFIG),
    ("button", True, er.EntityCategory.CONFIG),
    ("sensor", False, er.EntityCategory.DIAGNOSTIC),  # Wi-Fi signal, off by default
)


async def test_3_esphome_proxy_buttons_and_update_recovers_on_reconnect(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp_device(hass, source, "r12bt", ("button", "button", "update"))
    values = ("unknown", "unknown", "off")
    coord = await setup_coordinator(hass)
    record = _arm(coord, device.id)
    for eid, value in zip(eids, values):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    back = record_events(hass, EVENT_RECOVERED)

    source.runtime_data.available = False
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    source.runtime_data.available = True
    for eid, value in zip(eids, values):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "connected again for six hours and still listed unavailable",
        record[DEV_FROZEN_CATEGORY], record.get(DEV_DOWN_SINCE), coord._live_entity_states(device.id),
        [e for e in back if e.get("device_id") == device.id],
    )


# 4. The same proxy, newly added: not never reported after the wait,
# because its connection has been up the whole time (rule WATCH-04).
async def test_4_new_esphome_proxy_is_not_never_reported(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp_device(hass, source, "r12bn", ("button", "button", "update"))
    for eid, value in zip(eids, ("unknown", "unknown", "off")):
        hass.states.async_set(eid, value)
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    for _ in range(int(50 * HOUR // 1800)):
        hass.states.async_set(eids[2], "off", force_update=True)
        await hass.async_block_till_done()
        await walk(hass, freezer, 1800, step=600)
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_NEVER_REPORTED, (
        "a connected ESPHome proxy called never reported",
    )


async def test_7_esphome_sensor_down_on_a_live_device_is_not_back_on_reconnect(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp_device(hass, source, "r12s", ("sensor", "update"))
    coord = await setup_coordinator(hass)
    record = _arm(coord, device.id)
    hass.states.async_set(eids[0], "21.5")
    hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    source.runtime_data.available = False
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    back = record_events(hass, EVENT_RECOVERED)
    source.runtime_data.available = True
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "its sensor still reads unavailable"
    assert not [e for e in back if e.get("device_id") == device.id]


# A. An ESPHome device whose only entities switched on are a firmware
# notice and a command button is judged by its connection alone, never
# frozen, whatever it has switched off (rule WATCH-04).
async def test_a_esphome_proxy_with_a_switched_off_sensor_is_not_frozen(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp(hass, source, "r14a", PROXY)
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    record = arm(coord, device.id)
    await past_grace(hass, freezer)
    assert device.id in coord._watched
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "a connected ESPHome proxy, its only switched-on entities a notice and a button, judged",
        record[DEV_FROZEN_CATEGORY], coord._connection_only(device.id),
    )


# B. The same proxy newly added: not never reported after the wait.
async def test_b_new_esphome_proxy_with_a_switched_off_sensor_is_not_never_reported(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp(hass, source, "r14b", PROXY)
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    await walk(hass, freezer, 50 * HOUR, step=1800)
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_NEVER_REPORTED, (
        "a connected ESPHome proxy called never reported",
    )


# C. The same proxy drops: unavailable, and back when it reconnects.
async def test_c_esphome_proxy_with_a_switched_off_sensor_drop_and_return(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp(hass, source, "r14c", PROXY)
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    record = arm(coord, device.id, rhythm=30 * HOUR)
    await past_grace(hass, freezer)
    source.runtime_data.available = False
    for eid in eids[:2]:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    source.runtime_data.available = True
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None, ("reconnected, still listed", record[DEV_FROZEN_CATEGORY])


# 1. A connected ESPHome proxy whose only switched-on entities are a
# firmware notice and a command button is never "never reported". Its
# verdict says so, and the Devices tab and its page do not show the red
# "Never reported" word either (rule WATCH-04).
async def test_r15_1_connection_only_proxy_page_not_never_reported(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp(hass, source, "r15a", (
        ("update", True, er.EntityCategory.CONFIG),
        ("button", True, er.EntityCategory.CONFIG),
    ))
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    await walk(hass, freezer, 50 * HOUR, step=1800)
    assert coord._connection_only(device.id)
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_NEVER_REPORTED
    row = next(r for r in coord.dashboard_devices() if r["device_id"] == device.id)
    page = coord.dashboard_device(device.id)
    assert (row["status"], page["status"]["category"]) == ("reporting", "reporting"), (
        "connected proxy shown as", row["status"], page["status"]["category"],
    )


# 3. An ESPHome device with everything switched off, no notice or button at
# all: it is judged by its connection and never told it never reported
# (rule WATCH-04).
async def test_r15_3_esphome_all_switched_off_is_judged_by_its_connection(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, _eids = _esp(hass, source, "r15c", (
        ("sensor", False, None),
        ("binary_sensor", False, None),
    ))
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    await walk(hass, freezer, 50 * HOUR, step=1800)
    # Connected, so never "never reported" (rule WATCH-04).
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_NEVER_REPORTED
    assert coord._connection_only(device.id)


# 2. A connection-only ESPHome proxy that drops and reconnects. The
# outage start saved at the drop clears at the reconnect, so the next
# drop, days later, is dated from itself and waits its debounce
# (rules UNAV-03, UNAV-04).
async def test_r16_2_connection_only_outage_start_clears_on_reconnect(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    runtime = _Runtime(False)
    source = _source(hass, runtime)
    device, eids = _esp(hass, source, "r16b", (
        ("update", True, er.EntityCategory.CONFIG),
        ("button", True, er.EntityCategory.CONFIG),
    ))
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    assert coord._connection_only(device.id)
    first_drop = dt_util.utcnow().timestamp()
    runtime.available = False
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    runtime.available = True
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None, "reconnect is the device speaking"
    await walk(hass, freezer, 2 * 24 * HOUR, step=1800)
    second_drop = dt_util.utcnow().timestamp()
    runtime.available = False
    await walk(hass, freezer, 60)
    # One minute into the second drop: inside the 180 s debounce.
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "published inside the debounce", record[DEV_DOWN_SINCE], record[DEV_FROZEN_SINCE]
    )
    await walk(hass, freezer, 10 * 60)
    since = record[DEV_FROZEN_SINCE]
    assert since is not None and since >= second_drop - 120, (
        "second drop dated from the first", since, first_drop, second_drop
    )


# 3. A connected Bluetooth proxy reads as reporting, and its page says it
# is judged by its connection, not that it is still learning a rhythm
# (rule WATCH-04).
async def test_r17_3_connection_only_page_last_report(hass: HomeAssistant, freezer):

    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device, eids = _esp(hass, source, "r17c", (
        ("update", True, er.EntityCategory.CONFIG),
        ("button", True, er.EntityCategory.CONFIG),
    ))
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 50 * HOUR, step=1800)
    page = coord.dashboard_device(device.id)
    assert page["status"]["category"] == "reporting"
    # Judged by its connection: the page says so (rule WATCH-04).
    assert page["status"]["connection"] == "connected"


# 2. A Bluetooth proxy carried over with a learned rhythm. Its page says
# it is judged by its connection and carries no window, so no window
# bar is drawn (rule WATCH-04).
async def test_r18_2_connection_only_page_carries_window(hass: HomeAssistant, freezer):

    freezer.move_to(PIN)
    source = _source(hass, _Runtime(False))
    device = __import__("homeassistant.helpers.device_registry", fromlist=["x"]).async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", "r18b")}, name="Proxy r18b")
    reg = er.async_get(hass)
    upd = reg.async_get_or_create("update", "esphome", "r18b_u", device_id=device.id, config_entry=source,
                                  entity_category=EntityCategory.CONFIG).entity_id
    hass.states.async_set(upd, "off")
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    page = coord.dashboard_device(device.id)
    assert page["status"]["connection"] == "connected"
    assert page["status"]["window"] is None, ("window shown on a page judged by connection", page["status"]["window"])


# 3. A connection-only proxy whose connection cannot be read holds a
# standing unavailable verdict, and its page does not say "connected"
# (rule WATCH-04).
async def test_r18_3_connection_only_unreadable_says_connected(hass: HomeAssistant, freezer):

    freezer.move_to(PIN)
    runtime = _Runtime(False, available=False)
    source = _source(hass, runtime)
    from homeassistant.helpers import device_registry as dr
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", "r18c")}, name="Proxy r18c")
    reg = er.async_get(hass)
    upd = reg.async_get_or_create("update", "esphome", "r18c_u", device_id=device.id, config_entry=source,
                                  entity_category=EntityCategory.CONFIG).entity_id
    hass.states.async_set(upd, "off")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    runtime.available = None  # unreadable from here
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    page = coord.dashboard_device(device.id)
    assert page["status"]["connection"] != "connected", page["status"]


# 4. A connection-only proxy carried over with a frozen verdict, its
# connection unreadable: the verdict never ends as a recovery with no
# report (rule LIST-08).
async def test_r18_4_connection_only_frozen_cleared_without_report(hass: HomeAssistant, freezer):

    freezer.move_to(PIN)
    runtime = _Runtime(False)
    runtime.available = None
    source = _source(hass, runtime)
    from homeassistant.helpers import device_registry as dr
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", "r18d")}, name="Proxy r18d")
    reg = er.async_get(hass)
    upd = reg.async_get_or_create("update", "esphome", "r18d_u", device_id=device.id, config_entry=source,
                                  entity_category=EntityCategory.CONFIG).entity_id
    hass.states.async_set(upd, "off")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    from homeassistant.util import dt as dt_util
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 3 * 24 * HOUR
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - 2 * 24 * HOUR
    back = record_events(hass, EVENT_RECOVERED)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN or not _mine(back, device.id), (
        "frozen verdict ended as a recovery with no report", _mine(back, device.id))


# 3b. As 3, a deep-sleep proxy asleep (connection down): its page does
# not say "connected".
async def test_r18_3b_connection_only_asleep_says_connected(hass: HomeAssistant, freezer):
    from homeassistant.helpers import device_registry as dr

    freezer.move_to(PIN)
    source = _source(hass, _Runtime(True, available=False))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", "r18e")}, name="Sleeper r18e")
    reg = er.async_get(hass)
    upd = reg.async_get_or_create("update", "esphome", "r18e_u", device_id=device.id, config_entry=source,
                                  entity_category=EntityCategory.CONFIG).entity_id
    hass.states.async_set(upd, "off")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    page = coord.dashboard_device(device.id)
    assert page["status"]["connection"] != "connected", page["status"]
