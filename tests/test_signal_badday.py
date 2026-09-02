# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_badday.py, Version: 0.19.14 (2026-09-02)

"""The bad signal day detector (ruling #310).

A bad day is a fall in a device's own daily P5 against the median of
its recent days, far enough in the device's units and far enough in
its own spread, both gates together. The numbers here re-state the
gates' reasons: the absolute gate stops a trivial move on a steady
device reading as a catastrophe, and the spread gate stops a large
move on a jittery device reading as news.

The fixtures carry no cause fields and no dwell, because the
detector reads neither: the lesson of the stitch that shipped inert
was a rule reading a field the live journal never writes.
"""

from __future__ import annotations

import json
import pathlib
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    CONF_BADDAY_BASELINE_DAYS,
    CONF_BADDAY_DROP_LQI,
    CONF_BADDAY_SENSITIVITY,
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_SCALE,
    SIGNAL_SCALE_RSSI,
)

from .helpers import register_device, setup_coordinator

STEADY_WEEK = [160.0, 162.0, 158.0, 161.0, 160.0, 159.0]


async def test_a_fall_past_both_gates_is_a_bad_day(hass: HomeAssistant):
    """Sixty points below a tight week: both gates, plainly."""
    device, _ = register_device(hass, "bd1", "Falls Hard")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = STEADY_WEEK + [100.0]

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["bad"] is True
    assert reading["fall"] == 60.0
    assert reading["deviations"] > 4


async def test_a_large_fall_on_a_jittery_device_is_not_news(
    hass: HomeAssistant,
):
    """The spread gate. A device swinging 60 points a day falling 60
    points is having a normal day, and flagging it daily is the
    false-alarm engine the sensitivity slider exists to stop."""
    device, _ = register_device(hass, "bd2", "Jittery")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [200.0, 90.0, 180.0, 100.0, 190.0, 95.0, 110.0]

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["bad"] is False
    assert reading["deviations"] < 4


async def test_a_small_fall_on_a_steady_device_is_not_news(
    hass: HomeAssistant,
):
    """The absolute gate. A device holding within a point can fall
    ten and clear its spread many times over; without the floor in
    scale units, arithmetic would call a wobble a catastrophe."""
    device, _ = register_device(hass, "bd3", "Very Steady")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [160.0, 160.5, 160.0, 159.5, 160.0, 160.5, 150.0]

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["fall"] == 10.0
    assert reading["bad"] is False


async def test_an_rssi_device_is_judged_in_decibels(hass: HomeAssistant):
    """The gate is scale-native (ruling #310, following #250). A
    -60 dBm link losing 8 dB is a bad day at the 6 dB default; the
    25-point LQI gate would never fire on an RSSI scale at all."""
    device, _ = register_device(hass, "bd4", "Shade Motor")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_SCALE] = SIGNAL_SCALE_RSSI
    record[DEV_SIGNAL_DAILY_P5] = [-60.0, -61.0, -59.0, -60.0, -61.0, -60.0, -68.0]

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["drop_gate"] == 6.0
    assert reading["bad"] is True


async def test_too_little_history_is_not_judged(hass: HomeAssistant):
    """Three prior days cannot supply a spread worth dividing by, so
    the day is unjudged rather than misjudged. None, not False: the
    strip shows it blank instead of green."""
    device, _ = register_device(hass, "bd5", "Fresh Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [160.0, 161.0, 159.0, 100.0]

    assert coord.signal_badday(record) is None


async def test_a_flat_baseline_cannot_make_the_ratio_explode(
    hass: HomeAssistant,
):
    """The spread floor. A week at exactly 160 has spread zero, and
    without the floor a one-point dip would read as infinite
    deviations. With it, the deviations are the fall itself, and the
    absolute gate still rules."""
    device, _ = register_device(hass, "bd6", "Ruler Flat")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [160.0] * 6 + [130.0]

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["spread"] == 1.0
    assert reading["bad"] is True


async def test_the_sliders_move_the_gates(hass: HomeAssistant):
    """Each setting reaches the arithmetic it names."""
    device, _ = register_device(hass, "bd7", "Tunable")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = STEADY_WEEK + [130.0]

    assert coord.signal_badday(record)["bad"] is True

    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_BADDAY_DROP_LQI: 45},
    )
    assert coord.signal_badday(record)["bad"] is False

    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_BADDAY_DROP_LQI: 25,
            CONF_BADDAY_SENSITIVITY: 8.0,
        },
    )
    reading = coord.signal_badday(record)
    assert reading["deviations"] < 25
    assert reading["bad"] is (reading["deviations"] >= 8.0)


async def test_the_baseline_window_is_the_days_of_signal_history(
    hass: HomeAssistant,
):
    """The fourth slider. With the window at 4, a fall six days ago
    has aged out of the baseline and a lower level has become what is
    typical, so the same today reads unremarkable."""
    device, _ = register_device(hass, "bd8", "Short Memory")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = (
        [200.0, 201.0, 199.0, 200.0]
        + [130.0, 131.0, 129.0, 130.0, 131.0]
        + [128.0]
    )

    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_BADDAY_BASELINE_DAYS: 4},
    )
    short = coord.signal_badday(record)
    assert short["bad"] is False

    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_BADDAY_BASELINE_DAYS: 14},
    )
    remembered = coord.signal_badday(record)
    assert remembered["baseline"] > short["baseline"]


async def test_the_approved_slider_words_are_pinned(hass: HomeAssistant):
    """The four texts James approved on 21 August, verbatim.

    The config screen is a document with an author. A regenerated
    strings file that paraphrases these is wrong even where it is
    fluent, and the translations copy must match byte for byte, which
    the build gate also compares.
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    strings = json.loads((package / "strings.json").read_text())
    translated = json.loads(
        (package / "translations" / "en.json").read_text()
    )
    for source in (strings, translated):
        signal = source["options"]["step"]["signal"]
        assert signal["data"]["badday_drop_lqi"] == "Bad Day Drop, LQI"
        assert signal["data"]["badday_drop_rssi"] == "Bad Day Drop, RSSI"
        assert signal["data"]["badday_sensitivity"] == "Bad Day Sensitivity"
        assert (
            signal["data"]["badday_baseline_days"] == "Days of Signal History"
        )
        assert signal["data_description"]["badday_baseline_days"] == (
            "This setting defines how many past days are used to calculate "
            "what is typical for a device. Today's signal is compared "
            "against that typical level, and a fall below it, as set "
            "above, is flagged."
        )
        assert "signal_red_threshold" not in signal["data"]


async def test_the_strip_shows_only_devices_worth_a_look(
    hass: HomeAssistant,
):
    """Ruling #315, and Tim Plas's whole complaint about the page.

    He read the first version and said there was no chance he would
    read it daily: 79 rows, 74 of them entirely green, with the
    answer buried under a chart nobody asked a question of. A device
    now earns a row by having fallen three of its own spreads below
    its normal at some point in the window; the rest are named in a
    line and the full fleet stays behind a toggle.
    """
    coord = await setup_coordinator(hass)
    for index in range(9):
        device, _ = register_device(hass, f"q{index}", f"Quiet {index}")
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = [
            160.0, 161.0, 159.0, 160.0, 161.0, 160.0, 159.5,
        ]
    loud, _ = register_device(hass, "loud", "Fallen Device")
    coord.data[DATA_DEVICES][loud.id][DEV_SIGNAL_DAILY_P5] = (
        STEADY_WEEK + [100.0]
    )

    rows = coord._signal_report_rows()
    worth, quiet = coord._signal_strip_rows(rows)

    assert len(rows) == 10
    assert worth[0]["name"] == "Fallen Device"
    # The floor holds: a fleet with one fallen device still shows
    # enough rows to read a band against.
    assert len(worth) == 5
    assert len(quiet) == 5


async def test_a_fleet_wide_event_cannot_put_every_row_back(
    hass: HomeAssistant,
):
    """The ceiling. A broker outage drops everything at once, and a
    page of eighty rows is the page this ruling removed."""
    coord = await setup_coordinator(hass)
    for index in range(30):
        device, _ = register_device(hass, f"d{index}", f"Device {index}")
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = (
            STEADY_WEEK + [90.0]
        )

    rows = coord._signal_report_rows()
    worth, quiet = coord._signal_strip_rows(rows)

    assert len(rows) == 30
    assert len(worth) == 20
    assert len(quiet) == 10


async def test_each_row_carries_its_area(hass: HomeAssistant):
    """Shown even though it can mislead (ruling #315).

    The router unplugged on 18 August took devices in five different
    rooms, because a router serves by radio topology rather than by
    the room it sits in. The area is still a fact, and withholding a
    fact because it is not yet interpretable is how dwell came to
    measure against a line that moved.
    """
    device, _ = register_device(hass, "ar1", "Placed Device")
    areas = ar.async_get(hass)
    area = areas.async_get_or_create("Master Bedroom")
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = (
        STEADY_WEEK + [100.0]
    )

    rows = coord._signal_report_rows()

    assert rows[0]["area"] == "Master Bedroom"
    assert "Master Bedroom" in coord._signal_strip_svg(rows)


# 0.19.14: the signal report release (ruling #380).


def _signal_page(hass):
    """Return the signal report as written to www."""
    import os
    from custom_components.device_sentinel.const import REPORT_WWW_DIR

    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "signal_report.html"
    )
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def test_the_steady_devices_are_named(hass: HomeAssistant):
    """The count and the list come from one place, so the page can
    never say a different number than it shows (ruling #380)."""
    coord = await setup_coordinator(hass)
    for index in range(9):
        device, _ = register_device(hass, f"sq{index}", f"Quiet {index}")
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = [
            150.0 + index
        ] * 12

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _signal_page(hass)

    assert "<h2>Steady Signals</h2>" in page
    assert "stayed within their own normal." in page
    steady = page[page.index("<h2>Steady Signals</h2>"):]
    steady = steady[: steady.index("<h2>Devices That Had a Bad Day")]
    named = [
        cell
        for cell in re.findall(r"<td>(.*?)</td>", steady)
        if cell.strip()
    ]
    counted = int(
        re.search(r"(\d+) device\(s\) stayed within", steady).group(1)
    )
    assert len(named) == counted
    # The old line that counted without naming is gone.
    assert "and are not shown" not in page


async def test_the_page_reads_in_plain_words(hass: HomeAssistant):
    """The section heading, the legend and the help text carry no
    method, and the footer says only what a footer can (#380)."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "pw1", "Plain Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = [
        150.0
    ] * 12

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = " ".join(_signal_page(hass).split())

    assert "<h2>Signal Anomalies</h2>" in page
    assert "Devices Worth a Look" not in page
    # The legend names depths rather than spreads.
    assert "slightly below normal" in page
    assert "spreads below" not in page
    # The help text sits under its chart, not above it.
    assert page.index("Signal Anomalies") < page.index("<svg")
    assert page.index("<svg") < page.index("A vertical cluster of orange")
    assert "needs your attention" in page

    footer = page[page.index("<footer>"):]
    assert "Regenerate Reports" in footer
    assert "<code>" in footer
    assert "The Signal Report" in footer
    # What left the footer.
    assert "fifth percentile" not in footer
    assert "dwell chart" not in footer
    assert "Configure, Signal Strength" not in footer
    assert "alerts or joins the problem list" not in footer


async def test_a_bad_day_is_described_without_arithmetic(
    hass: HomeAssistant,
):
    """The biography says how far below normal in the legend's own
    words rather than in spreads (ruling #380)."""
    coord = await setup_coordinator(hass)

    assert coord._signal_depth_words(10.0) == "far below"
    assert coord._signal_depth_words(6.0) == "far below"
    assert coord._signal_depth_words(3.5) == "well below"
    assert coord._signal_depth_words(2.5) == "slightly below"
    assert coord._signal_depth_words(1.0) == "below"
