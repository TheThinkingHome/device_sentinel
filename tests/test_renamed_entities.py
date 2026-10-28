# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_renamed_entities.py, Version: 0.27.10 (2026-10-27)

"""Entities renamed, removed or added back during an outage (rules
UNAV-04, FRZ-14).

The outage start is the device's, saved when it goes down as a whole,
so a rename or a removal, seen or not, cannot lose it, and the value
Home Assistant moves across on a rename is not the device speaking. An
entity that goes unavailable alone, while another of the device's own
entities holds a value, starts no outage, whatever then happens to it:
a disabled entity or another integration's holds nothing, and an event
entity resting at unknown holds.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_MUTED_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from .helpers import record_events, register_device, registry_settled, setup_coordinator
from .outage_helpers import (
    PIN, Runtime, arm, entry_of, esp_device, esp_source, past_grace, rec, tick, walk,
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


async def _rename(hass, old, new, state):
    er.async_get(hass).async_update_entity(old, new_entity_id=new)
    await hass.async_block_till_done()
    hass.states.async_remove(old)
    await registry_settled(hass)
    hass.states.async_set(new, state)
    await hass.async_block_till_done()


async def test_renamed_twice_while_absent(hass: HomeAssistant, freezer):
    """A one-entity device unavailable three hours; renamed ten minutes
    before it returns, and again five minutes before. The outage began
    under the first id; the latest orphan start is the second id's."""
    coord, device, eids = await _ready(hass, freezer, "o01", count=1)
    record = rec(coord, device.id)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 3600 - 600)
    await _rename(hass, eids[0], "sensor.o01_second", "unavailable")
    await walk(hass, freezer, 300)
    await _rename(hass, "sensor.o01_second", "sensor.o01_third", "unavailable")
    await walk(hass, freezer, 300)
    hass.states.async_set("sensor.o01_third", "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < 3600, (
        "three-hour outage learned after two renames", record[DEV_TODAY_MAX])


async def test_rename_when_not_absent(hass: HomeAssistant, freezer):
    """Control: renamed while healthy, the device reports on its rhythm:
    the gap is learned."""
    coord, device, eids = await _ready(hass, freezer, "o02")
    record = rec(coord, device.id)
    await walk(hass, freezer, 600)
    await _rename(hass, eids[1], "sensor.o02_new", "21.5")
    await walk(hass, freezer, 2400)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 2900


async def test_a_lone_absent_entity_renamed_leaves_the_healthy_gap_learned(hass: HomeAssistant, freezer):
    """Entity 1 alone goes unavailable (the device is quiet, entity 0
    holds its value); it is renamed. Fifty minutes after its last report
    the device reports through entity 0, on its rhythm. The gap is
    learned, because the renamed entity's start is not an outage
    (rule UNAV-04)."""
    coord, device, eids = await _ready(hass, freezer, "o03")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 600)
    await _rename(hass, eids[1], "sensor.o03_new", "unavailable")
    await walk(hass, freezer, 2400)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is not None, "a healthy 50-minute gap was set aside"


async def test_a_removed_absent_entity_leaves_the_healthy_gap_learned(hass: HomeAssistant, freezer):
    """As O03 with entity 1 removed instead of renamed."""
    coord, device, eids = await _ready(hass, freezer, "o04")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 600)
    er.async_get(hass).async_remove(eids[1])
    hass.states.async_remove(eids[1])
    await registry_settled(hass)
    await walk(hass, freezer, 2400)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is not None, "a healthy 50-minute gap was set aside"


async def test_foreign_entity_speaks_during_outage(hass: HomeAssistant, freezer):
    """Every own entity down three hours; a foreign entity on the device
    (another integration's) changes value inside. The outage must not
    be learned."""
    coord, device, eids = await _ready(hass, freezer, "o05")
    other = MockConfigEntry(domain="battery_notes")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    foreign = er.async_get(hass).async_get_or_create(
        "sensor", "battery_notes", "o05f", device_id=device.id, config_entry=other).entity_id
    hass.states.async_set(foreign, "1")
    await registry_settled(hass)
    record = rec(coord, device.id)
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3600)
    hass.states.async_set(foreign, "2")
    hass.states.async_set(foreign, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 7200)
    hass.states.async_set(eids[1], "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is None


async def test_all_entities_removed_and_readded_inside_outage(hass: HomeAssistant, freezer):
    """Every entity down three hours; ten minutes before the return both
    are removed from Home Assistant, and re-added with the same ids as
    the device comes back. The outage must not be learned."""
    coord, device, eids = await _ready(hass, freezer, "o06")
    record = rec(coord, device.id)
    source = hass.config_entries.async_get_entry(er.async_get(hass).async_get(eids[0]).config_entry_id)
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 3600 - 600)
    uids = [er.async_get(hass).async_get(eid).unique_id for eid in eids]
    for eid in eids:
        er.async_get(hass).async_remove(eid)
        hass.states.async_remove(eid)
    await registry_settled(hass)
    await walk(hass, freezer, 600)
    back = []
    for uid in uids:
        back.append(er.async_get(hass).async_get_or_create(
            "sensor", "test", uid, device_id=device.id, config_entry=source).entity_id)
    await registry_settled(hass)
    for eid in back:
        hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is None, record[DEV_TODAY_MAX]


async def test_esphome_drop_after_stale_entity_absence(hass: HomeAssistant, freezer):
    """An awake ESPHome device of buttons (silent); its update entity
    reads unavailable for a day with the connection up. Then the
    connection drops for twenty minutes. The verdict should be dated
    from the drop, and the recovered event say about twenty minutes."""
    freezer.move_to(PIN)
    runtime = Runtime(False, True)
    source = esp_source(hass, runtime)
    device, eids = esp_device(hass, source, "o07", domains=("binary_sensor", "update"))
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    events = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(eids[0], "off")
    hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 86400, step=600)
    runtime.available = False
    went = dt_util.utcnow().timestamp()
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 1200)
    since = record[DEV_FROZEN_SINCE]
    runtime.available = True
    hass.states.async_set(eids[0], "on")
    hass.states.async_set(eids[1], "off")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    downs = [e.get("down_for") for e in events if e.get("device_id") == device.id]
    assert record[DEV_FROZEN_CATEGORY] is None
    assert since is not None and abs(since - went) <= 90, since - went
    assert downs and abs(downs[-1] - 1200) <= 180, downs


async def test_partial_absence_then_whole_device(hass: HomeAssistant, freezer):
    """Entity 1 unavailable at t0 (the device quiet); entity 0 at t0 + 2 h.
    The device is dated down from the latest start. Then a restart inside
    the outage, five minutes before the verdict would be read: the
    verdict is still dated from t0 + 2 h (rule UNAV-04)."""
    coord, device, eids = await _ready(hass, freezer, "o08")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 3600)
    hass.states.async_set(eids[0], "unavailable")
    whole = dt_util.utcnow().timestamp()
    await hass.async_block_till_done()
    from tests.outage_helpers import restart
    coord = await restart(hass, freezer, down=60)
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 600)
    since = record[DEV_FROZEN_SINCE]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert abs(since - whole) <= 90, since - whole


async def test_rename_of_a_frozen_device(hass: HomeAssistant, freezer):
    """A frozen device (dead, values held); a person renames one of its
    entities. Home Assistant writes the new id's held value. That is
    not the device speaking: the verdict should stand."""
    from custom_components.device_sentinel.const import FREEZE_CATEGORY_FROZEN
    coord, device, eids = await _ready(hass, freezer, "o09")
    record = rec(coord, device.id)
    events = record_events(hass, EVENT_RECOVERED)
    for _ in range(400):
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            break
        await walk(hass, freezer, 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    await _rename(hass, eids[1], "sensor.o09_new", "21.5")
    await tick(hass, freezer)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, events


async def test_a_removed_lone_start_does_not_turn_a_blip_into_an_outage(hass: HomeAssistant, freezer):
    """Entity 1 alone goes unavailable and is removed five minutes later,
    entity 0 holding. Fifty minutes after the device's last report,
    entity 0 blips for thirty seconds and comes back with a fresh value:
    the removed entity's start went with it, and the gap is learned."""
    coord, device, eids = await _ready(hass, freezer, "o10")
    record = rec(coord, device.id)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 300)
    er.async_get(hass).async_remove(eids[1])
    hass.states.async_remove(eids[1])
    await registry_settled(hass)
    await walk(hass, freezer, 2700)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30)
    hass.states.async_set(eids[0], "22.0")
    await hass.async_block_till_done()
    assert record[DEV_TODAY_MAX] is not None, "a healthy gap discarded for a removed entity's start"


async def test_a_muted_device_renamed_unseen_during_a_reload(hass: HomeAssistant, freezer):
    """A muted device holds no verdict but keeps learning. Unavailable
    three hours, its only entity renamed while Device Sentinel reloads,
    back under the new id: the outage is not learned as its quiet."""
    coord, device, eids = await _ready(hass, freezer, "o11", count=1)
    entry = entry_of(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MUTED_DEVICES: [device.id]})
    await hass.async_block_till_done()
    await registry_settled(hass)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 3600 - 600)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    new = "sensor.o11_renamed"
    er.async_get(hass).async_update_entity(eids[0], new_entity_id=new)
    hass.states.async_remove(eids[0])
    hass.states.async_set(new, "unavailable")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 300)
    hass.states.async_set(new, "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < 3600, record[DEV_TODAY_MAX]


async def _lone_blip_then_sibling(hass, freezer, uid, coord, device, eids):
    record = rec(coord, device.id)
    await walk(hass, freezer, 3000 - 120)
    hass.states.async_set(eids[1], "22.4")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    return record


async def test_a_lone_blipping_entity_moved_away_leaves_the_gap_learned(hass: HomeAssistant, freezer):
    """Entity 0 alone goes unavailable and is moved to another device;
    entity 1 reports on the device's rhythm. Its start is left behind,
    but a healthy entity reporting is not a return, so the gap is
    learned (rule FRZ-14)."""
    coord, device, eids = await _ready(hass, freezer, "o12")
    other, _ = register_device(hass, "o12_other", entity_count=1)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    er.async_get(hass).async_update_entity(eids[0], device_id=other.id)
    await registry_settled(hass)
    record = await _lone_blip_then_sibling(hass, freezer, "o12", coord, device, eids)
    assert record[DEV_TODAY_MAX] is not None and abs(record[DEV_TODAY_MAX] - 3000) < 300, record[DEV_TODAY_MAX]


async def test_a_lone_blipping_entity_removed_during_a_reload_leaves_the_gap_learned(hass: HomeAssistant, freezer):
    """As above, with entity 0 removed while Device Sentinel reloads."""
    coord, device, eids = await _ready(hass, freezer, "o13")
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    er.async_get(hass).async_remove(eids[0])
    hass.states.async_remove(eids[0])
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    await past_grace(hass, freezer)
    record = await _lone_blip_then_sibling(hass, freezer, "o13", coord, device, eids)
    assert record[DEV_TODAY_MAX] is not None and abs(record[DEV_TODAY_MAX] - 3000) < 600, record[DEV_TODAY_MAX]


async def test_a_disabled_sibling_does_not_make_a_removal_lone(hass: HomeAssistant, freezer):
    """A device whose one enabled entity is unavailable three hours, with
    a sibling disabled by its integration. The entity is removed and
    added back ten minutes before the device returns: a disabled entity
    holds no value, so the start is kept and the outage is not learned
    (rule UNAV-04)."""
    freezer.move_to(PIN)
    device, eids = register_device(hass, "o14", entity_count=2)
    reg = er.async_get(hass)
    reg.async_update_entity(eids[1], disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    hass.states.async_set(eids[0], "21.5")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    record = rec(coord, device.id)
    record[DEV_TODAY_MAX] = None
    await walk(hass, freezer, 600)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 3600 - 600)
    old = reg.async_get(eids[0])
    source = hass.config_entries.async_get_entry(old.config_entry_id)
    reg.async_remove(eids[0])
    hass.states.async_remove(eids[0])
    await registry_settled(hass)
    again = reg.async_get_or_create("sensor", "test", old.unique_id, device_id=device.id, config_entry=source)
    hass.states.async_set(again.entity_id, "unavailable")
    await registry_settled(hass)
    await walk(hass, freezer, 600)
    hass.states.async_set(again.entity_id, "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is None or record[DEV_TODAY_MAX] < 3600, record[DEV_TODAY_MAX]


async def test_a_removed_lone_blip_beside_a_resting_event_entity(hass: HomeAssistant, freezer):
    """A button: a battery sensor and an event entity resting at
    unknown. The sensor blips alone and is removed; fifty minutes later
    the button is pressed. A resting event entity is not absent, so the
    sensor's start went with it and the gap is learned (rule UNAV-04)."""
    coord, device, eids = await _ready(hass, freezer, "o15", count=1)
    first = er.async_get(hass).async_get(eids[0])
    source = hass.config_entries.async_get_entry(first.config_entry_id)
    press = er.async_get(hass).async_get_or_create(
        "event", "test", "o15_press", device_id=device.id, config_entry=source).entity_id
    hass.states.async_set(press, "unknown")
    await registry_settled(hass)
    record = rec(coord, device.id)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    er.async_get(hass).async_remove(eids[0])
    hass.states.async_remove(eids[0])
    await registry_settled(hass)
    await walk(hass, freezer, 3000 - 120)
    hass.states.async_set(press, "2026-10-11T16:00:00.000+00:00")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is not None and abs(record[DEV_TODAY_MAX] - 3000) < 300, record[DEV_TODAY_MAX]


async def test_an_old_orphan_does_not_date_a_short_blip(hass: HomeAssistant, freezer):
    """Entity 0 blips alone and is removed while Device Sentinel reloads,
    so its start is left behind. Twenty minutes later entity 1 is
    unavailable for one minute: that blip has its own start and is a
    mesh blip, so the gap is learned (rule FRZ-14)."""
    coord, device, eids = await _ready(hass, freezer, "o16")
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    er.async_get(hass).async_remove(eids[0])
    hass.states.async_remove(eids[0])
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    await past_grace(hass, freezer)
    record = rec(coord, device.id)
    await walk(hass, freezer, 20 * 60)
    hass.states.async_set(eids[1], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    hass.states.async_set(eids[1], "22.0")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert record[DEV_TODAY_MAX] is not None, "a one-minute blip dated from an old orphan"
