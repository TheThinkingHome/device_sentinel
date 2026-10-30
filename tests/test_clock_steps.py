# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_clock_steps.py, Version: 0.27.15 (2026-10-30)

"""Time across a clock step is unknown (rule FRZ-21).

At a step every clock and outage start restarts, an outage running
across it is not learned, every verdict stands until the device
reports, and every "down for" counts from the step.
"""

from __future__ import annotations

import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
)

from .helpers import record_events, register_device, setup_coordinator
from .outage_helpers import (
    PIN, Runtime, arm, esp_device, esp_source, past_grace, rec, restart,
)

H = 3600
DOWN = "down_since"
PRESS = "2026-10-11T16:00:00.000+00:00"


def add_entity(hass, device, domain, suffix, **kw):
    first = next(e for e in er.async_entries_for_device(er.async_get(hass), device.id))
    source = hass.config_entries.async_get_entry(first.config_entry_id)
    return er.async_get(hass).async_get_or_create(
        domain, "test", suffix, device_id=device.id, config_entry=source, **kw).entity_id


async def ready(hass, freezer, uid, count=2, event_too=False, sensors=True, extra=()):
    freezer.move_to(PIN)
    device, eids = register_device(hass, uid, entity_count=count)
    event_id = add_entity(hass, device, "event", f"{uid}_press") if event_too else None
    extras = [add_entity(hass, device, d, f"{uid}_x{i}") for i, d in enumerate(extra)]
    if not sensors:
        for eid in eids:
            er.async_get(hass).async_remove(eid)
        eids = []
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    for eid in eids:
        hass.states.async_set(eid, "21.5")
    if event_id:
        hass.states.async_set(event_id, "unknown")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for eid in eids:
        hass.states.async_set(eid, "21.6")
    if event_id and not eids:
        hass.states.async_set(event_id, "2026-10-11T15:00:00.000+00:00")
    await hass.async_block_till_done()
    rec(coord, device.id)[DEV_TODAY_MAX] = None
    return coord, device, eids, event_id, extras


def downs(events, device_id):
    return [(e.get("kind"), e.get("down_for")) for e in events if e.get("device_id") == device_id]




def _mono(coord):
    box = {"off": 0.0}
    coord._monotonic = lambda: time.monotonic() + box["off"]
    return box


async def _minute(hass, freezer, coord, n=1):
    for _ in range(n):
        freezer.tick(timedelta(seconds=60))
        await coord._on_render_tick(None)
        await hass.async_block_till_done()


async def _step(hass, freezer, coord, box, seconds):
    freezer.tick(timedelta(seconds=seconds))
    box["off"] -= seconds
    await _minute(hass, freezer, coord)


async def test_two_clock_steps_in_a_row_count_from_the_second(hass: HomeAssistant, freezer):
    """Unavailable thirty minutes, the clock set forward two hours and back
    two hours a minute later, back twenty minutes after: the verdict
    holds, nothing is learned, and down for counts from the second step."""
    coord, device, eids, _, _ = await ready(hass, freezer, "k03", count=1)
    box = _mono(coord)
    events = record_events(hass, EVENT_RECOVERED)
    record = rec(coord, device.id)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await _minute(hass, freezer, coord, 30)
    await _step(hass, freezer, coord, box, 2 * H)
    await _step(hass, freezer, coord, box, -2 * H)
    seen = []
    for _ in range(20):
        await _minute(hass, freezer, coord)
        seen.append(record[DEV_FROZEN_CATEGORY])
    hass.states.async_set(eids[0], "22")
    await hass.async_block_till_done()
    await _minute(hass, freezer, coord)
    assert set(seen) == {"unavailable"}, seen
    assert record[DEV_TODAY_MAX] is None
    got = downs(events, device.id)
    assert got and 0 <= got[-1][1] <= 60 * 60, got



async def _esp(hass, freezer, uid):
    freezer.move_to(PIN)
    runtime = Runtime(False, available=True)
    source = esp_source(hass, runtime)
    device, eids = esp_device(hass, source, uid, domains=("sensor", "binary_sensor"))
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    for eid in eids:
        hass.states.async_set(eid, "on" if eid.startswith("binary") else "21.5")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    rec(coord, device.id)[DEV_TODAY_MAX] = None
    return coord, device, eids, runtime



async def test_an_esphome_return_at_a_clock_step_is_not_counted_across_it(hass: HomeAssistant, freezer):
    """An ESPHome connection is down forty minutes and comes back with no
    entity state change in the minute the clock is set forward two hours:
    down for counts from the step, never with the two hours added."""
    coord, device, eids, runtime = await _esp(hass, freezer, "k04")
    box = _mono(coord)
    events = record_events(hass, EVENT_RECOVERED)
    record = rec(coord, device.id)
    runtime.available = False
    await _minute(hass, freezer, coord, 40)
    mid = record[DEV_FROZEN_CATEGORY]
    runtime.available = True
    await _step(hass, freezer, coord, box, 2 * H)
    await _minute(hass, freezer, coord, 3)
    assert mid == "unavailable"
    got = downs(events, device.id)
    assert got and 0 <= got[-1][1] <= 5 * 60, got



async def test_an_outage_across_a_clock_step_is_not_learned(hass: HomeAssistant, freezer):
    """Unavailable thirty minutes, the clock set forward two hours, back
    twenty minutes later: the outage's length across the step is unknown,
    so the gap it ends is not learned."""
    coord, device, eids, _, _ = await ready(hass, freezer, "k07", count=1)
    box = _mono(coord)
    record = rec(coord, device.id)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await _minute(hass, freezer, coord, 30)
    await _step(hass, freezer, coord, box, 2 * H)
    await _minute(hass, freezer, coord, 20)
    hass.states.async_set(eids[0], "22")
    await hass.async_block_till_done()
    await _minute(hass, freezer, coord)
    assert record[DEV_TODAY_MAX] is None, "an outage straddling a clock step was learned"



async def test_a_frozen_device_stays_frozen_across_a_restart_and_a_clock_step(hass: HomeAssistant, freezer):
    """Frozen, Home Assistant restarted (five minutes down), and later the
    clock set forward an hour: the verdict holds and no recovery is told,
    since the restart's downtime was measured in the old clock."""
    coord, device, eids, _, _ = await ready(hass, freezer, "k09", count=1)
    events = record_events(hass, EVENT_RECOVERED)
    await _minute(hass, freezer, coord, 3 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    coord = await restart(hass, freezer, down=300)
    await past_grace(hass, freezer)
    box = _mono(coord)
    record = rec(coord, device.id)
    await _minute(hass, freezer, coord, 30)
    await _step(hass, freezer, coord, box, H)
    seen = []
    for _ in range(10):
        await _minute(hass, freezer, coord)
        seen.append(record[DEV_FROZEN_CATEGORY])
    assert set(seen) == {"frozen"}, seen
    assert not downs(events, device.id)


async def test_a_trouble_across_a_clock_step_and_a_restart_counts_from_the_step(hass: HomeAssistant, freezer):
    """Frozen, the clock set forward an hour, then Home Assistant
    restarted: the step is forgotten at the restart, so the start the
    freeze saved moved to the step with it, and the recovery counts from
    the step, not across the hour nobody lived (rules UNAV-07, FRZ-21)."""
    from homeassistant.util import dt as dt_util

    coord, device, eids, _, _ = await ready(hass, freezer, "k10", count=1)
    await _minute(hass, freezer, coord, 3 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    box = _mono(coord)
    await _step(hass, freezer, coord, box, H)
    stepped = dt_util.utcnow().timestamp()
    assert abs(rec(coord, device.id)["down_from"] - stepped) <= 120, rec(coord, device.id)["down_from"]
    coord = await restart(hass, freezer, down=300)
    await past_grace(hass, freezer)
    events = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    back = dt_util.utcnow().timestamp()
    await _minute(hass, freezer, coord, 3)
    told = downs(events, device.id)
    assert told and told[0][1] is not None, told
    assert told[0][1] <= back - stepped + 120, (told, back - stepped)
