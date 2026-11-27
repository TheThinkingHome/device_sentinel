# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_day_highest.py, Version: 0.30.8 (2026-11-26)

"""Battery trends read each day's highest level (rule BAT-05), and each
day keeps the device's own temperatures (rule BAT-16).

A cold night or a reading taken while the radio sends pulls a level down
for a while; the day's highest is the cell's own. The level carried in
at midnight counts only once the device is heard at it again. The daily
series kept with midnight levels takes each day's kept high once, at the upgrade.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_EVIDENCE,
    DEV_BATTERY_TEMP_AT_VOLTS_HIGH,
    DEV_BATTERY_TEMP_AT_VOLTS_LOW,
    DEV_BATTERY_TEMP_TODAY_HIGH,
    DEV_BATTERY_TEMP_TODAY_LOW,
    DEV_BATTERY_VALUE,
    DEV_DAILY_DATES,
)
from custom_components.device_sentinel.detect_battery import (
    battery_day_high,
    highs_into_daily,
    note_battery_sample,
    note_battery_volts,
)
from custom_components.device_sentinel.normalise import _evidence_row_ok

from tests.helpers import setup_coordinator


def _record():
    return {DEV_BATTERY_VALUE: None, DEV_BATTERY_DAILY: []}


def test_the_day_high_is_the_highest_level_held():
    record = _record()
    for level, times in ((80.0, 2), (74.0, 5), (79.0, 3)):
        for _ in range(times):
            note_battery_sample(record, level)
    assert battery_day_high(record) == 80.0


def test_the_level_carried_in_at_midnight_counts_only_when_heard_again():
    record = _record()
    note_battery_sample(record, 80.0)   # carried in at midnight
    note_battery_sample(record, 77.0)   # the device's one report today
    assert battery_day_high(record) == 77.0
    note_battery_sample(record, 80.0)   # heard at it again
    assert battery_day_high(record) == 80.0


def test_a_day_with_only_the_carried_level_says_nothing():
    record = _record()
    note_battery_sample(record, 80.0)
    assert battery_day_high(record) is None
    assert battery_day_high({}) is None


async def test_the_series_takes_the_days_high_not_the_midnight_level(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record()
    for high, midnight in ((90.0, 84.0), (88.0, 81.0), (86.0, 79.5)):
        for _ in range(3):
            note_battery_sample(record, high)
        note_battery_sample(record, midnight)
        record[DEV_BATTERY_VALUE] = midnight
        coord._roll_battery(record, "dev-h")
    assert record[DEV_BATTERY_DAILY] == [90.0, 88.0, 86.0]


def _dated(series, last: date):
    days = [(last - timedelta(days=len(series) - 1 - i)).isoformat() for i in range(len(series))]
    return days


def test_the_upgrade_takes_each_kept_high_once():
    last = date(2026, 11, 25)
    record = {DEV_BATTERY_DAILY: [84.0, 81.0, 79.0]}
    days = _dated(record[DEV_BATTERY_DAILY], last)
    record[DEV_BATTERY_DAY_RANGES] = [
        [days[0], 83.0, 90.0, None, None],
        [days[1], 80.0, 88.0, None, None],
        [days[2], 78.0, 86.0, None, None],
    ]
    assert highs_into_daily(record, last) is True
    assert record[DEV_BATTERY_DAILY] == [90.0, 88.0, 86.0]
    assert highs_into_daily(record, last) is False


def test_a_high_that_is_only_the_carried_level_is_not_taken():
    last = date(2026, 11, 25)
    record = {DEV_BATTERY_DAILY: [84.0, 81.0]}
    days = _dated(record[DEV_BATTERY_DAILY], last)
    # Day two's high equals day one's midnight level: it may be only the
    # level carried in, so the midnight level stays.
    record[DEV_BATTERY_DAY_RANGES] = [[days[1], 81.0, 84.0, None, None]]
    assert highs_into_daily(record, last) is False
    assert record[DEV_BATTERY_DAILY] == [84.0, 81.0]


def test_the_upgrade_keeps_a_half_step_that_rounds_to_the_high():
    """The day's levels are kept as whole numbers, so a level held at a
    half step reads below its own high; the half step stays, as the
    nightly roll keeps it. Otherwise a sensor that reports in half steps
    loses half a point on many of its days."""
    last = date(2026, 11, 25)
    record = {DEV_BATTERY_DAILY: [88.5, 89.5, 45.5]}
    days = _dated(record[DEV_BATTERY_DAILY], last)
    record[DEV_BATTERY_DAY_RANGES] = [
        [days[0], 88.0, 88.0, None, None],
        [days[1], 89.0, 90.0, None, None],
        [days[2], 45.0, 48.0, None, None],
    ]
    assert highs_into_daily(record, last) is True
    assert record[DEV_BATTERY_DAILY] == [88.5, 89.5, 48.0]


def test_the_level_carried_in_is_the_midnight_one_not_the_raised_high():
    """A battery reporting in steps of ten held 30 at each midnight and
    was heard at 50 on two days running. The second day's 50 is not the
    level carried in, which was 30: both days take 50. Found on the
    reference house, where every other such day kept its midnight level."""
    last = date(2026, 11, 25)
    record = {DEV_BATTERY_DAILY: [30.0, 30.0, 30.0]}
    days = _dated(record[DEV_BATTERY_DAILY], last)
    record[DEV_BATTERY_DAY_RANGES] = [
        [days[0], 30.0, 50.0, None, None],
        [days[1], 30.0, 50.0, None, None],
        [days[2], 30.0, 30.0, None, None],
    ]
    assert highs_into_daily(record, last) is True
    assert record[DEV_BATTERY_DAILY] == [50.0, 50.0, 30.0]


def test_the_upgrade_leaves_odd_records_alone():
    last = date(2026, 11, 25)
    for record in ({}, {DEV_BATTERY_DAILY: "x"}, {DEV_BATTERY_DAILY: []},
                   {DEV_BATTERY_DAILY: [80.0], DEV_BATTERY_DAY_RANGES: "x"},
                   {DEV_BATTERY_DAILY: [True], DEV_BATTERY_DAY_RANGES: [[last.isoformat(), 70.0, 75.0, None, None]]}):
        assert highs_into_daily(record, last) is False
    record = {DEV_BATTERY_DAILY: [80.0], DEV_DAILY_DATES: {"battery": "x"},
              DEV_BATTERY_DAY_RANGES: [[last.isoformat(), 70.0, 82.0, None, None]]}
    assert highs_into_daily(record, last) in (True, False)


def test_each_voltage_keeps_the_temperature_with_it():
    record = {}
    note_battery_volts(record, 2.98, 18.0)
    note_battery_volts(record, 2.91, 4.5)    # colder and lower
    note_battery_volts(record, 3.01, 21.0)   # warmer and higher
    note_battery_volts(record, 2.95, -3.0)   # neither extreme
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_LOW] == 4.5
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] == 21.0
    assert (record[DEV_BATTERY_TEMP_TODAY_LOW], record[DEV_BATTERY_TEMP_TODAY_HIGH]) == (-3.0, 21.0)


def test_no_temperature_or_a_wild_one_is_kept_as_none():
    record = {}
    note_battery_volts(record, 2.98, None)
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_LOW] is None and DEV_BATTERY_TEMP_TODAY_LOW not in record
    for wild in (float("nan"), float("inf"), 400.0, True, "20"):
        note_battery_volts(record, 2.90, wild)
        assert record[DEV_BATTERY_TEMP_AT_VOLTS_LOW] is None
        assert DEV_BATTERY_TEMP_TODAY_LOW not in record


def test_the_evidence_row_takes_eight_columns_and_still_reads_four():
    assert _evidence_row_ok(["2026-11-26", 2.95, 21.5, 400])
    assert _evidence_row_ok(["2026-11-26", 2.95, 21.5, 400, -3.0, 21.0, 4.5, 21.0])
    assert _evidence_row_ok(["2026-11-26", 2.95, 21.5, 400, None, None, None, None])
    assert not _evidence_row_ok(["2026-11-26", 2.95, 21.5, 400, 999.0, None, None, None])
    assert not _evidence_row_ok(["2026-11-26", 2.95, 21.5, 400, None])


async def test_the_days_temperatures_go_into_its_row_and_start_again(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = {DEV_BATTERY_TEMP_TODAY_LOW: -3.0, DEV_BATTERY_TEMP_TODAY_HIGH: 21.0,
              DEV_BATTERY_TEMP_AT_VOLTS_LOW: 4.5, DEV_BATTERY_TEMP_AT_VOLTS_HIGH: 21.0,
              "last_activity": time.time(), "event_count": 10}
    coord._battery_entity["dev-t"] = "sensor.t_battery"
    coord.watched_records = lambda: [("dev-t", record)]
    coord.battery_evidence_fold(date.today())
    assert record[DEV_BATTERY_EVIDENCE][-1][4:] == [-3.0, 21.0, 4.5, 21.0]
    for field in (DEV_BATTERY_TEMP_TODAY_LOW, DEV_BATTERY_TEMP_TODAY_HIGH,
                  DEV_BATTERY_TEMP_AT_VOLTS_LOW, DEV_BATTERY_TEMP_AT_VOLTS_HIGH):
        assert record[field] is None
    coord._battery_entity.pop("dev-t", None)
