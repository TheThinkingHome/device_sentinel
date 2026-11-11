# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_day_level_cap.py, Version: 0.28.12 (2026-11-11)

"""A battery that passes through every level in a day keeps its true
low and high, and a cycling rechargeable is not taken for a new battery
(rule BAT-06).

Each test asserts the correct behaviour, so a failing test is a finding.

note_battery_sample keeps at most BATTERY_DAY_LEVELS_KEPT (24) distinct
levels a day and, when full, drops the level heard least often. A level
just heard has count 1, so once the 24 kept levels have each been heard
twice, every new level is dropped the moment it arrives. A battery that
moves through more than 24 levels in a day keeps only the first 24 it
reached: its high and low are cut short.

Devices that do this every day and are watched by default: robot
mowers, EV state of charge, home battery storage, power stations. Their
range should refuse every daily cycle (their high reaches the next
day's level), but with the cut the old high reads far too low and the
next day's low far too high, so a charge cycle is confirmed as a new
battery: a Confirm card, the history restarted, the Log-Normal
Percentile restarted (FRZ-05) and a battery life row written.

Samples are fed in the real event order: _record_activity samples the
held level, then _evaluate_battery samples a new one, and the device
speaks a few more times at each level.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.detect_battery import (
    battery_day_range,
    note_battery_sample,
)

from tests.helpers import setup_coordinator


def _record(start: float):
    from custom_components.device_sentinel.records import _new_device_record

    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_BATTERY_VALUE] = start
    note_battery_sample(record, start)
    return record


def _walk(record, start: int, end: int, speaks: int = 3) -> None:
    step = 1 if end >= start else -1
    for level in range(start, end + step, step):
        level = float(level)
        note_battery_sample(record, record.get(DEV_BATTERY_VALUE))
        if record.get(DEV_BATTERY_VALUE) != level:
            record[DEV_BATTERY_VALUE] = level
            note_battery_sample(record, level)
        for _ in range(speaks):
            note_battery_sample(record, level)


async def test_a_day_through_80_levels_keeps_its_real_range(hass: HomeAssistant):
    record = _record(30.0)
    _walk(record, 30, 20)
    _walk(record, 20, 100)
    _walk(record, 100, 25)
    assert battery_day_range(record) == (20.0, 100.0)


async def test_a_robot_mower_charge_cycle_is_not_a_new_battery(hass: HomeAssistant):
    """Mows 30 to 20, charges to 100, mows to 25, every day; two nights
    running it is charging at midnight (25, then 90, then 80)."""
    coord = await setup_coordinator(hass)
    record = _record(30.0)
    for _ in range(3):
        _walk(record, int(record[DEV_BATTERY_VALUE]), 20)
        _walk(record, 20, 100)
        _walk(record, 100, 25)
        coord._roll_battery(record, "dev-mower")
    _walk(record, 25, 20)
    _walk(record, 20, 90)
    coord._roll_battery(record, "dev-mower")
    # Next day: tops up to 100, mows to 20, is charging again at midnight (80).
    _walk(record, 90, 100)
    _walk(record, 100, 20)
    _walk(record, 20, 80)
    coord._roll_battery(record, "dev-mower")
    assert record[DEV_BATTERY_REPLACED_AT] is None
