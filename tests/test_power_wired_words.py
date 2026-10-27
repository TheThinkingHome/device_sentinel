# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_power_wired_words.py, Version: 0.27.7 (2026-10-27)

"""Wired words typed under Other are the wired choice, whatever their
capitals (rules DEV-08, DEV-09): "usb direct to server" is USB Direct to
Server, never one battery, and is never offered to Battery Notes."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.power_source import POWER_OTHER, _clean_entry, wired_choice

from .helpers import register_device, setup_coordinator


@pytest.mark.parametrize("typed", ["USB Direct to Server", "usb direct to server", "  USB  direct to SERVER "])
async def test_typed_under_other_it_is_the_wired_choice(hass: HomeAssistant, typed):
    device, _ = register_device(hass, "z1", name="Z-Wave Stick")
    dr.async_get(hass).async_update_device(device.id, manufacturer="Zooz", model="ZST39")
    coord = await setup_coordinator(hass)
    coord.page_set_power(device.id, POWER_OTHER, 1, typed)
    known = coord.power_of(device.id)
    assert known["kind"] != "battery"
    assert known["type"] == "USB Direct to Server"
    assert coord.power_report_url(device.id) is None


def test_a_stored_entry_in_any_capitals_loads_as_the_choice():
    entry = _clean_entry({"kind": "battery", "type": "usb direct to server", "quantity": 1})
    assert entry["kind"] != "battery" and entry["type"] == "USB Direct to Server"


def test_a_real_battery_is_not_taken_for_a_wired_choice():
    assert wired_choice("CR2032") is None
    assert wired_choice("USB Direct to Server Pack") is None
