# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_ceiling.py, Version: 0.27.0 (2026-10-22)

"""A cell is judged falling only at or under three times the low
threshold (ruling #725, James, 22 October 2026).

No battery on either house had yet been watched from new to replaced,
and every method tried missed a far-off date. So a cell above three
times the threshold keeps its weekly history and is judged nothing:
not falling, not accelerating, no time left, nothing on the Problem
List or the Battery: Falling sensor. At or under it, the warning days
setting decides what is reported, as before.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BATTERY_DAYS,
    CONF_LOW_THRESHOLD,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.report_battery import battery_trend

from .helpers import register_device, registry_settled, setup_coordinator

# Down about a point every two days for six weeks, ending at 45.
FALLING = [round(66.0 - 0.5 * day, 1) for day in range(43)]


def test_the_trend_judges_nothing_above_the_ceiling():
    assert battery_trend(FALLING, 45.0, True)["reading"] == "falling"
    assert battery_trend(FALLING, 45.0, True, 45.0)["reading"] == "falling"
    above = battery_trend(FALLING, 45.0, True, 44.9)
    assert above["reading"] == "" and above["pace"] is None and above["fit"] is None
    assert len(above["weeks"]) == 5, "the weeks are still shown"


async def _house(hass: HomeAssistant, threshold: float, days: int = 30):
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: threshold, CONF_BATTERY_DAYS: days})
    device, _ = register_device(hass, "ceil1", "Back Door")
    await registry_settled(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = list(FALLING)
    record[DEV_BATTERY_VALUE] = FALLING[-1]
    return coord, device


async def test_above_three_times_the_threshold_nothing_reports_it(hass: HomeAssistant):
    """At 45 percent with a threshold of 14, the ceiling is 42."""
    coord, device = await _house(hass, 14)
    rows = coord._battery_rows()
    assert rows["falling"] == []
    assert device.id in [row["device_id"] for row in rows["flat"]]
    assert coord.battery_falling_list == []
    page = coord._page_battery(coord.data["devices"][device.id])
    assert page["reading"] == "" and page["left"] is None and page["ceiling"] == 42.0


async def test_at_three_times_the_threshold_it_is_judged(hass: HomeAssistant):
    """The same cell with a threshold of 15: the ceiling is 45, the
    cell is at it, and it is judged falling with a time left."""
    coord, device = await _house(hass, 15)
    rows = coord._battery_rows()
    assert [row["device_id"] for row in rows["falling"]] == [device.id]
    page = coord._page_battery(coord.data["devices"][device.id])
    assert page["reading"] == "falling" and page["left"]


async def test_the_warning_days_still_decide_what_is_reported(hass: HomeAssistant):
    """Judged falling is not reported until its time left is inside the
    warning days: about 60 days left to 15 percent here, so seven days
    says nothing."""
    coord, device = await _house(hass, 15, days=7)
    assert [row["device_id"] for row in coord._battery_rows()["falling"]] == [device.id]
    assert coord.battery_falling_list == []
