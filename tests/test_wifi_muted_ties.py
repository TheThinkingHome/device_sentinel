# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_muted_ties.py, Version: 0.29.0 (2026-11-14)

"""A muted Wi-Fi device cannot raise a Wi-Fi outage (rule UP-12).

A device muted for unavailable, or for everything, is one the person chose
not to hear about going offline, so it is not tied to its router tracker and
does not count toward declaring an outage. Three Wi-Fi bulbs on one wall
switch, muted, no longer read as the network going down on a house
whose server cannot scan for its network.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
)

from tests.test_wifi_outage import _fall, _house


async def _mute(hass, coord, key, devices):
    options = dict(coord.entry.options)
    options[key] = [device.id for device in devices]
    hass.config_entries.async_update_entry(coord.entry, options=options)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()


async def test_muted_for_unavailable_is_not_tied(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, count=5)
    assert len(coord._wifi_ties) == 5
    await _mute(hass, coord, CONF_UNAVAILABLE_MUTED_DEVICES, devices[:3])
    assert set(coord._wifi_ties) == {device.id for device in devices[3:]}


async def test_muted_for_everything_is_not_tied(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, count=5)
    await _mute(hass, coord, CONF_MUTED_DEVICES, devices[:3])
    assert set(coord._wifi_ties) == {device.id for device in devices[3:]}


async def test_three_muted_bulbs_switched_off_declare_nothing(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, count=5)
    await _mute(hass, coord, CONF_UNAVAILABLE_MUTED_DEVICES, devices[:3])
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is None
    assert coord._wifi_burst == []


async def test_unmuted_they_still_declare(hass: HomeAssistant):
    """The control: the same three falls, unmuted, start the hold."""
    coord, trackers, devices, _untied = await _house(hass, count=5)
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is not None
