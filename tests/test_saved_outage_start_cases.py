# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_saved_outage_start_cases.py, Version: 0.27.10 (2026-10-27)

"""The saved outage start under restarts, renames and removals
(rules FRZ-14, UNAV-04).

A device with two entities on a one-hour rhythm: an outage across a
restart is not learned; a lone entity going unavailable, or one removed
while unavailable, starts no outage; a rename changes nothing, since
the start is the device's; the debounce counts from the moment the
whole device went.
"""

from __future__ import annotations


import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from tests.helpers import register_device, setup_coordinator
from .outage_helpers import (
    PIN, arm, past_grace, rec, reload, restart, tick, verdict, walk,
)


async def _ready(hass, freezer, uid, count=2):
    freezer.move_to(PIN)
    device, eids = register_device(hass, uid, entity_count=count)
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    for eid in eids:
        hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    rec(coord, device.id)[DEV_TODAY_MAX] = None
    return coord, device, eids


# ------------------------------------------------------------ the debounce and _outage_began

async def test_stale_absence_skips_the_unavailable_debounce(hass: HomeAssistant, freezer):
    """Entity 1 goes unavailable and stays so; the device says nothing new
    for forty minutes (its rhythm is an hour). Then entity 0 blips
    unavailable for 150 seconds. Every entity reads bad only for those 150
    seconds, under the 180-second debounce, so no verdict is owed; a stamp
    dated from entity 1's start, forty minutes old, must not publish one
    at the next sweep (rule UNAV-03)."""
    coord, device, eids = await _ready(hass, freezer, "a01")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    published = []
    for _ in range(5):
        await tick(hass, freezer, step=30)
        published.append(verdict(record))
    hass.states.async_set(eids[0], "21.7")
    await hass.async_block_till_done()
    assert all(v[0] is None for v in published), (
        "a 100-second blip published unavailable: the stamp came from a stale absence", published)


async def test_stale_absence_inflates_down_for(hass: HomeAssistant, freezer):
    """As A01 but the blip lasts five minutes, so a verdict is owed. The
    recovered event's down_for counts from when the device went, so it
    reads about five minutes, not forty-five (rule UNAV-07)."""
    coord, device, eids = await _ready(hass, freezer, "a02")
    record = rec(coord, device.id)
    from tests.helpers import record_events
    from custom_components.device_sentinel.const import EVENT_RECOVERED as EVENT_DEVICE_RECOVERED
    events = record_events(hass, EVENT_DEVICE_RECOVERED)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    went = dt_util.utcnow().timestamp()
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 300)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    since = record["frozen_since"]
    hass.states.async_set(eids[0], "21.7")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    downs = [e.get("down_for") for e in events if e.get("device_id") == device.id]
    assert since >= went - 60, ("verdict dated", (went - since) / 60, "minutes before every entity was down")
    assert downs and downs[-1] < 15 * 60, ("down_for", downs)


# ------------------------------------------------------------ taint across restarts

@pytest.mark.parametrize("at", [60, 600, 1700])
@pytest.mark.parametrize("boot_event", [False, True])
async def test_restart_inside_a_30_minute_outage(hass: HomeAssistant, freezer, at, boot_event):
    """Every entity unavailable for 30 minutes (two minutes of it Home
    Assistant stopped); a restart at `at` seconds in. 28 minutes is far
    past the 10-minute floor: the gap is not learned."""
    coord, device, eids = await _ready(hass, freezer, f"a03{at}{boot_event}")
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, at)

    def boot():
        if boot_event:
            for eid in eids:
                hass.states.async_remove(eid)
                hass.states.async_set(eid, "unavailable")
    coord = await restart(hass, freezer, down=120, before_setup=boot)
    record = rec(coord, device.id)
    await walk(hass, freezer, 1800 - at - 120)
    for eid in eids:
        hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is None, ("30-minute outage learned across a restart", record[DEV_TODAY_MAX])


@pytest.mark.parametrize("before,down,after,want_taint", [
    (180, 1200, 180, False),   # an ordinary restart inside a short absence
    (420, 120, 300, True),     # 12 minutes absent, 2 of them stopped: 10 counted, at the floor
    (60, 3600, 400, False),    # an hour stopped, under eight minutes absent, back after the grace
    (1000, 120, 600, True),    # 1,600 s counted, past the 1,446 s debounce
    (700, 1800, 700, False),   # 1,400 s counted with half an hour stopped
])
async def test_stopped_within(hass: HomeAssistant, freezer, before, down, after, want_taint):
    """The stop is taken out of the absence (rule FRZ-14)."""
    coord, device, eids = await _ready(hass, freezer, f"a04{before}{down}")
    record = rec(coord, device.id)
    debounce = coord._taint_debounce(record)
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, before)
    coord = await restart(hass, freezer, down=down)
    record = rec(coord, device.id)
    await walk(hass, freezer, after)
    for eid in eids:
        hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    counted = before + after
    lost = record[DEV_TODAY_MAX] is None
    if counted >= debounce:
        assert lost, ("counted absence past the debounce but learned", record[DEV_TODAY_MAX])
    else:
        assert not lost, ("ordinary restart cost the gap", record[DEV_TAINTED])


async def test_rename_while_absent(hass: HomeAssistant, freezer):
    """A single-entity device unavailable for three hours; the person
    renames the entity two minutes before it returns. The three-hour
    outage must not be learned."""
    coord, device, eids = await _ready(hass, freezer, "a05", count=1)
    old = eids[0]
    hass.states.async_set(old, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 3600 - 120)
    record = rec(coord, device.id)
    new = "sensor.renamed_a05"
    er.async_get(hass).async_update_entity(old, new_entity_id=new)
    await hass.async_block_till_done()
    hass.states.async_remove(old)
    hass.states.async_set(new, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    hass.states.async_set(new, "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < 3600, (
        "three-hour outage learned after a rename", record[DEV_TODAY_MAX])


async def test_a_removed_entity_leaves_no_outage(hass: HomeAssistant, freezer):
    """Entity 1 goes unavailable and is then removed from Home Assistant.
    The device never went down as a whole, so a later two-minute blip on
    entity 0 is not dated from entity 1."""
    coord, device, eids = await _ready(hass, freezer, "a06")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    er.async_get(hass).async_remove(eids[1])
    hass.states.async_remove(eids[1])
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    seen = []
    for _ in range(5):
        await tick(hass, freezer, step=30)
        seen.append(verdict(record))
    assert all(v[0] is None for v in seen), ("removed entity's absence published a 110 s blip", seen)


async def test_partial_absence_cleared_by_report(hass: HomeAssistant, freezer):
    """Control: entity 1 unavailable, the device reports through entity 0
    with a moving clock: entity 1's start is forgotten untainted."""
    coord, device, eids = await _ready(hass, freezer, "a07")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    hass.states.async_set(eids[0], "22.5")
    await hass.async_block_till_done()
    assert record[DEV_DOWN_SINCE] is None
    assert not record[DEV_TAINTED]


async def test_reload_keeps_the_start(hass: HomeAssistant, freezer):
    """Absence saved; a reload; the device returns 20 minutes in."""
    coord, device, eids = await _ready(hass, freezer, "a08")
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30)  # no sweep, no critical save yet
    coord = await reload(hass)
    record = rec(coord, device.id)
    await walk(hass, freezer, 30 * 60)
    for eid in eids:
        hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is None, record[DEV_TODAY_MAX]


async def test_return_missed_across_a_restart(hass: HomeAssistant, freezer):
    """Entity 1 goes unavailable (entity 0 holds its value; the device is
    quiet). Home Assistant restarts and entity 1 comes back with a value
    before Device Sentinel is listening, so no event ends the absence.
    Thirty minutes later every entity blips unavailable for 150 seconds:
    under the debounce, so nothing should be published."""
    coord, device, eids = await _ready(hass, freezer, "a09")
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)

    def back():
        hass.states.async_set(eids[1], "21.5")
    coord = await restart(hass, freezer, down=120, before_setup=back)
    record = rec(coord, device.id)
    await walk(hass, freezer, 30 * 60)
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    seen = []
    for _ in range(5):
        await tick(hass, freezer, step=30)
        seen.append(verdict(record))
    assert all(v[0] is None for v in seen), ("150 s blip published from a stale absence", seen)
