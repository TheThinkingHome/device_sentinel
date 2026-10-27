# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_parked_item_holds.py, Version: 0.27.7 (2026-10-27)

"""An item waiting its minute after its last problem cleared (rule
LIST-06), against faults still held for their debounce and a person
deleting the item: a problem that heals inside its debounce is never
announced, a fault that matured while the item waited is sent if the
device goes down again inside the minute, and a deleted item waits for
nothing. Found by the first adversarial round of 0.27.7."""
from __future__ import annotations


from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import setup_entry
from .push_helpers import bus, device, down, messages, phone, sync, up

FAULT, RECOVERED = "device_sentinel_fault", "device_sentinel_recovered"


async def _house(hass, delay=30.0):
    dev = device(hass, "a1", "Door Hall")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[dev.id] = "mqtt"
    # A chatty device: 30% of a 100-second learned gap.
    coord._notification_delay = lambda _d: delay
    return coord, dev, phone(hass), bus(hass, FAULT, RECOVERED)


async def _wait(hass, freezer, seconds):
    for _ in range(int(seconds)):
        freezer.tick(1)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()


async def test_a_brief_drop_on_a_chatty_device_sends_nothing(hass: HomeAssistant, freezer):
    """Debounce 30 s. Down 10 s, back. Before 0.27.7 the recovery
    cancelled the hold and nothing reached the phone. Now the hold
    matures during the park, is dropped, and the recovery at the end of
    the minute finds no hold to cancel, so it is pushed alone."""
    coord, dev, calls, heard = await _house(hass)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    assert not calls
    await _wait(hass, freezer, 10)
    up(coord, dev)
    await sync(hass, coord)
    assert dev.id in coord._parked
    await _wait(hass, freezer, 90)
    assert coord.todo_items == []
    assert not calls, f"phone got a recovery for a fault it never heard: {messages(calls)}"


async def test_a_drop_that_returns_inside_the_minute_still_sends_its_fault(hass: HomeAssistant, freezer):
    """Debounce 30 s. Down 10 s, back 25 s (parked, the hold matures and
    is dropped), down again for good. The item carries on, so no new
    hold is made: the device stays down and the phone is never told."""
    coord, dev, calls, heard = await _house(hass)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    await _wait(hass, freezer, 10)
    up(coord, dev)
    await sync(hass, coord)
    await _wait(hass, freezer, 25)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    assert coord.todo_items and dev.id not in coord._parked, "carried on"
    # 45 seconds more: past any debounce a new hold would carry.
    for _ in range(45):
        freezer.tick(1)
        down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert coord.todo_items, "still down, still listed"
    assert not coord._held_events
    assert calls, "down again, listed, and the phone never heard"


async def test_a_hand_deletion_during_the_minute_waits_for_nothing(hass: HomeAssistant, freezer):
    """Deleting the item in its minute leaves _parked holding the device:
    the release timer then re-syncs the whole list every second, for ever."""
    coord, dev, calls, heard = await _house(hass, delay=0.0)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    await _wait(hass, freezer, 5)
    up(coord, dev)
    await sync(hass, coord)
    assert dev.id in coord._parked
    await coord.async_todo_delete([coord.todo_items[0]["uid"]])
    await hass.async_block_till_done()
    count = 0
    real = coord._sync_problem_list

    def counting():
        nonlocal count
        count += 1
        real()

    coord._sync_problem_list = counting
    await _wait(hass, freezer, 70)
    count = 0
    await _wait(hass, freezer, 120)
    assert count <= 3, f"{count} list syncs in two quiet minutes; parked={coord._parked}"
    assert dev.id not in coord._parked, "the deleted device is still parked"
    assert count <= 3, f"{count} list syncs in two quiet minutes"


# Second adversarial round of 0.27.7.
async def test_a_ticked_item_is_silent_when_it_returns_in_its_minute(hass: HomeAssistant, freezer):
    """Fault held 30 s; person ticks it at 5 s; device up at 10 s (parked);
    hold matures at 30 s in the park; device down again at 40 s.
    Ruling: a ticked item is silent until its last problem clears, and a
    return inside the minute announces nothing."""
    coord, dev, calls, heard = await _house(hass)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    await _wait(hass, freezer, 5)
    await coord.async_todo_update(coord.todo_items[0]["uid"], status="completed")
    await hass.async_block_till_done()
    await _wait(hass, freezer, 5)
    up(coord, dev)
    await sync(hass, coord)
    assert dev.id in coord._parked
    await _wait(hass, freezer, 25)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    assert coord.todo_items[0]["status"] == "completed"
    assert not calls, f"ticked item pushed: {messages(calls)}"


async def test_a_withdrawn_item_leaves_nothing_to_swallow_a_later_recovery(hass: HomeAssistant, freezer):
    """Hold matures in the park, then the device is set aside inside the
    minute (excluded). The matured entry is never cleared. Taken back,
    the device later goes down (fault pushed after its debounce), comes
    back for good: its recovery is swallowed by the stale entry."""
    coord, dev, calls, heard = await _house(hass)
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    await _wait(hass, freezer, 10)
    up(coord, dev)
    await sync(hass, coord)
    await _wait(hass, freezer, 25)
    assert coord._matured_in_park
    coord._watched.pop(dev.id)
    await sync(hass, coord)
    assert coord.todo_items == []
    assert coord._matured_in_park == {}
    # Taken back later.
    await _wait(hass, freezer, 600)
    coord._watched[dev.id] = "mqtt"
    calls.clear()
    # Second episode: debounce 0 so the fault goes at once.
    coord._notification_delay = lambda _d: 0.0
    down(coord, dev, FREEZE_CATEGORY_UNAVAILABLE, ago=0.0)
    await sync(hass, coord)
    await hass.async_block_till_done()
    got_fault = list(messages(calls))
    assert got_fault, ("fault pushed after its debounce", coord.todo_items, coord._held_events, coord._matured_in_park, coord._parked, calls)
    up(coord, dev)
    await sync(hass, coord)
    await _wait(hass, freezer, 90)
    assert coord.todo_items == [], coord.todo_items
    after = messages(calls)[len(got_fault):]
    assert after, f"fault pushed {got_fault} but recovery never sent"

