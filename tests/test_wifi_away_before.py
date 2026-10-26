# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_away_before.py, Version: 0.27.5 (2026-10-25)

"""A tracker already away when a Wi-Fi outage began (rules UP-12,
UP-15, UP-16; ruling #409).

Ruled a bug by James, 25 October 2026 (Known Gap 34): a tracker
already away when the outage began is not a casualty. Until 0.27.5
the burst hold counted every tracker away, so phones away all day
helped a small flap reach the threshold, and the claim took a tied
device whose tracker had left hours before.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)

from tests.test_wifi_outage import _declared, _fall, _house, _rise


async def test_a_tracker_away_for_hours_does_not_hold_a_flap_open(
    hass: HomeAssistant, freezer
):
    """Three fall together and start the hold, one comes back inside
    it. Two are still gone from the burst; the tracker that left two
    hours earlier does not make it three."""
    coord, trackers, _devices, _untied = await _house(hass, 8)
    await _fall(hass, trackers[7])
    freezer.tick(timedelta(hours=2))

    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is not None
    await _rise(hass, trackers[0])
    freezer.tick(timedelta(seconds=WIFI_HOLD_SECONDS + 5))
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()

    assert coord.wifi_down_at is None
    assert coord._wifi_hold_since is None


async def test_three_gone_from_the_burst_still_declare(
    hass: HomeAssistant, freezer
):
    """The control: the long-away tracker changes nothing when the
    burst holds on its own."""
    coord, trackers, _devices, _untied = await _house(hass, 8)
    await _fall(hass, trackers[7])
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers[:3], freezer, count=3)
    assert trackers[7] not in coord.wifi_fallen_set


async def test_a_device_whose_tracker_left_hours_before_is_not_claimed(
    hass: HomeAssistant, freezer
):
    """It failed when its tracker left, two hours before the outage, so
    it is not a casualty and keeps its own row. Until 0.27.5 a tracker
    still away was enough to claim it."""
    coord, trackers, devices, _untied = await _house(hass, 8)
    await _fall(hass, trackers[7])
    record = coord.data[DATA_DEVICES][devices[7].id]
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers[:3], freezer, count=3)

    assert coord.upstream_down_since(devices[7].id) is None
    # A casualty of the burst is still claimed.
    found = coord.upstream_down_since(devices[0].id)
    assert found is not None and found[0] == WIFI_KEY


async def test_a_tracker_away_before_whose_device_fails_inside_is_claimed(
    hass: HomeAssistant, freezer
):
    """Its tracker claims nothing, but its own failure began inside the
    outage, so the outage claims it like any other device (rule UP-15)."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    await _fall(hass, trackers[5])
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers, freezer, count=3)
    since = coord.wifi_down_at
    freezer.tick(timedelta(seconds=60))
    record = coord.data[DATA_DEVICES][devices[5].id]
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp()
    assert coord.upstream_down_since(devices[5].id) == (WIFI_KEY, since)


async def test_a_returned_member_that_fails_again_is_still_claimed(
    hass: HomeAssistant, freezer
):
    """A fallen tracker comes home and leaves again inside the outage,
    and its device then fails: the outage claims it."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    since = coord.wifi_down_at
    await _rise(hass, trackers[0])
    freezer.tick(timedelta(seconds=30))
    await _fall(hass, trackers[0])
    record = coord.data[DATA_DEVICES][devices[0].id]
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp()
    assert coord.wifi_down_at is not None
    assert coord.upstream_down_since(devices[0].id) == (WIFI_KEY, since)
