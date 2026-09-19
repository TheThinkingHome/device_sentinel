# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_stage2.py, Version: 0.22.2 (2026-09-19)

"""The Problem List and Recommendations tabs.

The Problem List reads the to-do items themselves, acknowledged ones
included, because the to-do list shows them and the brief's Now table
does not. A tick on the dashboard is the same act as a tick on the
to-do list: one path, one record. Recommendations come from the brief's
own builder, so the tab and the brief say the same thing.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_TODO_ITEMS

from tests.helpers import register_device, setup_coordinator


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _item(uid, device_id, name, problem, kind, since, status="needs_action"):
    return {
        "uid": uid,
        "device_id": device_id,
        "summary": f"{name}: {problem}",
        "description": f"{problem} since then.",
        "status": status,
        "acked_at": None if status == "needs_action" else "2026-09-12T11:25:32+00:00",
        "sort_name": name,
        "kinds": {kind: since},
    }


async def _house(hass):
    soil, _ = register_device(hass, "soil", name="Soil Irrigation (Monstera)")
    window, _ = register_device(hass, "win", name="Window Living Room Right")
    coord = await setup_coordinator(hass)
    coord.data[DATA_TODO_ITEMS] = [
        _item("u1", soil.id, "Soil Irrigation (Monstera)", "battery 0%", "low_battery", 1784750864.9),
        _item("u2", window.id, "Window Living Room Right", "signal (rail)", "railed_signal",
              1788930000.4, status="completed"),
    ]
    return coord, soil, window


async def test_the_problem_list_carries_every_item(hass: HomeAssistant, hass_ws_client):
    coord, soil, window = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/problem_list")
    assert reply["success"], reply
    rows = reply["result"]["rows"]
    assert [row["uid"] for row in rows] == ["u1", "u2"]
    first = rows[0]
    assert first["name"] == "Soil Irrigation (Monstera)"
    assert first["problem"] == "battery 0%"
    assert first["device_id"] == soil.id
    assert first["integration"] == coord._watched[soil.id]
    assert first["acknowledged"] is False
    assert first["since"].startswith("2026-07-22")
    assert rows[1]["acknowledged"] is True
    assert rows[1]["problem"] == "signal (rail)"


async def test_acknowledging_is_the_to_do_lists_own_act(hass: HomeAssistant, hass_ws_client):
    coord, _, _ = await _house(hass)
    client = await hass_ws_client(hass)
    before = coord.change_marker
    reply = await _call(client, type="device_sentinel/acknowledge", uid="u1", acknowledged=True)
    assert reply["success"], reply
    item = next(i for i in coord.data[DATA_TODO_ITEMS] if i["uid"] == "u1")
    assert item["status"] == "completed"
    assert item["acked_at"] is not None
    assert coord.change_marker > before
    await _call(client, type="device_sentinel/acknowledge", uid="u1", acknowledged=False)
    assert item["status"] == "needs_action"
    assert item["acked_at"] is None


async def test_acknowledging_an_item_that_is_gone_says_so(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/acknowledge", uid="nope", acknowledged=True)
    assert not reply["success"]
    assert reply["error"]["code"] == "not_found"


async def test_recommendations_are_the_briefs_own(hass: HomeAssistant, hass_ws_client, monkeypatch):
    from custom_components.device_sentinel import wifi as wifi_module

    async def _found(_hass):
        return [{"interface": "wlan0"}]

    monkeypatch.setattr(wifi_module, "wireless_interfaces", _found)
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/recommendations")
    assert reply["success"], reply
    lines = reply["result"]["lines"]
    assert lines == coord._recommendation_items()
    assert any("(wlan0)" in line for line in lines)
    assert reply["result"]["closing"].startswith("These are suggestions")


async def test_the_new_commands_are_admin_only(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await _house(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "device_sentinel/problem_list"},
        {"type": "device_sentinel/recommendations"},
        {"type": "device_sentinel/acknowledge", "uid": "u1", "acknowledged": True},
    ):
        reply = await _call(client, **message)
        assert reply["error"]["code"] == "unauthorized", message
