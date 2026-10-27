# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_empty_forecasts.py, Version: 0.27.10 (2026-10-27)

"""Forecasts to empty after a cell's first low (rules BAT-13, BAT-15).

A battery that crosses the threshold the first time may recover over
it, but from then on the forecast runs to empty, and those forecasts
are kept and scored apart. Few devices are seen reading 0 percent, so
one that went silent before its battery was replaced ran out on the
day it was last heard.
"""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_BATTERY_EMPTY_TALLY,
    DATA_BATTERY_FORECAST_TALLY,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_FIRST_LOW,
    DEV_BATTERY_FORECASTS,
    DEV_BATTERY_LOW,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.daily_dates import FAMILY_BATTERY_PREVIOUS, set_dates
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.report_battery import battery_latched

from .helpers import register_device, registry_settled, setup_coordinator
from .test_falling_surfaces import _battery_device

# A real S63 cell carried down: steady, then speeding up.
S63 = [73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
       74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
       68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
       58.0, 57.5, 57.5]


def _yesterday() -> date:
    return dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()


def _row(made: date, near: float, far: float | None, target: float) -> list:
    return [made.isoformat(), 12.0, True, target, near, far, None, None]


async def test_the_first_low_holds_the_target_at_empty(hass: HomeAssistant):
    """Low once, the target is 0 until a new battery goes in, even back
    above the threshold; a second low keeps the first time."""
    device, entity_id = _battery_device(hass, "Door 2nd Bedroom", 25.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    coord._grace_until = 0.0
    record = coord.data["devices"][device.id]
    assert coord.battery_target(25.0, record) == 18.0

    hass.states.async_set(entity_id, "16", {"device_class": "battery"})
    await hass.async_block_till_done()
    first = record[DEV_BATTERY_FIRST_LOW]
    assert record[DEV_BATTERY_LOW] is True and first

    hass.states.async_set(entity_id, "22", {"device_class": "battery"})
    await hass.async_block_till_done()
    assert record[DEV_BATTERY_LOW] is False
    assert battery_latched(record) and coord.battery_target(22.0, record) == 0.0
    assert coord.battery_until_words({"days": 10, "days_far": 20, "target": 0.0}).startswith("empty in ")

    hass.states.async_set(entity_id, "15", {"device_class": "battery"})
    await hass.async_block_till_done()
    assert record[DEV_BATTERY_FIRST_LOW] == first

    # A new battery, noticed after the low, lifts the latch.
    record[DEV_BATTERY_LOW] = False
    record[DEV_BATTERY_REPLACED_AT] = (dt_util.utcnow() + timedelta(seconds=1)).isoformat()
    assert not battery_latched(record) and coord.battery_target(22.0, record) == 18.0
    assert check_records({device.id: record}) == []


async def _cell(hass: HomeAssistant, series: list[float], key: str = "e1"):
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 15})
    device, _ = register_device(hass, key, "Back Door")
    await registry_settled(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = series[-1]
    return coord, record


async def test_a_latched_cell_above_the_threshold_is_forecast_to_empty(hass: HomeAssistant):
    series = [round(level - 40.0, 1) for level in S63]  # ends at 17.5
    coord, record = await _cell(hass, series)
    record[DEV_BATTERY_FIRST_LOW] = (dt_util.utcnow() - timedelta(days=5)).isoformat()
    coord.battery_forecasts_fold(_yesterday())
    rows = record[DEV_BATTERY_FORECASTS]
    assert len(rows) == 1 and rows[0][3] == 0.0 and rows[0][1] == 17.5
    page = coord._page_battery(record)
    assert page["projection"]["target"] == 0.0
    assert check_records({"e1": record}) == []


async def test_a_reading_of_nought_closes_a_forecast_to_empty(hass: HomeAssistant):
    coord, record = await _cell(hass, [5.0] * 26 + [0.0] * 4)
    yesterday = _yesterday()
    record[DEV_BATTERY_FORECASTS] = [_row(yesterday - timedelta(days=12), 5, 20, 0.0)]
    coord.battery_forecasts_fold(yesterday)
    row = record[DEV_BATTERY_FORECASTS][0]
    assert row[6] == "inside" and row[7] == (yesterday - timedelta(days=3)).isoformat()
    assert coord.data[DATA_BATTERY_EMPTY_TALLY]["inside"] == 1
    # Kept apart from the forecasts to the threshold.
    assert coord.data[DATA_BATTERY_FORECAST_TALLY]["inside"] == 0


async def _replaced(hass: HomeAssistant, silent_days: int):
    """An old cell last heard silent_days before a new one went in, the
    new one heard for the last three days."""
    coord, record = await _cell(hass, [100.0, 100.0, 100.0])
    yesterday = _yesterday()
    rise = yesterday - timedelta(days=2)
    last_heard = rise - timedelta(days=silent_days)
    old = [round(30.0 - 0.5 * day, 1) for day in range(30)]
    record[DEV_BATTERY_DAILY_PREVIOUS] = old
    set_dates(record, FAMILY_BATTERY_PREVIOUS, [last_heard - timedelta(days=29 - i) for i in range(30)])
    record[DEV_BATTERY_REPLACED_AT] = f"{rise.isoformat()}T09:00:00+00:00"
    made = last_heard - timedelta(days=10)
    record[DEV_BATTERY_FORECASTS] = [
        _row(made, 7, 14, 0.0),
        _row(made, 30, 60, 15.0),
    ]
    coord.battery_forecasts_fold(yesterday)
    return coord, record, last_heard


async def test_a_device_silent_before_its_replacement_ran_out_when_last_heard(hass: HomeAssistant):
    coord, record, last_heard = await _replaced(hass, silent_days=4)
    empty, threshold = record[DEV_BATTERY_FORECASTS]
    assert empty[6] == "inside" and empty[7] == last_heard.isoformat()
    # A forecast to the threshold is not judged by the silence: the old
    # cell read 15.5 last, so it was replaced first.
    assert threshold[6] == "replaced" and threshold[7] is None
    assert coord.data[DATA_BATTERY_EMPTY_TALLY]["inside"] == 1
    assert coord.data[DATA_BATTERY_FORECAST_TALLY]["replaced"] == 1


async def test_a_battery_replaced_while_the_device_still_spoke_is_replaced(hass: HomeAssistant):
    coord, record, _ = await _replaced(hass, silent_days=1)
    assert record[DEV_BATTERY_FORECASTS][0][6] == "replaced"
    assert coord.data[DATA_BATTERY_EMPTY_TALLY]["replaced"] == 1


async def test_a_cell_low_before_the_upgrade_gains_its_first_low(hass: HomeAssistant):
    coord, record = await _cell(hass, [12.0] * 30)
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_SINCE] = "2026-10-01T06:00:00+00:00"
    record[DEV_BATTERY_FIRST_LOW] = None
    coord.battery_forecasts_fold(_yesterday())
    assert record[DEV_BATTERY_FIRST_LOW] == "2026-10-01T06:00:00+00:00"
    record[DEV_BATTERY_LOW] = False
    assert battery_latched(record)


async def test_a_forecast_after_a_replacement_is_about_the_new_cell(hass: HomeAssistant):
    """The new cell's kept history can be shorter than its life; the
    replacement is still dated no later than it was noticed, so a
    forecast made after it is never scored on the old cell's days."""
    coord, record = await _cell(hass, [100.0, 100.0, 100.0])
    yesterday = _yesterday()
    record[DEV_BATTERY_DAILY_PREVIOUS] = [10.0] * 30
    record[DEV_BATTERY_REPLACED_AT] = f"{(yesterday - timedelta(days=20)).isoformat()}T09:00:00+00:00"
    record[DEV_BATTERY_FORECASTS] = [_row(yesterday - timedelta(days=10), 30, 60, 15.0)]
    coord.battery_forecasts_fold(yesterday)
    assert record[DEV_BATTERY_FORECASTS][0][6] is None
