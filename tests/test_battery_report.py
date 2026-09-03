# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_report.py, Version: 0.19.14 (2026-09-03)

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

from unittest.mock import patch

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
    # The names sit in a two-column table now rather than a wall of
    # prose (ruling #379), so the cell and its level are separate.
    assert "<td>Motion Hall</td><td>100%</td>" in page


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

    assert "<td>LUX Outdoors</td><td>186%</td>" in page
    assert "raw sensor reading rather than a valid battery level" in page


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
    assert row["left"] == "about a month"
    assert row["device_id"] == soon.id


async def test_the_report_is_written_whole_or_not_at_all(
    hass: HomeAssistant,
):
    """Ruling #208. A report opened directly leaves a truncated file
    if the write is interrupted, and a dashboard card would show half
    a page. Every report is written beside its destination and moved
    onto it, which is atomic on one filesystem.

    Nothing is lost either way, because reports regenerate. What this
    buys is that the file on disk is always a whole report.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "aw1", "Atomic Cell")
    _seed(coord, device.id, HEALTHY, 82.0)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    before = _page(hass)

    def _boom(path, text):
        raise OSError("disk full")

    with patch.object(type(coord), "_write_file", staticmethod(_boom)):
        with pytest.raises(OSError):
            await hass.async_add_executor_job(
                coord._write_reports, "manual"
            )

    # The previous whole report is still there, not a fragment.
    assert _page(hass) == before
    # And no temporary file is left lying beside it.
    directory = hass.config.path(REPORT_WWW_DIR)
    assert not [n for n in os.listdir(directory) if n.endswith(".tmp")]


async def test_an_interrupted_write_leaves_no_fragment(
    hass: HomeAssistant,
):
    """The helper itself, on a write that fails part way."""
    coord = await setup_coordinator(hass)
    directory = hass.config.path(REPORT_WWW_DIR)
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


async def test_the_page_names_the_settings_that_govern_it(
    hass: HomeAssistant,
):
    """A reader who wants fewer rows must be able to find the slider.

    The footer said "the low threshold", which described the setting
    rather than naming it, and stopped naming anything at all when
    the label became Low Battery Threshold in 0.15.0. The Falling
    table never named the setting that decides who appears in it.
    Both now name the setting and the screen, the way the dwell
    chart's footer already did.
    """
    coord = await setup_coordinator(hass)
    dying, _ = register_device(hass, "bat1", "Door 2nd Bedroom")
    _seed(coord, dying.id, DYING, 12.0, low=True,
          since="2026-08-03T06:41:02+00:00")

    await hass.async_add_executor_job(coord._write_reports, "manual")
    # The template wraps its prose, so a phrase can span a newline.
    # HTML does not care and neither should the assertion.
    page = " ".join(_page(hass).split())

    # Each section names the setting that governs it, beneath its own
    # table, rather than one footer naming all of them (ruling #379).
    assert (
        "<b>Low Battery Threshold</b>, on the Low Battery settings "
        "screen" in page
    )
    assert (
        "<b>Days Till Empty Warning</b> setting, on the Low Battery "
        "settings screen" in page
    )
    # The description that named nothing is gone.
    assert "the low threshold on the Low Battery" not in page


# 0.19.13: the battery report release (ruling #379).


async def test_the_steady_table_columns_are_equal(hass: HomeAssistant):
    """Split by count, not by level, so the columns are the same
    height whatever the data does (ruling #379).

    An odd count puts the extra entry in the earlier column, and the
    short column is padded so the table stays rectangular.
    """
    coord = await setup_coordinator(hass)
    for index in range(7):
        device, _ = register_device(hass, f"col{index}", f"Cell {index}")
        _seed(coord, device.id, STEADY, 60.0 + index)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "<th>DEVICE</th><th>LEVEL</th><th>DEVICE</th><th>LEVEL</th>" in page
    # Seven cells become four rows: four left, three right, with the
    # last right-hand pair blank.
    assert "<td></td><td></td></tr>" in page
    # Reading order is down the first column, so the lowest level
    # leads the left and the split falls after the fourth.
    assert "<td>Cell 0</td><td>60%</td><td>Cell 4</td><td>64%</td>" in page


async def test_the_no_battery_list_names_the_devices(
    hass: HomeAssistant,
):
    """The count and the list come from one source, so the page can
    never name a different number than it shows (ruling #379)."""
    coord = await setup_coordinator(hass)
    register_device(hass, "mains1", "Switch Kitchen")
    register_device(hass, "mains2", "Switch Laundry")
    coord._rebuild_registry_view()

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "watched device(s) report no battery." in page
    assert "<td>Switch Kitchen</td>" in page
    assert "<td>Switch Laundry</td>" in page
    assert "These devices report no battery level." in page


async def test_the_footer_carries_only_what_a_footer_can_say(
    hass: HomeAssistant,
):
    """The projection caution and the threshold pointer moved to the
    sections they belong to, so the footer no longer repeats them
    (ruling #379)."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "foot1", "Door 2nd Bedroom")
    _seed(coord, device.id, DYING, 12.0, low=True)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = " ".join(_page(hass).split())
    footer = page[page.index("<footer>"):]

    assert "Regenerate Reports" in footer
    assert "<code>" in footer
    assert "The Battery Report" in footer
    # What left the footer.
    assert "holds a level for most of its life" not in footer
    assert "Low Battery Threshold" not in footer
    assert "projection" not in footer


def _bank(hass, count, prefix):
    """Register `count` battery devices and return them."""
    return [
        register_device(hass, f"{prefix}{index}", f"{prefix.upper()} Cell {index}")[0]
        for index in range(count)
    ]


def _counted_and_shown(page, heading, stop, pattern, pairs):
    """Return what a section claims and what it shows.

    Ruling #379 put the count and the list in one source so a page can
    never claim a different number than it shows. That is only true
    while something checks it, and at scale is where it would break.
    """
    block = page[page.index(heading):page.index(stop)]
    found = re.search(pattern, block)
    if found is None:
        # An empty section prints "None." and claims no number, which
        # is a section that cannot disagree with itself.
        return None, None
    counted = int(found.group(1))
    rows = re.findall(r"<tr><td>.*?</tr>", block)
    step = 2 if pairs else 1
    shown = sum(
        1
        for row in rows
        for cell in re.findall(r"<td>(.*?)</td>", row)[::step]
        if cell.strip()
    )
    return counted, shown


async def test_a_bank_of_five_hundred_cells_stays_legible(
    hass: HomeAssistant,
):
    """Ten times the reference fleet, every cell steady.

    The failure this looks for is the count and the list parting
    company once the list is long, and the two columns drifting out of
    balance when the split has hundreds of rows to make.
    """
    devices = _bank(hass, 500, "big")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    for index, device in enumerate(devices):
        level = float(40 + (index % 60))
        _seed(coord, device.id, [level] * 10, level)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    counted, shown = _counted_and_shown(
        page, "<h2>Steady</h2>", "<h2>Unreadable</h2>",
        r"(\d+) cell\(s\) holding steady", True,
    )
    assert counted == 500, counted
    assert shown == counted, (counted, shown)

    block = page[page.index("<h2>Steady</h2>"):page.index("<h2>Unreadable</h2>")]
    rows = re.findall(r"<tr><td>.*?</tr>", block)
    left = sum(
        1 for row in rows
        if re.findall(r"<td>(.*?)</td>", row)[0].strip()
    )
    right = sum(
        1 for row in rows
        if len(re.findall(r"<td>(.*?)</td>", row)) > 2
        and re.findall(r"<td>(.*?)</td>", row)[2].strip()
    )
    assert abs(left - right) <= 1, (left, right)


async def test_a_bank_falling_off_a_cliff(hass: HomeAssistant):
    """Sixty cells dropping fast, one already at zero.

    The page must not print an impossible percentage, and the sections
    that claim a count must still show that many when most of the bank
    is in trouble at once.
    """
    devices = _bank(hass, 60, "cliff")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    for index, device in enumerate(devices):
        level = max(0.0, 90.0 - index * 1.5)
        _seed(
            coord, device.id,
            [level + step * 2.0 for step in range(9, -1, -1)],
            level,
            low=level <= 10.0,
            since="2026-08-30T06:00:00+00:00" if level <= 10.0 else None,
        )

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    assert "<h2>Falling</h2>" in page
    assert "<h2>Under the Threshold</h2>" in page
    levels = [int(value) for value in re.findall(r"<td>(\d+)%</td>", page)]
    assert levels, "no levels rendered"
    assert min(levels) >= 0 and max(levels) <= 100, (min(levels), max(levels))

    counted, shown = _counted_and_shown(
        page, "<h2>Steady</h2>", "<h2>Unreadable</h2>",
        r"(\d+) cell\(s\) holding steady", True,
    )
    assert shown == counted, (counted, shown)
    # Every cell is falling here, so Steady is empty and claims
    # nothing, which is the one state where there is no count to check.
    assert counted is None or counted > 0


async def test_a_bank_of_raw_scales_never_reads_as_healthy(
    hass: HomeAssistant,
):
    """Ten devices reporting a raw scale above 100.

    They belong in Unreadable, and must never be counted among the
    healthiest cells in the bank because their number is the largest.
    """
    devices = _bank(hass, 10, "lux")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    for index, device in enumerate(devices):
        level = 150.0 + index
        _seed(coord, device.id, [level] * 10, level)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)

    block = page[
        page.index("<h2>Unreadable</h2>"):page.index("<h2>No Battery Reported</h2>")
    ]
    named = [
        cell for cell in re.findall(r"<td>(.*?)</td>", block)
        if cell.strip() and "%" not in cell
    ]
    assert len(named) == 10, len(named)
    assert "holding steady" not in block
