# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_recovery.py, Version: 0.21.11 (2026-09-16)

"""When an outage ends. Rulings #408, #409, #422 to #426.

Written before the change, and every case here fails against 0.21.0.

The shipped rule restores when fewer than three tied trackers read
not_home. That answers a different question from the one that
declared the outage. Three falling together is a fair threshold for
declaring one; three still away is not a fair threshold for ending
one, because a house with three devices switched off can never
recover. On the second fleet that produced outages of 3.0, 4.3 and
5.5 hours against real events of minutes, and one of the three
trackers holding an outage open had gone away forty-nine minutes
before the network was touched.

#408 An outage ends when the devices that fell in it come back,
     judged against that set rather than a count of devices away.
#409 A device already away when the outage began is not a casualty
     of it and does not vote against recovery.
#422 A returned member leaves the fallen set permanently. Coming home
     ends the outage for that device; leaving again later is a new
     event. Without this the set can never empty, which is the
     shipped defect wearing a different hat.
#423 A recovery is announced when 40 percent of the fallen set has
     returned. No minimum count: on a three device outage requiring
     three back is the hours-long hold this work exists to remove.
#424 The settle extends while returns keep arriving and closes after
     two consecutive ticks with none.
#425 Three losses during the settle reopens the outage, reusing the
     declaration floor.
#426 What is still away when an outage closes goes back to per-device
     detection, which has its own debounce.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    WIFI_BURST_FLOOR,
    WIFI_HANDBACK_SECONDS,
    WIFI_RECOVERY_SHARE,
    WIFI_SETTLE_TICKS,
)

from tests.test_wifi_outage import _declared, _fall, _house, _rise


async def _tick(coord, now: float) -> None:
    coord._sample_wifi(now)


# ------------------------------------------------------------- #408


async def test_the_outage_is_judged_against_the_set_that_fell(
    hass: HomeAssistant, freezer
):
    """Ten fall, ten return, and the outage ends even though three
    other devices in the house are switched off throughout."""
    coord, trackers, _devices, _untied = await _house(hass, 14)

    # Three devices are off before anything happens. They are not in
    # the outage and must not hold it open.
    for tracker in trackers[10:13]:
        await _fall(hass, tracker)
    # Outside the burst window, so these are plainly before the
    # outage rather than part of its first wave.
    freezer.tick(timedelta(seconds=120))

    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    assert coord.wifi_down_at is not None

    for tracker in trackers[:10]:
        await _rise(hass, tracker)
    await _tick(coord, first + 120.0)   # announces
    await _tick(coord, first + 180.0)   # quiet one
    await _tick(coord, first + 240.0)   # quiet two

    assert coord.wifi_down_at is None


# ------------------------------------------------------------- #409


async def test_a_device_already_away_is_not_a_casualty(
    hass: HomeAssistant, freezer
):
    """The second fleet's tablet, which left forty-nine minutes
    before the network was touched and was one of three holding the
    outage open for five and a half hours."""
    coord, trackers, _devices, _untied = await _house(hass, 12)

    await _fall(hass, trackers[11])
    freezer.tick(timedelta(seconds=120))
    await _declared(hass, coord, trackers[:10], freezer, count=10)

    assert trackers[11] not in coord.wifi_fallen_set
    assert len(coord.wifi_fallen_set) == 10


# ------------------------------------------------------------- #422


async def test_a_returned_member_does_not_rejoin_the_set(
    hass: HomeAssistant, freezer
):
    """Two trackers came home with the rest and left again seventeen
    minutes later. If they rejoin, the set never empties."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers:
        await _rise(hass, tracker)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)
    await _tick(coord, first + 240.0)
    assert coord.wifi_down_at is None

    for tracker in trackers[:2]:
        await _fall(hass, tracker)
    await _tick(coord, first + 1200.0)

    assert coord.wifi_down_at is None


# ------------------------------------------------------------- #423


@pytest.mark.parametrize(("fell", "needed"), [(3, 2), (10, 4), (76, 31)])
async def test_the_announce_threshold_is_a_bare_share(
    hass: HomeAssistant, fell: int, needed: int
):
    """Forty percent of the fallen set, with no floor. A floor was
    measured and rejected: on a three device outage it requires all
    three back."""
    coord, _trackers, _devices, _untied = await _house(hass, 3)

    assert coord._wifi_recovery_needed(fell) == needed
    assert WIFI_RECOVERY_SHARE == 0.4


async def test_a_three_device_outage_ends_on_two_returns(
    hass: HomeAssistant, freezer
):
    """The hours-long hold, answered. Two of three back is forty
    percent rounded up, and closing early is cheap because the third
    goes back to per-device detection."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    first = await _declared(hass, coord, trackers, freezer, count=3)

    for tracker in trackers[:2]:
        await _rise(hass, tracker)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)
    await _tick(coord, first + 240.0)

    assert coord.wifi_down_at is None


# ------------------------------------------------------------- #424


async def test_the_settle_extends_while_returns_arrive(
    hass: HomeAssistant, freezer
):
    """A return on any settle tick restarts the count, so the burst
    is ridden out rather than cut off at a fixed delay."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:4]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)
    assert coord.wifi_down_at is not None

    # One more arrives on each of the next two ticks, so neither is
    # quiet and the outage is still open.
    await _rise(hass, trackers[4])
    await _tick(coord, first + 120.0)
    await _rise(hass, trackers[5])
    await _tick(coord, first + 180.0)
    assert coord.wifi_down_at is not None

    # Two quiet ticks and it closes.
    await _tick(coord, first + 240.0)
    await _tick(coord, first + 300.0)
    assert coord.wifi_down_at is None


async def test_it_closes_after_exactly_two_quiet_ticks(
    hass: HomeAssistant, freezer
):
    """One quiet tick is not enough, two is."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:4]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)
    await _tick(coord, first + 120.0)
    assert coord.wifi_down_at is not None
    assert WIFI_SETTLE_TICKS == 2

    await _tick(coord, first + 180.0)
    assert coord.wifi_down_at is None


# ------------------------------------------------------------- #425


async def test_three_losses_during_the_settle_reopens_it(
    hass: HomeAssistant, freezer
):
    """Losing ground is what a flapping network looks like, and three
    falling together is what declared the outage in the first place.
    Never seen on either fleet: reasoned from the declaration floor
    rather than observed."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:6]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)
    assert coord.wifi_down_at is not None

    for tracker in trackers[:WIFI_BURST_FLOOR]:
        await _fall(hass, tracker)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)

    # Reopened: the announce is withdrawn, so two quiet ticks do not
    # close it while the set is short again.
    assert coord.wifi_down_at is not None


async def test_two_losses_do_not_reopen_it(hass: HomeAssistant, freezer):
    """The control. A single flap on a large set is not a flapping
    network, which is why the threshold is three rather than one."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:6]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)

    for tracker in trackers[:2]:
        await _fall(hass, tracker)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)

    assert coord.wifi_down_at is None


# ------------------------------------------------------------- #426


async def test_the_remainder_is_handed_back(hass: HomeAssistant, freezer):
    """What is still away at close stops being the network's problem
    and becomes its own, once it has had a chance to come back.

    Rewritten for 0.21.7. It asserted the claim ended the instant the
    outage did, which is what put six devices on the problem list
    mid-recovery on 14 September. The hand-back now waits
    WIFI_HANDBACK_SECONDS (#433).
    """
    coord, trackers, devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:6]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)
    assert coord.wifi_down_at is None

    freezer.tick(timedelta(seconds=WIFI_HANDBACK_SECONDS + 5))
    for device in devices[6:]:
        assert coord.upstream_down_since(device.id) is None


# ------------------------------- the staged outage of 14 September, 15:13


async def test_the_scan_does_not_close_the_outage_itself(
    hass: HomeAssistant, freezer
):
    """Found on hardware, not by this suite.

    A house that can hear its own radio declares from the scan (#391)
    and, until 0.21.5, closed from it too: `on_wifi_scan_restored`
    called the restore directly and the recovery rule never ran. On
    14 September the trackers came home at 15:13:38, the scan closed
    the outage at 15:13:58, and the five Motion Blinds devices behind
    it finished reconnecting at 15:14:16 to 15:14:18. In that twenty
    second window every one of them was handed back under #426, wrote
    its own row and announced itself, and twenty seconds later they
    were all fine.

    Hearing the network is not the same as the devices on it being
    back. The scan now reports the return and the recovery rule
    decides when the outage ends.
    """
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    for tracker in trackers[:9]:
        await _rise(hass, tracker)
    coord.on_wifi_scan_restored(first, first + 120.0)
    await hass.async_block_till_done()

    # The network is back and the outage is not over: the settle has
    # not run, so nothing has been handed back yet.
    assert coord.wifi_down_at is not None


async def test_the_settle_ends_early_when_everyone_is_back(
    hass: HomeAssistant, freezer
):
    """Two quiet ticks, or the whole fallen set returned, whichever
    comes first. A clean outage where everything returns at once
    closes at once rather than waiting out a debounce for devices
    that are provably already home."""
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    for tracker in trackers[:10]:
        await _rise(hass, tracker)
    coord._sample_wifi(first + 120.0)
    await hass.async_block_till_done()

    assert coord.wifi_down_at is None


async def test_the_settle_still_waits_when_some_are_missing(
    hass: HomeAssistant, freezer
):
    """The control. The early exit fires only when there is provably
    nothing left to wait for."""
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    for tracker in trackers[:9]:
        await _rise(hass, tracker)
    coord._sample_wifi(first + 120.0)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is not None

    coord._sample_wifi(first + 180.0)
    coord._sample_wifi(first + 240.0)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
