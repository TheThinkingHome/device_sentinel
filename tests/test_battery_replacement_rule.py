# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_replacement_rule.py, Version: 0.28.12 (2026-11-11)

"""A new battery, told from a dip, a sag or a swing (rule BAT-06).

The battery level is sampled each moment the device is heard: its own
battery report and every time it speaks, since the level it holds is
still its own. A day's low and high count only levels heard at two
moments or more, so a value held for seconds decides nothing.

A rise of 25 or more, or one that lands at 95 or more and gains 10 or
more, is a candidate. It is confirmed when the whole next day's low is
above the old cell's high plus 2. The old cell's high is the whole day
before the rise when the rise lands at full, and the two days before it
when it lands below full, which a new cell never does.

In each test a day is a list of the levels the device was heard
holding, in order; a level repeated is a level heard at that many
moments. The last level of a day is held at midnight.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_DAY_COUNTS,
    DEV_BATTERY_DAY_LEVELS,
    DEV_BATTERY_RANGE_HIGHS,
    DEV_BATTERY_RANGE_LOWS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.detect_battery import battery_day_range, note_battery_sample

from tests.helpers import setup_coordinator


def _record(start: float):
    from custom_components.device_sentinel.records import _new_device_record

    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_BATTERY_VALUE] = start
    note_battery_sample(record, start)
    return record


def _days(coord, record, days):
    for heard in days:
        for level in heard:
            record[DEV_BATTERY_VALUE] = level
            note_battery_sample(record, level)
        coord._roll_battery(record, "dev-battery")


def _held(level: float, moments: int = 6) -> list[float]:
    return [level] * moments


async def _replaced(hass: HomeAssistant, start: float, days) -> bool:
    coord = await setup_coordinator(hass)
    record = _record(start)
    _days(coord, record, days)
    return record[DEV_BATTERY_REPLACED_AT] is not None


# ------------------------------------------------------------ not a new cell


async def test_a_lock_low_warning_held_over_one_midnight(hass: HomeAssistant):
    """A lock near 40% sends its low warning (level 0) one evening; its
    next report, the next morning, reads 40 again."""
    assert not await _replaced(hass, 40.0, [
        _held(40.0), _held(40.0), _held(40.0, 4) + _held(0.0, 3),
        _held(0.0, 2) + _held(40.0, 5), _held(40.0), _held(40.0),
    ])


async def test_a_lock_low_warning_held_a_whole_day(hass: HomeAssistant):
    assert not await _replaced(hass, 40.0, [
        _held(40.0), _held(40.0, 4) + _held(0.0, 3), _held(0.0),
        _held(0.0, 2) + _held(40.0, 5), _held(40.0), _held(40.0),
    ])


async def test_a_coin_cell_cold_sag_held_over_one_midnight(hass: HomeAssistant):
    assert not await _replaced(hass, 100.0, [
        _held(100.0), _held(100.0, 4) + _held(70.0, 3),
        _held(70.0, 2) + _held(100.0, 5), _held(100.0), _held(100.0),
    ])


async def test_a_coin_cell_that_swings_once_a_day(hass: HomeAssistant):
    """100 each afternoon, 70 each night; a warm night reads 100 at
    midnight."""
    swing = _held(100.0, 4) + _held(70.0, 3)
    assert not await _replaced(hass, 70.0, [
        swing, swing, _held(70.0, 2) + _held(100.0, 5), swing, swing,
    ])


async def test_a_battery_swinging_7_to_12_points(hass: HomeAssistant):
    """A real mmWave sensor's readings over five days, one report each."""
    assert not await _replaced(hass, 98.0, [
        [98.5, 97.0, 93.5, 98.5, 97.5, 98.5, 95.5, 97.5, 98.0, 97.5],
        [98.5, 93.0, 97.0, 98.0, 93.0, 97.5, 95.5, 98.0, 96.0, 98.0],
        [97.5, 92.5, 96.5, 98.0, 92.0, 97.5, 96.0, 97.5, 86.5],
        [96.5, 92.0, 95.5, 97.0, 96.5],
        [94.0, 91.5, 96.0, 92.0, 95.5],
    ])


async def test_a_warm_drift_near_full_is_not_a_candidate(hass: HomeAssistant):
    assert not await _replaced(hass, 92.0, [_held(92.0), _held(92.0), _held(96.0), _held(96.0)])


async def test_a_warm_drift_in_the_middle_is_not_a_candidate(hass: HomeAssistant):
    assert not await _replaced(hass, 72.0, [
        _held(70.0, 3) + _held(75.0, 3), _held(75.0), _held(78.0), _held(80.0),
    ])


# ------------------------------------------------------------- a new cell


async def test_a_plain_change(hass: HomeAssistant):
    assert await _replaced(hass, 31.0, [
        _held(31.0), _held(30.0), _held(30.0, 2) + _held(100.0, 4), _held(100.0), _held(100.0),
    ])


async def test_a_change_at_80(hass: HomeAssistant):
    assert await _replaced(hass, 81.0, [
        _held(81.0), _held(80.0), _held(80.0, 2) + _held(100.0, 4), _held(100.0), _held(100.0),
    ])


async def test_a_cell_that_swung_near_full_then_collapsed(hass: HomeAssistant):
    """An Aqara coin cell reads 98 by day and 93 on cold nights, falls to
    60 and 40 at two midnights, and the person fits a new cell."""
    swing = _held(98.0, 4) + _held(93.0, 3)
    assert await _replaced(hass, 98.0, [
        swing, swing, _held(93.0, 2) + _held(60.0, 4), _held(60.0, 2) + _held(40.0, 4),
        _held(40.0, 2) + _held(100.0, 4), _held(100.0), _held(100.0),
    ])


async def test_a_three_level_cell_changed_after_two_days_at_10(hass: HomeAssistant):
    """A Tuya cell that reports 100, 50 or 10."""
    assert await _replaced(hass, 100.0, [
        _held(100.0, 3) + _held(50.0, 3), _held(50.0, 3) + _held(10.0, 3), _held(10.0),
        _held(10.0, 2) + _held(100.0, 4), _held(100.0), _held(100.0),
    ])


async def test_one_stray_low_on_the_new_cell_does_not_lose_the_change(hass: HomeAssistant):
    """A reconnect reads 0 for a moment the day after the change."""
    assert await _replaced(hass, 31.0, [
        _held(31.0), _held(30.0), _held(30.0, 2) + _held(100.0, 4),
        _held(100.0, 3) + [0.0] + _held(100.0, 3), _held(100.0),
    ])


async def test_one_stray_high_the_day_before_does_not_hide_the_change(hass: HomeAssistant):
    assert await _replaced(hass, 31.0, [
        _held(31.0), _held(30.0, 3) + [100.0] + _held(30.0, 2),
        _held(30.0, 2) + _held(100.0, 4), _held(100.0), _held(100.0),
    ])


async def test_without_days_kept_the_midnight_levels_decide(hass: HomeAssistant):
    """Just after the upgrade no day's range is kept yet."""
    coord = await setup_coordinator(hass)
    record = _record(30.0)
    record[DEV_BATTERY_DAILY] = [31.0, 30.0]
    record[DEV_BATTERY_VALUE] = 100.0
    coord._roll_battery(record, "dev-battery")
    record[DEV_BATTERY_RANGE_LOWS] = []
    record[DEV_BATTERY_RANGE_HIGHS] = []
    coord._roll_battery(record, "dev-battery")
    assert record[DEV_BATTERY_REPLACED_AT] is not None


# ------------------------------------------------- what is left to a person


async def test_a_collapse_changed_the_next_day_looks_like_a_sag(hass: HomeAssistant):
    """98, 40, then a new cell the next day reads exactly as a sag does:
    refused, and the person can give the day."""
    assert not await _replaced(hass, 98.0, [
        _held(98.0), _held(98.0, 3) + _held(40.0, 3), _held(40.0, 2) + _held(100.0, 4),
        _held(100.0), _held(100.0),
    ])


# --------------------------------------------------------------- the day


async def test_a_value_heard_once_decides_nothing(hass: HomeAssistant):
    record = _record(60.0)
    for level in (60.0, 60.0, 0.0, 60.0, 61.0, 61.0):
        record[DEV_BATTERY_VALUE] = level
        note_battery_sample(record, level)
    assert battery_day_range(record) == (60.0, 61.0)


async def test_the_day_starts_with_the_level_held(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(55.0)
    _days(coord, record, [_held(55.0)])
    assert record[DEV_BATTERY_DAY_LEVELS] == [55.0]
    assert record[DEV_BATTERY_DAY_COUNTS] == [1]
    assert record[DEV_BATTERY_RANGE_LOWS] == [55.0]


async def test_each_moment_the_device_speaks_is_a_sample(hass: HomeAssistant, freezer):
    """Through the state machine: a battery report, then the device's
    other entity speaking, each counts the level it holds."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from tests.test_battery import _battery_device

    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 80, percentage=True, binary=False)
    eids["plain"] = er.async_get(hass).async_get_or_create(
        "sensor", "test", "bat80_motion", device_id=device.id, config_entry=source,
    ).entity_id
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    hass.states.async_set(eids["pct"], "71")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    before = dict(zip(record[DEV_BATTERY_DAY_LEVELS], record[DEV_BATTERY_DAY_COUNTS], strict=True))
    assert before.get(71.0, 0) >= 1
    # Within the minute of the battery's own report: the same moment.
    hass.states.async_set(eids["plain"], "a")
    await hass.async_block_till_done()
    same = dict(zip(record[DEV_BATTERY_DAY_LEVELS], record[DEV_BATTERY_DAY_COUNTS], strict=True))
    assert same[71.0] == before[71.0]
    # Each later minute the device speaks is another moment.
    for value in ("b", "c"):
        freezer.tick(61)
        hass.states.async_set(eids["plain"], value)
        await hass.async_block_till_done()
    after = dict(zip(record[DEV_BATTERY_DAY_LEVELS], record[DEV_BATTERY_DAY_COUNTS], strict=True))
    assert after[71.0] == before[71.0] + 2


async def test_a_confirmed_change_keeps_the_old_history(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(31.0)
    _days(coord, record, [
        _held(31.0), _held(30.0), _held(30.0, 2) + _held(100.0, 4), _held(100.0),
    ])
    assert record[DEV_BATTERY_DAILY] == [100.0, 100.0]
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == [31.0, 30.0]
