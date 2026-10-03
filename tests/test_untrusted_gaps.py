# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_untrusted_gaps.py, Version: 0.24.1 (2026-10-03)

"""A gap is learned only if Device Sentinel could have heard the device for all of it.

Two more ways an untrusted gap was learned before 0.24.1. A jump of the
system clock is noticed at the next minute check, and a report before
that check measured its gap across the jump. And an unclean stop banked
each device's silence up to the last save, which on the reference rig
on 1 October took the Zigbee bridge's outage as every Zigbee device's
own silence: Leak Sink Bath Main learned 190 minutes.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
)

from .helpers import register_device, setup_coordinator


def _speak(hass, entities, n):
    eid = entities[0].entity_id if hasattr(entities[0], "entity_id") else entities[0]
    hass.states.async_set(eid, "on", {"zz": n})


async def test_a_report_before_the_check_does_not_learn_a_clock_jump(hass, freezer):
    device, entities = register_device(hass, "ck", name="Clock Probe")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    now = dt_util.utcnow()
    record[DEV_LAST_ACTIVITY] = (now - timedelta(minutes=5)).timestamp()
    record[DEV_TODAY_MAX] = 300.0
    mono = [1000.0]
    coord._monotonic = lambda: mono[0]
    await coord._detect_clock_reset()
    freezer.move_to(now + timedelta(hours=3))  # the wall clock jumps; the monotonic one does not
    _speak(hass, entities, 1)
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] == 300.0, "the three-hour jump was learned as the device's silence"
    # The check sees the jump and restarts the clocks; the next ordinary
    # gap is learned as before.
    mono[0] += 60.0
    await coord._detect_clock_reset()
    freezer.tick(timedelta(minutes=10))
    mono[0] += 600.0
    _speak(hass, entities, 2)
    await hass.async_block_till_done()
    assert 500.0 <= record[DEV_TODAY_MAX] <= 700.0, "after the check, the next ordinary gap was not learned"


async def test_an_unclean_load_banks_nothing(hass):
    device, _entities = register_device(hass, "bk", name="Leak Probe")
    coord = await setup_coordinator(hass)
    fell = 1_790_000_000.0
    record = dict(coord.data[DATA_DEVICES][device.id])
    record[DEV_LAST_ACTIVITY] = fell - 60
    record[DEV_TODAY_MAX] = 240.0
    loaded = {
        DATA_DEVICES: {device.id: record},
        DATA_SYSTEM_EVENTS: [{"kind": "bridge_down", "scope": "zigbee2mqtt", "when": fell, "duration": None, "detail": None}],
        "todo_items": [],
        "first_installed": "2026-07-10T00:00:00+00:00",
    }
    coord._last_alive = fell + 190 * 60
    coord._handle_unclean_restart(loaded)
    assert record[DEV_TODAY_MAX] == 240.0, "the silence before the stop was banked"
    assert record[DEV_LAST_ACTIVITY] > fell + 190 * 60, "the clock was not restarted"
