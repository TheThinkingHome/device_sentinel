# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recovery_down_time.py, Version: 0.27.15 (2026-10-30)

"""How long a recovered device was down, when it reports more than once
in the minute its recovery waits (rules UNAV-07, LIST-06).

A recovered device stays on the Problem List for a minute, and its
recovery is told only when that minute ends. A device coming back
seldom reports once: a Zigbee2MQTT door sensor sends several messages
in its first seconds. The down time is still counted from the silence
the first report ended, not from the report a few seconds before it,
and not from when the device was called frozen.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
)

from tests.helpers import record_events, register_device, setup_coordinator


async def _armed_device(hass, freezer, uid):
    """A device that reports hourly, armed and reporting."""
    freezer.move_to("2026-10-12 12:00:00+00:00")
    device, (eid,) = register_device(hass, uid, f"Device {uid}")
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_TODAY_MAX] = None
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()
    return coord, device, eid


async def _minutes_on(hass, freezer, n):
    for _ in range(n):
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def _report(hass, freezer, eid, value, seconds):
    freezer.tick(timedelta(seconds=seconds))
    hass.states.async_set(eid, value)
    await hass.async_block_till_done()


async def test_a_frozen_device_that_reports_twice_counts_from_its_silence(
    hass: HomeAssistant, freezer
):
    """Frozen, then back with three reports in its first seconds: down
    for the whole silence, from its last report before it."""
    coord, device, eid = await _armed_device(hass, freezer, "burst1")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 160)
    assert coord.data["devices"][device.id]["frozen_category"] == "frozen"
    await _report(hass, freezer, eid, "22.0", 30)
    await _report(hass, freezer, eid, "22.1", 5)
    await _report(hass, freezer, eid, "22.2", 5)
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1 and mine[0]["kind"] == "frozen", mine
    assert abs(mine[0]["down_for"] - (160 * 60 + 30)) <= 60, mine[0]


async def test_a_device_straight_to_unavailable_that_reports_twice_counts_from_when_it_went(
    hass: HomeAssistant, freezer
):
    """Straight to unavailable, then back with two reports: down from
    when it went, not from its quiet before (rule UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst2")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 30)
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 20)
    assert coord.data["devices"][device.id]["frozen_category"] == "unavailable"
    await _report(hass, freezer, eid, "22.0", 30)
    await _report(hass, freezer, eid, "22.1", 5)
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1 and mine[0]["kind"] == "unavailable", mine
    assert abs(mine[0]["down_for"] - (20 * 60 + 30)) <= 60, mine[0]


async def test_a_device_back_twice_after_its_minute_is_timed_afresh(
    hass: HomeAssistant, freezer
):
    """A report after the recovery was told belongs to no recovery: the
    next freeze is timed from its own silence."""
    coord, device, eid = await _armed_device(hass, freezer, "burst3")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 160)
    await _report(hass, freezer, eid, "22.0", 30)
    await _minutes_on(hass, freezer, 2)
    await _report(hass, freezer, eid, "22.1", 5)
    await _minutes_on(hass, freezer, 160)
    assert coord.data["devices"][device.id]["frozen_category"] == "frozen"
    await _report(hass, freezer, eid, "22.2", 30)
    await _report(hass, freezer, eid, "22.3", 5)
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 2, mine
    assert abs(mine[1]["down_for"] - (160 * 60 + 30)) <= 60, mine[1]


async def test_a_freeze_cleared_by_a_longer_wait_then_reports_counts_from_its_last_report(
    hass: HomeAssistant, freezer
):
    """A freeze that clears with no report, because its wait grew, and
    then reports twice inside its minute: down from its last report
    before the silence, not from when it was called frozen (rule
    UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst4")
    recoveries = record_events(hass, EVENT_RECOVERED)
    record = coord.data["devices"][device.id]
    last_report = record["last_activity"]
    await _minutes_on(hass, freezer, 240)
    assert record["frozen_category"] == "frozen"
    record[DEV_DAILY_MAX] = [12 * 3600.0] * (FREEZE_ARMING_DAYS + 2)
    await _minutes_on(hass, freezer, 1)
    assert record["frozen_category"] is None
    cleared = dt_util.utcnow().timestamp()
    await _report(hass, freezer, eid, "22.0", 10)
    await _report(hass, freezer, eid, "22.1", 5)
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1, mine
    assert abs(mine[0]["down_for"] - (cleared - last_report)) <= 61, (mine[0], cleared - last_report)


async def test_a_report_kept_for_a_recovery_that_was_never_told_times_nothing_later(
    hass: HomeAssistant, freezer
):
    """A device back from a freeze is muted inside its minute, so its
    recovery is never told. Its next freeze, cleared later with no
    report, is timed from its own silence, not from the first one
    (rule UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst5")
    recoveries = record_events(hass, EVENT_RECOVERED)
    record = coord.data["devices"][device.id]
    await _minutes_on(hass, freezer, 160)
    assert record["frozen_category"] == "frozen"
    await _report(hass, freezer, eid, "22.0", 30)
    # The minute passes without the recovery: as a mute or a deleted
    # row ends it, the park simply goes.
    coord._parked.pop(device.id, None)
    coord.data[DATA_TODO_ITEMS][:] = [
        item for item in coord.data[DATA_TODO_ITEMS] if item.get("device_id") != device.id
    ]
    last_report = record["last_activity"]
    await _minutes_on(hass, freezer, 160)
    assert record["frozen_category"] == "frozen"
    record[DEV_DAILY_MAX] = [12 * 3600.0] * (FREEZE_ARMING_DAYS + 2)
    await _minutes_on(hass, freezer, 1)
    cleared = dt_util.utcnow().timestamp()
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert mine, recoveries
    assert abs(mine[-1]["down_for"] - (cleared - last_report)) <= 61, (mine[-1], cleared - last_report)



async def test_a_freeze_across_a_restart_counts_from_its_last_report(
    hass: HomeAssistant, freezer
):
    """The start is saved with the record when the freeze opens, so a
    restart while the device is frozen does not move it (rule UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst6")
    record = coord.data["devices"][device.id]
    last_report = record["last_activity"]
    await _minutes_on(hass, freezer, 160)
    assert record["frozen_category"] == "frozen"
    assert record["down_from"] == last_report
    entry = coord.entry
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 5)
    await _report(hass, freezer, eid, "22.0", 30)
    await _report(hass, freezer, eid, "22.1", 5)
    back = dt_util.utcnow().timestamp()
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1, mine
    assert abs(mine[0]["down_for"] - (back - last_report)) <= 120, (mine[0], back - last_report)


async def test_an_outage_saves_when_the_device_went(
    hass: HomeAssistant, freezer
):
    """Straight to unavailable: the start saved is when it went, not the
    listing minutes later, and the recovery counts from it (rule
    UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst7")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 30)
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    went = dt_util.utcnow().timestamp()
    await _minutes_on(hass, freezer, 20)
    record = coord.data["devices"][device.id]
    assert record["frozen_category"] == "unavailable"
    assert abs(record["down_from"] - went) <= 60, (record["down_from"], went)
    back = dt_util.utcnow().timestamp()
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 3)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1, mine
    assert abs(mine[0]["down_for"] - (back - went)) <= 60, (mine[0], back - went)


async def test_a_freeze_that_turns_unavailable_keeps_the_freezes_start(
    hass: HomeAssistant, freezer
):
    """Frozen, then unavailable, then back: down from the last report,
    the start the freeze saved (rule UNAV-07)."""
    coord, device, eid = await _armed_device(hass, freezer, "burst8")
    record = coord.data["devices"][device.id]
    last_report = record["last_activity"]
    await _minutes_on(hass, freezer, 160)
    assert record["frozen_category"] == "frozen"
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 10)
    assert record["frozen_category"] == "unavailable"
    assert record["down_from"] == last_report
