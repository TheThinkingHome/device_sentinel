# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_fault_event_values.py, Version: 0.27.7 (2026-10-27)

"""The fault event carries the figures an automation needs (rule NOTE-12):
the battery level for a battery problem, the railed value for a railed
signal, and both again on a fault renewed by unticking its item."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DEV_SIGNAL_VALUE,
)

from .helpers import setup_entry
from .push_helpers import battery_low, bus, device, sync

FAULT = "device_sentinel_fault"


async def _house(hass, uid, name, battery=False):
    dev = device(hass, uid, name, battery=battery)
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    return coord, dev, bus(hass, FAULT)


def _rail(coord, dev, value=255):
    coord.data[DATA_DEVICES][dev.id][DEV_SIGNAL_VALUE] = value
    # Stands in for three days at the rail.
    coord.signal_railed = lambda record: record is coord.data[DATA_DEVICES][dev.id]


async def _untick(hass, coord):
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await coord.async_todo_update(uid=uid, status="needs_action")
    await hass.async_block_till_done()


async def test_a_railed_signal_fault_carries_its_value(hass: HomeAssistant):
    coord, dev, heard = await _house(hass, "s1", "Plug Rail")
    _rail(coord, dev)
    await sync(hass, coord)
    assert heard[0][1]["kinds"] == ["railed_signal"]
    assert heard[0][1]["signal_value"] == 255


async def test_a_renewed_battery_fault_carries_its_level(hass: HomeAssistant):
    coord, dev, heard = await _house(hass, "b1", "Remote Bed", battery=True)
    battery_low(coord, dev)
    await sync(hass, coord)
    assert heard[0][1]["battery_level"] == 12.0
    await _untick(hass, coord)
    renewed = [d for _t, d in heard if d.get("renewed")]
    assert renewed and renewed[0]["battery_level"] == 12.0


async def test_a_renewed_railed_fault_carries_its_value(hass: HomeAssistant):
    coord, dev, heard = await _house(hass, "s2", "Plug Rail Two")
    _rail(coord, dev, 0)
    await sync(hass, coord)
    await _untick(hass, coord)
    renewed = [d for _t, d in heard if d.get("renewed")]
    assert renewed and renewed[0]["signal_value"] == 0
    assert "battery_level" not in renewed[0]
