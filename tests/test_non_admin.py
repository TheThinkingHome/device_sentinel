# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_non_admin.py, Version: 0.28.12 (2026-11-11)

"""Attacks that must fail: a Home Assistant user who is not an administrator.

Device Sentinel's dashboard and every one of its WebSocket commands are
for administrators. A non-admin household member (or a stolen
non-admin token) must not read the house's problems through them, change
anything, or put the Problem List back in front of
Assist and the voice assistants.

Every test asserts the SAFE behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.models import Credentials
from homeassistant.components.homeassistant.exposed_entities import (
    KNOWN_ASSISTANTS,
    async_should_expose,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

from custom_components.device_sentinel.const import DOMAIN

from tests.helpers import register_device, setup_entry

LIST_ENTITY = "todo.device_sentinel_problem_list"

# Every command with a payload its schema accepts, so a refusal can only
# come from the permission check.
COMMANDS = [
    {"type": "device_sentinel/status"},
    {"type": "device_sentinel/action", "action": "maintenance"},
    {"type": "device_sentinel/subscribe_changes"},
    {"type": "device_sentinel/classification"},
    {"type": "device_sentinel/problem_list"},
    {"type": "device_sentinel/acknowledge", "uid": "x", "acknowledged": True},
    {"type": "device_sentinel/recommendations"},
    {"type": "device_sentinel/integrations"},
    {"type": "device_sentinel/integration", "domain": "test"},
    {"type": "device_sentinel/networks"},
    {"type": "device_sentinel/network", "key": "mqtt"},
    {"type": "device_sentinel/network_expected", "key": "mqtt", "minute": 0, "on": True},
    {"type": "device_sentinel/devices"},
    {"type": "device_sentinel/device", "device_id": "DEVICE"},
    {"type": "device_sentinel/use_trimmed_maximum", "device_id": "DEVICE"},
    {"type": "device_sentinel/device_day", "device_id": "DEVICE", "day": "2026-11-01", "removed": True},
    {"type": "device_sentinel/device_choices"},
    {"type": "device_sentinel/device_rename", "device_id": "DEVICE", "name": "Pwned"},
    {"type": "device_sentinel/device_power", "device_id": "DEVICE", "choice": "CR2032"},
    {"type": "device_sentinel/device_type", "device_id": "DEVICE", "choice": "plug"},
    {"type": "device_sentinel/device_area", "device_id": "DEVICE", "area_id": None},
    {"type": "device_sentinel/device_label", "device_id": "DEVICE", "label_id": "x", "add": True},
    {"type": "device_sentinel/device_new_area", "device_id": "DEVICE", "name": "Pwned"},
    {"type": "device_sentinel/device_new_label", "device_id": "DEVICE", "name": "Pwned"},
    {"type": "device_sentinel/device_battery", "device_id": "DEVICE", "action": "confirm"},
    {"type": "device_sentinel/recommendation_ack", "on": True, "kind": "slow"},
    {"type": "device_sentinel/device_turn_on", "device_id": "DEVICE", "kind": "last_seen"},
    {"type": "device_sentinel/device_mute", "device_id": "DEVICE", "kind": "everything", "on": True},
    {"type": "device_sentinel/device_exclude", "device_id": "DEVICE", "on": True},
    {"type": "device_sentinel/integration_exclude", "domain": "test", "on": True},
    {"type": "device_sentinel/integration_mute", "domain": "test", "kind": "everything", "on": True},
    {"type": "device_sentinel/brief"},
    {"type": "device_sentinel/battery_trends"},
    {"type": "device_sentinel/signal_trends"},
]


async def _user_token(hass: HomeAssistant) -> tuple[MockUser, str]:
    """An ordinary, non-admin household user and an access token."""
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    user = MockUser(name="Kid", groups=[group]).add_to_hass(hass)
    credential = Credentials(
        id="exploit-user-credential",
        auth_provider_type="homeassistant",
        auth_provider_id=None,
        data={"username": "kid"},
        is_new=False,
    )
    user.credentials.append(credential)
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID, credential=credential)
    return user, hass.auth.async_create_access_token(refresh)


@pytest.mark.parametrize("who", ["read_only", "user"])
async def test_every_command_refuses_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token, local_auth, who
):
    device, _ = register_device(hass, "nonadmin_target", name="Front Door")
    await setup_entry(hass)
    token = hass_read_only_access_token if who == "read_only" else (await _user_token(hass))[1]
    client = await hass_ws_client(hass, token)
    name_before = device.name
    for index, command in enumerate(COMMANDS, start=1):
        message = {**command, "id": index}
        if message.get("device_id") == "DEVICE":
            message["device_id"] = device.id
        await client.send_json(message)
        reply = await client.receive_json()
        while reply.get("type") == "event":
            reply = await client.receive_json()
        assert reply["success"] is False, command["type"]
        assert reply["error"]["code"] == "unauthorized", (command["type"], reply["error"])
    from homeassistant.helpers import device_registry as dr

    after = dr.async_get(hass).async_get(device.id)
    assert after.name_by_user is None and after.name == name_before


async def test_the_list_is_hidden_even_where_new_entities_are_exposed(hass: HomeAssistant):
    """A house that set Assist to expose new entities still gets the
    Problem List hidden on first setup (expected to hold)."""
    from homeassistant.components.homeassistant.const import DATA_EXPOSED_ENTITIES

    assert await async_setup_component(hass, "homeassistant", {})
    for assistant in KNOWN_ASSISTANTS:
        hass.data[DATA_EXPOSED_ENTITIES].async_set_expose_new_entities(assistant, True)
    await setup_entry(hass)
    entity_id = next(
        e.entity_id for e in er.async_get(hass).entities.values()
        if e.platform == DOMAIN and e.domain == "todo"
    )
    for assistant in KNOWN_ASSISTANTS:
        assert async_should_expose(hass, assistant, entity_id) is False, assistant


async def test_a_non_admin_cannot_put_the_list_back_in_front_of_assist(
    hass: HomeAssistant, hass_ws_client, local_auth
):
    """Home Assistant's expose command is the only way back, and it is
    admin only; Device Sentinel offers none of its own (expected to
    hold)."""
    assert await async_setup_component(hass, "homeassistant", {})
    await setup_entry(hass)
    entity_id = next(
        e.entity_id for e in er.async_get(hass).entities.values()
        if e.platform == DOMAIN and e.domain == "todo"
    )
    _, token = await _user_token(hass)
    client = await hass_ws_client(hass, token)
    await client.send_json({
        "id": 1, "type": "homeassistant/expose_entity",
        "assistants": list(KNOWN_ASSISTANTS), "entity_ids": [entity_id], "should_expose": True,
    })
    reply = await client.receive_json()
    assert reply["success"] is False
    for assistant in KNOWN_ASSISTANTS:
        assert async_should_expose(hass, assistant, entity_id) is False, assistant


# ------------------------------------------------ the Problem List is the admin's (rule LIST-03)


async def _one_open_item(hass: HomeAssistant):
    from homeassistant.core import Context  # noqa: F401

    from .test_todo import _freeze, _items, _register_device

    device, eids = _register_device(hass, "nonadmin_ack", "Smoke Alarm Hall")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(eids["plain"], "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    items = await _items(hass)
    assert len(items) == 1
    return items[0]["uid"], _items


async def _call(hass, service, data, user_id):
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    try:
        await hass.services.async_call(
            "todo", service, {"entity_id": LIST_ENTITY, **data},
            blocking=True, context=Context(user_id=user_id),
        )
    except Unauthorized:
        return False
    return True


async def _ordinary_user(hass):
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    return MockUser(name="Kid", groups=[group]).add_to_hass(hass)


async def test_a_non_admin_cannot_tick_a_problem(hass: HomeAssistant):
    """Ticking is the acknowledgment, which stops the pushes: refused
    for a user who is not an admin, and the item stays open."""
    uid, items = await _one_open_item(hass)
    user = await _ordinary_user(hass)
    assert not await _call(hass, "update_item", {"item": uid, "status": "completed"}, user.id)
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "needs_action"


async def test_a_non_admin_cannot_delete_a_problem(hass: HomeAssistant):
    uid, items = await _one_open_item(hass)
    user = await _ordinary_user(hass)
    assert not await _call(hass, "remove_item", {"item": [uid]}, user.id)


async def test_an_admin_and_an_automation_still_can(hass: HomeAssistant):
    uid, items = await _one_open_item(hass)
    from homeassistant.auth.const import GROUP_ID_ADMIN

    admin = MockUser(name="Owner", groups=[await hass.auth.async_get_group(GROUP_ID_ADMIN)]).add_to_hass(hass)
    assert admin.is_admin
    assert await _call(hass, "update_item", {"item": uid, "status": "completed"}, admin.id)
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "completed"
    # An automation or a script carries no user.
    assert await _call(hass, "update_item", {"item": uid, "status": "needs_action"}, None)
    await hass.async_block_till_done()
    assert (await items(hass))[0]["status"] == "needs_action"


# ------------------------------------------------ Device Sentinel's buttons are the admin's (rule CFG-08)


def _buttons(hass: HomeAssistant) -> list[str]:
    return [
        entry.entity_id for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN and entry.domain == "button" and not entry.disabled_by
    ]


async def test_a_non_admin_cannot_press_a_button(hass: HomeAssistant):
    """Maintenance Mode sets learning aside; no button is a household
    user's to press."""
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    await setup_entry(hass)
    user = await _ordinary_user(hass)
    buttons = _buttons(hass)
    assert buttons
    for entity_id in buttons:
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "button", "press", {"entity_id": entity_id},
                blocking=True, context=Context(user_id=user.id),
            )


async def test_an_automation_still_presses_one(hass: HomeAssistant):
    from homeassistant.core import Context

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    maintenance = next(b for b in _buttons(hass) if "maintenance" in b)
    await hass.services.async_call(
        "button", "press", {"entity_id": maintenance}, blocking=True, context=Context(),
    )
    await hass.async_block_till_done()
    assert coord._maintenance_until is not None
