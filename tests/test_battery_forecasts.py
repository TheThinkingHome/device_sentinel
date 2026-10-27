# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_forecasts.py, Version: 0.27.10 (2026-10-27)

"""The forecast log: each battery forecast kept at the midnight fold, and
scored when the battery reaches its threshold (rule BAT-15).

If Device Sentinel says a battery will last until some range of dates,
and it lasts three months past the far end, a person can look back and
see what was said.
"""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.battery_forecasts import score_row
from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_BATTERY_FORECAST_TALLY,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_FORECASTS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.normalise import check_records

from .helpers import register_device, registry_settled, setup_coordinator

# A real S63 cell carried down to 21.5 percent: steady, then speeding up.
S63 = [73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
       74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
       68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
       58.0, 57.5, 57.5]
S63_LOW = [round(level - 36.0, 1) for level in S63]


def _yesterday() -> date:
    """Yesterday in the house's time zone. Read inside each test, after
    the harness has set that zone: read when the file loads, it was a
    UTC date, a day apart from the history's after 00:00 UTC."""
    return dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()


def _row(made: date, near: float, far: float | None, target: float = 15.0) -> list:
    return [made.isoformat(), 25.0, True, target, near, far, None, None]


def test_an_outcome_is_inside_earlier_or_later():
    made = date(2026, 10, 22)
    row = _row(made, 21, 35)
    assert score_row(row, date(2026, 11, 19), date(2026, 11, 20), None) == "inside"
    assert score_row(row, date(2026, 11, 1), date(2026, 11, 2), None) == "earlier"
    assert score_row(row, date(2026, 12, 20), date(2026, 12, 21), None) == "later"
    # Still above with the far end passed is later at once.
    assert score_row(row, None, date(2026, 11, 30), None) == "later"
    # Still above and inside the range: open.
    assert score_row(row, None, date(2026, 11, 10), None) is None
    # A battery replaced first says nothing about the forecast.
    assert score_row(row, None, date(2026, 11, 10), date(2026, 11, 5)) == "replaced"
    # A far end of "over a year" never closes a row as later by itself.
    assert score_row(_row(made, 21, None), None, date(2027, 6, 1), None) is None


async def _house(hass: HomeAssistant, series: list[float]):
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 15})
    device, _ = register_device(hass, "fc1", "Back Door")
    await registry_settled(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = series[-1]
    return coord, record


async def test_the_fold_keeps_one_forecast_a_day(hass: HomeAssistant):
    coord, record = await _house(hass, S63_LOW)
    yesterday = _yesterday()
    coord.battery_forecasts_fold(yesterday)
    coord.battery_forecasts_fold(yesterday)
    rows = record[DEV_BATTERY_FORECASTS]
    assert len(rows) == 1
    day, level, accelerating, target, near, far, outcome, arrived = rows[0]
    assert day == yesterday.isoformat() and level == 21.5 and accelerating is True
    assert target == 15.0 and 0 < near <= (far or near) and outcome is None and arrived is None
    assert check_records({"fc1": record}) == []
    # The device page lists it.
    page = coord._page_battery(record)
    assert page["forecasts"][0]["left"] and page["forecasts"][0]["outcome"] is None


async def test_a_battery_above_the_ceiling_is_not_forecast(hass: HomeAssistant):
    high = [round(level + 10.0, 1) for level in S63]
    coord, record = await _house(hass, high)
    coord.battery_forecasts_fold(_yesterday())
    assert record[DEV_BATTERY_FORECASTS] == []


async def test_reaching_the_threshold_scores_each_open_row(hass: HomeAssistant):
    # Twenty days at 20 percent, then four at 14: the battery reached
    # its 15 percent four days before yesterday.
    series = [20.0] * 26 + [14.0] * 4
    coord, record = await _house(hass, series)
    yesterday = _yesterday()
    reached = yesterday - timedelta(days=3)
    record[DEV_BATTERY_FORECASTS] = [
        _row(yesterday - timedelta(days=12), 5, 20),   # took 9 days: inside
        _row(yesterday - timedelta(days=11), 10, 12),  # took 8: earlier
        _row(yesterday - timedelta(days=30), 5, 20),   # took 27: later
    ]
    coord.battery_forecasts_fold(yesterday)
    rows = record[DEV_BATTERY_FORECASTS]
    assert [row[6] for row in rows[:3]] == ["inside", "earlier", "later"]
    assert all(row[7] == reached.isoformat() for row in rows[:3])
    assert coord.data[DATA_BATTERY_FORECAST_TALLY] == {"inside": 1, "earlier": 1, "later": 1, "replaced": 0}
    # Scored once: a second fold changes nothing.
    coord.battery_forecasts_fold(yesterday)
    assert coord.data[DATA_BATTERY_FORECAST_TALLY]["inside"] == 1
    assert check_records({"fc1": record}) == []


async def test_a_replaced_battery_closes_its_rows_without_a_verdict(hass: HomeAssistant):
    coord, record = await _house(hass, [20.0] * 30)
    yesterday = _yesterday()
    record[DEV_BATTERY_FORECASTS] = [_row(yesterday - timedelta(days=10), 20, 40)]
    record[DEV_BATTERY_REPLACED_AT] = (yesterday - timedelta(days=2)).isoformat() + "T08:00:00+00:00"
    coord.battery_forecasts_fold(yesterday)
    assert record[DEV_BATTERY_FORECASTS][0][6] == "replaced"
    assert record[DEV_BATTERY_FORECASTS][0][7] is None
    assert coord.data[DATA_BATTERY_FORECAST_TALLY]["replaced"] == 1


def test_a_damaged_row_is_found():
    good = _row(date(2026, 10, 22), 21, 35)
    for bad in (
        good[:7],
        ["22 Oct", *good[1:]],
        [*good[:1], 140.0, *good[2:]],
        [*good[:2], "yes", *good[3:]],
        [*good[:6], "maybe", None],
        [*good[:7], "tomorrow"],
    ):
        faults = check_records({"d": {DEV_BATTERY_FORECASTS: [good, bad]}})
        assert any(field == DEV_BATTERY_FORECASTS for _, field, _ in faults), bad
