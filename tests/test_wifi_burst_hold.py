# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_burst_hold.py, Version: 0.21.12 (2026-09-17)

"""A burst of tied devices waits for the router (ruling #446).

On the second fleet's staged outage of 16 September the devices'
own integrations noticed within the first minute and their verdicts
landed three and a half minutes in, while the router marked its
first client away at four and a half minutes and the outage was
declared at five minutes thirty-five seconds. Replayed through the
coordinator, 31 and then 40 device rows stood on the list for the
two minutes between, long enough for most of their notification
holds to mature.

When enough tied devices to declare an outage fail within one burst
window, their rows wait for the router: the outage claims them if it
is declared, and they appear, dated from their own failure, if it is
not. The wait is the router's detection time, the outage's own hold
and one tick.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_SINCE,
    WIFI_BURST_HOLD_SECONDS,
    WIFI_BURST_WINDOW_SECONDS,
    WIFI_HOLD_SECONDS,
    WIFI_LOOKBACK_SECONDS,
)
from tests.test_wifi_outage import _declared, _house
from tests.test_wifi_row import _judge


def _listed(coord):
    return {row["device_id"] for row in coord.reportable_down_rows}


def test_the_wait_covers_the_measured_outage():
    """5 min 35 s from the first failure to the declaration."""
    assert WIFI_BURST_HOLD_SECONDS == (
        WIFI_LOOKBACK_SECONDS + WIFI_HOLD_SECONDS + 60
    )
    assert WIFI_BURST_HOLD_SECONDS > 335


async def test_a_burst_waits_for_the_router(hass: HomeAssistant, freezer):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    now = dt_util.utcnow().timestamp()
    _judge(coord, devices[:4], now)
    assert coord._wifi_burst_needed() == 3
    assert not _listed(coord) & {device.id for device in devices[:4]}
    assert coord.suppressed_down_counts == {}


async def test_the_outage_takes_them_when_it_is_declared(
    hass: HomeAssistant, freezer
):
    coord, trackers, devices, _untied = await _house(hass, 14)
    lost = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(seconds=200))
    await _declared(hass, coord, trackers[:4], freezer, count=4)
    _judge(coord, devices[:4], lost)
    coord._wifi_backdate()
    assert not _listed(coord) & {device.id for device in devices[:4]}
    assert coord.wifi_down_at == lost


async def test_they_appear_if_no_outage_comes(hass: HomeAssistant, freezer):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    failed = dt_util.utcnow().timestamp()
    _judge(coord, devices[:4], failed)
    freezer.tick(timedelta(seconds=WIFI_BURST_HOLD_SECONDS + 1))
    assert {device.id for device in devices[:4]} <= _listed(coord)
    # Dated from the failure, not from the end of the wait.
    record = coord.data[DATA_DEVICES][devices[0].id]
    assert record[DEV_FROZEN_SINCE] == failed


async def test_too_few_to_be_an_outage_appear_at_once(
    hass: HomeAssistant, freezer
):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    _judge(coord, devices[:2], dt_util.utcnow().timestamp())
    assert {device.id for device in devices[:2]} <= _listed(coord)


async def test_failures_spread_out_are_not_a_burst(
    hass: HomeAssistant, freezer
):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    start = dt_util.utcnow().timestamp()
    for index, device in enumerate(devices[:4]):
        _judge(coord, [device], start + index * (WIFI_BURST_WINDOW_SECONDS + 5))
    freezer.tick(timedelta(seconds=3 * (WIFI_BURST_WINDOW_SECONDS + 5)))
    assert {device.id for device in devices[:4]} <= _listed(coord)


async def test_an_untied_device_is_never_held(hass: HomeAssistant, freezer):
    coord, _trackers, devices, untied = await _house(hass, 14)
    now = dt_util.utcnow().timestamp()
    _judge(coord, devices[:4] + [untied], now)
    assert untied.id in _listed(coord)
    assert not _listed(coord) & {device.id for device in devices[:4]}


async def test_the_sync_writes_no_row_while_they_wait(
    hass: HomeAssistant, freezer
):
    """What a person sees: nothing, until the router has had its say."""
    from custom_components.device_sentinel.const import DATA_TODO_ITEMS

    coord, _trackers, devices, _untied = await _house(hass, 14)
    _judge(coord, devices[:4], dt_util.utcnow().timestamp())
    coord._sync_problem_list()
    rows = {item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]}
    assert not rows & {device.id for device in devices[:4]}


async def test_a_late_tracker_still_waits_after_the_declaration(
    hass: HomeAssistant, freezer
):
    """The replay of 16 September left one row from 16:48 to 16:49: a
    device that failed with the first wave, a little before the
    devices whose trackers left first, and whose own tracker left in
    the second wave. Neither the tie nor the window reached it."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    lost = dt_util.utcnow().timestamp()
    freezer.tick(timedelta(seconds=30))
    await _declared(hass, coord, trackers[:4], freezer, count=4)
    _judge(coord, devices[:4], lost)
    _judge(coord, devices[4:5], lost - 20)
    coord._wifi_backdate()
    assert coord.wifi_down_at == lost
    assert coord.upstream_down_since(devices[4].id) is None

    # Well past its own hold, and still waiting while the outage stands.
    freezer.tick(timedelta(seconds=WIFI_BURST_HOLD_SECONDS + 60))
    assert devices[4].id not in _listed(coord)

    # The outage ends without its tracker leaving: its own problem now.
    coord._wifi_restore(dt_util.utcnow().timestamp())
    assert devices[4].id in _listed(coord)
