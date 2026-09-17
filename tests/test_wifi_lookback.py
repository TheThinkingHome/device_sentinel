# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_lookback.py, Version: 0.21.12 (2026-09-17)

"""Devices that notice before the router are the outage's (#440).

The second fleet's staged outage of 16 September: the SSIDs paused
at 16:40:11 and 242 entities went unavailable within the minute, but
UniFi marked the first client away at 16:44:35, and the outage is
dated from that first tracker. Every device whose own integration
noticed first read as broken before the outage began, kept its own
row under the rule for an already broken device, and 53 were listed
beside the outage row. 51 were tied devices whose trackers fell in
that outage.

A tied device whose tracker fell in the outage, and whose failure
began no more than five minutes before the outage's first tracker,
is the outage's, and the outage is dated from the earliest such
failure. Five minutes is UniFi's default detection time; Home
Assistant's own device trackers wait three.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    WIFI_KEY,
    WIFI_LOOKBACK_SECONDS,
)
from tests.test_wifi_outage import _declared, _house
from tests.test_wifi_row import _judge


def _listed(coord):
    return {row["device_id"] for row in coord.reportable_down_rows}


# The fixture's entities never really go unavailable, so judging a
# device when its tracker falls clears any verdict set before the
# declaration. Each test sets its verdicts after declaring, dated when
# the failure began, which is what a detector's verdict carries, and
# then runs the check the render tick runs.


async def test_devices_that_noticed_first_are_the_outages(
    hass: HomeAssistant, freezer
):
    coord, trackers, devices, _untied = await _house(hass, 14)
    lost = dt_util.utcnow().timestamp()
    # UniFi took 4 minutes 24 seconds on the second fleet.
    freezer.tick(timedelta(seconds=264))
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    assert coord.wifi_down_at == first

    _judge(coord, devices[:10], lost)
    assert devices[0].id in _listed(coord)
    coord._wifi_backdate()

    assert coord.wifi_down_at == lost
    assert not _listed(coord) & {device.id for device in devices[:10]}
    assert coord.suppressed_down_counts[WIFI_KEY] == 10


async def test_the_declaration_asks_at_once(hass: HomeAssistant, freezer):
    """Verdicts already standing when the outage is declared move it
    before anything is said about it."""
    coord, trackers, _devices, _untied = await _house(hass, 14)
    asked = []
    real = coord._wifi_backdate

    def _spy():
        asked.append(coord.wifi_down_at)
        real()

    coord._wifi_backdate = _spy
    await _declared(hass, coord, trackers[:10], freezer, count=10)
    assert asked and asked[0] is not None


async def test_the_render_tick_asks_every_time(hass: HomeAssistant):
    coord, _trackers, _devices, _untied = await _house(hass, 14)
    asked = []
    coord._wifi_backdate = lambda: asked.append(True)
    await coord._on_render_tick(None)
    assert asked == [True]


async def test_a_device_broken_long_before_keeps_its_own_row(
    hass: HomeAssistant, freezer
):
    coord, trackers, devices, _untied = await _house(hass, 14)
    long_ago = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(seconds=WIFI_LOOKBACK_SECONDS + 120))
    lost = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(seconds=60))
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    _judge(coord, devices[:1], long_ago)
    _judge(coord, devices[1:10], lost)
    coord._wifi_backdate()

    assert coord.wifi_down_at == lost
    assert long_ago < first - WIFI_LOOKBACK_SECONDS
    assert devices[0].id in _listed(coord)
    assert not _listed(coord) & {device.id for device in devices[1:10]}


async def test_an_untied_device_is_not_a_reason_to_move_it(
    hass: HomeAssistant, freezer
):
    """Only a device the router saw leave in this outage can say the
    network went earlier than the router noticed."""
    coord, trackers, _devices, untied = await _house(hass, 14)
    early = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(seconds=120))
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    _judge(coord, [untied], early)
    coord._wifi_backdate()
    assert coord.wifi_down_at == first
    assert untied.id in _listed(coord)


async def test_the_next_outage_starts_fresh(hass: HomeAssistant, freezer):
    coord, trackers, _devices, _untied = await _house(hass, 14)
    await _declared(hass, coord, trackers[:10], freezer, count=10)
    coord._wifi_restore(dt_util.utcnow().timestamp())
    assert coord._wifi_declared_from is None
