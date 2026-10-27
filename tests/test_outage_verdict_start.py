# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_outage_verdict_start.py, Version: 0.27.10 (2026-10-27)

"""An outage judged down is ended from when it went (rule UNAV-04).

When a device reports while an unavailable or unknown verdict stands,
the gap is ended from the moment the outage began, whatever start the
reporting entity holds: an unseen rename whose new id gained a later
start, or a button whose battery entity carried the outage while its
event entity rested, is never learned as quiet. An event entity at
rest says nothing about the device, so a device of nothing else is
judged by its clock, not read as down.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
)
from .helpers import record_events, register_device, registry_settled, setup_coordinator
from .outage_helpers import PIN, arm, entry_of, past_grace, rec, restart, tick, walk

H = 3600
PRESS = "2026-10-11T16:00:00.000+00:00"


def _add_entity(hass, device, domain, suffix):
    first = next(e for e in er.async_entries_for_device(er.async_get(hass), device.id))
    source = hass.config_entries.async_get_entry(first.config_entry_id)
    return er.async_get(hass).async_get_or_create(
        domain, "test", suffix, device_id=device.id, config_entry=source).entity_id


async def _ready(hass, freezer, uid, count=2, event_too=False, sensors=True):
    freezer.move_to(PIN)
    device, eids = register_device(hass, uid, entity_count=count)
    event_id = _add_entity(hass, device, "event", f"{uid}_press") if event_too else None
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
    return coord, device, eids, event_id


def _downs(events, device_id):
    return [(e.get("kind"), e.get("down_for")) for e in events if e.get("device_id") == device_id]


async def _unload(hass):
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _load(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _o02(hass, freezer, uid, flip):
    coord, device, eids, _ = await _ready(hass, freezer, uid, count=1)
    events = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * H)
    entry = await _unload(hass)
    new = f"sensor.{uid}_renamed"
    er.async_get(hass).async_update_entity(eids[0], new_entity_id=new)
    hass.states.async_remove(eids[0])
    hass.states.async_set(new, "unavailable")
    await hass.async_block_till_done()
    coord = await _load(hass, entry)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 30 * 60)
    if flip:
        # The stack restarts five minutes before the device returns:
        # unknown as it starts, unavailable again until the device speaks.
        hass.states.async_set(new, "unknown")
        await hass.async_block_till_done()
        await walk(hass, freezer, 60)
        hass.states.async_set(new, "unavailable")
        await hass.async_block_till_done()
        await walk(hass, freezer, 240)
    hass.states.async_set(new, "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    record = rec(coord, device.id)
    return record, _downs(events, device.id)


async def test_an_unseen_rename_with_a_flip_before_the_return_is_not_learned(hass: HomeAssistant, freezer):
    """Unavailable two hours, its only entity renamed while Device
    Sentinel reloads, and a stack restart five minutes before the return
    gives the new id a start of its own. The standing verdict dates the
    outage, so it is not learned as quiet."""
    record, downs = await _o02(hass, freezer, "o02f", True)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H, (
        "a 2.6-hour outage was learned after an unseen rename and a stack restart", record[DEV_TODAY_MAX])


async def _o03(hass, freezer, uid, remove):
    """A button: a battery sensor and an event entity at rest. The
    battery sensor is unavailable five hours, then the button is
    pressed."""
    coord, device, eids, ev = await _ready(hass, freezer, uid, count=1, event_too=True)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 4 * H)
    record = rec(coord, device.id)
    verdict_mid = record[DEV_FROZEN_CATEGORY]
    if remove:
        er.async_get(hass).async_remove(eids[0])
        hass.states.async_remove(eids[0])
        await registry_settled(hass)
    await walk(hass, freezer, H)
    hass.states.async_set(ev, PRESS)
    await hass.async_block_till_done()
    await tick(hass, freezer)
    return record, verdict_mid


async def test_a_dead_button_pressed_back_is_not_learned(hass: HomeAssistant, freezer):
    record, _ = await _o03(hass, freezer, "o03c", False)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H


async def test_a_dead_button_whose_battery_entity_was_removed_is_not_learned(hass: HomeAssistant, freezer):
    """The battery sensor is removed while the button is judged down: its
    start is the outage's and is kept, so the press does not learn five
    hours down as a quiet gap."""
    record, verdict_mid = await _o03(hass, freezer, "o03r", True)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H, (
        "five hours down learned after the battery entity was removed", verdict_mid, record[DEV_TODAY_MAX])


async def test_an_event_only_device_at_rest_is_not_down(hass: HomeAssistant, freezer):
    """A device of event entities only, resting at unknown fifty minutes
    after a restart, is not read as down; the press is it speaking."""
    coord, device, _, ev = await _ready(hass, freezer, "o04", sensors=False, event_too=True)
    coord = await restart(hass, freezer, down=60, before_setup=lambda: hass.states.async_set(ev, "unknown"))
    await past_grace(hass, freezer)
    record = rec(coord, device.id)
    record[DEV_TODAY_MAX] = None
    await walk(hass, freezer, 50 * 60)
    mid = record[DEV_FROZEN_CATEGORY]
    hass.states.async_set(ev, PRESS)
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert mid is None, mid
    assert record[DEV_TODAY_MAX] is not None


async def test_an_unseen_rename_then_a_restart_is_not_learned(hass: HomeAssistant, freezer):
    """The unseen rename followed by a Home Assistant restart, which gives
    the new id a start of its own: the outage is still not learned."""
    coord, device, eids, _ = await _ready(hass, freezer, "o02r", count=1)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * H)
    entry = await _unload(hass)
    new = "sensor.o02r_renamed"
    er.async_get(hass).async_update_entity(eids[0], new_entity_id=new)
    hass.states.async_remove(eids[0])
    hass.states.async_set(new, "unavailable")
    await hass.async_block_till_done()
    coord = await _load(hass, entry)
    await walk(hass, freezer, 30 * 60)

    def during():
        hass.states.async_remove(new)

    coord = await restart(hass, freezer, down=120, before_setup=during)
    hass.states.async_set(new, "unavailable")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(new, "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    record = rec(coord, device.id)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < H, (
        "a 2.6-hour outage was learned after an unseen rename and a restart", record[DEV_TODAY_MAX])

