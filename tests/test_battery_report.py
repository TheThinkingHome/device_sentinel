# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_report.py, Version: 0.27.10 (2026-10-27)

"""Which cells are going to be low (rules BAT-11, BAT-13, BAT-14).

A threshold answers which cells are low; the battery rows answer which
are going to be. The shapes below come from a real house, including a
cell that sat ten days flat at 32 percent, then dropped ten points and
rebounded eight and a half on consecutive days, then fell to 21.

The rows are what Battery Trends, the Battery: Falling sensor, the
Problem List and the brief read, so they are asserted here directly,
and the brief's own line beside them.
"""

from __future__ import annotations

import os

import pytest

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BATTERY_DAYS,
    CONF_LOW_THRESHOLD,
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

from .helpers import registry_settled, register_device, setup_coordinator

# The dying cell, exactly as recorded: flat, then the sag and rebound,
# then the fall.
DYING = [
    32.0, 32.5, 31.5, 32.5, 32.5, 31.5, 31.0, 32.0,
    32.5, 31.5, 21.5, 30.0, 28.0, 23.5, 22.0, 21.0,
]
# A healthy cell drifting down at half a point a day.
HEALTHY = [91.0, 92.0, 92.5, 92.0, 91.5, 92.0, 91.5, 91.0,
           91.0, 91.0, 89.5, 88.5, 87.0, 86.0, 84.0, 82.5]
# S63 carried down to 21.5 percent: steady, then speeding up.
SPEEDING = [round(level - 36.0, 1) for level in [
    73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
    74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
    68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
    58.0, 57.5, 57.5]]
# A cell that has not moved at all.
STEADY = [100.0] * 16
# 20 percent falling 1.5 a day: a little over thirteen days.
TWO_WEEKS = [40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
             28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0]


def _held(series):
    """Two more weeks in front, carrying on the history's own first week
    backwards: a cell is judged only with 28 heard days of the last 42
    (rule BAT-10), and these histories are sixteen days long. A flat
    fortnight in front would make each fall a bend, which is
    accelerating, and these tests are about the steady kind."""
    first = list(series[:7])
    per_day = (first[0] - first[-1]) / 6
    return [round(first[0] + per_day * (14 - day), 2) for day in range(14)] + list(series)


def _seed(coord, device_id, series, level, low=False, since=None):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_BATTERY_DAILY] = _held(series) if len(series) < 28 else list(series)
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
    remaining still tells them apart (rule BAT-13).
    """
    coord = await setup_coordinator(hass)
    # Judged only at or under three times the low threshold (rule BAT-10):
    # raised so the high cells here are judged too.
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_LOW_THRESHOLD: 49}
    )
    dying, _ = register_device(hass, "bat1", "Door 2nd Bedroom")
    healthy, _ = register_device(hass, "bat2", "Soil Moisture")
    await registry_settled(hass)
    _seed(coord, dying.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")
    _seed(coord, healthy.id, HEALTHY, 82.0)

    falling = coord._battery_rows()["falling"]
    assert _names(falling) == ["Door 2nd Bedroom", "Soil Moisture"]
    # The six-week line's pace, four weeks being always held
    # (rule BAT-10).
    assert round(falling[0]["slope"], 3) == -1.031
    assert coord.battery_time_left(falling[0]["days"]) == "about 2 weeks"
    # Flat, the sag, then the fall: a bend, called accelerating
    # (rule BAT-12).
    assert falling[0]["reading"] == "accelerating"
    # The healthy cell's time left runs to the 49 percent threshold;
    # the dying one, under it, runs to empty (rule BAT-13).
    # About a month: four weeks held, the line reads the healthy cell's
    # last fortnight of falling too.
    assert coord.battery_time_left(falling[1]["days"]) == "about a month"
    assert falling[1]["target"] == 49.0 and falling[0]["target"] == 0.0


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
    """Writing the reports over a falling cell raises nothing. The
    Problem List's forecast item is its own rule and is asserted where
    it is built (rule BAT-14).
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat6", "Door 2nd Bedroom")
    await registry_settled(hass)
    _seed(coord, device.id, DYING, 12.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert coord.data[DATA_TODO_ITEMS] == []
    assert coord.data[DATA_INCIDENTS] == []


async def test_time_left_is_said_in_words_that_widen_with_distance(
    hass: HomeAssistant,
):
    """The band a projection lands in widens the further out it
    reaches, because the error grows with it: a cell can move forty
    percent in one afternoon, which on a reading of 1122 days is a true
    value somewhere between 670 and 1570 (rule BAT-13).
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
    """Low is a level that has been crossed; falling is one that is
    going to be, and the two rarely name the same device (rule BAT-14).

    The dying cell is at 12 percent and is counted low. The healthy
    faller is at 82 and is counted by neither, being two months out.
    A third at 21.5 percent speeding up is the case that belongs in
    falling and nowhere else. A cell falling at a steady pace is a
    battery to watch, not on the sensor.
    """
    coord = await setup_coordinator(hass)
    low, _ = register_device(hass, "fs1", "Already Low")
    soon, _ = register_device(hass, "fs2", "Nearly Out")
    far, _ = register_device(hass, "fs3", "Months Away")
    await registry_settled(hass)
    _seed(coord, low.id, DYING, 12.0, low=True)
    _seed(coord, soon.id, SPEEDING, 21.5)
    _seed(coord, far.id, HEALTHY, 82.0)

    names = [row["name"] for row in coord.battery_falling_list]
    assert names == ["Nearly Out"]
    assert coord.battery_falling_count == 1
    # Already counted as low, so not counted twice.
    assert "Already Low" not in names
    # And the sensor agrees with the report and the brief.
    row = coord.battery_falling_list[0]
    assert row["until"] == "reaches 15% in under a week"
    assert row["device_id"] == soon.id


async def test_a_steady_fall_is_watched_not_counted(hass: HomeAssistant):
    """20 percent falling 1.5 a day: a week-against-week pace of about
    ten points, where a seven-day slope would be flattened by the last
    three days' 20.5, 20 and 20. Sixteen days is too short to call it
    speeding up, so it is a battery to watch (rule BAT-14)."""
    coord = await setup_coordinator(hass)
    soon, _ = register_device(hass, "fs2", "Nearly Out")
    await registry_settled(hass)
    _seed(coord, soon.id, TWO_WEEKS, 20.0)
    assert coord.battery_falling_list == []
    watched = coord.battery_watch_rows()
    assert [row["name"] for row in watched] == ["Nearly Out"]
    assert coord.battery_until_words(watched[0]) == "reaches 15% in under a week"


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
    await registry_settled(hass)
    _seed(coord, device.id, STEADY, 100.0)

    rows = coord._battery_rows()
    assert _names(rows["falling"]) == []
    assert _names(rows["flat"]) == ["Motion Hall"]


async def test_a_reading_above_100_is_called_unreadable(hass: HomeAssistant):
    """An MQTT device reporting around 196 every day is on a raw scale,
    not a percentage. It can never cross the low threshold, and counted
    as a level it would look healthier than anything else (rule BAT-02).
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat4", "LUX Outdoors")
    await registry_settled(hass)
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
    await registry_settled(hass)

    rows = coord._battery_rows()
    assert _names(rows["absent"]) == ["Wired Thing"]
    assert rows["flat"] == rows["falling"] == rows["low"] == []


async def test_the_brief_names_a_cell_that_is_nearly_out(hass: HomeAssistant):
    """The brief names what is close and sends the reader to Battery
    Trends on the dashboard (rules BAT-14, BAT-18).
    """
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    device, _ = register_device(hass, "brf1", "Door 2nd Bedroom")
    steady, _ = register_device(hass, "brf2", "Nearly Out")
    await registry_settled(hass)
    _seed(coord, device.id, SPEEDING, 21.5)
    _seed(coord, steady.id, TWO_WEEKS, 20.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = _brief(hass)

    assert "Batteries falling faster each week: Door 2nd Bedroom (reaches 15% in under a week)." in brief
    # A steady fall is named to watch, and the pointer is said once,
    # after the last battery line.
    assert ("Batteries to watch: Nearly Out (reaches 15% in under a week). "
            "Details are in Battery Trends on the Device Sentinel dashboard.") in brief
    assert brief.count("Details are in Battery Trends") == 1
    assert "battery_report" not in brief
    assert "/local/" not in brief


async def test_the_brief_leaves_out_what_nobody_can_act_on(hass: HomeAssistant):
    """A cell a season away belongs on Battery Trends and not in a
    document that arrives whether it was wanted or not, where an
    unfiltered list can run to sixteen devices (rule BAT-14).
    """
    coord = await setup_coordinator(hass)
    # Judged only at or under three times the low threshold (rule BAT-10):
    # raised to 28 so the 82 percent cell is judged, and its time left to
    # 28 is still months.
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_LOW_THRESHOLD: 28}
    )
    near, _ = register_device(hass, "brf2", "Nearly Out")
    far, _ = register_device(hass, "brf3", "Months Away")
    await registry_settled(hass)
    _seed(coord, near.id, DYING, 12.0)
    # Half a point a day for a month, down to 82: months from 28.
    _seed(coord, far.id, [round(97.0 - 0.5 * day, 1) for day in range(31)], 82.0)

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
    await registry_settled(hass)
    _seed(coord, device.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)


async def test_a_quiet_fleet_adds_no_line(hass: HomeAssistant):
    """Nothing to say means nothing said."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf5", "Motion Hall")
    await registry_settled(hass)
    _seed(coord, device.id, STEADY, 100.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)


async def test_the_horizon_is_the_persons_to_set(hass: HomeAssistant):
    """Days Till Low Warning, 7 to 30 (rule BAT-14). A cell two weeks
    out is named at thirty and silent at seven.
    """
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    device, _ = register_device(hass, "hz1", "Two Weeks Out")
    await registry_settled(hass)
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


async def test_a_short_history_is_shown_and_not_judged(hass: HomeAssistant):
    """Sixteen days falling ten points a week, at 20 percent: no
    reading, no time left, on no list; its weeks are shown and its page
    says it is short (rule BAT-10)."""
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    soon, _ = register_device(hass, "sh1", "Nearly Out")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][soon.id]
    record[DEV_BATTERY_DAILY] = list(TWO_WEEKS)
    record[DEV_BATTERY_VALUE] = 20.0
    rows = coord._battery_rows()
    assert rows["falling"] == [] and _names(rows["flat"]) == ["Nearly Out"]
    assert coord.battery_falling_list == [] and coord.battery_watch_rows() == []
    page = coord._page_battery(record)
    assert page["short"] is True and page["reading"] == "" and page["left"] is None
    assert len(page["weeks"]) == 2
    record[DEV_BATTERY_DAILY] = _held(TWO_WEEKS)
    assert coord._page_battery(record)["short"] is False
