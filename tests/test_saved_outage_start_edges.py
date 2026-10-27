# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_saved_outage_start_edges.py, Version: 0.27.10 (2026-10-27)

"""The device's saved outage start at its edges (rule UNAV-04).

Set aside, a device's outage is not followed, so its return reads it
afresh. A clock step restarts the start at the moment it is noticed, as
it restarts the device clocks (rule FRZ-21). A button never pressed
rests, as an event entity does. With nothing saved, as at the upgrade,
a standing unavailable verdict gives the start.
"""

from __future__ import annotations

import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
    STORAGE_CLOCKS_KEY,
)

from .helpers import record_events, register_device, registry_settled, setup_coordinator
from .outage_helpers import PIN, arm, entry_of, past_grace, rec, tick, walk

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


async def unload(hass):
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def load(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def options(hass, **changes):
    entry = entry_of(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **changes})
    await hass.async_block_till_done()
    await registry_settled(hass)
    return entry_of(hass).runtime_data


async def aside(hass, device, on):
    return await options(hass, **{CONF_EXCLUDED_DEVICES: [device.id] if on else []})


async def test_an_outage_while_set_aside_starts_afresh_on_return(hass: HomeAssistant, freezer):
    """Down at t0 (start saved), set aside, back up while aside, down again
    while aside one minute before it is taken back. The new outage is a
    minute old: the unavailable verdict must wait out its debounce, and the
    recovery's down_for must not count the stale start from hours before."""
    coord, device, eids, _, _ = await ready(hass, freezer, "e01", count=1)
    events = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    coord = await aside(hass, device, True)
    await walk(hass, freezer, 2 * H)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * H)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    went = dt_util.utcnow().timestamp()
    await walk(hass, freezer, 60)
    coord = await aside(hass, device, False)
    record = rec(coord, device.id)
    await tick(hass, freezer, step=60, n=2)
    first = record[DEV_FROZEN_CATEGORY]
    await walk(hass, freezer, 20 * 60)
    hass.states.async_set(eids[0], "22.5")
    await hass.async_block_till_done()
    want = dt_util.utcnow().timestamp() - went
    await tick(hass, freezer)
    got = downs(events, device.id)
    assert got and abs(got[-1][1] - want) <= 300, (got, want)
    assert first != FREEZE_CATEGORY_UNAVAILABLE, "verdict published three minutes into a drop, inside the debounce"


async def test_a_device_down_through_a_stretch_set_aside_counts_from_its_return(hass: HomeAssistant, freezer):
    """Down, set aside three hours while still down, taken back still
    down, back an hour later: not learned, and down for counts from the
    return, since nobody watched it while it was set aside (rule WATCH-08)."""
    coord, device, eids, _, _ = await ready(hass, freezer, "e02", count=1)
    events = record_events(hass, EVENT_RECOVERED)
    went = dt_util.utcnow().timestamp()
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    coord = await aside(hass, device, True)
    await walk(hass, freezer, 3 * H)
    coord = await aside(hass, device, False)
    back_at = dt_util.utcnow().timestamp()
    record = rec(coord, device.id)
    await walk(hass, freezer, H)
    hass.states.async_set(eids[0], "22.5")
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H
    got = downs(events, device.id)
    # The three hours set aside are nobody's watching, so down for
    # counts from the return (rule WATCH-08).
    assert got and got[-1][1] <= now - back_at + 300, (got, now - went, now - back_at)


async def _minute(hass, freezer, coord, n=1):
    for _ in range(n):
        freezer.tick(timedelta(seconds=60))
        await coord._on_render_tick(None)
        await hass.async_block_till_done()


async def _run(hass, freezer, uid, step, drop_after_step, gap=20 * 60, pre_down=0):
    coord, device, eids, _, _ = await ready(hass, freezer, uid, count=1)
    box = {"off": 0.0}
    coord._monotonic = lambda: time.monotonic() + box["off"]
    events = record_events(hass, EVENT_RECOVERED)
    record = rec(coord, device.id)
    await _minute(hass, freezer, coord, 2)
    real = 0.0  # real seconds elapsed since the drop
    if pre_down:
        hass.states.async_set(eids[0], "unavailable")
        await hass.async_block_till_done()
        await _minute(hass, freezer, coord, pre_down // 60)
        real += pre_down
    freezer.tick(timedelta(seconds=20))
    if not pre_down and not drop_after_step:
        hass.states.async_set(eids[0], "unavailable")
        await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=step))
    box["off"] -= step
    freezer.tick(timedelta(seconds=10))
    if not pre_down and drop_after_step:
        hass.states.async_set(eids[0], "unavailable")
        await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    real += 40 if not (not pre_down and drop_after_step) else 30
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    seen = []
    for _ in range(gap // 60):
        await _minute(hass, freezer, coord)
        seen.append(record[DEV_FROZEN_CATEGORY])
    real += gap
    hass.states.async_set(eids[0], "22.5")
    await hass.async_block_till_done()
    # Its recovery is told after a minute's wait (rule LIST-06).
    await _minute(hass, freezer, coord, 2)
    return downs(events, device.id), real, seen


async def test_a_drop_just_after_a_clock_set_back(hass: HomeAssistant, freezer):
    """Clock set back two hours; the device drops ten seconds later, before
    the minute check that notices the step. Its start restarts at the
    check: the debounce is kept and down for is about the drop's length."""
    got, real, seen = await _run(hass, freezer, "e03", -2 * H, True)
    assert got and abs(got[-1][1] - real) <= 300, (got, real)
    assert seen[0] != FREEZE_CATEGORY_UNAVAILABLE, seen[:5]


async def test_a_drop_just_before_a_clock_set_forward(hass: HomeAssistant, freezer):
    """The device drops and the debounce starts; the clock is set forward
    two hours before the next check. Both restart at the check: the
    verdict waits out its debounce, and down for is not two hours long."""
    got, real, seen = await _run(hass, freezer, "e04", 2 * H, False)
    assert got and abs(got[-1][1] - real) <= 300, (got, real)
    assert seen[0] != FREEZE_CATEGORY_UNAVAILABLE, seen[:5]


async def test_a_drop_just_before_a_clock_set_back_is_still_told(hass: HomeAssistant, freezer):
    """As above with the clock set back two hours: the debounce does not
    lie in the future, so a device down twenty minutes is published
    unavailable."""
    got, real, seen = await _run(hass, freezer, "e07", -2 * H, False)
    assert FREEZE_CATEGORY_UNAVAILABLE in seen, seen


async def test_an_unavailable_verdict_across_a_clock_step_counts_from_the_step(hass: HomeAssistant, freezer):
    """Unavailable thirty minutes, the clock set forward or back two hours,
    back twenty minutes later: the start restarts at the step, so down for
    counts from it, never negative and never two hours long."""
    for uid, step in (("e05", 2 * H), ("e06", -2 * H)):
        got, real, seen = await _run(hass, freezer, uid, step, False, pre_down=30 * 60)
        assert got and 0 <= got[-1][1] and abs(got[-1][1] - (real - 30 * 60)) <= 300, (got, real)

async def test_a_remote_with_a_resting_button_is_not_down(hass: HomeAssistant, freezer):
    """A remote with an action entity and an identify button never pressed:
    the action entity rests at unknown and the button reads unknown. It must
    not read down, and a press must be learned."""
    coord, device, _, ev, extras = await ready(hass, freezer, "e08", sensors=False, event_too=True,
                                               extra=("button",))
    record = rec(coord, device.id)
    hass.states.async_set(extras[0], "unknown")
    hass.states.async_set(ev, "unknown")
    await hass.async_block_till_done()
    seen = set()
    for _ in range(50):
        await walk(hass, freezer, 60)
        seen.add(record[DEV_FROZEN_CATEGORY])
    hass.states.async_set(ev, "2026-10-11T17:00:00.000+00:00")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    # The press (3000 s) is learned: a never-pressed button rests, so it
    # is not the device down and nothing is tainted.
    assert record[DEV_TODAY_MAX] is not None, "the first press after a restart was not learned"
    # The unknown verdict on a device at rest.
    assert seen == {None}, seen


async def _upgrade(hass, hass_storage, freezer, uid, back_during):
    coord, device, eids, _, _ = await ready(hass, freezer, uid, count=1)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * H)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    entry = await unload(hass)
    # The file as an older release left it: no saved outage start.
    hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"][device.id].pop(DOWN, None)
    freezer.tick(120)
    if back_during:
        hass.states.async_set(eids[0], "25")
    coord = await load(hass, entry)
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 10 * 60)
    if not back_during:
        hass.states.async_set(eids[0], "25")
        await hass.async_block_till_done()
        await walk(hass, freezer, 10 * 60)
    hass.states.async_set(eids[0], "26")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    return record


async def test_the_upgrade_with_a_device_back_during_the_restart(hass: HomeAssistant, hass_storage, freezer):
    """Unavailable three hours with the verdict standing, back while Home
    Assistant restarts into the release that saves the outage start. The
    three hours must not be learned; the standing verdict says when it
    went (rule UNAV-04)."""
    record = await _upgrade(hass, hass_storage, freezer, "e09", True)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H, record[DEV_TODAY_MAX]


