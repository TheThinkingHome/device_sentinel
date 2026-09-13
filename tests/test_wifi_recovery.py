# File: tests/test_wifi_recovery.py, Version: 0.21.1 (2026-09-13)
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
    and becomes its own. The claim ends with the outage."""
    coord, trackers, devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers[:6]:
        await _rise(hass, tracker)
    await _tick(coord, first + 60.0)
    await _tick(coord, first + 120.0)
    await _tick(coord, first + 180.0)
    assert coord.wifi_down_at is None

    for device in devices[6:]:
        assert coord.upstream_down_since(device.id) is None
