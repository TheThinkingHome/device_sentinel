# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_long_durations.py, Version: 0.23.19 (2026-09-30)

"""Figures a person can read: long spans, a running silence, a scale.

Hours carried past the point of meaning. A battery flat since July
read 1485.3h in one report and 61.9d in another. A silence truncated
by the nightly reboot showed 8.22h and 11.13h in two columns and its
real 19.3h in none. A vibration sensor that left the house for six
weeks gave its rhythm chart an axis of 1032 hours, against a rhythm of
1.6, so every ordinary day lay flat on the floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_EPISODES,
    DEV_DAILY_MAX,
    EP_AT,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_NAME,
    EP_SINCE,
)
from custom_components.device_sentinel.durations import long_span

from .helpers import register_device, setup_coordinator

PANEL = (
    Path(__file__).parents[1]
    / "custom_components" / "device_sentinel" / "frontend" / "panel.js"
)
HOUR = 3600.0
DAY = 86400.0


@pytest.mark.parametrize(
    ("hours", "said"),
    [
        (48, "2 days"),
        (60, "2 and a half days"),
        (72, "3 days"),
        (240, "10 days"),
        (252, "a week and a half"),  # ten and a half days, where weeks begin
        (264, "a week and a half"),  # rounded down, the owner's rule
        (336, "2 weeks"),
        (432, "2 and a half weeks"),
        (1032, "6 weeks"),           # the vibration sensor's absence
        (1485.3, "8 and a half weeks"),  # the battery flat since July
    ],
)
def test_a_long_span_reads_in_days_then_weeks(hours: float, said: str):
    assert long_span(hours * HOUR) == said


def test_the_panel_says_the_same_words():
    """The dashboard and the reports word a duration the same way."""
    text = PANEL.read_text(encoding="utf-8")
    assert "halves(seconds / (7 * 86400), \"week\")" in text
    assert "a ${noun} and a half" in text
    assert "and a half ${noun}s" in text


async def test_a_report_reads_a_long_duration_in_words(hass: HomeAssistant):
    device, _entities = register_device(hass, "d1", name="Watering Kit")
    coord = await setup_coordinator(hass)
    assert coord._human_span(62 * DAY) == "8 and a half weeks"
    assert coord._human_span(17.4 * HOUR) == "17.4h"
    assert coord._episode_duration(43 * DAY) == "6 weeks"
    assert coord._episode_duration(9 * HOUR) == "9.0h"


async def test_a_running_silence_shows_the_whole_silence(hass: HomeAssistant):
    """The truncated lower bound said nothing useful; the total does."""
    device, _entities = register_device(hass, "d2", name="Watering Kit")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_EPISODES] = [{
        EP_DEVICE_ID: device.id, EP_NAME: "Watering Kit",
        EP_SINCE: now - 19.3 * HOUR, "basis": 540.0, "window": 2290.0,
        EP_ENDED: "intervention (reboot)", EP_AT: now - 11.13 * HOUR,
        EP_LAG: None, "learned": None, "taint_seconds": None, "signal": None,
    }]
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = Path(
        hass.config.path("device_sentinel", "silence_episodes.md")
    ).read_text(encoding="utf-8")
    row = [line for line in text.splitlines() if "Watering Kit" in line][0]
    assert "| 19.3h |" in row, row
    assert "not yet, 11.1h since the reboot" in row, row
    assert "8.17h" not in row, "the truncated lower bound is gone"

    page = coord.dashboard_device(device.id)
    assert round(page["silences"][0]["silence_total"] / HOUR, 1) == 19.3


async def test_a_resumed_silence_keeps_its_own_length(hass: HomeAssistant):
    device, _entities = register_device(hass, "d3", name="Door Entryway")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_EPISODES] = [{
        EP_DEVICE_ID: device.id, EP_NAME: "Door Entryway",
        EP_SINCE: now - 5 * HOUR, "basis": 540.0, "window": 2290.0,
        EP_ENDED: "resumed", EP_AT: now - 3 * HOUR,
        EP_LAG: None, "learned": "yes", "taint_seconds": None, "signal": None,
    }]
    await hass.async_add_executor_job(coord._write_reports, "test")
    row = [
        line
        for line in Path(
            hass.config.path("device_sentinel", "silence_episodes.md")
        ).read_text(encoding="utf-8").splitlines()
        if "Door Entryway" in line
    ][0]
    assert "| 2.0h |" in row, row
    assert "still silent" not in row


async def test_a_rhythm_chart_is_scaled_to_what_can_be_read(hass: HomeAssistant):
    """The absence stays in the history and out of the scale."""
    device, _entities = register_device(hass, "d4", name="Vibration FJ40")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    ordinary = [1.4 * HOUR] * 20
    record[DEV_DAILY_MAX] = [*ordinary[:10], 43 * DAY, *ordinary[10:]]
    page = coord.dashboard_device(device.id)
    scale = page["rhythm"]["scale"]
    window = page["status"]["window"]
    assert scale is not None and scale < 4 * HOUR, scale
    assert scale >= window, (scale, window)
    assert 43 * DAY in page["rhythm"]["daily"], "the absence is still recorded"


def test_the_chart_draws_a_day_beyond_the_scale_at_the_top():
    text = PANEL.read_text(encoding="utf-8")
    assert "page.rhythm.scale" in text
    assert "a day beyond the scale, drawn at the top." in text


def test_the_compact_format_at_every_boundary():
    """Ruling #546: seconds below ninety, minutes below ninety, hours
    below two days, days below two weeks, then weeks."""
    from custom_components.device_sentinel.durations import compact_span

    assert compact_span(0) == "0s"
    assert compact_span(45) == "45s"
    assert compact_span(89) == "89s"
    assert compact_span(90) == "2m"
    assert compact_span(1062) == "18m"
    assert compact_span(90 * 60) == "1.5h"
    assert compact_span(2 * 86400) == "2.0d"
    assert compact_span(14 * 86400) == "2.0w"
    assert compact_span(30 * 86400, cap=30 * 86400) == "more than 30 days"
    assert compact_span(float("nan")) == "?"


def test_the_one_compact_format_at_its_boundaries():
    """Ruling #546: seconds below ninety, then minutes below ninety,
    hours below two days, days below two weeks, then weeks; "more than"
    at a cap; unknown for what is not a number."""
    from custom_components.device_sentinel.durations import compact_span

    cases = {
        0: "0s", 22: "22s", 89: "89s", 90: "2m", 1062: "18m",
        89 * 60: "89m", 90 * 60: "1.5h", 4 * 3600: "4.0h",
        2 * 86400: "2.0d", 5.5 * 86400: "5.5d", 14 * 86400: "2.0w",
        42.9 * 86400: "6.1w", -5: "0s",
    }
    for seconds, shown in cases.items():
        assert compact_span(seconds) == shown, (seconds, compact_span(seconds))
    assert compact_span(200 * 86400, cap=180 * 86400) == "more than 180 days"
    assert compact_span(float("nan")) == "?"
