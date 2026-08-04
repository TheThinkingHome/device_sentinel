# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_todo.py, Version: 0.10.4 (2026-07-28)

"""The problem list: one item per device, maintained by the sync.

The todo entity is where a person reads trouble devices. From 0.6.0 the
detection-to-todo sync alone maintains it: one item per device keyed by
device_id however many detections tag it, added on first appearance,
its text following the kinds as they come and go, deleted the moment
the last clears. A person can check an item to acknowledge it (it stays,
marked done, its check time untouched by the sync) or hand-delete it (a
still-troubled device is re-added fresh next sync). Every addition lands
in the bounded journal and fires the dispatcher signal. This file holds
the entity surface, the sync lifecycle, and the real-plumbing wiring.
"""

import pytest

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_TODO_JOURNAL,
    DEV_BATTERY_DAILY,
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
    INCIDENT_OPENED,
    INC_EVENT,
    SIGNAL_PROBLEM_ADDITION,
    STARTUP_GRACE_SECONDS,
    TODO_JOURNAL_KEEP,
    TODO_KIND_BATTERY,
    TODO_KIND_BATTERY_FALLING,
)

from tests.helpers import setup_entry

DOMAIN = "device_sentinel"
LIST_ENTITY = "todo.device_sentinel_problem_list"


def _register_device(hass, uid: str, name: str, battery: bool = False):
    """A device with a plain sensor and, optionally, a battery entity.

    Returns (device, entity_ids) where entity_ids is a dict with a
    "plain" key and, when battery is set, a "pct" key, matching the
    shape the sync tests drive.
    """
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


def _freeze(coord, device_id, since=1_000_000.0,
            category=FREEZE_CATEGORY_FROZEN):
    """Plant a stored down verdict the sync reads as a freeze-family
    input, with an armed rhythm and a past clock so a reload's
    judgment re-derives the same verdict (the reboot-survival path)."""
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


async def _items(hass):
    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": LIST_ENTITY},
        blocking=True, return_response=True,
    )
    return result[LIST_ENTITY]["items"]


# ------------------------------------------------- the entity surface

async def test_list_exists_and_starts_empty(hass: HomeAssistant):
    await setup_entry(hass)
    state = hass.states.get(LIST_ENTITY)
    assert state is not None
    assert state.state == "0"
    assert await _items(hass) == []


async def test_add_item_is_rejected(hass: HomeAssistant):
    """No add box, no add service: detections alone fill the list."""
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo", "add_item",
            {"entity_id": LIST_ENTITY, "item": "Buy AA batteries"},
            blocking=True,
        )
    assert await _items(hass) == []


async def test_check_acknowledges_and_delete_removes(hass: HomeAssistant):
    device, eids = _register_device(hass, "t1", "Attic Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    items = await _items(hass)
    assert len(items) == 1
    assert items[0]["summary"] == "Attic Sensor: frozen"

    # Checking acknowledges: the item stays, marked completed.
    await hass.services.async_call(
        "todo", "update_item",
        {
            "entity_id": LIST_ENTITY,
            "item": items[0]["uid"],
            "status": "completed",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coord.todo_items[0]["status"] == "completed"
    assert coord.todo_items[0]["acked_at"] is not None
    assert len(coord.todo_items) == 1  # checking never removes

    # A sync pass leaves the acknowledgment alone.
    coord._sync_problem_list()
    assert coord.todo_items[0]["status"] == "completed"

    # Hand-deleting removes it now; the device is still frozen, so
    # the next sync re-adds it fresh: the hard un-acknowledge.
    await hass.services.async_call(
        "todo", "remove_item",
        {"entity_id": LIST_ENTITY, "item": items[0]["uid"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coord.todo_items == []
    coord._sync_problem_list()
    assert len(coord.todo_items) == 1
    assert coord.todo_items[0]["status"] == "needs_action"


async def test_a_missing_status_does_not_reopen_an_item(
    hass: HomeAssistant,
):
    """A status Home Assistant did not send is not needs_action.

    The coordinator already ignores a status of None; the entity
    used to fold None into needs_action before that guard could
    help, so a caller updating text alone would silently have
    thrown away an acknowledgment.
    """
    from homeassistant.components.todo import TodoItem

    device, eids = _register_device(hass, "t9", "Guard Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    acked = coord.todo_items[0]["acked_at"]
    assert acked is not None

    entity = hass.data["entity_components"]["todo"].get_entity(
        LIST_ENTITY
    )
    await entity.async_update_todo_item(
        TodoItem(uid=uid, summary="anything", status=None)
    )

    assert coord.todo_items[0]["status"] == "completed"
    assert coord.todo_items[0]["acked_at"] == acked


async def test_a_hand_deletion_does_not_orphan_a_live_episode(
    hass: HomeAssistant,
):
    """The pairing bug this release exists to stop.

    The brief matches each opening to its recovery on a key of
    device and kind. A second opening on a key that already had one
    pending overwrote the entry, so the real opening was orphaned
    and rendered as a fault that never resolved, while the spurious
    one paired with the eventual recovery.
    """
    device, eids = _register_device(hass, "t8", "Episode Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()

    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_delete([uid])
    coord._sync_problem_list()

    # The device recovers for real.
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()

    units = coord._pair_incidents(coord.data[DATA_INCIDENTS])
    unpaired = [
        first
        for first, second in units
        if second is None and first[INC_EVENT] == INCIDENT_OPENED
    ]
    assert unpaired == [], "the real opening was orphaned"


async def test_items_survive_reload(hass: HomeAssistant):
    """An acknowledged item rides the reload: still listed, still
    checked, same since. The reboot-survival proof at bench scale."""
    device, eids = _register_device(hass, "t2", "Cellar Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "7")
    _freeze(coord, device.id, since=2_000_000.0)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    # The frozen verdict survives in storage, the setup judgment
    # rebuilds the detection, and the sync keeps the same item.
    assert len(coord2.todo_items) == 1
    record = coord2.todo_items[0]
    assert record["status"] == "completed"
    assert record["device_id"] == device.id
    assert record["kinds"][FREEZE_CATEGORY_FROZEN] == 2_000_000.0
    # The entity state counts open items, so a list whose only item
    # is acknowledged reads zero: nothing needs action.
    assert hass.states.get(LIST_ENTITY).state == "0"


# ------------------------------------------- the detection-to-todo sync

async def test_detection_adds_and_recovery_deletes(hass: HomeAssistant):
    """The core lifecycle: appear on detection, go on recovery."""
    device, eids = _register_device(hass, "s1", "Presence Guest")
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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


# --------------------------------------------- the real-plumbing wiring

async def test_tick_carries_a_freeze_into_the_list(
    hass: HomeAssistant, freezer
):
    """End to end on HA's own timer: a device with an armed rhythm
    goes silent, the render tick judges it frozen and the same tick
    lists it, with no test code calling the machinery directly."""
    device, eids = _register_device(hass, "t1w", "Tick Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "1")
    await hass.async_block_till_done()

    # Arm the rhythm: an hourly reporter, learned past the gate. The
    # last activity is real (the state write above); the window is an
    # hour, so silence beyond it must fire on a natural tick.
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)

    # Leave the startup grace, then go silent far past the window.
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _item_for(coord, device.id) is None  # inside its window

    freezer.tick(timedelta(hours=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    item = _item_for(coord, device.id)
    assert item is not None
    assert "Tick Sensor" in item["summary"]
    assert item["status"] == "needs_action"


async def test_option_exclusion_clears_the_item(hass: HomeAssistant):
    """Through the real path: excluding a listed device by updating
    the entry's options deletes its item via the update listener, no
    direct sync call."""
    device, eids = _register_device(hass, "o1", "Excluded Later")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")

    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - 8 * 3600
    )
    coord._judge_all_devices()
    coord._sync_problem_list()
    assert _item_for(coord, device.id) is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "excluded_devices": [device.id]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _item_for(coord, device.id) is None


async def test_journal_cap_evicts_only_the_oldest(hass: HomeAssistant):
    """Entry 101 evicts entry 1 and nothing else; the bound holds at
    exactly TODO_JOURNAL_KEEP."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    for n in range(TODO_JOURNAL_KEEP + 1):
        coord._journal_addition(f"dev{n}", f"Device {n}", "frozen")

    journal = coord.data[DATA_TODO_JOURNAL]
    assert len(journal) == TODO_JOURNAL_KEEP
    names = [e["name"] for e in journal]
    assert "Device 0" not in names          # the oldest, evicted
    assert names[0] == "Device 1"           # order preserved
    assert names[-1] == f"Device {TODO_JOURNAL_KEEP}"


async def test_a_falling_cell_reaches_the_problem_list(
    hass: HomeAssistant,
):
    """Ruling #213. Low is a level that has been crossed; falling is
    one that is going to be, and the two rarely name the same device.
    The forecast is worth a person's attention on its own, so it
    reaches the list like any other kind rather than living only on a
    report they may never open.

    It reads as a warning rather than a fault, because the cell is
    working: what is wrong is where it is heading.
    """
    device, eids = _register_device(hass, "bf1", "Falling Cell",
                                    battery=True)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = [
        40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
        28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0,
    ]
    record[DEV_BATTERY_VALUE] = 20.0
    coord._sync_problem_list()

    item = _item_for(coord, device.id)
    assert item is not None
    assert item["summary"] == "Falling Cell: empty in about a month"


async def test_low_and_falling_read_as_one_line(
    hass: HomeAssistant,
):
    """One device, one item, one line: the level then where it is
    heading, rather than two phrases stacked (ruling #213)."""
    device, eids = _register_device(hass, "bf2", "Dying Cell",
                                    battery=True)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    summary, _description = coord._problem_item_text(
        "Dying Cell",
        {TODO_KIND_BATTERY: None, TODO_KIND_BATTERY_FALLING: None},
        16.0,
        "about 2 weeks",
    )
    assert summary == "Dying Cell: battery 16%, empty in about 2 weeks"


async def test_the_falling_kind_keeps_an_acknowledgment(
    hass: HomeAssistant,
):
    """Rulings #123 and #133 hold without amendment. Acknowledging
    silences the phone and not the record, so a person who ticked off
    a forecast still watches it come true on the list: the item stays,
    gains the level, and says nothing further to anyone.

    This was nearly overturned when the falling kind arrived, on the
    reasoning that acknowledging a forecast should not acknowledge the
    event it forecasts. It does not need to: the item is still there.
    """
    device, eids = _register_device(hass, "bf3", "Watched Cell",
                                    battery=True)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "on")

    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = [
        40.0, 38.5, 37.0, 35.5, 34.0, 32.5, 31.0, 29.5,
        28.0, 26.5, 25.0, 23.5, 22.0, 20.5, 20.0, 20.0,
    ]
    record[DEV_BATTERY_VALUE] = 20.0
    coord._sync_problem_list()
    uid = _item_for(coord, device.id)["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    acked_at = _item_for(coord, device.id)["acked_at"]
    assert acked_at is not None

    # The cell crosses the threshold. The item gains the level and
    # stays acknowledged.
    _battery_low(coord, device.id)
    coord._sync_problem_list()
    item = _item_for(coord, device.id)
    assert item["status"] == "completed"
    assert item["acked_at"] == acked_at
    assert "battery" in item["summary"]
