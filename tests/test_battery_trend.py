# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_trend.py, Version: 0.23.6 (2026-09-25)

"""The battery trend by the week, and the knee (0.23.6).

The seven-day slope called a cell falling at 0.05 points a day, smaller
than the half-point steps most cells report in. On the reference rig
seven cells near full were listed as falling, several as
accelerating, each "over a year", while their weekly averages moved by
a few tenths. The owner ruled on 25 September: a cell is falling when
its last week averages a point below the week before, and
accelerating when two fitted lines joined at a knee show the pace
became at least two points a week and twice what it was.

Every series here is real: the reference rig's of 25 September and
Tim Plas's of 24 September, where S63 sped up and S71 did not.
"""

from __future__ import annotations

from datetime import date

from custom_components.device_sentinel.report_battery import (
    _least_squares,
    battery_knee,
    battery_month_drop,
    battery_sentence,
    battery_trend,
    battery_weeks,
)

# Tim Plas's S63: steady for two weeks, then down 2.5, 5.2, 6.4 a week.
S63 = [73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
       74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
       68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
       58.0, 57.5, 57.5]
# Tim Plas's S71: about four points a week throughout, with one pause.
S71 = [81.5, 82.0, 81.0, 80.5, 81.0, 80.0, 79.0, 78.5, 77.0, 76.5, 76.0, 75.5,
       75.0, 75.0, 73.5, 73.0, 72.5, 71.5, 72.0, 72.5, 73.0, 72.0, 72.5, 72.5,
       71.5, 70.0, 69.0, 68.0, 66.0, 64.5, 65.5, 66.0, 66.5, 66.5, 66.5, 64.0,
       62.5, 61.5, 61.0]
# Tim Plas's S91: one point a week, as even as a cell gets.
S91 = [96.0, 96.0, 96.0, 95.0, 95.0, 95.0, 95.0, 95.0, 95.0, 95.0, 95.0, 94.0,
       94.0, 94.0, 94.0, 94.0, 94.0, 94.0, 94.0, 93.0, 93.0, 93.0, 93.0, 93.0,
       92.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0, 92.0, 91.0, 91.0, 91.0, 91.0,
       90.0, 90.0, 90.0]
# The reference rig's Door Master Shower, which today's page called
# "just started falling" while its weekly averages rose.
DOOR_MASTER_SHOWER = [76.5, 75.0, 76.0, 76.0, 76.0, 77.5, 76.0, 74.5, 76.0,
                      75.5, 77.0, 76.5, 77.0, 77.0, 77.0, 77.0, 77.0, 75.5,
                      75.0, 74.0, 75.0, 75.5, 75.0, 75.5, 75.0, 77.0, 76.5,
                      76.5, 76.5, 76.0, 76.5, 76.5, 76.5, 76.0, 77.5, 77.0,
                      77.5, 77.5, 77.5, 77.0, 77.0, 76.5]
# The reference rig's Temperature Master Shower, called accelerating.
TEMPERATURE_MASTER_SHOWER = [99.5, 99.5, 99.0, 99.0, 98.5, 99.0, 99.5, 98.0,
                             98.0, 98.0, 99.0, 98.5, 97.0, 97.5, 98.5, 98.5,
                             98.0, 97.0, 98.0, 98.0, 98.0, 97.5, 97.0, 96.0,
                             97.5, 98.0, 98.0, 97.0, 98.0, 97.0, 97.0, 97.0,
                             96.5, 97.0, 97.0, 97.5, 97.0, 96.5, 95.0, 96.0,
                             96.0, 96.5]


def test_weeks_are_whole_and_counted_back_from_the_newest_day():
    series = [float(i) for i in range(20)]
    # 20 days: two whole weeks, days 6 to 12 and 13 to 19.
    assert battery_weeks(series) == [9.0, 16.0]
    assert battery_weeks(list(range(50)), 5)[-1] == 46.0
    assert len(battery_weeks([50.0] * 60)) == 5
    assert battery_weeks([50.0] * 6) == []


def test_a_wobbling_cell_is_not_falling():
    """The fault 0.23.6 exists for, on the rig's own cells."""
    for series, level in ((DOOR_MASTER_SHOWER, 76.0), (TEMPERATURE_MASTER_SHOWER, 96.0)):
        trend = battery_trend(series, level, True)
        assert trend["reading"] == "", series[-7:]
        assert trend["pace"] is None


def test_a_week_a_point_below_the_last_is_falling():
    steady = [80.0] * 14
    falling = steady[:7] + [79.0] * 7
    assert battery_trend(falling, 79.0, True)["reading"] == "falling"
    nearly = steady[:7] + [79.1] * 7
    assert battery_trend(nearly, 79.1, True)["reading"] == ""


def test_the_cell_that_sped_up_is_accelerating_from_its_knee():
    trend = battery_trend(S63, 57.0, True)
    assert trend["reading"] == "accelerating"
    fit = trend["fit"]
    assert fit["knee"] is True
    assert fit["knee_ago"] == 19
    assert 5.5 < trend["pace"] < 6.5
    assert fit["before"] < 1.0
    # The drawn line: from the window's first day, to the knee, to today.
    assert [ago for ago, _ in fit["line"]] == [38, 19, 0]


def test_a_steady_fall_with_a_pause_is_falling_not_accelerating():
    """S71: the first weekly rule flipped it to accelerating on one day,
    because the week it compared against was the pause."""
    trend = battery_trend(S71, 61.5, True)
    assert trend["reading"] == "falling"
    assert trend["fit"]["knee"] is False
    assert 3.0 < trend["pace"] < 4.0


def test_an_even_fall_is_falling_not_accelerating():
    trend = battery_trend(S91, 90.0, True)
    assert trend["reading"] == "falling"
    assert trend["fit"]["knee"] is False


def test_one_slow_week_does_not_take_accelerating_off():
    """The wobble test, replayed day by day: from the first day S63
    reads accelerating it keeps it every day after, and S71 never
    reads it on any day with four weeks behind it."""
    first = next(end for end in range(28, len(S63) + 1)
                 if battery_trend(S63[:end], S63[end - 1], True)["reading"] == "accelerating")
    for end in range(first, len(S63) + 1):
        assert battery_trend(S63[:end], S63[end - 1], True)["reading"] == "accelerating", end
    for end in range(28, len(S71) + 1):
        assert battery_trend(S71[:end], S71[end - 1], True)["reading"] != "accelerating", end


def test_no_knee_before_four_weeks():
    assert battery_knee(S63[-27:]) is None
    assert battery_knee(S63[-28:]) is not None


def test_a_coarse_cell_and_an_empty_cell_are_not_judged():
    """Guard: coarse steps are judged against the low threshold alone
    (0.23.1), and a cell at nothing has nothing left to lose."""
    assert battery_trend(S63, 57.0, False)["reading"] == ""
    assert battery_trend([5.0] * 7 + [0.0] * 7, 0.0, True)["reading"] == ""


def test_under_two_weeks_nothing_is_said():
    assert battery_trend([90.0] * 7 + [80.0] * 6, 80.0, True)["reading"] == ""


def test_the_month_drop_and_the_sentence():
    # Weekly averages 73.71, 71.21, 66.0, 59.64: 14.07 points in four weeks.
    assert round(battery_month_drop(S63), 2) == 14.07
    assert battery_month_drop([90.0] * 20) is None
    accelerating = battery_trend(S63, 57.0, True)
    words = battery_sentence(accelerating, date(2026, 9, 23))
    assert words.startswith("Accelerating: steady until about Sep 4, then falling about")
    assert battery_sentence(battery_trend(S71, 61.5, True)).startswith("Falling about 3.")
    assert battery_sentence(battery_trend(DOOR_MASTER_SHOWER, 76.0, True)) == ""


def test_a_singular_fit_returns_nothing():
    """Guard: a flat column cannot be solved, and must not raise."""
    assert _least_squares([[0.0] * 5, [0.0] * 5], [1.0] * 5) is None


# Tim Plas's S57: flat, then one two-point step, and a day at 34 added
# as the forward simulation's fold added it.
S57 = [38.0, 38.0] + [37.0] * 24 + [36.0] * 11 + [34.0, 34.0, 34.0]
# Tim Plas's B01, a button that reads 84 and 80.5 by turns, with a day
# at 80.5 added.
B01 = [80.5, 80.5, 80.5, 80.5, 80.5, 84.0, 80.5, 84.0, 80.5, 80.5, 80.5, 80.5,
       80.5, 80.5, 80.5, 80.5, 80.5, 84.0, 84.0, 84.0, 84.0, 80.5, 80.5, 80.5,
       80.5, 84.0, 84.0, 84.0, 80.5, 80.5, 80.5, 80.5, 84.0, 80.5, 80.5, 84.0,
       80.5, 80.5, 80.5, 80.5]


def test_one_step_is_not_two_fast_weeks():
    """The knee needs two weeks after it (the owner's two fast weeks);
    with one week allowed, this single step read as accelerating."""
    assert battery_trend(S57, 34.0, True)["reading"] != "accelerating"


def test_a_cell_flipping_between_two_levels_is_not_falling():
    """One week can dip a point by chance; the six-week line must also
    be going down at least half a point a week."""
    assert battery_trend(B01, 80.5, True)["reading"] == ""


# ------------------------------------------------ through the coordinator

from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.device_sentinel.const import (  # noqa: E402
    CONF_BATTERY_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_coordinator  # noqa: E402

# S63's shape carried down to 21.5 percent, so it is projected empty
# inside a month: the case the owner ruled belongs on the Problem List.
S63_LOW = [round(level - 36.0, 1) for level in S63]


def _seed(coord, device_id, series):
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = series[-1]
    return record


async def test_every_surface_reads_the_same_trend(hass: HomeAssistant):
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    fast, _ = register_device(hass, "bw1", "Garage Door")
    even, _ = register_device(hass, "bw2", "Radar Presence")
    wobble, _ = register_device(hass, "bw3", "Door Master Shower")
    _seed(coord, fast.id, S63_LOW)
    _seed(coord, even.id, S91)
    _seed(coord, wobble.id, DOOR_MASTER_SHOWER)

    rows = {row["name"]: row for row in coord._battery_rows()["falling"]}
    assert set(rows) == {"Garage Door", "Radar Presence"}
    assert rows["Garage Door"]["reading"] == "accelerating"
    assert rows["Radar Presence"]["reading"] == "falling"

    # The device page: the weeks, the fitted line with its knee, and
    # the sentence; a steady cell gets none of the three.
    page = coord._page_battery(coord.data["devices"][fast.id])
    assert page["reading"] == "accelerating" and page["fit"]["knee"] is True
    assert len(page["fit"]["line"]) == 3
    assert page["sentence"].startswith("Accelerating: steady until about ")
    steady = coord._page_battery(coord.data["devices"][wobble.id])
    assert steady["fit"] is None and steady["sentence"] == "" and len(steady["weeks"]) == 5

    # Battery Trends: the falling rows carry the weeks and the pace;
    # a steady cell carries the four weeks' drop in points.
    trends = coord.battery_trends()
    falling = {row["name"]: row for row in trends["falling"]}
    assert len(falling["Garage Door"]["weeks"]) == 5
    assert 5.5 < falling["Garage Door"]["pace"] < 6.5
    steady_row = next(row for row in trends["steady"] if row["name"] == "Door Master Shower")
    assert steady_row["month_drop"] < 0, "its weekly averages rose"

    # The Battery: Falling sensor names the accelerating cell inside
    # the horizon, and the Problem List carries it (ruled 25 September).
    assert [row["name"] for row in coord.battery_falling_list] == ["Garage Door"]
    coord._sync_problem_list()
    item = next(item for item in coord.todo_items if item["device_id"] == fast.id)
    assert item["summary"].startswith("Garage Door: battery empty in")


async def test_the_diagnostics_carry_each_cells_weeks(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    fast, _ = register_device(hass, "bw4", "Garage Door")
    _seed(coord, fast.id, S63)
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    trend = diagnostics["devices"][fast.id]["battery_trend"]
    assert trend["reading"] == "accelerating"
    assert trend["knee_days_ago"] == 19
    assert [round(week, 1) for week in trend["weeks"]] == [74.6, 73.7, 71.2, 66.0, 59.6]
