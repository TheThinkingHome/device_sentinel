# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_mute_everything_signal.py, Version: 0.27.10 (2026-10-27)

"""Mute everything judges a device for nothing, a railed signal included,
so the rail leaves the Problem List, the card and the to-do count
(rules MUTE-01, MUTE-07).
"""

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
    TODO_KIND_RAILED_SIGNAL,
)

from .test_signal import _rail_coordinator


async def _railed(hass):
    coord, device_id = await _rail_coordinator(hass)
    coord._grace_until = 0.0
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_COUNT] = [400, 380, 0, 0, 0]
    rec[DEV_SIGNAL_DAILY_RAIL] = [0, 2, 9, 7, 8]
    assert coord.signal_railed(rec)
    return coord, device_id


async def test_mute_everything_takes_a_railed_signal_off(hass: HomeAssistant):
    coord, device_id = await _railed(hass)
    assert TODO_KIND_RAILED_SIGNAL in coord._current_problems()[device_id]["kinds"]
    coord.page_set_mute(device_id, "everything", True)
    await hass.async_block_till_done()
    assert coord.signal_problem_list == []
    assert device_id not in coord._current_problems()


async def test_the_signal_mute_still_does(hass: HomeAssistant):
    coord, device_id = await _railed(hass)
    coord.page_set_mute(device_id, "signal", True)
    await hass.async_block_till_done()
    assert coord.signal_problem_list == []


async def test_lifting_mute_everything_brings_the_rail_back(hass: HomeAssistant):
    coord, device_id = await _railed(hass)
    coord.page_set_mute(device_id, "everything", True)
    await hass.async_block_till_done()
    coord.page_set_mute(device_id, "everything", False)
    await hass.async_block_till_done()
    assert [row["device_id"] for row in coord.signal_problem_list] == [device_id]
