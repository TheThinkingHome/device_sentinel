# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_type_list_names.py, Version: 0.27.10 (2026-10-27)

"""Words typed through Other that name a type on the list (rule DEV-11).

An owner's answer typed through Other is kept as the list's name when
it names a type on the list: the same words in another case or
spacing, or an earlier name for it. Coordinators typed as "ZHA
Coordinator" and "Zigbee2MQTT Coordinator" before the list named them,
and a robot vacuum typed as "Vacuum", take the list's names. Anything
else stays as the owner wrote it.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.device_type import (
    TYPE_CHOICES,
    list_name,
)

from .helpers import setup_coordinator


@pytest.mark.parametrize(("words", "expected"), [
    # Answers typed on the first fleet.
    ("ZHA Coordinator", "Zigbee Coordinator (ZHA)"),
    ("Zigbee2MQTT Coordinator", "Zigbee Coordinator (Zigbee2MQTT)"),
    ("Z-Wave Coordinator", "Z-Wave Controller"),
    # Answers typed on the second fleet.
    ("Vacuum", "Vacuum"),
    ("vacuum", "Vacuum"),
    ("RF IR Remote", "IR Remote"),
    ("ups", "UPS"),
    ("zigbee coordinator zha", "Zigbee Coordinator (ZHA)"),
    ("door window sensor", "Door/Window Sensor"),
    # His own words that name no type on the list stay his.
    ("Clothes dryer", "Clothes dryer"),
    ("Misc.", "Misc."),
    ("Lab equip", "Lab equip"),
    ("Other", "Other"),
])
def test_words_that_name_a_listed_type_take_its_name(words, expected):
    assert list_name(words) == expected


def test_every_listed_name_is_its_own_name():
    for name in TYPE_CHOICES[:-1]:
        assert list_name(name) == name


def _device(hass, uid, model):
    source = MockConfigEntry(domain="smlight")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("smlight", uid)}, name=uid,
        manufacturer="SMLIGHT", model=model,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "smlight", f"{uid}_temp", device_id=device.id, config_entry=source)
    return device


async def test_a_stored_answer_is_read_as_the_list_name(hass: HomeAssistant):
    """The rig's answers file as it stands: the coordinators read as listed."""
    zha = _device(hass, "SLZB-06", "SLZB-06")
    z2m = _device(hass, "SLZB-06M", "SLZB-06M")
    coord = await setup_coordinator(hass)
    coord._type_reset()
    dropped = coord._type_read({
        "models": {coord._power_key(zha.id): {"type": "ZHA Coordinator", "set": None, "device_id": zha.id}},
        "devices": {z2m.id: {"type": "Zigbee2MQTT Coordinator", "set": None},
                    "kept": {"type": "Clothes dryer", "set": None}},
    })

    assert dropped == 0
    assert coord.type_words(zha.id) == "Zigbee Coordinator (ZHA)"
    assert coord.type_words(z2m.id) == "Zigbee Coordinator (Zigbee2MQTT)"
    assert coord._type_payload()["devices"]["kept"]["type"] == "Clothes dryer"
    # The next save writes the list's name.
    assert coord._type_payload()["devices"][z2m.id]["type"] == "Zigbee Coordinator (Zigbee2MQTT)"


async def test_words_typed_now_that_name_a_listed_type_are_saved_as_it(hass: HomeAssistant):
    device = _device(hass, "vac", "RV20 Max Plus")
    coord = await setup_coordinator(hass)

    coord.page_set_type(device.id, "Other", "vacuum")

    assert coord.type_words(device.id) == "Vacuum"
    assert coord.type_view(device.id)["words"] == "Vacuum"
