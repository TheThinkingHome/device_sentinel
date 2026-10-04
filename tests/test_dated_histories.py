# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dated_histories.py, Version: 0.24.4 (2026-10-04)

"""The daily histories keep their calendar (0.24.4, issue #18).

The longest-gap, battery and signal histories hold one entry a day the
device measured something. Until 0.24.4 nothing recorded which day: the
gap and signal histories wrote nothing on a silent day, so every later
entry read one day early, and the battery history wrote the last level
again, inventing flat days and then a cliff.
"""

from __future__ import annotations

import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_STATS_EPOCH,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_TODAY_MAX,
    REPORT_DIR,
    STORAGE_KEY,
)
from custom_components.device_sentinel.daily_dates import (
    DAILY_DATES,
    FAMILY_BATTERY,
    FAMILY_GAP,
    FAMILY_SIGNAL,
    FAMILY_SIGNAL_ALT,
    dates_for,
    set_dates,
)
from custom_components.device_sentinel.report_battery import battery_calendar

from .helpers import register_device, setup_coordinator

H = 3600.0


async def _device(hass):
    device, _entities = register_device(hass, "dt", name="Dated Probe")
    coord = await setup_coordinator(hass)
    return coord, coord.data[DATA_DEVICES][device.id], device.id


_BASE: list = []


async def _fold(hass, freezer, days_ahead):
    """Move to just after a midnight and let Device Sentinel's own
    midnight timer fold the day, once, as it does on a server."""
    day = _midnight(freezer, days_ahead)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    return day


def _midnight(freezer, days_ahead):
    """Just after local midnight, `days_ahead` days after the test began,
    counted from a fixed start so each call is the next real day."""
    if not _BASE or _BASE[0][0] is not freezer:
        _BASE[:] = [(freezer, dt_util.start_of_local_day())]
    day = _BASE[0][1] + timedelta(days=days_ahead, seconds=30)
    freezer.move_to(day)
    return (dt_util.as_local(day) - timedelta(minutes=1)).date()


async def test_the_fold_dates_the_gap_history_and_skips_a_silent_day(hass: HomeAssistant, freezer):
    coord, record, _ = await _device(hass)
    record[DEV_TODAY_MAX] = 2 * H
    first = await _fold(hass, freezer, 1)
    await _fold(hass, freezer, 2)  # a day with no learned gap
    record[DEV_TODAY_MAX] = 3 * H
    third = await _fold(hass, freezer, 3)
    assert record[DEV_DAILY_MAX][-2:] == [2 * H, 3 * H]
    assert dates_for(record, FAMILY_GAP, 2, third) == [first, third], "the silent day was not skipped"


async def test_a_battery_day_the_device_was_not_heard_writes_nothing(hass: HomeAssistant, freezer):
    coord, record, _ = await _device(hass)
    record[DEV_BATTERY_DAILY] = []
    _midnight(freezer, 0)

    def heard_before(days_ahead):
        """The device reports an hour before the coming midnight."""
        freezer.move_to(_BASE[0][1] + timedelta(days=days_ahead) - timedelta(hours=1))
        record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()

    record[DEV_BATTERY_VALUE] = 84
    heard_before(1)
    first = await _fold(hass, freezer, 1)
    for ahead in (2, 3, 4):  # three days nothing was heard
        await _fold(hass, freezer, ahead)
    record[DEV_BATTERY_VALUE] = 81
    heard_before(5)
    fifth = await _fold(hass, freezer, 5)
    assert record[DEV_BATTERY_DAILY] == [84, 81], "an unheard day repeated the old level"
    assert dates_for(record, FAMILY_BATTERY, 2, fifth) == [first, fifth]


def test_the_battery_calendar_lays_a_fall_across_the_silent_days(freezer):
    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    record = {DEV_BATTERY_DAILY: [84, 81], DAILY_DATES: None}
    set_dates(record, FAMILY_BATTERY, [yesterday - timedelta(days=4), yesterday])
    assert battery_calendar(record) == [84, None, None, None, 81]


async def test_signal_rows_are_dated_on_both_scales(hass: HomeAssistant, freezer, monkeypatch):
    coord, record, _ = await _device(hass)
    record[DEV_SIGNAL_ALT] = {DEV_SIGNAL_DAILY_COUNT: [], DEV_SIGNAL_DAILY_RAIL: []}

    def one_row(bucket, fold_now, judged=True):
        bucket.setdefault(DEV_SIGNAL_DAILY_COUNT, []).append(5)
        bucket.setdefault(DEV_SIGNAL_DAILY_RAIL, []).append(0)

    monkeypatch.setattr(coord, "_roll_one_scale", one_row)
    record[DEV_SIGNAL_DAILY_COUNT] = []
    day = _midnight(freezer, 1)
    await coord._on_midnight(None)
    assert dates_for(record, FAMILY_SIGNAL, 1, day) == [day]
    assert dates_for(record, FAMILY_SIGNAL_ALT, 1, day) == [day]
    assert DAILY_DATES not in (record[DEV_SIGNAL_ALT] or {}), "the second scale's strict block gained a field"


async def test_the_catch_up_fold_dates_the_missed_day(hass: HomeAssistant, freezer):
    coord, record, _ = await _device(hass)
    record[DEV_TODAY_MAX] = 2 * H
    saved = dt_util.start_of_local_day() - timedelta(days=2) + timedelta(hours=12)
    coord._loaded_saved_at = saved.timestamp()
    coord._epoch_wiped = False  # an ordinary install, not a first one
    await coord._fold_if_a_midnight_was_missed()
    missed = dt_util.as_local(saved).date()
    assert dates_for(record, FAMILY_GAP, len(record[DEV_DAILY_MAX]), missed)[-1] == missed, (
        "the missed day was dated as yesterday"
    )


async def test_an_epoch_wipe_drops_the_gap_dates_and_keeps_the_others(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "ep", name="Epoch Probe")
    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    blocks: dict = {DAILY_DATES: None}
    set_dates(blocks, FAMILY_GAP, [yesterday - timedelta(days=1), yesterday])
    set_dates(blocks, FAMILY_BATTERY, [yesterday - timedelta(days=3), yesterday])
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            "first_installed": "2026-07-01T00:00:00+00:00",
            "setup_count": 5,
            DATA_STATS_EPOCH: "0.2.0",
            DATA_DEVICES: {
                device.id: {
                    DEV_LAST_ACTIVITY: 1752200000.0,
                    DEV_DAILY_MAX: [100.0, 200.0],
                    DEV_BATTERY_DAILY: [90, 88],
                    "first_observed": "2026-07-01T00:00:00+00:00",
                    DAILY_DATES: blocks[DAILY_DATES],
                }
            },
        },
    }
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_DAILY_MAX] == []
    assert FAMILY_GAP not in (record[DAILY_DATES] or {}), "the wiped gap history kept its dates"
    assert dates_for(record, FAMILY_BATTERY, 2, yesterday) == [yesterday - timedelta(days=3), yesterday]


async def test_the_device_page_lays_the_gap_history_on_the_calendar(hass: HomeAssistant):
    coord, record, device_id = await _device(hass)
    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    record[DEV_DAILY_MAX] = [2 * H, 3 * H]
    set_dates(record, FAMILY_GAP, [yesterday - timedelta(days=2), yesterday])
    page = coord.dashboard_device(device_id)
    assert page["rhythm"]["daily"] == [2 * H, None, 3 * H], "the skipped day did not leave its slot"


async def test_a_rail_broken_by_a_silent_day_is_not_confirmed(hass: HomeAssistant):
    coord, record, _ = await _device(hass)
    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    record[DEV_SIGNAL_DAILY_COUNT] = [0, 0, 0]
    record[DEV_SIGNAL_DAILY_RAIL] = [9, 9, 9]
    set_dates(record, FAMILY_SIGNAL, [yesterday - timedelta(days=2), yesterday - timedelta(days=1), yesterday])
    assert coord.signal_railed(record), "three consecutive rail days did not confirm"
    set_dates(record, FAMILY_SIGNAL, [yesterday - timedelta(days=3), yesterday - timedelta(days=1), yesterday])
    assert not coord.signal_railed(record), "a rail broken by a silent day confirmed"


async def test_the_retired_rhythm_shadow_file_is_removed(hass: HomeAssistant):
    coord, _record, _ = await _device(hass)
    folder = hass.config.path(REPORT_DIR)
    os.makedirs(folder, exist_ok=True)
    stale = os.path.join(folder, "rhythm_shadow.md")
    with open(stale, "w", encoding="utf-8") as handle:
        handle.write("# Device Sentinel v0.23.18 Rhythm Shadow\n")
    await hass.async_add_executor_job(coord._write_reports)
    assert not os.path.exists(stale), "rhythm_shadow.md survived the report write"
