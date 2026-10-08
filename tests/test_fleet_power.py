# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_fleet_power.py, Version: 0.25.0 (2026-10-08)

"""Real houses' power files through the Power row (fleet refresh, 8 October 2026).

The power file is the one thing in storage a person types by hand, and
until this refresh the suite read it only from entries the tests made
up. Each house that has one is loaded as it was saved: one device is
registered for every model entry, made by the stand-in maker, model and
model ID the anonymizer gave that entry, so the entry finds its device
exactly as it does in the house.

Three claims per house:
1. every entry loads, and none is left out;
2. every device answers with its owner's entry, in the words a person
   reads on the page;
3. a pencil save that changes nothing writes back every entry as it was
   loaded, so a save can never lose another device's answer.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.power_source import (
    POWER_STORE_KEY,
    SOURCE_OWNER,
    power_words,
)

from .conftest import fleet_param
from .helpers import register_device, setup_coordinator

HOUSES = [
    fleet_param("reference", "device_sentinel.power", id="reference"),
    fleet_param("second", "device_sentinel_power.json", id="second"),
]


def _seat(hass: HomeAssistant, hass_storage, path):
    """Load the house's power file and register one device per model."""
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    hass_storage[POWER_STORE_KEY] = document
    models = document["data"].get("models") or {}
    seated = {}
    for number, (key, entry) in enumerate(sorted(models.items())):
        maker, model, model_id = json.loads(key)
        device, _ = register_device(hass, f"pf{number}", f"Power {number:03d}")
        dr.async_get(hass).async_update_device(
            device.id, manufacturer=maker, model=model, model_id=model_id or None
        )
        seated[device.id] = (key, entry)
    return document, seated


@pytest.mark.parametrize("path", HOUSES)
async def test_a_real_power_file_loads_whole_and_answers_every_device(
    hass: HomeAssistant, hass_storage, caplog, path
):
    _document, seated = _seat(hass, hass_storage, path)
    assert seated, "the house's power file holds no model entries"
    coord = await setup_coordinator(hass)
    assert "could not read" not in caplog.text, "an entry was left out at load"
    assert len(coord._power_models) == len(seated)
    for device_id, (key, entry) in seated.items():
        known = coord.power_of(device_id)
        assert known is not None, f"{key}: no answer"
        assert known["source"] == SOURCE_OWNER, f"{key}: answered from {known['source']}"
        assert known["words"] == power_words(entry["type"], entry["quantity"]), key
        assert coord.power_view(device_id)["words"] == known["words"], key


@pytest.mark.parametrize("path", HOUSES)
async def test_an_unchanged_pencil_save_writes_every_entry_back(
    hass: HomeAssistant, hass_storage, path
):
    document, seated = _seat(hass, hass_storage, path)
    before = {
        key: (entry["kind"], entry["type"], entry["quantity"])
        for key, entry in document["data"]["models"].items()
    }
    coord = await setup_coordinator(hass)
    device_id, (key, entry) = next(iter(seated.items()))
    if entry["kind"] == "battery":
        coord.page_set_power(device_id, entry["type"], entry["quantity"] or 1)
    else:
        coord.page_set_power(device_id, entry["type"])
    await coord.async_flush_power()
    written = hass_storage[POWER_STORE_KEY]["data"]
    after = {
        k: (e["kind"], e["type"], e["quantity"]) for k, e in written["models"].items()
    }
    assert after == before
    # Each model entry keeps its copy under a device for 0.24.7.
    copies = [e for e in written["devices"].values() if "model" in e]
    assert len(copies) == len(before)
