# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v060_todo_sync.py, Version: 0.6.0 (2026-07-21)

"""0.6.0 tests: the detection-to-todo sync.

One item per device, keyed by device_id, however many detections tag
it. Added on first appearance, text following the kinds as they come
and go, deleted the moment the last one clears, open or acknowledged
alike. The acknowledgment and its check time are never touched by
the sync. Every addition lands in the journal and fires the
dispatcher signal, the Step 8 contract.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_TODO_JOURNAL,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    SIGNAL_PROBLEM_ADDITION,
    TODO_KIND_BATTERY,
)

DOMAIN = "device_sentinel"
LIST_ENTITY = "todo.device_sentinel_problem_list"


def _register_device(hass, uid: str, name: str, battery: bool = False):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent_reg = er.async_get(hass)
    plain = ent_reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    entity_ids = {"plain": plain.entity_id}
    if battery:
        pct = ent_reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
        entity_ids["pct"] = pct.entity_id
    return device, entity_ids


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _freeze(coord, device_id, since=1_000_000.0,
            category=FREEZE_CATEGORY_FROZEN):
    """Plant a stored down verdict, the sync's freeze-family input."""
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = since


def _clear_freeze(coord, device_id):
    record = coord.data["devices"][device_id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None


def _battery_low(coord, device_id, level=14.0,
                 since="2026-07-20T15:02:00+00:00"):
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_SINCE] = since


def _item_for(coord, device_id):
    for record in coord.todo_items:
        if record["device_id"] == device_id:
            return record
    return None


async def test_detection_adds_and_recovery_deletes(hass: HomeAssistant):
    """The core lifecycle: appear on detection, go on recovery."""
    device, eids = _register_device(hass, "s1", "Presence Guest")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    _freeze(coord, device.id)
    coord._sync_problem_list()
    item = _item_for(coord, device.id)
    assert item is not None
    assert item["summary"] == "Presence Guest: frozen"
    assert item["sort_name"] == "Presence Guest"
    assert item["status"] == "needs_action"
    assert item["kinds"] == {FREEZE_CATEGORY_FROZEN: 1_000_000.0}

    _clear_freeze(coord, device.id)
    coord._sync_problem_list()
    assert _item_for(coord, device.id) is None


async def test_one_item_per_device_across_lists(hass: HomeAssistant):
    """A device frozen and battery-low carries two kinds, one item,
    the name front and center, freeze first then battery."""
    device, eids = _register_device(hass, "s2", "FJ40 Vibration",
                                    battery=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    _freeze(coord, device.id, category=FREEZE_CATEGORY_UNAVAILABLE)
    _battery_low(coord, device.id, level=14.0)
    coord._sync_problem_list()

    assert len(coord.todo_items) == 1
    item = _item_for(coord, device.id)
    assert item["summary"] == "FJ40 Vibration: unavailable, battery 14%"
    assert set(item["kinds"]) == {
        FREEZE_CATEGORY_UNAVAILABLE, TODO_KIND_BATTERY,
    }
    # The battery since came through as epoch seconds.
    assert isinstance(item["kinds"][TODO_KIND_BATTERY], float)
    assert "since" in (item["description"] or "")


async def test_kind_joins_and_leaves_one_item(hass: HomeAssistant):
    """A second kind updates the item in place; losing one kind while
    another remains updates the text and keeps the item."""
    device, eids = _register_device(hass, "s3", "Laundry Leak",
                                    battery=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = _item_for(coord, device.id)["uid"]

    _battery_low(coord, device.id, level=9.0)
    coord._sync_problem_list()
    item = _item_for(coord, device.id)
    assert item["uid"] == uid  # same item, not a duplicate
    assert item["summary"] == "Laundry Leak: frozen, battery 9%"

    _clear_freeze(coord, device.id)
    coord._sync_problem_list()
    item = _item_for(coord, device.id)
    assert item["uid"] == uid
    assert item["summary"] == "Laundry Leak: battery 9%"
    assert list(item["kinds"]) == [TODO_KIND_BATTERY]


async def test_acknowledged_item_updates_and_recovers(
    hass: HomeAssistant,
):
    """The FJ40 rule: an acknowledged item stays acknowledged through
    kind changes, keeps its check time, and only recovery deletes
    it."""
    device, eids = _register_device(hass, "s4", "Truck Sensor",
                                    battery=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = _item_for(coord, device.id)["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    acked_at = _item_for(coord, device.id)["acked_at"]
    assert acked_at is not None

    # A new kind arrives: the item updates, stays acknowledged.
    _battery_low(coord, device.id)
    coord._sync_problem_list()
    item = _item_for(coord, device.id)
    assert item["status"] == "completed"
    assert item["acked_at"] == acked_at
    assert "battery" in item["summary"]

    # Full recovery deletes it, acknowledged or not.
    _clear_freeze(coord, device.id)
    coord.data["devices"][device.id][DEV_BATTERY_LOW] = False
    coord._sync_problem_list()
    assert _item_for(coord, device.id) is None


async def test_display_order_two_blocks(hass: HomeAssistant):
    """Open items alphabetical; acknowledged after them in the order
    checked, oldest first."""
    d1, e1 = _register_device(hass, "s5a", "Zebra Sensor")
    d2, e2 = _register_device(hass, "s5b", "Apple Sensor")
    d3, e3 = _register_device(hass, "s5c", "Mango Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    for eids in (e1, e2, e3):
        hass.states.async_set(eids["plain"], "on")
    for device in (d1, d2, d3):
        _freeze(coord, device.id)
    coord._sync_problem_list()

    # Check Zebra first, then Apple: acknowledged order is check
    # order, not the alphabet.
    await coord.async_todo_update(
        uid=_item_for(coord, d1.id)["uid"], status="completed"
    )
    await coord.async_todo_update(
        uid=_item_for(coord, d2.id)["uid"], status="completed"
    )
    names = [r["sort_name"] for r in coord.todo_items]
    assert names == ["Mango Sensor", "Zebra Sensor", "Apple Sensor"]


async def test_journal_and_dispatcher_on_addition(hass: HomeAssistant):
    """Every addition lands in the journal and fires the signal: the
    Step 8 contract."""
    device, eids = _register_device(hass, "s6", "Porch Motion",
                                    battery=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")
    heard = []
    async_dispatcher_connect(hass, SIGNAL_PROBLEM_ADDITION, heard.append)

    _freeze(coord, device.id)
    coord._sync_problem_list()
    _battery_low(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    journal = coord.data[DATA_TODO_JOURNAL]
    kinds = [(e["name"], e["kind"]) for e in journal]
    assert ("Porch Motion", FREEZE_CATEGORY_FROZEN) in kinds
    assert ("Porch Motion", TODO_KIND_BATTERY) in kinds
    assert [h["kind"] for h in heard] == [
        FREEZE_CATEGORY_FROZEN, TODO_KIND_BATTERY,
    ]
    # A clean pass adds nothing.
    before = len(journal)
    coord._sync_problem_list()
    assert len(coord.data[DATA_TODO_JOURNAL]) == before


async def test_battery_flip_syncs_without_a_tick(hass: HomeAssistant):
    """The live path: a battery crossing the line lists the device in
    the same evaluation, no render tick needed."""
    device, eids = _register_device(hass, "s7", "Door Contact",
                                    battery=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    hass.states.async_set(eids["pct"], "14")
    coord._evaluate_battery(device.id)
    item = _item_for(coord, device.id)
    assert item is not None
    assert item["summary"] == "Door Contact: battery 14%"

    hass.states.async_set(eids["pct"], "35")
    coord._evaluate_battery(device.id)
    assert _item_for(coord, device.id) is None


async def test_setup_purges_hand_typed_items(hass: HomeAssistant):
    """A pre-0.6.0 hand-typed item (no device_id) is purged at setup;
    engine items gain the new fields in place."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    coord.data["todo_items"] = [
        {"uid": "hand1", "summary": "Buy AA batteries",
         "description": None, "status": "needs_action",
         "sort_name": "Buy AA batteries", "kind": None, "ours": False},
    ]
    await coord._store.async_save(coord.data)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.todo_items == []
