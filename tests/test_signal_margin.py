# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_margin.py, Version: 0.12.18 (2026-08-11)

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

The formula is floor + pct * (perfect - floor) + lift, with the
distance frozen at its dropout-point width for floors below dropout
(rulings #250, #252). Distance from perfect is what makes the wedge
point the right way on both scales: the old percentage-of-floor
measured distance from zero, and zero is dead on LQI but perfect on
RSSI, so the band was widest exactly on the fleet's strongest LQI
links. Anchors are the working band (LQI 50 to 255, RSSI -90 to
-20), because no working link lives at the scale ends.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    SIGNAL_ANOMALY_TRIM,
    SIGNAL_LIFT,
    SIGNAL_MARGIN,
    DEV_SIGNAL_DAILY_MIN,
)

from .helpers import setup_coordinator

# Fourteen days, so the trim ladder is at its fortnight rung and the
# floor is the third lowest. LQI values from the development fleet's
# mid-strength devices.
LQI_DAYS = [100.0, 104.0, 108.0, 112.0, 116.0, 120.0, 124.0] * 2
RSSI_DAYS = [-60.0, -62.0, -64.0, -66.0, -68.0, -70.0, -72.0] * 2


def _record(days):
    return {DEV_SIGNAL_DAILY_MIN: list(days)}


async def test_a_zero_margin_would_be_the_floor_itself(
    hass: HomeAssistant, monkeypatch
):
    """At zero the line is the floor, which is 0.10.12's behaviour.

    Held here as arithmetic rather than as a setting: ruling #311
    made the margin a constant, so the only way to ask this question
    is to ask the method. It still matters, because a future change
    to the anchored formula must not quietly acquire a margin the
    band does not justify.
    """
    coord = await setup_coordinator(hass)
    monkeypatch.setattr(coord, "_signal_margin", lambda: 0.0)

    assert coord._danger_line(_record(LQI_DAYS)) == 104.0


async def test_the_margin_lifts_the_line_above_the_floor(
    hass: HomeAssistant
):
    """Five percent of the headroom above a floor of 104 is 7.55.

    A device sitting at 108, comfortably above its floor and invisible
    before, now counts as weak.
    """
    coord = await setup_coordinator(hass)
    line = coord._danger_line(_record(LQI_DAYS))

    assert line == pytest.approx(104.0 + 0.05 * (255.0 - 104.0))
    assert 108.0 < line


async def test_rssi_moves_the_same_way_as_lqi(hass: HomeAssistant):
    """The inversion this formula exists to avoid.

    RSSI is negative dBm, so a floor of -70 times 1.05 is -73.5, which
    is worse signal: the setting would mean the opposite thing on
    every RSSI device, and 11 of the development fleet's 84 tracked
    signals are RSSI. Adding a percentage of the absolute value moves
    the line up toward zero, which is the same direction as LQI.
    """
    coord = await setup_coordinator(hass)
    line = coord._danger_line(_record(RSSI_DAYS))
    floor = -70.0

    assert line > floor
    assert line == pytest.approx(floor + 0.05 * (-20.0 - floor))


async def test_the_margin_points_at_the_weak_end(hass: HomeAssistant):
    """Ruling #250's whole point: the wedge narrows as links improve.

    The old percentage-of-floor gave the strong device the wide band
    (10 units at floor 200 against 2 at floor 40), which watched the
    fleet's best links hardest. Distance-from-perfect inverts that:
    the weak device gets the wide band, and below the dropout anchor
    the width holds at its dropout-point maximum rather than growing
    on toward the scale end.
    """
    coord = await setup_coordinator(hass)
    strong = coord._danger_line(_record([200.0] * 14))
    weak = coord._danger_line(_record([40.0] * 14))

    assert strong - 200.0 == pytest.approx(0.05 * 55.0)
    assert weak - 40.0 == pytest.approx(0.05 * 205.0)  # clamped at DEAD 50
    assert weak - 40.0 > strong - 200.0

async def test_the_line_dies_at_perfect(hass: HomeAssistant):
    """A floor of 255 gets no margin at all: line equals floor, and
    with dwell strictly below the line (ruling #251) a perfect link
    can never dwell. Before the anchoring, floor 242.86 and above put
    the five percent line at or past the top of the scale, so the
    whole remaining scale was inside the band."""
    coord = await setup_coordinator(hass)

    assert coord._danger_line(_record([255.0 - 6.0] * 14)) == pytest.approx(
        249.0 + 0.05 * 6.0
    )

async def test_the_lift_raises_every_line_flat(hass: HomeAssistant):
    """Ruling #252: the lift is purely additive, the same amount at
    every floor, surviving even where the margin has died, and capped
    at 2.0 because the fleet replay showed 5.0 re-flagging the
    strongest links the anchored formula had just freed."""
    flat = await setup_coordinator(hass)
    lifted = await setup_coordinator(hass)
    lifted._signal_lift = lambda: 1.0
    for days in ([40.0] * 14, [200.0] * 14, RSSI_DAYS):
        low = flat._danger_line(_record(days))
        high = lifted._danger_line(_record(days))
        assert high == pytest.approx(low + 1.0)
    assert flat._signal_lift() == SIGNAL_LIFT


async def test_the_default_is_five_percent(hass: HomeAssistant):
    """An install that sets nothing gets the ruled default.

    Chosen from the fleet replay: five percent moves nonzero-dwell
    days from 22.5 to 30.8 percent and brings seven more devices into
    range, where ten percent reaches 41.6 percent and describes
    ordinary life rather than trouble.
    """
    coord = await setup_coordinator(hass)

    assert coord._signal_margin() == SIGNAL_MARGIN / 100.0
    assert coord._danger_line(_record(LQI_DAYS)) == pytest.approx(
        104.0 + 0.05 * (255.0 - 104.0)
    )


async def test_the_three_line_shapers_ignore_saved_options(
    hass: HomeAssistant,
):
    """They are constants, not settings (ruling #311).

    Each was a slider until 0.16.12, and the sliders are gone from
    the Signal screen because the line they build no longer judges
    anything: dwell stopped reporting at ruling #310. A saved option
    left behind by an older install, or hand-edited into the entry,
    must not reach the arithmetic, and the values held are the ones
    that were the defaults, so a fleet on the defaults records what
    it recorded before.
    """
    stale = await setup_coordinator(
        hass,
        {
            "signal_margin": 9,
            "signal_lift": 2.0,
            "signal_sensitivity": 2,
        },
    )

    assert stale._signal_margin() == SIGNAL_MARGIN / 100.0
    assert stale._signal_lift() == SIGNAL_LIFT
    assert stale._signal_trim() == SIGNAL_ANOMALY_TRIM
    assert (SIGNAL_MARGIN, SIGNAL_LIFT, SIGNAL_ANOMALY_TRIM) == (5, 0.0, 0)
    # And the line those three build is the line the defaults built.
    fresh = await setup_coordinator(hass)
    assert stale._danger_line(_record(LQI_DAYS)) == fresh._danger_line(
        _record(LQI_DAYS)
    )

async def test_the_two_settings_are_independent(hass: HomeAssistant):
    """Trim moves the floor, margin moves the line above it.

    With the trim one rung deeper the floor moves up a place in the
    series, and the margin is then taken from the new floor rather
    than from where the floor used to be.
    """
    days = [float(100 + 4 * i) for i in range(14)]
    normal = await setup_coordinator(hass)
    deeper = await setup_coordinator(hass)
    deeper._signal_trim = lambda: 1

    # Third lowest is 108, fourth is 112: the trim alone moves the
    # floor, and the margin rides on whichever floor it lands on.
    assert normal._danger_line(_record(days)) == pytest.approx(
        108.0 + 0.05 * (255.0 - 108.0)
    )
    assert deeper._danger_line(_record(days)) == pytest.approx(
        112.0 + 0.05 * (255.0 - 112.0)
    )


async def test_no_history_still_has_no_line(hass: HomeAssistant):
    """The margin does not invent a line where there is no floor.

    A device whose whole history is rail has no floor at all rather
    than a false one, and multiplying nothing by a percentage must not
    change that.
    """
    coord = await setup_coordinator(hass)

    assert coord._danger_line(_record([])) is None


async def test_the_trim_renders_as_a_word(hass: HomeAssistant):
    """The report header names the trim depth.

    Only one word is reachable now that the trim is a constant
    (ruling #311), and the header must still carry it rather than a
    number: the report calls the per-device trim depth k, and the
    header showing a second k meant two different things wore one
    letter.
    """
    coord = await setup_coordinator(hass)

    assert coord._signal_trim_label() == "Normal"
    for depth, word in (
        (-2, "None"), (-1, "Light"), (1, "Deep"), (2, "Deepest")
    ):
        coord._signal_trim = lambda depth=depth: depth
        assert coord._signal_trim_label() == word


async def test_fleet_fixture_the_design_day_numbers(hass: HomeAssistant):
    """The 11 August simulation, pinned. Door Entryway (floor 220):
    the old formula put its line at 231.0, above almost every daily
    minimum it had ever recorded, and it read 19 percent dwell on an
    objectively superb link. The anchored line is 221.75. The
    dropout-zone clamp: a floor-36 night-light plug holds the full
    10.25-unit dropout-point margin rather than 10.95 and growing."""
    coord = await setup_coordinator(hass)

    entryway = coord._danger_line(_record([220.0] * 14))
    assert entryway == pytest.approx(220.0 + 0.05 * 35.0)
    assert entryway < 231.0

    night_light = coord._danger_line(_record([36.0] * 14))
    assert night_light == pytest.approx(36.0 + 0.05 * 205.0)
