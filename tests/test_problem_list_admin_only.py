# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_problem_list_admin_only.py, Version: 0.28.12 (2026-11-11)

"""Who may tick, untick, delete or move Problem List items (rule LIST-03).

Device Sentinel refuses a tick, an untick or a delete from a user who
is not an admin (todo.py _refuse_a_non_admin). Home Assistant's service
path sets the entity's context to the caller's just before it calls in;
the to-do intents that Assist, a conversation agent or an AI tool use
call in directly, with no user and whatever context came before, so
they are refused outright: a list shown to Assist can be read there,
never ticked or deleted.

Every test asserts the safe behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.models import Credentials
from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

LIST_ENTITY = "todo.device_sentinel_problem_list"


async def _one_open_item(hass: HomeAssistant, uid: str = "pl_exploit"):
    from tests.helpers import setup_entry
    from tests.test_todo import _freeze, _items, _register_device

    device, eids = _register_device(hass, uid, "Smoke Alarm Hall")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    items = await _items(hass)
    assert len(items) == 1
    return items[0], _items


async def _user(hass: HomeAssistant, admin: bool = False) -> MockUser:
    group = await hass.auth.async_get_group(GROUP_ID_ADMIN if admin else GROUP_ID_USER)
    return MockUser(name="Owner" if admin else "Kid", groups=[group]).add_to_hass(hass)


async def _user_token(hass: HomeAssistant) -> str:
    user = await _user(hass)
    credential = Credentials(
        id="exploit-pl-credential",
        auth_provider_type="homeassistant",
        auth_provider_id=None,
        data={"username": "kid"},
        is_new=False,
    )
    user.credentials.append(credential)
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID, credential=credential)
    return hass.auth.async_create_access_token(refresh)


async def _exposed_to_assist(hass: HomeAssistant) -> str:
    """The admin's own choice, offered by rule LIST-14: the list shown
    to Assist. Returns the name Assist knows it by."""
    from homeassistant.components.todo.intent import async_setup_intents

    async_expose_entity(hass, "conversation", LIST_ENTITY, True)
    await async_setup_intents(hass)
    return hass.states.get(LIST_ENTITY).attributes["friendly_name"]


async def _say(hass, intent_type, item, name, user_id):
    try:
        await intent.async_handle(
            hass, "conversation", intent_type,
            {"item": {"value": item}, "name": {"value": name}},
            context=Context(user_id=user_id), assistant="conversation",
        )
    except (Unauthorized, HomeAssistantError):
        return False
    return True


# ---------------------------------------------------------- Assist / intents


async def test_a_non_admin_cannot_tick_through_assist(hass: HomeAssistant):
    """No service call has run on the list yet, so its `_context` is
    None and the guard reads the intent as an automation.28.12."""
    assert await async_setup_component(hass, "homeassistant", {})
    item, items = await _one_open_item(hass)
    name = await _exposed_to_assist(hass)
    kid = await _user(hass)
    await _say(hass, "HassListCompleteItem", item["uid"], name, kid.id)
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "needs_action"


async def test_a_non_admin_cannot_tick_on_the_admins_stale_context(hass: HomeAssistant):
    """The admin ticked and unticked through the service a moment ago,
    so `_context` still carries the admin's user id; the non-admin's
    intent passes on it.28.12."""
    assert await async_setup_component(hass, "homeassistant", {})
    item, items = await _one_open_item(hass)
    name = await _exposed_to_assist(hass)
    owner = await _user(hass, admin=True)
    for status in ("completed", "needs_action"):
        await hass.services.async_call(
            "todo", "update_item",
            {"entity_id": LIST_ENTITY, "item": item["uid"], "status": status},
            blocking=True, context=Context(user_id=owner.id),
        )
    kid = await _user(hass)
    await _say(hass, "HassListCompleteItem", item["uid"], name, kid.id)
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "needs_action"


async def test_a_non_admin_cannot_delete_through_assist(hass: HomeAssistant):
    """Deleting is the hard un-acknowledge; its fault fires on the bus
    again as a renewal.28.12: the
    intent deletes on a None context."""
    assert await async_setup_component(hass, "homeassistant", {})
    item, _items = await _one_open_item(hass)
    name = await _exposed_to_assist(hass)
    kid = await _user(hass)
    deleted = await _say(hass, "HassListRemoveItem", item["uid"], name, kid.id)
    await hass.async_block_till_done()
    assert not deleted


# ---------------------------------------------------------- service and WebSocket 


async def test_a_non_admin_cannot_clear_completed_items(hass: HomeAssistant):
    """todo.remove_completed_items reaches async_delete_todo_items
    through the entity service path """
    item, items = await _one_open_item(hass)
    owner = await _user(hass, admin=True)
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": LIST_ENTITY, "item": item["uid"], "status": "completed"},
        blocking=True, context=Context(user_id=owner.id),
    )
    kid = await _user(hass)
    try:
        await hass.services.async_call(
            "todo", "remove_completed_items", {"entity_id": LIST_ENTITY},
            blocking=True, context=Context(user_id=kid.id),
        )
    except (Unauthorized, HomeAssistantError):
        pass
    await hass.async_block_till_done()
    after = await items(hass)
    assert len(after) == 1 and after[0]["status"] == "completed"


async def test_a_refused_untick_changes_nothing(hass: HomeAssistant):
    """An admin's tick, then a non-admin's untick: refused, and the
    acknowledgment stands """
    item, items = await _one_open_item(hass)
    owner = await _user(hass, admin=True)
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": LIST_ENTITY, "item": item["uid"], "status": "completed"},
        blocking=True, context=Context(user_id=owner.id),
    )
    kid = await _user(hass)
    try:
        await hass.services.async_call(
            "todo", "update_item",
            {"entity_id": LIST_ENTITY, "item": item["uid"], "status": "needs_action"},
            blocking=True, context=Context(user_id=kid.id),
        )
    except (Unauthorized, HomeAssistantError):
        pass
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "completed"


async def test_websocket_paths_refuse_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token, local_auth
):
    """call_service over the WebSocket from a non-admin and a read-only
    token, and todo/item/move (the list offers no move): all refused,
    and the item stays open """
    item, items = await _one_open_item(hass)
    for token in (await _user_token(hass), hass_read_only_access_token):
        client = await hass_ws_client(hass, token)
        await client.send_json({
            "id": 1, "type": "call_service", "domain": "todo", "service": "update_item",
            "service_data": {"item": item["uid"], "status": "completed"},
            "target": {"entity_id": LIST_ENTITY},
        })
        reply = await client.receive_json()
        assert reply["success"] is False
        await client.send_json({
            "id": 2, "type": "call_service", "domain": "todo", "service": "remove_item",
            "service_data": {"item": [item["uid"]]},
            "target": {"entity_id": LIST_ENTITY},
        })
        reply = await client.receive_json()
        assert reply["success"] is False
        await client.send_json({
            "id": 3, "type": "todo/item/move", "entity_id": LIST_ENTITY, "uid": item["uid"],
        })
        reply = await client.receive_json()
        assert reply["success"] is False
    after = await items(hass)
    assert len(after) == 1 and after[0]["status"] == "needs_action"
