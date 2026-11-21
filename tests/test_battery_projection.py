# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_projection.py, Version: 0.30.0 (2026-11-21)

"""When a falling cell runs empty, as a range (rule BAT-13).

A fall that is speeding up is projected on a curve, a steady one on a
straight line; the range comes from the cell's own week-to-week
swings; the near end decides Days Till Low Warning, on the Problem List as
on the chart; and every days-left figure reads the range in words. The
sentence above the chart agrees with the range (rule BAT-17).
"""

from __future__ import annotations

import math

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.battery_projection import (
    accelerating_pace,
    battery_projection,
    days_to_empty,
    time_left_range,
)
from custom_components.device_sentinel.report_battery import battery_sentence
from custom_components.device_sentinel.const import (
    CONF_BATTERY_DAYS,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

from tests.helpers import register_device, setup_coordinator, thresholds

# A real door sensor's last 63 kept days: flat near 25 for weeks, then
# bending down. The straight pace read about 91 days left.
DOOR = [
    24.5, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 24.5, 24.0, 24.5, 24.5, 24.0, 24.5,
    24.5, 24.5, 24.0, 24.0, 24.0, 24.5, 24.0, 23.5, 23.0, 23.0, 23.0, 22.5, 23.0, 23.5, 23.0,
    23.0, 23.0, 22.0, 23.0, 22.0, 23.5, 22.5, 23.5, 23.0, 22.0, 22.5, 23.0, 21.0, 21.5, 22.5,
    21.5, 21.0, 21.0, 20.5, 20.5, 20.0, 19.5, 19.0, 19.0, 17.0, 19.5, 19.0, 17.0, 17.5, 15.0,
    15.0, 18.0, 18.0, 17.5, 16.5,
]


def _wobble(i: int) -> float:
    return ((i * 37) % 11 - 5) / 20.0


def test_a_fall_that_is_speeding_up_is_projected_on_a_curve():
    found = battery_projection(DOOR, 16.5)
    assert found is not None and found["curved"] is True
    # About a month, not three: the straight pace said about 91 days. The
    # curve's own day is the far end, and the width comes off it.
    assert 15 <= found["near"] <= found["centre"] == found["far"] <= 40, found
    assert time_left_range(found["near"], found["far"]) == "about 3 to 4 weeks"


def test_a_steady_fall_is_projected_on_a_straight_line():
    steady = [80 - 0.3 * i + _wobble(i) for i in range(60)]
    found = battery_projection(steady, steady[-1])
    assert found is not None and found["curved"] is False
    # From the line's value today, the slot after the newest, and the
    # fit's own day is the far end.
    straight = (80 - 0.3 * len(steady)) / 0.3
    assert found["near"] <= found["far"] and abs(found["far"] - straight) < 0.02 * straight, (found, straight)


def test_the_same_history_gives_the_same_range():
    """Seeded from the history, so a page never changes on a refresh."""
    first = battery_projection(DOOR, 16.5)
    from custom_components.device_sentinel import battery_projection as module

    module._MEMO.clear()
    assert battery_projection(DOOR, 16.5) == first


def test_a_jumpier_cell_gets_a_wider_range():
    calm = [80 - 0.3 * i + _wobble(i) for i in range(60)]
    jumpy = [80 - 0.3 * i + 6 * _wobble(i) for i in range(60)]
    a = battery_projection(calm, calm[-1])
    b = battery_projection(jumpy, jumpy[-1])
    assert (b["far"] - b["near"]) > (a["far"] - a["near"])


def test_too_few_days_heard_gives_no_range():
    assert battery_projection([50 - i for i in range(10)], 40.0) is None


def test_days_to_empty_on_a_curve_and_a_line():
    assert days_to_empty(30.0, -1.0, 0.0) == 30.0
    assert days_to_empty(30.0, 0.5, 0.0) is None
    curved = days_to_empty(30.0, -1.0, -0.01)
    assert curved is not None and curved < 30.0
    assert math.isclose(30.0 - curved - 0.01 * curved * curved, 0.0, abs_tol=1e-6)


def test_the_words_take_a_range():
    assert time_left_range(3, 5) == "under a week"
    assert time_left_range(26.9, 35.2) == "about 4 to 5 weeks"
    assert time_left_range(91, 113) == "about 3 to 4 months"
    assert time_left_range(300, 500) == "about 10 months to over a year"
    assert time_left_range(400, None) == "over a year"


async def test_the_near_end_decides_the_falling_forecast(hass: HomeAssistant):
    """Door 2nd Bedroom with Days Till Low Warning at 30: the straight
    pace kept it off the Problem List; the near end of its range puts it
    on, with the range in words. At 16.5 percent its time left runs to
    the 15 percent threshold, not to empty (rule BAT-13)."""
    device, (entity_id,) = register_device(hass, "door", name="Door 2nd Bedroom")
    coord = await setup_coordinator(hass, {**thresholds(15), CONF_BATTERY_DAYS: 30})
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_DAILY] = list(DOOR)
    record[DEV_BATTERY_VALUE] = 16.5
    falling = coord.battery_falling_list
    row = next(r for r in falling if r["device_id"] == device.id)
    assert row["left"] == "under a week"
    assert row["until"] == "reaches 15% in under a week"
    page = coord._page_battery(record)
    assert page["left"] == "under a week" and page["left_soon"] is True
    assert page["projection"]["target"] == 15.0
    assert page["projection"]["curved"] is True and page["days_setting"] == 30.0


def test_the_curve_is_used_at_any_level():
    """A cell is judged only at or under three times the threshold, so a
    bending fall is curved wherever it is judged, with no other level
    limit (rules BAT-10, BAT-12)."""
    high = [v + 70.0 for v in DOOR]
    assert battery_projection(high, high[-1])["curved"] is True
    assert battery_projection(DOOR, DOOR[-1])["curved"] is True


def test_each_end_of_the_range_has_its_own_unit():
    """A near end inside Days Till Low Warning never reads as months
    (rule BAT-13)."""
    assert time_left_range(3, 75) == "under a week to about 11 weeks"
    assert time_left_range(13, 72) == "about 2 to 10 weeks"
    assert time_left_range(0, None) == "under a week to over a year"
    assert time_left_range(50, 100) == "about 7 to 14 weeks"
    # Never backwards.
    assert time_left_range(69, 72) == "about 10 weeks"
    assert time_left_range(66, 75) == "about 9 to 11 weeks"


def test_a_range_under_three_months_is_said_in_weeks():
    """A range under three months is said in weeks, so it never reads
    "about 8 weeks to 2 months", one span said twice. Weeks run to just
    under 13; months only past that (rule BAT-13)."""
    assert time_left_range(56, 75) == "about 8 to 11 weeks"
    assert time_left_range(84, 90) == "about 12 to 13 weeks"
    assert time_left_range(60, 120) == "about 9 weeks to 4 months"
    assert time_left_range(91, 113) == "about 3 to 4 months"
    # Never one span said twice near the turn.
    assert time_left_range(88, 92) == "about 13 weeks"
    assert time_left_range(88, 100) == "about 13 to 14 weeks"
    assert time_left_range(365, 400) == "about a year or more"
    assert time_left_range(350, 400) == "about a year or more"
    assert time_left_range(300, 500) == "about 10 months to over a year"


def test_the_range_edges_found_by_review():
    assert time_left_range(60, 72) == "about 9 to 10 weeks"
    assert time_left_range(3, 9) == "about 1 week"


async def test_a_forecast_alone_is_not_counted_among_listed_faults(hass: HomeAssistant):
    """The maintainer report counts the devices it lists; a falling
    forecast has no line there. The Problem List's own set keeps it
    (rule BAT-14)."""
    device, _ = register_device(hass, "door", name="Door 2nd Bedroom")
    coord = await setup_coordinator(hass, {**thresholds(15), CONF_BATTERY_DAYS: 30})
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_DAILY] = list(DOOR)
    record[DEV_BATTERY_VALUE] = 16.5
    assert device.id in coord._problem_device_ids()
    assert "## Devices With a Fault (0)" in "\n".join(coord._reporting_lines())


def test_a_curved_fall_is_said_as_speeding_up():
    """A curved range says the fall is speeding up, at the curve's pace
    today, never "at a steady pace" beside it; a straight one keeps the
    steady sentence (rule BAT-17)."""
    curved = battery_projection(DOOR, 16.5)
    assert curved["curved"] is True and curved["pace"] > 0
    steady = {"reading": "falling", "pace": 1.3, "fit": None}
    words = battery_sentence(steady, curved)
    assert words == f"Falling faster each week, about {curved['pace']:.1f} points a week today."
    assert "steady" not in words
    straight = dict(curved, curved=False)
    assert battery_sentence(steady, straight).endswith("at a steady pace.")
    assert battery_sentence(steady).endswith("at a steady pace.")
    # The pace today is the fitted path's, faster than the weeks' average.
    assert curved["pace"] > 1.3


def test_a_perfectly_straight_fall_is_not_accelerating():
    """An exact half point a day leaves the curve no error to divide by,
    so without the gain floor the F test would read it as speeding up
    (rule BAT-12)."""
    straight = [round(61.0 - 0.5 * day, 1) for day in range(43)]
    assert accelerating_pace(straight) is None
    assert battery_projection(straight, 40.0, 15.0)["curved"] is False


# A real door sensor's last six weeks, ending at 19 percent: a bend of
# 1.9 points a week today.
DOOR_AT_19 = [24.5, 24.5, 24.0, 24.0, 24.0, 24.5, 24.0, 23.5, 23.0, 23.0, 23.0,
              22.5, 23.0, 23.5, 23.0, 23.0, 23.0, 22.0, 23.0, 22.0, 23.5, 22.5,
              23.5, 23.0, 22.0, 22.5, 23.0, 21.0, 21.5, 22.5, 21.5, 21.0, 21.0,
              20.5, 20.5, 20.0, 19.5, 19.0, 19.0, 17.0, 19.5, 19.0]


def test_a_bend_under_two_points_a_week_is_accelerating():
    """There is no floor on the pace: a curve that passes its test and
    is still falling today is accelerating, so a bend of 1.9 points a
    week counts (rule BAT-12)."""
    pace = accelerating_pace(DOOR_AT_19)
    assert pace is not None and 1.8 < pace < 2.0
    assert battery_projection(DOOR_AT_19, 19.0, 15.0)["curved"] is True
    # The same history turned upside down, rising faster, is not.
    rising = [round(48.0 - level, 1) for level in DOOR_AT_19]
    assert accelerating_pace(rising) is None


def test_the_time_left_starts_from_the_line_not_the_reading():
    """A reading a step off the line, inside the swings the six weeks
    already held, moves the date by days, not weeks: the time left starts
    from the fit's value today (rule BAT-13)."""
    # Swings of up to 3 points a day, as a bouncing cell has.
    steady = [80 - 0.3 * i + 12 * _wobble(i) for i in range(60)]
    on_line = battery_projection(steady, 62.0)
    step_low = battery_projection(steady, 60.0)
    step_high = battery_projection(steady, 65.0)
    assert on_line is not None and step_low is not None and step_high is not None
    assert on_line["near"] == step_low["near"] == step_high["near"]
    assert on_line["far"] == step_low["far"] == step_high["far"]
    # The reading is still what the page shows.
    assert (on_line["level"], step_low["level"]) == (62.0, 60.0)
    assert abs(on_line["start"] - (80 - 0.3 * 60)) < 1.0, on_line["start"]


def test_a_curved_fall_starts_from_the_curve_today():
    from custom_components.device_sentinel.battery_projection import _fit, _value

    found = battery_projection(DOOR, 16.5)
    assert found is not None and found["curved"] is True
    t = [float(i) for i in range(len(DOOR[-42:]))]
    bend = _fit(t, [float(v) for v in DOOR[-42:]], True)
    assert bend is not None
    assert abs(found["start"] - _value(bend, 42.0)) < 0.01


def test_a_line_already_under_the_target_starts_from_the_reading():
    """A reading just over the threshold on a line already under it: the
    fit has crossed before the battery has, so the reading starts it and
    the range is a few days, never "reached" with nothing to draw."""
    steady = [40 - 0.5 * i + _wobble(i) for i in range(60)]
    found = battery_projection(steady, 16.0, 15.0)
    assert found is not None and found["start"] == 16.0
    assert 0.0 < found["near"] <= found["far"] < 7.0, found


def test_a_collapse_the_line_has_not_caught_up_with_starts_from_the_reading():
    """A steady fall near 40 that reads 9 today, under the threshold: the
    reading is further under the line than any day was, so the time to
    empty starts a point over 9, weeks rather than months."""
    steady = [52 - 0.3 * i + _wobble(i) for i in range(42)]
    found = battery_projection(steady, 9.0, 0.0)
    assert found is not None and found["start"] == 10.0
    assert found["near"] < 60, found
    # A reading inside a point of the line still starts from the line.
    usual = battery_projection(steady, 39.3, 15.0)
    assert usual is not None and usual["start"] != 39.3


def test_a_warm_day_over_the_line_does_not_hide_a_collapse():
    """Only days under the line say how far under it a reading may sit:
    a cell's one high day never lets a reading 10 points under pass as a
    swing, and the start follows the reading down without a jump."""
    steady = [52 - 0.3 * i + _wobble(i) for i in range(42)]
    steady[20] += 10.0
    line = battery_projection(steady, 39.0, 15.0)["start"]
    starts = [battery_projection(steady, line - drop, 15.0)["start"] for drop in (0.5, 5.0, 10.0, 10.5)]
    assert starts[0] == line
    assert starts[1] < line - 3.0
    # Each half point lower moves the start by at most half a point.
    assert abs(starts[3] - starts[2]) <= 0.5 + 1e-9


def test_the_start_nears_the_reading_as_the_line_nears_the_target():
    """A reading a step over a line that is falling to the threshold: the
    time left shrinks day by day and never drops to nothing while the
    reading is still over the threshold (rule BAT-13)."""
    nears = []
    for today_line in (17.0, 16.0, 15.5, 15.2, 15.0, 14.8):
        steady = [today_line + 0.3 * (60 - i) + _wobble(i) for i in range(60)]
        found = battery_projection(steady, today_line + 2.0, 15.0)
        assert found is not None
        # The fit, held a point over the threshold (the wobble moves the
        # fit a few hundredths).
        assert abs(found["start"] - max(today_line, 16.0)) < 0.1, found
        nears.append(found["near"])
    assert all(near > 1.0 for near in nears), nears
    # No jump where the line crosses the target.
    assert max(abs(a - b) for a, b in zip(nears, nears[1:])) < 4.0, nears


def test_one_stray_day_does_not_hide_a_collapse():
    """A reconnect that read 10 points low once: the second deepest day
    sets how far under the line a reading may sit."""
    steady = [52 - 0.3 * i + _wobble(i) for i in range(42)]
    steady[25] -= 10.0
    found = battery_projection(steady, 20.0, 15.0)
    assert found is not None and found["start"] <= 21.5, found


def test_the_far_end_is_the_fits_own_day_and_the_width_comes_off_it():
    """The fit's day is the longest the battery is likely
    to last, and the cell's own swings set how much earlier the near end
    is; the near end's path is the fit's, run faster (rule BAT-13)."""
    found = battery_projection(DOOR, 16.5)
    assert found["far"] == found["centre"]
    assert found["far_path"][0] < 0
    # The near path reaches empty on the near day.
    from custom_components.device_sentinel.battery_projection import days_to_empty

    reached = days_to_empty(found["start"], found["near_path"][0], found["near_path"][1])
    assert abs(reached - found["near"]) < 0.5, (reached, found["near"])



def test_a_wide_range_never_says_under_a_week_for_a_battery_far_from_its_target():
    """A slow, noisy fall whose swings are wider than its own day: the near
    end is held to a quarter of the far end, never today (rule BAT-13)."""
    import random as _random

    draw = _random.Random(7)
    noisy = [40 - 0.5 / 7 * i + draw.uniform(-3, 3) for i in range(60)]
    found = battery_projection(noisy, noisy[-1], 15.0)
    assert found is not None
    assert found["near"] >= 0.25 * found["far"] - 0.1, found
    assert not time_left_range(found["near"], found["far"]).startswith("under a week"), found


def test_a_far_end_past_three_years_keeps_a_near_end_past_it_too():
    """The width is taken on days held to the longest said, as the far end
    is, so a battery with years left never reads "under a week"."""
    slow = [62 - 0.04 * i + _wobble(i) for i in range(60)]
    found = battery_projection(slow, slow[-1], 0.0)
    assert found is not None and found["far"] == 3 * 365, found
    assert found["near"] >= 0.25 * found["far"], found
