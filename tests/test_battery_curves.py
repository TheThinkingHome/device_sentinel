# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_curves.py, Version: 0.30.1 (2026-11-21)

"""Keep the curve (rule BAT-20).

Each battery's weeks are kept for good, whatever How Much History to
Keep trims, and a battery that ends leaves its curve: its weeks, the
daily detail of its last six weeks and how it ended. A curve is kept
when its readings reach back to three times its threshold; a device
keeps its newest, and a full one is not given up for a shorter one.
"""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import history_file
from custom_components.device_sentinel.battery_curves import weekly_rows, week_of
from custom_components.device_sentinel.const import (
    DATA_BATTERY_CURVES,
    DATA_BATTERY_LIVES,
    DATA_BATTERY_WEEKS,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
)
from custom_components.device_sentinel.normalise import check_storage, curve_ok, week_row_ok

from .test_battery_last_replaced import _house
from .test_battery_lives import _first_seen

TODAY = date(2026, 11, 21)


def test_a_week_is_one_row():
    monday = date(2026, 11, 9)
    levels = [(monday + timedelta(days=i), 50.0 - i) for i in range(7)] + [(monday + timedelta(days=7), 42.0)]
    ranges = {monday: [49.0, 51.0, 2.95, 3.01], monday + timedelta(days=1): [48.0, 50.0, 2.94, 3.0]}
    evidence = {monday: [3.0, 21.0, 1000], monday + timedelta(days=6): [2.98, 23.0, 1700]}
    rows = weekly_rows(levels, ranges, evidence, monday - timedelta(days=30))
    assert rows[0] == ["2026-11-09", "2026-10-10", 47.0, 44.0, 51.0, 2.94, 3.01, 700, 22.0]
    assert rows[1][:5] == ["2026-11-16", "2026-10-10", 42.0, 42.0, 42.0]
    assert rows[1][5:] == [None, None, None, None]
    assert all(week_row_ok(row) for row in rows)


def test_a_level_outside_its_day_range_widens_the_week():
    """The day's range and its level are read at different moments."""
    monday = date(2026, 11, 16)
    row = weekly_rows([(monday, 63.9)], {monday: [64.0, 65.0, None, None]}, {}, monday)[0]
    assert row[2:5] == [63.9, 63.9, 65.0] and week_row_ok(row)


def test_a_count_that_starts_again_says_nothing_of_the_week():
    monday = date(2026, 11, 9)
    levels = [(monday + timedelta(days=i), 50.0) for i in range(3)]
    evidence = {monday: [3.0, None, 1000], monday + timedelta(days=2): [3.0, None, 40]}
    assert weekly_rows(levels, {}, evidence, monday)[0][7] is None


def test_week_of_is_its_monday():
    assert week_of(date(2026, 11, 21)) == date(2026, 11, 16)
    assert week_of(date(2026, 11, 16)) == date(2026, 11, 16)


async def _run(coord, record, device_id, levels, first):
    """One midnight a day from `first`: the day rolls, then the weeks fold."""
    from .test_battery_last_replaced import _fold

    for i, level in enumerate(levels):
        _fold(coord, record, device_id, [level], first + timedelta(days=i))
        coord.battery_weeks_fold()


async def test_the_weeks_outlive_the_days(hass: HomeAssistant):
    """Ninety days of a slow alkaline fall; the days are then trimmed to 30,
    and every week is still there (rule BAT-20)."""
    _entry, coord, device, record = await _house(hass)
    first = dt_util.now().date() - timedelta(days=90)
    await _run(coord, record, device.id, [90.0 - i * 0.3 for i in range(90)], first)
    weeks = coord.data[DATA_BATTERY_WEEKS][device.id]
    assert len(weeks) >= 13
    assert weeks[0][0] == week_of(first).isoformat()
    record[DEV_BATTERY_DAILY] = record[DEV_BATTERY_DAILY][-30:]
    coord.battery_weeks_fold()
    assert coord.data[DATA_BATTERY_WEEKS][device.id][: len(weeks) - 6] == weeks[: len(weeks) - 6]
    assert not [f for f in check_storage(coord.data) if DATA_BATTERY_WEEKS in str(f)]


async def test_a_battery_that_ran_out_leaves_its_curve(hass: HomeAssistant):
    """The first battery's start was never seen, but it read 40%, over
    three times its 10%: kept, not full. The second went in on a
    replacement Device Sentinel saw, ran 9 weeks, went silent and was
    replaced: its curve replaces the first, full, ended as ran out."""
    _entry, coord, device, record = await _house(hass)
    coord.page_set_power(device.id, "AAA", 2)
    _first_seen(record, 100)
    first = dt_util.now().date() - timedelta(days=80)
    second = [100.0 - i * 1.5 for i in range(64)]
    await _run(coord, record, device.id, [40, 39, 38, 37, 100, 100], first)
    # The person confirms the new battery, so its start is seen.
    coord.battery_answer(device.id, "confirm")
    await _run(coord, record, device.id, second, first + timedelta(days=6))
    first_curve = coord.data[DATA_BATTERY_CURVES][device.id]
    assert first_curve["good"] is True and first_curve["full"] is False, (
        "a battery whose start was not seen keeps its curve when it reaches back to three times its threshold"
    )
    # Silent for three days, then a new cell.
    from .test_battery_last_replaced import _fold

    gone = first + timedelta(days=6 + len(second))
    for i in range(3):
        # Midnights with nothing heard: the device's last report stays put.
        coord._folding_day = gone + timedelta(days=i)
        coord._roll_battery(record, device.id)
    coord._folding_day = None
    _fold(coord, record, device.id, [100.0, 100.0], gone + timedelta(days=3))
    lives = coord.data[DATA_BATTERY_LIVES]
    assert len(lives) == 2
    curve = coord.data[DATA_BATTERY_CURVES].get(device.id)
    assert curve is not None and curve_ok(curve)
    assert curve["start_seen"] is True and curve["full"] is True and curve["battery_type"] == "AAA"
    assert curve["first_under"] is not None, "it crossed 10%"
    assert curve["ended"] == "ran_out" and curve["from_week"] is not None
    assert len(curve["tail"]) <= 42
    assert len(curve["weeks"]) >= 9
    view = coord.battery_curves_view()
    assert [(m["curves"], m["full"]) for m in view["models"]] == [(1, 1)]
    assert view["models"][0]["levels_before_end"][0][0] == 0, "weeks counted back from the end"
    assert "Hall Motion" not in str(view), "names stay out of the download"


async def test_cancel_takes_the_curve_back(hass: HomeAssistant):
    _entry, coord, device, record = await _house(hass)
    coord.data.setdefault(DATA_BATTERY_CURVES, {})[device.id] = {"stamp": "2026-11-20T10:00:00+00:00"}
    coord.battery_curve_withdrawn(device.id, "2026-11-19T10:00:00+00:00")
    assert device.id in coord.data[DATA_BATTERY_CURVES], "another replacement's curve stays"
    coord.battery_curve_withdrawn(device.id, "2026-11-20T10:00:00+00:00")
    assert device.id not in coord.data[DATA_BATTERY_CURVES]


def test_the_history_file_keeps_them_whole():
    week = ["2026-11-16", "2026-07-18", 12.0, 10.5, 13.0, None, None, 3500, None]
    data = {
        DATA_DEVICES: {},
        DATA_BATTERY_WEEKS: {"dev": [week]},
        DATA_BATTERY_CURVES: {},
    }
    view, part = history_file.split(data)
    assert DATA_BATTERY_WEEKS not in view and part[DATA_BATTERY_WEEKS] == {"dev": [week]}
    assert not history_file.is_empty(part)
    payload = {"generation": 3, **part}
    assert history_file.check_payload(payload) is None
    loaded = {DATA_DEVICES: {}}
    history_file.join(loaded, payload)
    assert loaded[DATA_BATTERY_WEEKS] == {"dev": [week]}
    bad = {"generation": 3, DATA_BATTERY_WEEKS: {"dev": [["2026-11-16", "x"]]}}
    assert history_file.check_payload(bad) is not None, "a damaged week refuses the copy"


def test_a_damaged_week_or_curve_is_found():
    assert not week_row_ok(["2026-11-16", "2026-07-18", 120.0, 10.0, 13.0, None, None, None, None])
    assert not week_row_ok(["2026-11-16", "2026-07-18", 12.0, 13.0, 11.0, None, None, None, None])
    assert not curve_ok({"device_id": "d"})
    assert not curve_ok({"device_id": "d", "start": "2026-01-01", "end": "2026-02-01", "last_heard": "2026-02-01",
                         "start_seen": True, "good": True, "full": "yes"})
    faults = check_storage({DATA_BATTERY_CURVES: {"d": {"device_id": "d"}}})
    assert faults and DATA_BATTERY_CURVES in str(faults[0])


async def test_a_battery_first_seen_low_keeps_no_curve(hass: HomeAssistant):
    """Seen first at 25%, under three times an alkaline 10%: nothing from
    where a time left begins, so no curve."""
    _entry, coord, device, record = await _house(hass)
    coord.page_set_power(device.id, "AA", 2)
    _first_seen(record, 30)
    first = dt_util.now().date() - timedelta(days=20)
    await _run(coord, record, device.id, [25, 24, 23, 22, 100, 100], first)
    assert len(coord.data[DATA_BATTERY_LIVES]) == 1
    assert device.id not in (coord.data.get(DATA_BATTERY_CURVES) or {})


async def test_a_full_curve_is_not_given_up_for_a_shorter_one(hass: HomeAssistant):
    _entry, coord, device, record = await _house(hass)
    table = coord.data.setdefault(DATA_BATTERY_CURVES, {})
    table[device.id] = {"stamp": "a", "full": True, "good": True}
    coord._curve_of = lambda *_args: {"stamp": "b", "full": False, "good": True}
    import custom_components.device_sentinel.battery_curves as module

    real = module.curve_ok
    module.curve_ok = lambda _curve: True
    try:
        coord.battery_curve_ended(device.id, record, [])
        assert table[device.id]["stamp"] == "a", "the full curve stays"
        coord._curve_of = lambda *_args: {"stamp": "a", "full": False, "good": True}
        coord.battery_curve_ended(device.id, record, [])
        assert table[device.id]["full"] is False, "made again for its own replacement, it is replaced"
        coord._curve_of = lambda *_args: {"stamp": "c", "full": True, "good": True}
        coord.battery_curve_ended(device.id, record, [])
        assert table[device.id]["stamp"] == "c", "a newer full curve replaces"
    finally:
        module.curve_ok = real


async def test_a_replacement_taken_back_leaves_no_second_copy_of_its_weeks(hass: HomeAssistant):
    """A replacement detected and then cancelled: the weeks it started are
    worked out again under the battery that never left, once each."""
    _entry, coord, device, record = await _house(hass)
    coord.page_set_power(device.id, "AAA", 2)
    first = dt_util.now().date() - timedelta(days=40)
    await _run(coord, record, device.id, [60.0 - i * 0.2 for i in range(20)], first)
    from .test_battery_last_replaced import _fold

    # A jump read as a new battery, folded for a while, then cancelled.
    _fold(coord, record, device.id, [100.0, 100.0], first + timedelta(days=20))
    coord.battery_weeks_fold()
    assert len({row[1] for row in coord.data[DATA_BATTERY_WEEKS][device.id]}) == 2
    coord.battery_answer(device.id, "cancel")
    coord.battery_weeks_fold()
    weeks = coord.data[DATA_BATTERY_WEEKS][device.id]
    starts = [row[0] for row in weeks]
    assert len(starts) == len(set(starts)), "each week once"
    assert len({row[1] for row in weeks}) == 1, "one battery"
