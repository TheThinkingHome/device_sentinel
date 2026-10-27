# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_push_phases.py, Version: 0.27.10 (2026-10-27)

"""When a Wi-Fi outage pushes (rule UP-09).

An upstream outage pushes twice, when it is down and when it is over;
recovering sends no push, and the row says it. A Wi-Fi outage stays
open while it recovers, so it must not push when it starts recovering,
as bridges, the broker and integrations do not.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_WIFI_OUTAGE,
    STORAGE_KEY,
    WIFI_KEY,
    WIFI_OUTAGE_PUSHED,
)

from tests.outage_helpers import restart, tick
from tests.test_wifi_outage import _declared, _fall, _house, _rise


def _owed(coord):
    """The pushes this sync owes, recorded as sent the way
    async_push_upstream records them."""
    messages = coord._upstream_messages()
    for name, count, recovered in messages:
        if recovered:
            coord._upstream_announced.pop(name, None)
        else:
            coord._upstream_announced[name] = count
    return [(name, recovered) for name, _count, recovered in messages]


async def test_down_and_over_push_and_recovering_does_not(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    freezer.tick(timedelta(seconds=90))
    assert _owed(coord) == [(WIFI_KEY, False)]

    # The network is heard and the recovery begins.
    for tracker in trackers[:5]:
        await _rise(hass, tracker)
    coord.on_wifi_scan_restored(first, first + 150.0)
    await hass.async_block_till_done()
    assert coord.wifi_recovering_at is not None
    assert coord.wifi_down_at is not None
    assert _owed(coord) == []

    # A reopen takes the row back to down, and that is no new push.
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_recovering_at is None
    assert _owed(coord) == []

    # Everyone back: the outage is over, and that is pushed.
    for tracker in trackers[:10]:
        await _rise(hass, tracker)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert _owed(coord) == [(WIFI_KEY, True)]


async def test_a_resumed_outage_does_not_push_down_a_second_time(
    hass: HomeAssistant, freezer
):
    """It was pushed as down before the restart. After the grace there
    is no second down push, which as a first push would sound, and the
    over push is still owed."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    freezer.tick(timedelta(seconds=90))
    _owed(coord)
    assert WIFI_KEY in coord._upstream_announced

    coord = await restart(hass, freezer, down=120)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    coord._grace_until = 0.0
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord.wifi_down_at is not None
    assert _owed(coord) == []

    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert _owed(coord) == [(WIFI_KEY, True)]


async def test_a_resumed_outage_closing_at_grace_end_still_pushes_over(
    hass: HomeAssistant, freezer
):
    """Everything is back by the end of the grace, so it closes on the
    first tick after it. The over push is still sent."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    freezer.tick(timedelta(seconds=90))
    _owed(coord)
    assert WIFI_KEY in coord._upstream_announced

    coord = await restart(hass, freezer, down=120)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._grace_until = 0.0
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert _owed(coord) == [(WIFI_KEY, True)]


@pytest.mark.parametrize(
    "pinned",
    [
        # The first and third are moments at which the coordinator's
        # own tick comes due inside the test and sends the push itself.
        "2026-10-26 03:00:00+00:00",
        "2026-10-26 12:00:30+00:00",
        "2026-10-26 12:37:30+00:00",
        "2026-10-26 17:37:50+00:00",
    ],
)
async def test_the_down_push_reaches_the_main_file_before_a_power_cut(
    hass: HomeAssistant, freezer, hass_storage, pinned
):
    """Once the down is pushed, the stored outage says so on disk, not
    only in memory: after a power cut the down is not pushed again.

    The coordinator's own minute tick keeps running under the test, and
    the frozen clock jumps far enough for it to come due while a save
    is awaited. Whichever sends the down push, the tick or the test,
    what is proven is the same: the push reaches the main file. Run at
    several pinned hours, since nothing here may hang on the time of day
    (rule CODE-13).
    """
    freezer.move_to(pinned)
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    freezer.tick(timedelta(seconds=90))
    # The down push, unless the coordinator's own tick has sent it.
    assert _owed(coord) in ([(WIFI_KEY, False)], [])
    await hass.async_block_till_done()
    assert WIFI_KEY in coord._upstream_announced
    for _ in range(10):
        freezer.tick(timedelta(seconds=60))
        coord._wifi_backdate()
        coord._next_routine_save = 0.0
        await coord._routine_save()
    assert coord.data[DATA_WIFI_OUTAGE][WIFI_OUTAGE_PUSHED] is True
    stored = hass_storage[STORAGE_KEY]["data"][DATA_WIFI_OUTAGE]
    assert stored[WIFI_OUTAGE_PUSHED] is True
    on_disk = copy.deepcopy(hass_storage[STORAGE_KEY])

    def power_cut():
        hass_storage[STORAGE_KEY] = on_disk

    coord = await restart(hass, freezer, down=120, before_setup=power_cut)
    coord._grace_until = 0.0
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord.wifi_down_at is not None
    assert _owed(coord) == []


async def _pushed_by_the_tick(hass, coord, freezer):
    for _ in range(5):
        await tick(hass, freezer, step=61)
        # The minute check runs as a background task, which a plain
        # block_till_done does not wait for, and its save awaits file work on a
        # worker thread: without this the test could read the disk before the
        # tick's save landed (rule CODE-13).
        await hass.async_block_till_done(wait_background_tasks=True)
        if WIFI_KEY in coord._upstream_announced:
            return
    raise AssertionError("the down was never pushed")


async def test_the_tick_that_pushes_leaves_it_on_disk(
    hass: HomeAssistant, freezer, hass_storage
):
    """The tick whose sync owes the down push saves it at once, so a
    power cut in the next minute does not push the down again."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    await _pushed_by_the_tick(hass, coord, freezer)
    on_disk = copy.deepcopy(hass_storage[STORAGE_KEY])
    assert on_disk["data"][DATA_WIFI_OUTAGE][WIFI_OUTAGE_PUSHED] is True

    def lost_power():
        hass_storage[STORAGE_KEY] = on_disk

    coord = await restart(hass, freezer, down=120, before_setup=lost_power)
    coord._grace_until = 0.0
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord.wifi_down_at is not None
    assert _owed(coord) == []


async def test_a_home_assistant_restart_after_the_push_keeps_it(
    hass: HomeAssistant, freezer, hass_storage
):
    """A restart in the minute after the down push: the stop handler,
    the only write a restart gets, stores the outage as it stands."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    await _pushed_by_the_tick(hass, coord, freezer)
    coord = await restart(hass, freezer, down=60)
    stored = hass_storage[STORAGE_KEY]["data"][DATA_WIFI_OUTAGE]
    assert stored[WIFI_OUTAGE_PUSHED] is True
    coord._grace_until = 0.0
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord.wifi_down_at is not None
    assert _owed(coord) == []
