# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_margin.py, Version: 0.10.13 (2026-08-01)

"""The margin above the floor, and why it exists.

Until 0.10.13 the floor was the line: a reading counted as weak only
at or under it. The fleet showed the limit of that. Across 84 devices
and 21 days, 82 percent of device-days recorded exactly zero dwell,
and the reason is structural rather than a happy mesh: the floor is
the (k+1)th lowest of the device's own recent minima, so the share of
days that reach it is set by the arithmetic, near (k+1)/14, whatever
the radio is doing.

Moving the anomaly trim cannot fix that, because it only chooses a
different historical day to call the floor. Replayed against the
fleet's own daily minima, the trim spans 7 percent of days at its
calmest to 38 percent at its deepest, and the great majority of days
still read exactly zero at every setting.

A margin above the floor breaks the self-reference. A link that
hovers just above its own baseline all day registers dwell where it
used to register nothing, so a slow degradation shows as a rising
number instead of staying silent until it crosses a line.

The formula is floor + pct * abs(floor). The absolute value is the
part that matters and the part that is easy to get wrong: LQI runs 0
to 255 upward while RSSI is negative dBm, so a naive percentage
inverts the setting on every RSSI device. That case has its own test
below.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_SIGNAL_ANOMALY_TRIM,
    CONF_SIGNAL_MARGIN,
    DEFAULT_SIGNAL_MARGIN,
    DEV_SIGNAL_DAILY_MIN,
    SIGNAL_MARGIN_MAX,
)

from .helpers import setup_coordinator

# Fourteen days, so the trim ladder is at its fortnight rung and the
# floor is the third lowest. LQI values from the development fleet's
# mid-strength devices.
LQI_DAYS = [100.0, 104.0, 108.0, 112.0, 116.0, 120.0, 124.0] * 2
RSSI_DAYS = [-60.0, -62.0, -64.0, -66.0, -68.0, -70.0, -72.0] * 2


def _record(days):
    return {DEV_SIGNAL_DAILY_MIN: list(days)}


async def test_zero_margin_is_the_floor_itself(hass: HomeAssistant):
    """The setting can be turned off, and off is what shipped before.

    This is what makes the change safe to deploy: an install that
    slides it to zero behaves exactly as 0.10.12 did.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    line = coord._danger_line(_record(LQI_DAYS))

    assert line == 104.0


async def test_the_margin_lifts_the_line_above_the_floor(
    hass: HomeAssistant
):
    """Five percent of a floor of 104 is 5.2, so the line is 109.2.

    A device sitting at 108, comfortably above its floor and invisible
    before, now counts as weak.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 5})
    line = coord._danger_line(_record(LQI_DAYS))

    assert line == pytest.approx(109.2)
    assert 108.0 <= line


async def test_rssi_moves_the_same_way_as_lqi(hass: HomeAssistant):
    """The inversion this formula exists to avoid.

    RSSI is negative dBm, so a floor of -70 times 1.05 is -73.5, which
    is worse signal: the setting would mean the opposite thing on
    every RSSI device, and 11 of the development fleet's 84 tracked
    signals are RSSI. Adding a percentage of the absolute value moves
    the line up toward zero, which is the same direction as LQI.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 5})
    line = coord._danger_line(_record(RSSI_DAYS))
    floor = -70.0

    assert line > floor
    assert line == pytest.approx(floor + 0.05 * 70.0)


async def test_the_margin_scales_with_the_device(hass: HomeAssistant):
    """Ruled deliberately: a strong link can absorb larger swings.

    The same percentage is a wider band on a strong device than on a
    weak one. Recorded as a test rather than left implicit, because it
    is the consequence most likely to be questioned later.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 5})
    strong = coord._danger_line(_record([200.0] * 14))
    weak = coord._danger_line(_record([40.0] * 14))

    assert strong - 200.0 == pytest.approx(10.0)
    assert weak - 40.0 == pytest.approx(2.0)


async def test_the_default_is_five_percent(hass: HomeAssistant):
    """An install that sets nothing gets the ruled default.

    Chosen from the fleet replay: five percent moves nonzero-dwell
    days from 22.5 to 30.8 percent and brings seven more devices into
    range, where ten percent reaches 41.6 percent and describes
    ordinary life rather than trouble.
    """
    coord = await setup_coordinator(hass)

    assert coord._signal_margin() == DEFAULT_SIGNAL_MARGIN / 100.0
    assert coord._danger_line(_record(LQI_DAYS)) == pytest.approx(109.2)


@pytest.mark.parametrize("value,expected", [(-5, 0.0), (99, 0.10)])
async def test_an_out_of_band_margin_is_clamped(
    hass: HomeAssistant, value, expected
):
    """A hand-edited entry cannot widen the band past its maximum."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: value})

    assert coord._signal_margin() == pytest.approx(expected)
    assert SIGNAL_MARGIN_MAX == 10


async def test_the_two_settings_are_independent(hass: HomeAssistant):
    """Trim moves the floor, margin moves the line above it.

    With the trim one rung deeper the floor moves up a place in the
    series, and the margin is then taken from the new floor rather
    than from where the floor used to be.
    """
    days = [float(100 + 4 * i) for i in range(14)]
    normal = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 5})
    deeper = await setup_coordinator(
        hass, {CONF_SIGNAL_ANOMALY_TRIM: 1, CONF_SIGNAL_MARGIN: 5}
    )

    # Third lowest is 108, fourth is 112: the trim alone moves the
    # floor, and the margin rides on whichever floor it lands on.
    assert normal._danger_line(_record(days)) == pytest.approx(108.0 * 1.05)
    assert deeper._danger_line(_record(days)) == pytest.approx(112.0 * 1.05)


async def test_no_history_still_has_no_line(hass: HomeAssistant):
    """The margin does not invent a line where there is no floor.

    A device whose whole history is rail has no floor at all rather
    than a false one, and multiplying nothing by a percentage must not
    change that.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 5})

    assert coord._danger_line(_record([])) is None


@pytest.mark.parametrize(
    "value,word",
    [(-2, "None"), (-1, "Light"), (0, "Normal"), (1, "Deep"), (2, "Deepest")],
)
async def test_the_trim_renders_as_a_word(
    hass: HomeAssistant, value, word
):
    """The report header names the trim depth.

    The earlier words ran Calm to Sensitive, and the last of them
    collided with the Sensitivity setting added beside it in 0.10.13,
    which is a different control entirely.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_ANOMALY_TRIM: value})

    assert coord._signal_trim_label() == word
