# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_badday.py, Version: 0.16.11 (2026-08-21)

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

from homeassistant.core import HomeAssistant

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
