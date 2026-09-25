# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_badday.py, Version: 0.23.5 (2026-09-25)

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
import math
import os
import pathlib
import statistics
from fractions import Fraction

import pytest

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    REPORT_WWW_DIR,
    CONF_BADDAY_BASELINE_DAYS,
    CONF_BADDAY_DROP_LQI,
    CONF_BADDAY_SENSITIVITY,
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_SCALE,
    SIGNAL_SCALE_RSSI,
    BADDAY_BASELINE_DAYS_MAX,
    BADDAY_BASELINE_DAYS_MIN,
    BADDAY_SENSITIVITY_MAX,
    BADDAY_SENSITIVITY_MIN,
    DEFAULT_BADDAY_BASELINE_DAYS,
    DEFAULT_BADDAY_SENSITIVITY,
)
from custom_components.device_sentinel import detect_signal
from custom_components.device_sentinel.detect_signal import _spread

from .conftest import fleet_param
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


# 0.19.14: the signal report release (ruling #380).


def _mk(hass, count, prefix):
    """Register `count` signal devices and return them."""
    return [
        register_device(hass, f"{prefix}{index}", f"{prefix.upper()} {index}")[0]
        for index in range(count)
    ]


def _signal_page(hass):
    """Return the signal report as written to www."""
    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "signal_report.html"
    )
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ==================================================================
# The spread in floating point gives the exact answer (0.22.20).
# ==================================================================

_FLEETS = [
    fleet_param("reference", "device_sentinel.storage", id="reference"),
    fleet_param("second", "device_sentinel_storage.json", id="second"),
    fleet_param(
        "fourth", "device_sentinel_storage.json", id="fourth"
    ),
]


def test_the_spread_matches_exact_arithmetic():
    """Half steps on both scales, a flat run, and values with no exact
    binary form, each against the deviation worked in fractions."""
    for values in (
        [200.0, 201.5, 199.0, 200.5],
        [-71.5, -70.0, -74.5, -69.0, -72.0, -71.0, -70.5],
        [255.0] * 14,
        [0.1, 0.2, 0.3, 0.1],
        [12.0, 250.0, 131.5, 7.5, 64.0, 199.0],
    ):
        exact = math.sqrt(statistics.pvariance([Fraction(v) for v in values]))
        assert math.isclose(_spread(values), exact, rel_tol=1e-15, abs_tol=1e-15)


@pytest.mark.parametrize("path", _FLEETS)
async def test_the_spread_changes_no_judgment_on_a_fleet(
    hass: HomeAssistant, path, monkeypatch
):
    """Every stored day of every device, at the defaults and at both
    ends of the two sliders that shape the baseline, judged with the
    floating-point spread and with the exact one the release before
    used. No verdict, normal or fall may move, and no spread by more
    than rounding."""
    coord = await setup_coordinator(hass)
    devices = json.loads(path.read_text(encoding="utf-8"))["data"]["devices"]
    records = [r for r in devices.values() if r.get("signal_daily_p5")]
    judged = 0
    for days in (BADDAY_BASELINE_DAYS_MIN, DEFAULT_BADDAY_BASELINE_DAYS, BADDAY_BASELINE_DAYS_MAX):
        for sensitivity in (BADDAY_SENSITIVITY_MIN, DEFAULT_BADDAY_SENSITIVITY, BADDAY_SENSITIVITY_MAX):
            monkeypatch.setattr(coord, "_badday_baseline_days", lambda d=days: d)
            monkeypatch.setattr(coord, "_badday_sensitivity", lambda s=sensitivity: s)
            for record in records:
                for index in range(len(record["signal_daily_p5"])):
                    fast = coord.signal_badday(record, index)
                    monkeypatch.setattr(detect_signal, "_spread", statistics.pstdev)
                    exact = coord.signal_badday(record, index)
                    monkeypatch.setattr(detect_signal, "_spread", _spread)
                    if exact is None:
                        assert fast is None
                        continue
                    judged += 1
                    assert fast["bad"] == exact["bad"]
                    assert fast["baseline"] == exact["baseline"]
                    assert fast["fall"] == exact["fall"]
                    assert math.isclose(fast["spread"], exact["spread"], rel_tol=1e-15)
    # A house younger than the baseline has no day to judge yet: the
    # fourth fleet held four days when captured. Anything older must
    # have judged a good many.
    longest = max((len(r["signal_daily_p5"]) for r in records), default=0)
    if longest > DEFAULT_BADDAY_BASELINE_DAYS:
        assert judged > 1000
