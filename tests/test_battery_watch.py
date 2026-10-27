# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_watch.py, Version: 0.27.10 (2026-10-27)

"""Two warning levels for a falling battery, and a time left that runs to
the low threshold (rules BAT-14, BAT-13).

A warning on a cell falling at a steady pace comes true about half the
time, and one on a cell speeding up about 85 percent. So only an
accelerating cell gets the full warning: the Problem List, the phone,
the brief and the Battery: Falling sensor. A steady one inside Days
Till Low Warning is listed as a battery to watch, with no push.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BATTERY_DAYS,
    CONF_LOW_THRESHOLD,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

from .helpers import register_device, registry_settled, setup_coordinator

# A straight half point a day for six weeks, ending at 40.
STEADY = [round(61.0 - 0.5 * day, 1) for day in range(43)]
# A real S63 cell carried down to 21.5 percent: steady, then speeding up.
S63 = [73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
       74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
       68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
       58.0, 57.5, 57.5]
SPEEDING = [round(level - 36.0, 1) for level in S63]


async def _house(hass: HomeAssistant, series: list[float]):
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 15, CONF_BATTERY_DAYS: 365})
    device, _ = register_device(hass, "watch1", "Back Door")
    await registry_settled(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = series[-1]
    return coord, device


async def test_a_steady_battery_is_watched_not_warned(hass: HomeAssistant):
    coord, device = await _house(hass, STEADY)
    assert coord.battery_falling_list == []
    watched = coord.battery_watch_rows()
    assert [row["device_id"] for row in watched] == [device.id]
    assert coord.battery_until_words(watched[0]).startswith("reaches 15% in ")
    assert watched[0]["target"] == 15.0


async def test_a_battery_speeding_up_gets_the_full_warning(hass: HomeAssistant):
    coord, device = await _house(hass, SPEEDING)
    falling = coord.battery_falling_list
    assert [row["device_id"] for row in falling] == [device.id]
    assert falling[0]["until"].startswith("reaches 15% in ")
    assert coord.battery_watch_rows() == []


async def test_the_time_left_runs_to_the_threshold(hass: HomeAssistant):
    """At 40 percent losing half a point a day, 0 is about 80 days away
    and 15 percent about 50: the range is to 15."""
    coord, device = await _house(hass, STEADY)
    row = coord.battery_watch_rows()[0]
    assert 35 <= row["days"] <= 65, row["days"]


def test_a_battery_under_the_threshold_runs_to_empty():
    from custom_components.device_sentinel.report_battery import BatteryReportMixin

    class Probe(BatteryReportMixin):
        low_threshold = 15

    probe = Probe()
    assert probe.battery_target(16.0) == 15.0
    assert probe.battery_target(15.0) == 0.0
    assert probe.battery_until_words({"days": 10, "days_far": 20, "target": 0.0}).startswith("empty in ")
