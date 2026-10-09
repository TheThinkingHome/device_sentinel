# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_type_columns.py, Version: 0.25.3 (2026-10-09)

"""Types where devices are listed (0.25.3).

Battery Trends, the Classification tab and the Devices tab narrow to one
type; Battery Trends' By Model lists the types a model's cells have; two
recommendation cards name devices with no type and models split between
types. Ruled by James on 9 October 2026. The panel's side is checked in
tools/panel_checks/check_type_filters.js.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

from .helpers import register_device, setup_coordinator

STEADY = [80.0] * 14


def _model(hass, device, maker, model):
    dr.async_get(hass).async_update_device(device.id, manufacturer=maker, model=model, model_id="")


async def _house(hass):
    """Three motion sensors of one model and a door sensor, each with a cell."""
    devices = {}
    for key, name, maker, model in [
        ("m1", "Motion Laundry", "Third Reality", "Wireless motion sensor"),
        ("m2", "Motion Closet", "Third Reality", "Wireless motion sensor"),
        ("m3", "Motion Hall", "Third Reality", "Wireless motion sensor"),
        ("d1", "Door Bedroom", "Third Reality", "Door sensor"),
        ("x1", "Mystery Tag", "Acme", "Tag"),
    ]:
        device, _ = register_device(hass, key, name=name)
        _model(hass, device, maker, model)
        devices[key] = device
    coord = await setup_coordinator(hass)
    for device in devices.values():
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_BATTERY_DAILY] = list(STEADY)
        record[DEV_BATTERY_VALUE] = STEADY[-1]
    coord.page_set_type(devices["m1"].id, "Motion Sensor")  # covers the model
    coord.page_set_type(devices["d1"].id, "Door/Window Sensor")
    return coord, devices


async def test_battery_trends_carries_each_cells_type(hass: HomeAssistant):
    coord, devices = await _house(hass)
    trends = coord.battery_trends()
    by_id = {row["device_id"]: row for row in trends["cell_rows"]}
    assert by_id[devices["m2"].id]["type"] == "Motion Sensor", "a model's answer covers its other devices"
    assert by_id[devices["d1"].id]["maker"] == "Third Reality" and by_id[devices["d1"].id]["model"] == "Door sensor"
    listed = trends["falling"] + trends["low"] + trends["steady"]
    assert listed and all("type" in row for row in listed)
    assert {row["device_id"]: row["type"] for row in listed}[devices["d1"].id] == "Door/Window Sensor"


async def test_a_model_split_between_types_lists_each(hass: HomeAssistant):
    coord, devices = await _house(hass)
    # Motion Hall with an answer of its own, apart from its model's (an
    # answer kept from before answers covered the model).
    coord._type_models.clear()
    coord._type_entries[devices["m1"].id] = {"type": "Motion Sensor", "set": "x"}
    coord._type_entries[devices["m2"].id] = {"type": "Motion Sensor", "set": "x"}
    coord._type_entries[devices["m3"].id] = {"type": "Presence Sensor", "set": "x"}
    trends = coord.battery_trends()
    motion = next(row for row in trends["models"] if row["model"] == "Wireless motion sensor")
    assert motion["cells"] == 3
    assert [list(item) for item in motion["types"]] == [["Motion Sensor", 2], ["Presence Sensor", 1]]
    door = next(row for row in trends["models"] if row["model"] == "Door sensor")
    assert [list(item) for item in door["types"]] == [["", 1]], "a cell with no type is counted as \"\""


async def test_classification_rows_carry_types_watched_and_set_aside(hass: HomeAssistant):
    coord, devices = await _house(hass)
    rows = {row["device_id"]: row for row in coord.classification_rows()}
    assert rows[devices["m1"].id]["type"] == "Motion Sensor"
    assert all("type" in row for row in rows.values())
    set_aside = [row for row in rows.values() if not row["watched"]]
    assert set_aside, "the house has set-aside devices (the integration's own)"
    for row in set_aside:
        assert row["type"] == coord.type_words(row["device_id"])


async def test_type_not_set_lists_watched_devices_with_no_type(hass: HomeAssistant):
    coord, devices = await _house(hass)
    cards = {card["kind"]: card for card in coord.device_recommendations()}
    untyped = {row["device_id"] for row in cards["type"]["devices"]}
    assert devices["m1"].id not in untyped and devices["d1"].id not in untyped
    for device_id in untyped:
        assert device_id in coord._watched and not coord.type_words(device_id)
    assert cards["type"]["title"] == "Type Not Set"
    assert "brief" not in cards["type"], "a missing type is not a fault the brief reports"


async def test_a_model_split_between_types_gets_its_own_card(hass: HomeAssistant):
    coord, devices = await _house(hass)
    assert "mixed_types" not in {card["kind"] for card in coord.device_recommendations()}
    coord.page_set_type(devices["m3"].id, "Presence Sensor")  # answers the whole model again
    assert "mixed_types" not in {card["kind"] for card in coord.device_recommendations()}
    coord._type_models.clear()
    coord._type_entries[devices["m1"].id] = {"type": "Motion Sensor", "set": "x"}
    coord._type_entries[devices["m3"].id] = {"type": "Presence Sensor", "set": "x"}
    coord._type_entries[devices["m2"].id] = {"type": "Motion Sensor", "set": "x"}
    cards = {card["kind"]: card for card in coord.device_recommendations()}
    mixed = cards["mixed_types"]
    assert mixed["title"] == "Model With More Than One Type"
    rows = {row["device_id"]: row for row in mixed["devices"]}
    assert set(rows) == {devices["m1"].id, devices["m2"].id, devices["m3"].id}
    assert rows[devices["m3"].id]["type"] == "Presence Sensor"
    assert rows[devices["m3"].id]["model"] == "Third Reality Wireless motion sensor"
    assert "brief" not in mixed


async def test_the_brief_leaves_out_the_type_cards(hass: HomeAssistant):
    coord, devices = await _house(hass)
    coord._type_models.clear()
    coord._type_entries[devices["m1"].id] = {"type": "Motion Sensor", "set": "x"}
    coord._type_entries[devices["m3"].id] = {"type": "Presence Sensor", "set": "x"}
    kinds = {card["kind"] for card in coord.device_recommendations()}
    assert {"type", "mixed_types"} <= kinds
    text = "\n".join(coord._recommendations_section())
    assert "Type Not Set" not in text and "More Than One Type" not in text
    assert "Power Not Set" in text, "the other device cards still reach the brief"


async def test_the_recommendations_tab_gets_the_type_choices(hass: HomeAssistant, hass_ws_client):
    from custom_components.device_sentinel.device_type import TYPE_CHOICES, TYPE_OTHER

    await _house(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/recommendations"})
    reply = await client.receive_json()
    assert reply["success"], reply
    assert reply["result"]["types"] == {"choices": list(TYPE_CHOICES), "other": TYPE_OTHER}
    assert any(card["kind"] == "type" for card in reply["result"]["devices"])
