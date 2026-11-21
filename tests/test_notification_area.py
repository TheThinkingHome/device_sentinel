# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notification_area.py, Version: 0.30.0 (2026-11-21)

"""A phone message says where the device is (rules NOTE-13, BRIEF-13).

Home Assistant 2026.11 names each device for what it is and lets the
area tell devices of one name apart, so three sensors of one name read
apart only with their rooms. Every phone and persistent notification
carries the area in brackets, unless the name already says where the
device is: it ends in a bracket, or holds the area's name, as names
were written before Home Assistant had areas.
"""

from __future__ import annotations

import os

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    TODO_KIND_LOW_BATTERY,
)
from custom_components.device_sentinel.naming import area_is_said, with_area

from .helpers import setup_coordinator, thresholds
from .test_falling_surfaces import _battery_device

NAME = "TIMMERFLOTTE temp/hmd sensor"


@pytest.mark.parametrize(
    ("name", "area", "said"),
    [
        (NAME, "Kitchen", f"{NAME} (Kitchen)"),
        (NAME, None, NAME),
        (NAME, "  ", NAME),
        ("Kitchen light", "Kitchen", "Kitchen light"),
        ("kitchen light", "Kitchen", "kitchen light"),
        ("Soil Moisture (Monstera)", "Living Room", "Soil Moisture (Monstera)"),
        ("Sensor [spare]", "Office", "Sensor [spare]"),
        ("Door 2nd Bedroom", "Guest", "Door 2nd Bedroom (Guest)"),
        ("Socket 1", "1", "Socket 1 (1)"),
    ],
)
def test_a_name_takes_its_area_unless_it_says_it(name, area, said):
    assert with_area(name, area) == said


@pytest.mark.parametrize(
    ("name", "area", "said"),
    [("Garden plug", "Den", False), ("Bathroom shelf", "Bath", False), ("Bedroom 2 lamp", "Bedroom", True),
     ("Lamp (Living Room)", "Office", True), ("Office.Lamp", "Office", True), ("Den+lamp", "Den", True),
     ("kitchen_light", "Kitchen", True), ("Socket 1", "1", False), ("Plug 2.4", "2.4", False),
     ("Lamp (spare)", "3", True), ("Room 12 sensor", "Room 12", True)],
)
def test_an_area_is_said_only_as_whole_words(name, area, said):
    """"Den" is not in "Garden plug": the area is found as whole words,
    so a short area inside a longer word still gets its bracket."""
    assert area_is_said(name, area) is said


def _room(hass: HomeAssistant, device_id: str, name: str) -> None:
    area = ar.async_get(hass).async_create(name)
    dr.async_get(hass).async_update_device(device_id, area_id=area.id)


async def test_the_phone_summary_names_the_room(hass: HomeAssistant):
    device, entity_id = _battery_device(hass, NAME, 12)
    _room(hass, device.id, "Kitchen")
    coord = await setup_coordinator(hass, {**thresholds(15.0), "persistent_enabled": True})
    coord._grace_until = 0.0
    hass.states.async_set(entity_id, "12", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    coord._sync_problem_list()
    assert f"{NAME} (Kitchen) 12%" in coord._family_summary("battery")


async def test_the_phone_message_names_the_room(hass: HomeAssistant):
    device, _ = _battery_device(hass, NAME, 12)
    _room(hass, device.id, "Kitchen")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._pending_events.clear()
    coord._collect_event(TODO_KIND_LOW_BATTERY, NAME, False, device.id)
    lines = [line for _family, line, _recovery in coord._pending_events]
    assert lines and "At " in lines[0] and f"{NAME} (Kitchen) battery" in lines[0], lines


async def test_a_name_holding_its_room_is_not_told_it_twice(hass: HomeAssistant):
    device, entity_id = _battery_device(hass, "Kitchen leak sensor", 12)
    _room(hass, device.id, "Kitchen")
    coord = await setup_coordinator(hass, {**thresholds(15.0), "persistent_enabled": True})
    coord._grace_until = 0.0
    hass.states.async_set(entity_id, "12", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    coord._sync_problem_list()
    summary = coord._family_summary("battery")
    assert "Kitchen leak sensor 12%" in summary
    assert "(Kitchen)" not in summary

    # The brief's table does not add "[Kitchen]" either (rule BRIEF-13).
    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML), encoding="utf-8") as handle:
        brief = handle.read()
    assert "[Kitchen]" not in brief


async def test_a_device_with_no_area_reads_as_before(hass: HomeAssistant):
    _device, entity_id = _battery_device(hass, NAME, 12)
    coord = await setup_coordinator(hass, {**thresholds(15.0), "persistent_enabled": True})
    coord._grace_until = 0.0
    hass.states.async_set(entity_id, "12", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    coord._sync_problem_list()
    summary = coord._family_summary("battery")
    assert f"{NAME} 12%" in summary
