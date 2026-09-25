# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_report.py, Version: 0.23.6 (2026-09-25)

"""Which cells are going to be low (ruling #194).

A threshold answers which cells are low; the battery rows answer which
are going to be. The shapes below are taken from the reference fleet
on 2026-08-03, including the cell that motivated it: ten days flat at
32 percent, then a ten point drop and an eight and a half point
rebound on consecutive days, then a fall to 21.

The battery report page retired with the www folder in 0.23.5 (#470).
The rows it drew are what Battery Trends, the Battery: Falling sensor,
the Problem List and the brief read, so they are asserted here
directly, and the brief's own line beside them.
"""

from __future__ import annotations

import os

import pytest

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BATTERY_DAYS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
)

from .helpers import register_device, setup_coordinator

# The dying cell, exactly as recorded: flat, then the sag and rebound,
# then the fall.
DYING = [
    32.0, 32.5, 31.5, 32.5, 32.5, 31.5, 31.0, 32.0,
    32.5, 31.5, 21.5, 30.0, 28.0, 23.5, 22.0, 21.0,
]
# A healthy cell drifting down at half a point a day.
HEALTHY = [91.0, 92.0, 92.5, 92.0, 91.5, 92.0, 91.5, 91.0,
           91.0, 91.0, 89.5, 88.5, 87.0, 86.0, 84.0, 82.5]
# A cell that has not moved at all.
STEADY = [100.0] * 16
# 20 percent falling 1.5 a day: a little over thirteen days.
TWO_WEEKS = [40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
             28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0]


def _seed(coord, device_id, series, level, low=False, since=None):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_LOW] = low
    record[DEV_BATTERY_SINCE] = since
    return record


def _brief(hass) -> str:
    with open(
        os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML),
        encoding="utf-8",
    ) as handle:
        return handle.read()


def _names(rows) -> list[str]:
    return [row["name"] for row in rows]


async def test_the_dying_cell_is_first_and_the_healthy_one_is_not(
    hass: HomeAssistant,
):
    """Both cells are falling. One is at 12 percent and its last week
    averaged 6.6 points below the week before, about two weeks left;
    the other is at 82 percent and fell 4.7, about four months. Their
    paces are within two points a week of each other, and time
    remaining still tells them apart.

    Before 0.23.6 the dying cell's pace came from a seven-day slope,
    1.75 a day; it comes from the weekly averages now, since sixteen
    days is too few for a knee.
    """
    coord = await setup_coordinator(hass)
    dying, _ = register_device(hass, "bat1", "Door 2nd Bedroom")
    healthy, _ = register_device(hass, "bat2", "Soil Moisture")
    _seed(coord, dying.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")
    _seed(coord, healthy.id, HEALTHY, 82.0)

    falling = coord._battery_rows()["falling"]
    assert _names(falling) == ["Door 2nd Bedroom", "Soil Moisture"]
    assert round(falling[0]["slope"], 3) == -0.939
    assert coord.battery_time_left(falling[0]["days"]) == "about 2 weeks"
    assert falling[0]["reading"] == "falling"
    assert coord.battery_time_left(falling[1]["days"]) == "about 6 months"


async def test_the_sag_and_rebound_do_not_move_the_slope(
    hass: HomeAssistant,
):
    """A cell sags under load and recovers, which is what the ten
    point drop and the eight and a half point rebound were. A fit
    would be dragged by both. The median of pairwise slopes puts them
    in the tails, so the answer is what the rest of the window
    agrees on.
    """
    coord = await setup_coordinator(hass)
    with_spike = coord._battery_slope(DYING[-7:])
    without = coord._battery_slope([30.0, 28.0, 23.5, 22.0, 21.0])
    assert with_spike == -1.75
    assert abs(with_spike - without) < 0.6


async def test_a_falling_cell_raises_nothing(
    hass: HomeAssistant,
):
    """Ruling #194: writing the reports over a falling cell raises
    nothing. The Problem List's forecast item is its own rule (#213,
    #471) and is asserted where it is built.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat6", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert coord.data[DATA_TODO_ITEMS] == []
    assert coord.data[DATA_INCIDENTS] == []


async def test_time_left_is_said_in_words_that_widen_with_distance(
    hass: HomeAssistant,
):
    """Ruling #197. The band a projection lands in has to be wider
    the further out it reaches, because the error grows with it: the
    proving cell moved forty percent in one afternoon, which on a
    reading of 1122 days is a true value somewhere between 670 and
    1570.
    """
    coord = await setup_coordinator(hass)
    said = coord.battery_time_left
    assert said(3) == "under a week"
    assert said(7) == "under a week"
    assert said(7.1) == "about 2 weeks"
    assert said(30) == "about a month"
    assert said(59) == "about 2 months"
    assert said(92) == "about 6 months"
    assert said(304) == "under a year"
    assert said(1122) == "over a year"


async def test_the_falling_sensor_is_a_different_set_from_low(
    hass: HomeAssistant,
):
    """Ruling #209. Low is a level that has been crossed; falling is
    one that is going to be, and the two rarely name the same device.

    The dying cell is at 12 percent and is counted low. The healthy
    faller is at 82 and is counted by neither, being two months out.
    A third at 20 percent dropping fast is the case that belongs in
    falling and nowhere else.
    """
    coord = await setup_coordinator(hass)
    low, _ = register_device(hass, "fs1", "Already Low")
    soon, _ = register_device(hass, "fs2", "Nearly Out")
    far, _ = register_device(hass, "fs3", "Months Away")
    _seed(coord, low.id, DYING, 12.0, low=True)
    _seed(coord, soon.id,
          [40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
           28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0], 20.0)
    _seed(coord, far.id, HEALTHY, 82.0)

    names = [row["name"] for row in coord.battery_falling_list]
    assert names == ["Nearly Out"]
    assert coord.battery_falling_count == 1
    # Already counted as low, so not counted twice.
    assert "Already Low" not in names
    # And the sensor agrees with the report and the brief.
    row = coord.battery_falling_list[0]
    # A week-against-week pace (0.23.6): the last week averaged about
    # ten points below the one before, so two weeks, where the old
    # seven-day slope was flattened by the last three days' 20.5, 20
    # and 20 and said a month.
    assert row["left"] == "about 2 weeks"
    assert row["device_id"] == soon.id


async def test_an_interrupted_write_leaves_no_fragment(
    hass: HomeAssistant,
):
    """The helper itself, on a write that fails part way."""
    coord = await setup_coordinator(hass)
    directory = hass.config.path(REPORT_DIR)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, "atomic_probe.html")

    with open(target, "w", encoding="utf-8") as handle:
        handle.write("the whole previous report")

    # A directory where the temporary file wants to be, so the write
    # fails at the point the old code would already have truncated
    # the destination.
    os.makedirs(f"{target}.tmp", exist_ok=True)
    with pytest.raises(OSError):
        coord._write_file(target, "half a ")

    with open(target, encoding="utf-8") as handle:
        assert handle.read() == "the whole previous report"
    os.rmdir(f"{target}.tmp")


async def test_a_steady_cell_is_not_projected(hass: HomeAssistant):
    """A cell holds its level for most of its life and then falls, so
    steady is the healthy state rather than a stale reading.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat3", "Motion Hall")
    _seed(coord, device.id, STEADY, 100.0)

    rows = coord._battery_rows()
    assert _names(rows["falling"]) == []
    assert _names(rows["flat"]) == ["Motion Hall"]


async def test_a_reading_above_100_is_called_unreadable(hass: HomeAssistant):
    """Seen on the fleet: an MQTT device reporting around 196 every
    day, a raw scale rather than a percentage. It can never cross the
    low threshold, and counted as a level it would look healthier than
    anything else.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat4", "LUX Outdoors")
    _seed(coord, device.id, [196.0] * 16, 186.0)

    rows = coord._battery_rows()
    assert _names(rows["unreadable"]) == ["LUX Outdoors"]
    assert "LUX Outdoors" not in _names(rows["flat"] + rows["falling"])


async def test_a_device_with_no_battery_is_counted_not_listed_as_zero(
    hass: HomeAssistant,
):
    """A watched device with no battery entity is mains powered or
    has one switched off. Either way it is not a cell at zero.
    """
    coord = await setup_coordinator(hass)
    register_device(hass, "bat5", "Wired Thing")

    rows = coord._battery_rows()
    assert _names(rows["absent"]) == ["Wired Thing"]
    assert rows["flat"] == rows["falling"] == rows["low"] == []


async def test_the_brief_names_a_cell_that_is_nearly_out(hass: HomeAssistant):
    """Ruling #195. The brief names what is close, and since the
    battery report retired (0.23.5) it sends the reader to Battery
    Trends on the dashboard rather than to a page anyone could open.
    """
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    device, _ = register_device(hass, "brf1", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = _brief(hass)

    assert "Batteries falling: Door 2nd Bedroom (about 2 weeks)" in brief
    assert "Details are in Battery Trends on the Device Sentinel dashboard." in brief
    assert "battery_report" not in brief
    assert "/local/" not in brief


async def test_the_brief_leaves_out_what_nobody_can_act_on(hass: HomeAssistant):
    """A cell a season away belongs on Battery Trends and not in a
    document that arrives whether it was wanted or not. On the
    reference fleet the unfiltered list was sixteen devices.
    """
    coord = await setup_coordinator(hass)
    near, _ = register_device(hass, "brf2", "Nearly Out")
    far, _ = register_device(hass, "brf3", "Months Away")
    _seed(coord, near.id, DYING, 12.0)
    _seed(coord, far.id, HEALTHY, 82.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = _brief(hass)

    assert "Nearly Out" in brief
    assert "Months Away" not in brief
    # Both are still falling in the rows Battery Trends reads.
    assert "Months Away" in _names(coord._battery_rows()["falling"])


async def test_a_cell_already_low_is_not_said_twice(hass: HomeAssistant):
    """It has a row in Now already. One document, one mention."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf4", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)


async def test_a_quiet_fleet_adds_no_line(hass: HomeAssistant):
    """Nothing to say means nothing said."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf5", "Motion Hall")
    _seed(coord, device.id, STEADY, 100.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)


async def test_the_horizon_is_the_persons_to_set(hass: HomeAssistant):
    """Days Till Empty, 7 to 30 (ruling #197). A cell two weeks out
    is named at thirty and silent at seven.
    """
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    device, _ = register_device(hass, "hz1", "Two Weeks Out")
    _seed(coord, device.id, TWO_WEEKS, 20.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Two Weeks Out" in _brief(hass)

    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_BATTERY_DAYS: 7},
    )
    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)
    # Still falling in the rows, which list everything falling.
    assert "Two Weeks Out" in _names(coord._battery_rows()["falling"])
