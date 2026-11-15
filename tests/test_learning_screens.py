# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_learning_screens.py, Version: 0.29.2 (2026-11-15)

"""Battery Trends and Signal Trends on a new install (rules BAT-19,
SIG-18).

Signal Trends needs 21 days of a device's readings and a battery
forecast four weeks heard. Until then the tabs say when their trends
start: Signal Trends lists each device still learning with the day its
trend starts, and Battery Trends says the day the first forecast can
come, how far along the house is, and how many batteries are at or
under the threshold now.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_VALUE,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
)

from tests.helpers import register_device, setup_coordinator


async def _house(hass, *uids):
    devices = [register_device(hass, uid)[0] for uid in uids]
    coord = await setup_coordinator(hass)
    for device in devices:
        assert device.id in coord.data[DATA_DEVICES]
    return coord, devices


def _signal(coord, device, days, value=112.0, scale="lqi"):
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P50] = [value] * days
    record[DEV_SIGNAL_VALUE] = value
    record[DEV_SIGNAL_SCALE] = scale


def _battery(coord, device, days, level, low=False):
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_DAILY] = [level] * days
    record[DEV_BATTERY_LOW] = low


async def test_signal_devices_still_learning_are_listed_with_their_start(hass: HomeAssistant):
    coord, (door, plug, new, quiet) = await _house(hass, "door", "plug", "new", "quiet")
    _signal(coord, door, 7)
    _signal(coord, plug, 5, value=-58.0, scale="rssi")
    _signal(coord, new, 0)
    page = coord.signal_trends()
    today = dt_util.now().date()
    assert page["devices"] == [] and page["need"] == 21
    rows = {row["device_id"]: row for row in page["learning"]}
    assert set(rows) == {door.id, plug.id, new.id}
    assert rows[door.id]["days"] == 7 and rows[door.id]["from"] == (today + timedelta(days=14)).isoformat()
    assert rows[plug.id]["scale"] == "rssi" and rows[plug.id]["now"] == -58.0
    assert rows[new.id]["days"] == 0 and rows[new.id]["from"] == (today + timedelta(days=21)).isoformat()
    # Most days first.
    assert [row["device_id"] for row in page["learning"]][0] == door.id
    assert quiet.id not in rows


async def test_a_device_with_its_days_leaves_still_learning(hass: HomeAssistant):
    coord, (old, door) = await _house(hass, "old", "door")
    _signal(coord, old, 21)
    _signal(coord, door, 20)
    page = coord.signal_trends()
    assert [row["device_id"] for row in page["devices"]] == [old.id]
    assert [row["device_id"] for row in page["learning"]] == [door.id]


async def test_battery_learning_says_when_forecasts_start(hass: HomeAssistant):
    """The count is of batteries marked low, as the Problem List and the
    headline count them."""
    coord, (door, motion, edge) = await _house(hass, "door", "motion", "edge")
    _battery(coord, door, 7, 12.0, low=True)
    _battery(coord, motion, 5, 80.0)
    # At the threshold but not yet marked low: the Problem List doesn't
    # list it, so the box doesn't count it.
    _battery(coord, edge, 6, 14.0)
    learning = coord.battery_trends()["learning"]
    today = dt_util.now().date()
    assert learning == {
        "day": 7, "need": 28, "start": (today + timedelta(days=21)).isoformat(), "low_now": 1,
    }


async def test_battery_learning_ends_with_the_first_four_weeks(hass: HomeAssistant):
    coord, (door, motion) = await _house(hass, "door", "motion")
    _battery(coord, door, 28, 60.0)
    _battery(coord, motion, 8, 80.0)
    page = coord.battery_trends()
    assert page["learning"] is None
    learning = {row["lowest_id"]: row["learning"] for row in page["models"]}
    assert False in learning.values()
    cells = {row["device_id"]: row for row in page["cell_rows"]}
    assert cells[door.id]["learning"] is False and cells[motion.id]["learning"] is True


async def test_no_battery_no_box(hass: HomeAssistant):
    coord, _devices = await _house(hass, "plug")
    assert coord.battery_trends()["learning"] is None
