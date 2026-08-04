# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_report.py, Version: 0.11.2 (2026-08-03)

"""The battery report (ruling #194).

A threshold answers which cells are low. This page answers which are
going to be. The shapes below are taken from the reference fleet on
2026-08-03, including the cell that motivated it: ten days flat at 32
percent, then a ten point drop and an eight and a half point rebound
on consecutive days, then a fall to 21.

Nothing here alarms, and one test pins that: no problem-list item and
no incident comes out of writing this page.
"""

from __future__ import annotations

import os
import re

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
    REPORT_BATTERY_HTML,
    REPORT_BATTERY_PREFIX,
    REPORT_WWW_DIR,
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


def _seed(coord, device_id, series, level, low=False, since=None):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_BATTERY_DAILY] = list(series)
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_LOW] = low
    record[DEV_BATTERY_SINCE] = since
    return record


def _page(hass) -> str:
    with open(
        os.path.join(hass.config.path(REPORT_WWW_DIR), REPORT_BATTERY_HTML),
        encoding="utf-8",
    ) as handle:
        return handle.read()


async def test_the_dying_cell_is_first_and_the_healthy_one_is_not(
    hass: HomeAssistant,
):
    """The whole point of the page in one assertion.

    Both cells are falling. One is at 12 percent losing 1.75 a day
    and has a week; the other is at 82 percent losing 1.4 and has two
    months. A rate alone cannot tell them apart, because their rates
    are within half a point of each other. Time remaining can.
    """
    coord = await setup_coordinator(hass)
    dying, _ = register_device(hass, "bat1", "Door 2nd Bedroom")
    healthy, _ = register_device(hass, "bat2", "Soil Moisture")
    _seed(coord, dying.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")
    _seed(coord, healthy.id, HEALTHY, 82.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert page.index("Door 2nd Bedroom") < page.index("Soil Moisture")
    assert "-1.75/day" in page
    # Words rather than a count, and widening with distance, because
    # the projection moves further the further out it reaches
    # (ruling #197).
    assert "<td style='color:#D03B3B'>under a week</td>" in page
    assert "<td>about 2 months</td>" in page
    assert ">7<" not in page
    assert ">59<" not in page


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


async def test_a_steady_cell_is_not_projected(
    hass: HomeAssistant,
):
    """A cell holds its level for most of its life and then falls, so
    steady is the healthy state rather than a stale reading. Half
    point rounding alone yields a slope of a few hundredths, and a
    lifetime projected from rounding runs to thousands of days.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat3", "Motion Hall")
    _seed(coord, device.id, STEADY, 100.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "holding steady" in page
    assert "Motion Hall 100%" in page


async def test_a_reading_above_100_is_called_unreadable(
    hass: HomeAssistant,
):
    """Seen on the fleet: an MQTT device reporting around 196 every
    day, a raw scale rather than a percentage. It can never cross the
    low threshold, and counted as a level it would sit at the top of
    the bank looking healthier than anything else.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat4", "LUX Outdoors")
    _seed(coord, device.id, [196.0] * 16, 186.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "LUX Outdoors reads 186%" in page
    assert "A percentage cannot be above 100" in page


async def test_a_device_with_no_battery_is_counted_not_listed_as_zero(
    hass: HomeAssistant,
):
    """A watched device with no battery entity is mains powered or
    has one switched off. Either way it is not a cell at zero.
    """
    coord = await setup_coordinator(hass)
    register_device(hass, "bat5", "Wired Thing")

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "report no battery" in page


async def test_the_page_raises_nothing(
    hass: HomeAssistant,
):
    """Ruling #194: the projection is shown and never pushed. It moved
    from twelve days to seven in an afternoon on the fleet, so until a
    soak says how far it swings the low threshold does the alarming
    and this page does not.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat6", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert coord.data[DATA_TODO_ITEMS] == []
    assert coord.data[DATA_INCIDENTS] == []


async def test_the_page_gets_a_dated_copy_and_a_stable_address(
    hass: HomeAssistant,
):
    """The one www rule (ruling #180): a dated record, an undated
    current copy at an address a dashboard card can keep, and the
    fourteen day trim.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bat7", "Leak Sink")
    _seed(coord, device.id, HEALTHY, 82.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")

    directory = hass.config.path(REPORT_WWW_DIR)
    dated = [
        name
        for name in os.listdir(directory)
        if name.startswith(REPORT_BATTERY_PREFIX)
    ]
    assert len(dated) == 1
    with open(os.path.join(directory, dated[0]), encoding="utf-8") as handle:
        assert handle.read() == _page(hass)


async def test_the_bank_chart_fits_inside_its_own_box(
    hass: HomeAssistant,
):
    """Found by reading the rendered page on the fleet: ten bands at
    50 wide on 14 gaps ran to 646 inside a 640 viewBox, so the top
    band was clipped, and the unit label sat directly on top of the
    last band's number.

    Geometry is arithmetic and can be checked, so it is.
    """
    coord = await setup_coordinator(hass)
    for index in range(10):
        device, _ = register_device(hass, f"bank{index}", f"Cell {index}")
        _seed(coord, device.id, [float(index * 10 + 5)] * 16,
              float(index * 10 + 5))

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    box = re.search(r"viewBox='0 0 (\d+) (\d+)'", page)
    assert box is not None
    width, height = int(box.group(1)), int(box.group(2))
    bars = [
        (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        for m in re.finditer(
            r"<rect x='(\d+)' y='(\d+)' width='(\d+)'", page
        )
    ]
    assert len(bars) == 10
    assert max(x + w for x, _y, w in bars) <= width
    # Every label sits inside the box, and the unit is on its own row
    # rather than on top of the last band's number.
    rows = {
        int(m.group(2)): m.group(3)
        for m in re.finditer(
            r"<text x='(\d+)' y='(\d+)'[^>]*>([^<]+)</text>", page
        )
    }
    assert "percent" in rows.values()
    unit_y = next(y for y, text in rows.items() if text == "percent")
    assert unit_y <= height
    band_label_rows = {
        int(m.group(1))
        for m in re.finditer(r"<text x='\d+' y='(\d+)'[^>]*>\d0</text>", page)
    }
    assert unit_y not in band_label_rows


async def test_the_brief_names_a_cell_that_is_nearly_out(
    hass: HomeAssistant,
):
    """Ruling #195. The report shipped in 0.11.1 with nothing pointing
    at it, so a person who did not know the file existed had no way
    to find it. The brief now names it, on the same footing as the
    dwell chart, with a full address rather than a bare path.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf1", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        ),
        encoding="utf-8",
    ) as handle:
        brief = handle.read()

    assert "Batteries falling: Door 2nd Bedroom (under a week)" in brief
    assert "<a href='http" in brief
    assert "the battery report</a>" in brief
    assert "href='/local/device_sentinel/battery_report.html'" not in brief


async def test_the_brief_leaves_out_what_nobody_can_act_on(
    hass: HomeAssistant,
):
    """A cell a season away belongs in the report and not in a
    document that arrives whether it was wanted or not. On the
    reference fleet the unfiltered list was sixteen devices.
    """
    coord = await setup_coordinator(hass)
    near, _ = register_device(hass, "brf2", "Nearly Out")
    far, _ = register_device(hass, "brf3", "Months Away")
    _seed(coord, near.id, DYING, 12.0)
    _seed(coord, far.id, HEALTHY, 82.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        ),
        encoding="utf-8",
    ) as handle:
        brief = handle.read()

    assert "Nearly Out" in brief
    assert "Months Away" not in brief
    # Both are still in the report, which is not filtered.
    assert "Months Away" in _page(hass)


async def test_a_cell_already_low_is_not_said_twice(
    hass: HomeAssistant,
):
    """It has a row in Now already. One document, one mention."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf4", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        ),
        encoding="utf-8",
    ) as handle:
        brief = handle.read()

    assert "Batteries falling" not in brief


async def test_a_quiet_fleet_adds_no_line(
    hass: HomeAssistant,
):
    """Nothing to say means nothing said, as the signal line does."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "brf5", "Motion Hall")
    _seed(coord, device.id, STEADY, 100.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        ),
        encoding="utf-8",
    ) as handle:
        assert "Batteries falling" not in handle.read()


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


async def test_the_horizon_is_the_persons_to_set(
    hass: HomeAssistant,
):
    """Days Till Empty, 7 to 30 (ruling #197). A cell two weeks out
    is named at thirty and silent at seven.
    """
    coord = await setup_coordinator(hass, {CONF_BATTERY_DAYS: 30})
    device, _ = register_device(hass, "hz1", "Two Weeks Out")
    # 20 percent falling 1.5 a day is a little over thirteen days.
    _seed(coord, device.id,
          [40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
           28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0], 20.0)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Two Weeks Out" in _brief(hass)

    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_BATTERY_DAYS: 7},
    )
    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Batteries falling" not in _brief(hass)
    # Still in the report, which lists everything falling.
    assert "Two Weeks Out" in _page(hass)


def _brief(hass) -> str:
    with open(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        ),
        encoding="utf-8",
    ) as handle:
        return handle.read()
