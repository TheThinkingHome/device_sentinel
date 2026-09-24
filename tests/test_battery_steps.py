# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_steps.py, Version: 0.23.1 (2026-09-24)

"""A battery that reports in coarse steps is not forecast.

The second fleet's S02 Office Temp/Humid reports its battery in
10-point steps. It sat at 40 for nine days, dropped once to 30, and
the seven-day trend read the single step as a steep fall, listing the
cell as empty in about a month. The owner ruled on 24 September: a
fall of 5 points or more from one day to the next is a coarse drop;
two with no smaller change in the retained history make the cell
coarse, judged by the low threshold alone; the forecast is withheld
from the first; any smaller change returns it to smooth; a cell that
never changed is not coarse; the count is stored, so a second step
after the first has aged out still counts. The tests that are not
guards fail on 0.23.0.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

from .helpers import register_device, setup_coordinator

S02 = [40.0] * 9 + [30.0] * 5
TWO_STEPS = [50.0] * 6 + [40.0] * 6 + [30.0] * 5
SMOOTH_FALL = [52.0, 50.0, 48.5, 47.0, 45.0, 43.5, 42.0, 40.0]
SAG_LAST = [60.0, 59.5, 59.0, 58.0, 57.5, 57.0, 47.0]


async def _cell(hass, series, key="c1", name="Office Temp/Humid"):
    device, _entities = register_device(hass, key, name=name)
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = series[-1]
    return coord, device, record


def _falling_names(coord) -> list[str]:
    return [row["name"] for row in coord.battery_falling_list]


async def test_one_step_withholds_the_forecast(hass: HomeAssistant):
    coord, _device, record = await _cell(hass, S02)
    assert coord.battery_steps(record) == "not_enough"
    assert coord._battery_rows()["falling"] == []


async def test_two_steps_make_it_coarse(hass: HomeAssistant):
    coord, _device, record = await _cell(hass, TWO_STEPS)
    assert coord.battery_steps(record) == "coarse"
    assert coord._battery_rows()["falling"] == []


async def test_a_smooth_fall_is_still_forecast(hass: HomeAssistant):
    """Guard: the forecast Tim's steady cells earned stays."""
    coord, _device, record = await _cell(hass, SMOOTH_FALL)
    assert coord.battery_steps(record) == "smooth"
    assert [row["name"] for row in coord._battery_rows()["falling"]] == [
        "Office Temp/Humid"
    ]


async def test_a_sag_among_small_changes_stays_smooth(hass: HomeAssistant):
    """Guard: a 10-point sag in a smooth history is not a step."""
    coord, _device, record = await _cell(hass, SAG_LAST)
    assert coord.battery_steps(record) == "smooth"


async def test_a_cell_that_never_changed_is_not_coarse(hass: HomeAssistant):
    coord, _device, record = await _cell(hass, [100.0] * 20)
    assert coord.battery_steps(record) == "not_enough"


async def test_the_count_outlives_the_history(hass: HomeAssistant):
    """The second step lands after the first has aged out."""
    coord, _device, record = await _cell(hass, [40.0] * 25 + [30.0] * 5)
    record["battery_coarse_drops"] = 2
    assert coord.battery_steps(record) == "coarse"


async def test_the_fold_counts_and_a_small_change_clears(hass: HomeAssistant):
    coord, _device, record = await _cell(hass, [40.0])
    for level in (40.0, 30.0, 30.0, 20.0):
        record[DEV_BATTERY_VALUE] = level
        coord._roll_battery(record)
    assert record["battery_coarse_drops"] == 2
    record[DEV_BATTERY_VALUE] = 19.0
    coord._roll_battery(record)
    assert record["battery_coarse_drops"] == 0


async def test_the_words_reach_both_pages(hass: HomeAssistant):
    coord, device, _record = await _cell(hass, TWO_STEPS)
    coord._rebuild_registry_view()
    page = coord.dashboard_device(device.id)
    assert page["identity"]["battery_steps"] == "Coarse"
    trends = coord.battery_trends()
    words = [row["steps"] for row in trends["steady"]]
    assert "Coarse" in words
