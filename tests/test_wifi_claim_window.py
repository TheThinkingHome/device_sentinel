# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_claim_window.py, Version: 0.28.12 (2026-11-11)

"""A Wi-Fi outage claims what fails in its first 15 minutes (rule UP-15).

Three Wi-Fi devices on one switched circuit, a garage breaker or a TV
cabinet turned off at the wall, read as three trackers falling together,
and on a house with no chosen network to scan the outage stands until
they are powered again. Every device that failed while it stood used to
be folded into its row, with no row or push of its own. Now a device
that fails after the first 15 minutes is listed on its own, and so is a
tied device whose tracker falls that late.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import WIFI_CLAIM_SECONDS, WIFI_KEY
from tests.test_wifi_outage import _declared, _fall, _house
from tests.test_wifi_row import _judge


async def test_a_device_failing_in_the_first_minutes_is_claimed(hass: HomeAssistant, freezer):
    coord, trackers, _devices, untied = await _house(hass, 6)
    await _declared(hass, coord, trackers[:3], freezer, count=3)
    since = coord.wifi_down_at
    _judge(coord, [untied], since + 240)
    assert coord.wifi_down_since(untied.id) == (WIFI_KEY, since)


async def test_a_device_failing_hours_later_is_listed_on_its_own(hass: HomeAssistant, freezer):
    coord, trackers, _devices, untied = await _house(hass, 6)
    await _declared(hass, coord, trackers[:3], freezer, count=3)
    since = coord.wifi_down_at
    freezer.tick(timedelta(hours=3))
    _judge(coord, [untied], dt_util.utcnow().timestamp())
    assert coord.wifi_down_at == since, "the outage itself still stands"
    assert coord.wifi_down_since(untied.id) is None
    assert untied.id in {row["device_id"] for row in coord.reportable_down_rows}


async def test_a_tracker_falling_late_is_not_the_outages(hass: HomeAssistant, freezer):
    coord, trackers, devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers[:3], freezer, count=3)
    since = coord.wifi_down_at
    freezer.tick(timedelta(seconds=WIFI_CLAIM_SECONDS + 600))
    await _fall(hass, trackers[4])
    assert coord.wifi_down_since(devices[0].id) == (WIFI_KEY, since)
    assert coord.wifi_down_since(devices[4].id) is None
