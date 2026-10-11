# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_fleet_answers.py, Version: 0.25.6 (2026-10-11)

"""Real houses' answers files through the Power and Type rows.

The answers file holds the only things in storage a person types by
hand: what powers each device and what each device is. The suite reads
it from the houses as they saved it. One device is registered for every
model answer, made by the stand-in maker, model and model ID the
anonymizer gave that answer, so the answer finds its device exactly as
it does in the house.

Before the fleet refresh of 11 October 2026 the houses carried the
power file of 0.24.7, and this file proved its move into the answers
file. The move itself is proven on made-up entries in
test_answers_store.py.

Three claims per house:
1. every answer loads, and none is left out;
2. every device answers with its owner's power and type, in the words a
   person reads on the page;
3. a pencil save that changes nothing writes back every answer as it
   was loaded, power and type alike, so a save can never lose another
   device's answer. As loaded rather than as stored: the reference
   house's Zooz stick was typed "USB Direct to Server" under Other on
   9 October, hours before that became a choice, and it loads as the
   choice (#618).
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY
from custom_components.device_sentinel.power_source import SOURCE_OWNER, power_words

from .conftest import fleet_param
from .helpers import register_device, setup_coordinator

HOUSES = [
    fleet_param("reference", "device_sentinel.answers", id="reference"),
    fleet_param("second", "device_sentinel_answers.json", id="second"),
]


def _seat(hass: HomeAssistant, hass_storage, path):
    """Load the house's answers file and register one device per model
    that any answer names."""
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    hass_storage[ANSWERS_STORE_KEY] = document
    data = document["data"]
    keys = sorted(set(data["power"]["models"]) | set(data["types"]["models"]))
    seated = {}
    for number, key in enumerate(keys):
        maker, model, model_id = json.loads(key)
        device, _ = register_device(hass, f"af{number}", f"Answer {number:03d}")
        dr.async_get(hass).async_update_device(
            device.id, manufacturer=maker, model=model, model_id=model_id or None
        )
        seated[device.id] = key
    return document, seated


def _kept(part):
    """An answers part as the file states it, the time each was set aside."""
    return {
        side: {key: {k: v for k, v in entry.items() if k != "set"} for key, entry in part[side].items()}
        for side in ("models", "devices")
    }


@pytest.mark.parametrize("path", HOUSES)
async def test_a_real_answers_file_loads_whole_and_answers_every_device(
    hass: HomeAssistant, hass_storage, caplog, path
):
    document, seated = _seat(hass, hass_storage, path)
    assert seated, "the house's answers file holds no model answers"
    data = document["data"]
    coord = await setup_coordinator(hass)
    assert "could not read" not in caplog.text, "an answer was left out at load"
    counts = coord.answers_diagnostics()
    assert (counts["power_models"], counts["power_devices"], counts["type_models"], counts["type_devices"]) == (
        len(data["power"]["models"]), len(data["power"]["devices"]),
        len(data["types"]["models"]), len(data["types"]["devices"]),
    )
    for device_id, key in seated.items():
        power = data["power"]["models"].get(key)
        if power is not None:
            known = coord.power_of(device_id)
            assert known is not None and known["source"] == SOURCE_OWNER, f"{key}: power from {known}"
            assert known["words"] == power_words(power["type"], power["quantity"]), key
            assert coord.power_view(device_id)["words"] == known["words"], key
        kind = data["types"]["models"].get(key)
        if kind is not None:
            known = coord.type_of(device_id)
            assert known["source"] == SOURCE_OWNER, f"{key}: type from {known['source']}"
            assert known["words"] == kind["type"], key


@pytest.mark.parametrize("path", HOUSES)
async def test_an_unchanged_pencil_save_writes_every_answer_back(
    hass: HomeAssistant, hass_storage, path
):
    document, seated = _seat(hass, hass_storage, path)
    coord = await setup_coordinator(hass)
    # As loaded, which is not always byte for byte as stored: an answer
    # typed under Other in the words of a choice that came later reads
    # as that choice (#618), as the reference house's Zooz stick does.
    loaded = coord._answers_payload()
    before = {part: _kept(loaded[part]) for part in ("power", "types")}
    for part in before:
        for side in ("models", "devices"):
            assert set(before[part][side]) == set(document["data"][part][side]), f"{part} {side}"
    device_id, key = next(
        (d, k) for d, k in seated.items() if k in document["data"]["power"]["models"]
    )
    entry = document["data"]["power"]["models"][key]
    if entry["kind"] == "battery":
        coord.page_set_power(device_id, entry["type"], entry["quantity"] or 1)
    else:
        coord.page_set_power(device_id, entry["type"])
    await coord.async_flush_answers()
    # The save makes this device the one that set its model's answer;
    # nothing else may move.
    before["power"]["models"][key]["device_id"] = device_id
    written = hass_storage[ANSWERS_STORE_KEY]["data"]
    assert {part: _kept(written[part]) for part in ("power", "types")} == before
