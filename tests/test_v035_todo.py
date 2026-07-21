# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v035_todo.py, Version: 0.6.0 (2026-07-21)

"""The problem list entity surface, rewritten for the 0.6.0 sync.

The 0.3.5 backbone allowed hand-typed items so the entity could be
proven before an engine existed. From 0.6.0 the sync alone maintains
the list: the create feature is gone, so these tests cover what the
entity still offers a person, the checkbox and the hand delete, over
items the sync created.
"""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
)

DOMAIN = "device_sentinel"
LIST_ENTITY = "todo.device_sentinel_problem_list"


def _register_device(hass, uid: str, name: str):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _freeze(coord, device_id, since=1_000_000.0):
    """Plant a stored frozen verdict the setup judgment re-derives.

    An armed rhythm and a last-activity stamp far in the past make
    the verdict self-consistent: a reload's judgment pass reaches the
    same frozen conclusion from the stored clock, which is exactly
    the reboot-survival contract.
    """
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


async def _items(hass):
    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": LIST_ENTITY},
        blocking=True, return_response=True,
    )
    return result[LIST_ENTITY]["items"]


async def test_list_exists_and_starts_empty(hass: HomeAssistant):
    await _setup(hass)
    state = hass.states.get(LIST_ENTITY)
    assert state is not None
    assert state.state == "0"
    assert await _items(hass) == []


async def test_add_item_is_rejected(hass: HomeAssistant):
    """No add box, no add service: detections alone fill the list."""
    await _setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo", "add_item",
            {"entity_id": LIST_ENTITY, "item": "Buy AA batteries"},
            blocking=True,
        )
    assert await _items(hass) == []


async def test_check_acknowledges_and_delete_removes(hass: HomeAssistant):
    device, entity_id = _register_device(hass, "t1", "Attic Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
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


async def test_items_survive_reload(hass: HomeAssistant):
    """An acknowledged item rides the reload: still listed, still
    checked, same since. The reboot-survival proof at bench scale."""
    device, entity_id = _register_device(hass, "t2", "Cellar Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "7")
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
