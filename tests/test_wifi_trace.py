# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_trace.py, Version: 0.21.7 (2026-09-15)

"""A recorded outage, replayed through the shipped code.

On 14 September four defects were found by staging outages on real
hardware, after seven build gates and 1,702 constructed cases had
passed over every one of them. Three lived in the gaps between
moments: a constructed test lands its events in the same millisecond,
and twenty seconds cannot be expressed in it.

This replays the outage probe's own recording of 14 September 13:56,
at the offsets it actually happened: thirty trackers leaving from
fifteen seconds, sixteen devices going unavailable over the following
three minutes, the network returning at about 4,600 seconds, and the
devices behind it finishing their reconnection between 4,609 and
4,804.

The assertions are shapes rather than clock times. A settle length
that changes should not break these; a device reaching the problem
list during a recovery should.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from tests.trace_house import build, load_trace

TRACE = "reference_2026_09_14_1356.json"
ALL_TRACES = (
    "reference_2026_09_14_0917.json",
    "reference_2026_09_14_1111.json",
    "reference_2026_09_14_1356.json",
    "reference_2026_09_14_1644.json",
)


async def test_the_recorded_outage_declares(hass: HomeAssistant, freezer):
    """Thirty trackers leave over a few minutes. That is an outage,
    and the fallen set is not empty when it is declared.

    The empty fallen set was the 09:17 defect: the rule was built for
    the tie route and this house declares from the scan, so on real
    hardware there was never a fallen set at all.
    """
    house = await build(hass, load_trace(TRACE))
    trace = load_trace(TRACE)

    async for _event, _clock in house.play(freezer, trace["events"], until=400):
        pass

    assert house.coord.wifi_down_at is not None
    assert len(house.coord.wifi_fallen_set) > 0


async def test_the_count_is_taken_not_judged(hass: HomeAssistant, freezer):
    """The row counts the devices the outage took, not the verdicts
    that have landed.

    On 14 September the row read 1 of 12 four minutes in and 10 at
    thirteen minutes, while the network had been down and ten devices
    on it from the first minute.
    """
    house = await build(hass, load_trace(TRACE))
    trace = load_trace(TRACE)

    async for _event, clock in house.play(freezer, trace["events"], until=400):
        if house.coord.wifi_down_at is None:
            continue
        # The row counts the devices the outage took, so from the
        # moment it is declared that count stands at the size of the
        # fallen set. It does not creep upward as verdicts land,
        # which is what it did before 0.21.3: 1 of 12 at four
        # minutes, 10 at thirteen.
        counted = house.coord.suppressed_down_counts.get("wifi", 0)
        assert counted >= len(house.coord.wifi_fallen_set), (
            f"at {clock}s the row counted {counted} against a fallen "
            f"set of {len(house.coord.wifi_fallen_set)}"
        )


async def test_no_device_is_orphaned_during_the_recovery(
    hass: HomeAssistant, freezer
):
    """The defect this trace exists for.

    The scan heard the network at 15:13:58 and closed the outage. The
    five Motion Blinds devices behind it finished reconnecting
    between 15:14:16 and 15:14:18. Every one was handed back inside
    that window, wrote its own row and announced itself, and twenty
    seconds later they were all fine.

    No constructed test could hold twenty seconds. This one does.
    """
    house = await build(hass, load_trace(TRACE))
    trace = load_trace(TRACE)
    worst: tuple[int, int] = (0, 0)
    declared = False
    at_close: set[str] = set()

    async for _event, clock in house.play(freezer, trace["events"]):
        if house.coord.wifi_down_at is not None:
            declared = True
            at_close = house.claimed()
            continue
        if not declared:
            # Devices down before the outage was ever declared are
            # their own problems and always were: the Fire TV at
            # nought seconds, the Stove Vent Relays at 24.
            continue
        # Only the devices the outage was still claiming when it
        # closed. A device that recovered and then failed again is a
        # new fault, and its own row is the right answer: the Wi-Tek
        # switch does exactly that 110 seconds after the close.
        orphaned = at_close & house.orphaned()
        if len(orphaned) > worst[1]:
            worst = (clock, len(orphaned))
        at_close -= {d for d in at_close if d not in house.still_down()}

    assert worst[1] == 0, (
        f"{worst[1]} device(s) became their own problem at {worst[0]}s, "
        "while the recovery was still running"
    )


async def test_the_outage_ends(hass: HomeAssistant, freezer):
    """And it does end. A rule that never orphans anything by never
    closing would pass the case above and fail here."""
    house = await build(hass, load_trace(TRACE))
    trace = load_trace(TRACE)

    async for _event, _clock in house.play(freezer, trace["events"]):
        pass
    for step in range(4):
        freezer.tick(pytest.importorskip("datetime").timedelta(seconds=60))
        house.coord._sample_wifi(
            pytest.importorskip("homeassistant.util.dt").utcnow().timestamp()
        )
        await hass.async_block_till_done()

    assert house.coord.wifi_down_at is None


@pytest.mark.parametrize("name", ALL_TRACES)
async def test_no_device_is_orphaned_in_any_recording(
    hass: HomeAssistant, freezer, name: str
):
    """The same assertion against all four outages of 14 September.

    One recording proves a fix on one shape of event. Four recordings
    of the same house on the same day, of nine minutes, four minutes,
    twenty minutes and eighty, is the nearest this project has to an
    adversarial set.
    """
    house = await build(hass, load_trace(name))
    trace = load_trace(name)
    worst: tuple[int, int] = (0, 0)
    declared = False
    at_close: set[str] = set()

    async for _event, clock in house.play(freezer, trace["events"]):
        if house.coord.wifi_down_at is not None:
            declared = True
            at_close = house.claimed()
            continue
        if not declared:
            continue
        orphaned = at_close & house.orphaned()
        if len(orphaned) > worst[1]:
            worst = (clock, len(orphaned))
        at_close -= {d for d in at_close if d not in house.still_down()}

    assert worst[1] == 0, (
        f"{name}: {worst[1]} device(s) became their own problem at "
        f"{worst[0]}s, while the recovery was still running"
    )
