# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_phone_push_rules.py, Version: 0.27.10 (2026-10-27)

"""What reaches the phone, against what the bus hears (rules LIST-03,
LIST-06, NOTE-08).

A ticked item is silent on the phone until the device's last problem
clears, then its recovery is pushed; the bus hears every change. A
worsening inside a family, such as frozen becoming unavailable, sends
no push, as it sends no new fault.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import settle_parked, setup_entry
from .push_helpers import battery_low, bus, device, down, messages, phone, sync, up
from .test_bridge_hold import _house, _minutes

FAULT, RECOVERED = "device_sentinel_fault", "device_sentinel_recovered"


async def _ticked_house(hass):
    dev = device(hass, "a1", "Door Hall", battery=True)
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    return coord, dev, phone(hass), bus(hass, FAULT, RECOVERED)


async def _tick(hass, coord):
    await coord.async_todo_update(uid=coord.todo_items[0]["uid"], status="completed")
    await hass.async_block_till_done()


async def test_a_new_family_on_a_ticked_item_reaches_the_bus_not_the_phone(hass: HomeAssistant):
    """A ticked item stays silent on the phone even for a device with
    nothing learned, which would otherwise push at once (rule NOTE-08)."""
    coord, dev, calls, heard = await _ticked_house(hass)
    battery_low(coord, dev)
    await sync(hass, coord)
    await _tick(hass, coord)
    calls.clear()
    heard.clear()
    down(coord, dev, FREEZE_CATEGORY_FROZEN)
    await sync(hass, coord)
    assert coord.todo_items[0]["status"] == "completed"
    assert [t for t, _ in heard] == [FAULT]
    assert not calls


async def test_a_kind_leaving_a_ticked_item_is_silent_on_the_phone(hass: HomeAssistant):
    coord, dev, calls, heard = await _ticked_house(hass)
    down(coord, dev, FREEZE_CATEGORY_FROZEN)
    battery_low(coord, dev)
    await sync(hass, coord)
    await _tick(hass, coord)
    calls.clear()
    heard.clear()
    up(coord, dev)  # it reports again; the battery is still low
    await sync(hass, coord)
    assert coord.todo_items and coord.todo_items[0]["status"] == "completed"
    assert [t for t, _ in heard] == [RECOVERED]
    assert not calls


async def test_the_last_problem_clearing_on_a_ticked_item_is_pushed(hass: HomeAssistant):
    coord, dev, calls, heard = await _ticked_house(hass)
    down(coord, dev, FREEZE_CATEGORY_FROZEN)
    battery_low(coord, dev)
    await sync(hass, coord)
    await _tick(hass, coord)
    up(coord, dev)
    await sync(hass, coord)
    calls.clear()
    heard.clear()
    battery_low(coord, dev, on=False)
    await sync(hass, coord)
    await settle_parked(hass, coord)
    assert coord.todo_items == []
    assert [t for t, _ in heard] == [RECOVERED]
    assert len(calls) == 1 and "Door Hall" in messages(calls)[0].split("Summary:")[0]


async def test_an_unticked_item_is_pushed_as_before(hass: HomeAssistant):
    coord, dev, calls, heard = await _ticked_house(hass)
    battery_low(coord, dev)
    await sync(hass, coord)
    assert len(calls) == 1
    down(coord, dev, FREEZE_CATEGORY_FROZEN)
    await sync(hass, coord)
    assert len(calls) == 2


async def test_frozen_becoming_unavailable_is_not_pushed(hass: HomeAssistant, freezer):
    coord, dev, value, seen, _heard, calls, heard_bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 8)  # frozen, held, pushed
    assert coord.data[DATA_DEVICES][dev.id][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert len(calls) == 1
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 15)
    assert coord.data[DATA_DEVICES][dev.id][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(calls) == 1
    assert heard_bus == [("fault", ["frozen"])]


async def test_a_worsening_before_the_first_push_is_still_told(hass: HomeAssistant, freezer):
    """A freeze still held for its debounce has told nobody: when it
    worsens, the worse kind is pushed in its place, once."""
    coord, dev, value, seen, _heard, calls, _bus = await _house(hass, freezer)
    record = coord.data[DATA_DEVICES][dev.id]
    for _ in range(10):
        await _minutes(hass, coord, freezer, 1)
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            break
    assert not calls, "the freeze is still held"
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 20)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    pushed = [c.data["message"] for c in calls]
    assert len(pushed) == 1 and "Switch Hall Living" in pushed[0]
