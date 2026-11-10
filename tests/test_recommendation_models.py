# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendation_models.py, Version: 0.28.10 (2026-11-10)

"""Cards whose answer covers a model, grouped by it (rules DEV-06,
DEV-10, REC-04).

An answer given on one device covers each device of the same model,
but Power Not Set, Type Not Set and Model With More Than One Type
listed every device, so people set each one. A tester's house had 159
devices with no power source in about two dozen models; one Lightwave
L42MK3 answer covers 51 of them.

- Each row carries the model its answer covers, so the dashboard draws
  one row per model; a device with no model keeps its own.
- A maker or model that stands for none, such as "Default-Model", is
  no model: one answer on such a device covers only that device, and an
  answer stored that way belongs to the device that gave it.
- A chip maker's board, as ESPHome reports a device built on a bare
  Espressif board, and Tasmota's "Generic" are no model either: a dryer
  sensor and a furnace monitor on the same board are not one product.
- From a model's row on Model With More Than One Type, the answer is
  for the whole model, the answers its devices had of their own with it.
- A model split only as a unit and the parts under it, a Lightwave
  unit over its sockets, is not on Model With More Than One Type.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.device_recommendations import (
    KIND_MIXED_TYPES,
    KIND_POWER,
    KIND_TYPE,
)
from custom_components.device_sentinel.power_source import model_key, placeholder_key

from tests.helpers import register_device, setup_coordinator


def _model(hass, device, maker, model, via=None):
    dr.async_get(hass).async_update_device(device.id, manufacturer=maker, model=model, via_device_id=via)


def _card(coord, kind):
    return next((card for card in coord.device_recommendations() if card["kind"] == kind), None)


async def test_power_not_set_carries_each_rows_model(hass: HomeAssistant):
    sockets = [register_device(hass, f"s{n}", name=f"Socket {n}")[0] for n in range(3)]
    dimmer, _ = register_device(hass, "d1", name="Dimmer")
    loose, _ = register_device(hass, "x1", name="Accessory")
    for device in sockets:
        _model(hass, device, "LightwaveRF", "L42MK3")
    _model(hass, dimmer, "LightwaveRF", "L40MK2")
    coord = await setup_coordinator(hass)
    card = _card(coord, KIND_POWER)
    assert card["grouped"] is True
    keys = {row["name"]: row["model_key"] for row in card["devices"]}
    assert keys["Socket 0"] == keys["Socket 1"] == keys["Socket 2"] == model_key("LightwaveRF", "L42MK3", None)
    assert keys["Dimmer"] == model_key("LightwaveRF", "L40MK2", None)
    assert keys["Accessory"] is None
    assert next(row for row in card["devices"] if row["name"] == "Socket 0")["model"] == "LightwaveRF L42MK3"
    assert "in 2 models" in card["body"] and "One answer sets each device of that model" in card["body"]
    # One answer, saved on one socket, covers the other two.
    coord.page_set_power(sockets[0].id, "AA", 2)
    card = _card(coord, KIND_POWER)
    assert {row["name"] for row in card["devices"]} == {"Dimmer", "Accessory"}


async def test_type_not_set_is_grouped_too(hass: HomeAssistant):
    sockets = [register_device(hass, f"s{n}", name=f"Socket {n}")[0] for n in range(2)]
    for device in sockets:
        _model(hass, device, "LightwaveRF", "L42MK3")
    coord = await setup_coordinator(hass)
    card = _card(coord, KIND_TYPE)
    assert card["grouped"] is True and "in 1 model" in card["body"]
    assert {row["model_key"] for row in card["devices"] if row["name"].startswith("Socket")} == {model_key("LightwaveRF", "L42MK3", None)}


def test_a_placeholder_maker_or_model_is_no_model():
    assert model_key("Default-Manufacturer", "Default-Model", None) is None
    assert model_key("Acme", "Default-Model", None) is None
    assert model_key("Default-Manufacturer", "Plug", None) is None
    assert model_key("Acme", "Plug 2", None) is not None
    assert placeholder_key(json.dumps(["Default-Manufacturer", "Default-Model", ""]))
    assert not placeholder_key(json.dumps(["Acme", "Plug", ""]))


async def test_one_answer_on_a_placeholder_device_covers_only_it(hass: HomeAssistant):
    first, _ = register_device(hass, "h1", name="Camera Porch")
    second, _ = register_device(hass, "h2", name="Camera Yard")
    for device in (first, second):
        _model(hass, device, "Default-Manufacturer", "Default-Model")
    coord = await setup_coordinator(hass)
    coord.page_set_power(first.id, "AA", 2)
    assert coord.power_of(first.id) is not None
    assert coord.power_of(second.id) is None
    rows = {row["name"]: row for row in _card(coord, KIND_POWER)["devices"]}
    assert rows["Camera Yard"]["model_key"] is None


async def test_an_answer_stored_under_a_placeholder_stays_with_its_device(hass: HomeAssistant):
    """An answer saved before this release under a placeholder key covered
    every such device. It now belongs to the device that gave it."""
    first, _ = register_device(hass, "h1", name="Camera Porch")
    second, _ = register_device(hass, "h2", name="Camera Yard")
    for device in (first, second):
        _model(hass, device, "Default-Manufacturer", "Default-Model")
    coord = await setup_coordinator(hass)
    key = json.dumps(["Default-Manufacturer", "Default-Model", ""])
    entry = {"kind": "battery", "type": "AA", "quantity": 2, "set": "2026-11-01T00:00:00+00:00", "device_id": first.id}
    coord._power_models, coord._power_entries = {}, {}
    coord._power_read({"models": {key: entry}, "devices": {}})
    assert key not in coord._power_models
    assert first.id in coord._power_entries
    assert coord.power_of(second.id) is None


async def test_a_unit_over_its_sockets_is_not_a_mixed_model(hass: HomeAssistant):
    unit, _ = register_device(hass, "u1", name="Kitchen Unit")
    sockets = [register_device(hass, f"k{n}", name=f"Kitchen Socket {n}")[0] for n in range(2)]
    _model(hass, unit, "LightwaveRF", "L42MK3")
    for device in sockets:
        _model(hass, device, "LightwaveRF", "L42MK3", via=unit.id)
    coord = await setup_coordinator(hass)
    coord.page_set_type(unit.id, "Hub")
    coord._type_models.clear()
    coord._type_entries[unit.id] = {"type": "Hub", "set": "2026-11-01T00:00:00+00:00"}
    for device in sockets:
        coord._type_entries[device.id] = {"type": "Switch", "set": "2026-11-01T00:00:00+00:00"}
    assert _card(coord, KIND_MIXED_TYPES) is None
    # Two units of the same model that disagree are still a mixed model.
    other, _ = register_device(hass, "u2", name="Hall Unit")
    _model(hass, other, "LightwaveRF", "L42MK3")
    coord._registry_refresh() if hasattr(coord, "_registry_refresh") else None
    coord._watched[other.id] = "test"
    coord._type_entries[other.id] = {"type": "Plug", "set": "2026-11-01T00:00:00+00:00"}
    card = _card(coord, KIND_MIXED_TYPES)
    assert card is not None and card["grouped"] is True
    assert {row["type"] for row in card["devices"]} == {"Hub", "Switch", "Plug"}


def test_a_board_or_a_generic_template_is_no_model():
    """Names from two testers' houses."""
    assert model_key("Espressif", "m5stack-atom", None) is None
    assert model_key("Espressif", "esp32-s3-devkitc-1", None) is None
    assert model_key("Espressif Inc. (esphome)", "esp32doit-devkit-v1", None) is None
    assert model_key("Tasmota", "Generic", None) is None
    # A device's own project name is a model.
    assert model_key("tim_plas", "atom_lite_contact", None) is not None
    assert model_key("TP-Link", "HS200", None) is not None
    stored = json.dumps(["Espressif", "m5stack-atom", ""])
    assert placeholder_key(stored) is True


async def test_boards_keep_a_row_each(hass: HomeAssistant):
    names = ["dryer-temp", "furnace-electric", "Mopeka Display"]
    for n, name in enumerate(names):
        device, _ = register_device(hass, f"b{n}", name=name)
        _model(hass, device, "Espressif", "m5stack-atom")
    coord = await setup_coordinator(hass)
    card = _card(coord, KIND_POWER)
    rows = [row for row in card["devices"] if row["name"] in names]
    assert len(rows) == 3 and all(row["model_key"] is None for row in rows)
    # One answer covers only the device it was given on.
    coord.page_set_power(rows[0]["device_id"], "AA", 2)
    card = _card(coord, KIND_POWER)
    assert len([row for row in card["devices"] if row["name"] in names]) == 2


async def test_a_model_rows_answer_clears_its_devices_own(hass: HomeAssistant):
    units = [register_device(hass, f"u{n}", name=f"Unit {n}")[0] for n in range(3)]
    for device in units:
        _model(hass, device, "Acme", "Relay 2")
    coord = await setup_coordinator(hass)
    # Two devices with answers of their own, from an older file.
    coord._type_entries[units[1].id] = {"type": "Light", "set": "2026-10-01T00:00:00+00:00"}
    coord._type_entries[units[2].id] = {"type": "Plug", "set": "2026-10-01T00:00:00+00:00"}
    # From the device page, the others keep their own (rule DEV-10).
    coord.page_set_type(units[0].id, "Switch")
    assert units[1].id in coord._type_entries
    # From the model's row, the whole model.
    coord.page_set_type(units[0].id, "Switch", whole_model=True)
    assert units[1].id not in coord._type_entries and units[2].id not in coord._type_entries
    assert {coord.type_of(device.id)["words"] for device in units} == {"Switch"}


async def test_a_refused_answer_takes_nothing_with_it(hass: HomeAssistant):
    units = [register_device(hass, f"u{n}", name=f"Unit {n}")[0] for n in range(2)]
    for device in units:
        _model(hass, device, "Acme", "Relay 2")
    coord = await setup_coordinator(hass)
    coord._type_entries[units[1].id] = {"type": "Light", "set": "2026-10-01T00:00:00+00:00"}
    try:
        coord.page_set_type(units[0].id, "Other", "", whole_model=True)
    except ValueError:
        pass
    assert coord._type_entries[units[1].id]["type"] == "Light"
