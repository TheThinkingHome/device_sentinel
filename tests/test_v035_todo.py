# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""0.3.5 tests: the problem list backbone (no engine yet)."""

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"
LIST_ENTITY = "todo.device_sentinel_problem_list"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


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


async def test_add_check_and_delete_round_trip(hass: HomeAssistant):
    entry = await _setup(hass)
    coord = entry.runtime_data

    await hass.services.async_call(
        "todo", "add_item",
        {"entity_id": LIST_ENTITY, "item": "Zebra sensor"},
        blocking=True,
    )
    await hass.services.async_call(
        "todo", "add_item",
        {"entity_id": LIST_ENTITY, "item": "Apple sensor"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Alphabetical order is enforced on every add.
    items = await _items(hass)
    assert [i["summary"] for i in items] == ["Apple sensor", "Zebra sensor"]
    assert hass.states.get(LIST_ENTITY).state == "2"

    # Checking an item acknowledges it: it stays, marked completed.
    await hass.services.async_call(
        "todo", "update_item",
        {
            "entity_id": LIST_ENTITY,
            "item": "Apple sensor",
            "status": "completed",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    stored = {r["summary"]: r["status"] for r in coord.todo_items}
    assert stored["Apple sensor"] == "completed"
    assert len(coord.todo_items) == 2  # checking never removes

    # Deleting removes it.
    await hass.services.async_call(
        "todo", "remove_item",
        {"entity_id": LIST_ENTITY, "item": "Zebra sensor"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert [r["summary"] for r in coord.todo_items] == ["Apple sensor"]


async def test_user_items_are_marked_foreign(hass: HomeAssistant):
    """A user's own addition is never ours, so the engine leaves it."""
    entry = await _setup(hass)
    coord = entry.runtime_data
    await hass.services.async_call(
        "todo", "add_item",
        {"entity_id": LIST_ENTITY, "item": "Buy AA batteries"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coord.todo_items[0]["ours"] is False


async def test_items_survive_reload(hass: HomeAssistant):
    entry = await _setup(hass)
    await hass.services.async_call(
        "todo", "add_item",
        {"entity_id": LIST_ENTITY, "item": "Persistent item"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert [r["summary"] for r in coord2.todo_items] == ["Persistent item"]
    assert hass.states.get(LIST_ENTITY).state == "1"


async def test_engine_api_adds_sorted_and_ours(hass: HomeAssistant):
    """The Step 5 engine's entry point: add an item as ours."""
    entry = await _setup(hass)
    coord = entry.runtime_data
    await coord.async_todo_add(
        summary="Battery low: Kitchen sensor 15%",
        description="Area: Kitchen. Since: 2026-07-14.",
        sort_name="Kitchen sensor",
        kind="battery",
        ours=True,
        uid="abc123",
    )
    await coord.async_todo_add(
        summary="Frozen: Attic sensor",
        description="Area: Attic.",
        sort_name="Attic sensor",
        kind="frozen",
        ours=True,
        uid="def456",
    )
    await hass.async_block_till_done()
    # Sorted by the common name, not the summary text.
    assert [r["sort_name"] for r in coord.todo_items] == [
        "Attic sensor", "Kitchen sensor",
    ]
    assert all(r["ours"] for r in coord.todo_items)
    assert hass.states.get(LIST_ENTITY).state == "2"
