# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_trends_cell.py, Version: 0.27.10 (2026-10-27)

"""Battery Trends' CELL column names the battery each device takes
(rules BAT-16, BAT-18).

The column names every battery, not only a lithium cell, so a blank
never means two things: a battery known not to be lithium, such as the
AAA cells of a Third Reality door sensor, reads as its cells. Each
row carries the words its Power row shows, from the owner's answer or
the Battery Notes library, or None when neither knows, which the panel
shows as "Not set".
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import DEV_BATTERY_DAILY, DEV_BATTERY_VALUE

from .helpers import register_device, registry_settled, setup_coordinator


def _with_battery(coord, *devices):
    for device in devices:
        record = coord.data["devices"][device.id]
        record[DEV_BATTERY_DAILY] = [100.0] * 60
        record[DEV_BATTERY_VALUE] = 100.0


def _steady(coord):
    return {row["name"]: row for row in coord.battery_trends()["steady"]}


async def test_each_known_battery_is_named(hass: HomeAssistant):
    """The owner's answer, lithium or not, as the Power row says it."""
    coord = await setup_coordinator(hass)
    coin, _ = register_device(hass, "c1", "Door Bath Main")
    alkaline, _ = register_device(hass, "a1", "Door Kitchen")
    await registry_settled(hass)
    coord.page_set_power(coin.id, "CR1632", 1)
    coord.page_set_power(alkaline.id, "AAA", 2)
    _with_battery(coord, coin, alkaline)

    rows = _steady(coord)
    assert (rows["Door Bath Main"]["cell"], rows["Door Bath Main"]["lithium"]) == ("CR1632", "CR1632")
    assert (rows["Door Kitchen"]["cell"], rows["Door Kitchen"]["lithium"]) == ("2× AAA", None)


async def test_the_library_names_a_battery_nobody_set(hass: HomeAssistant):
    """A Third Reality door sensor, from the Battery Notes library."""
    coord = await setup_coordinator(hass)
    door, _ = register_device(hass, "t1", "Door Laundry")
    dr.async_get(hass).async_update_device(door.id, manufacturer="Third Reality, Inc", model="3RDS17BZ")
    await registry_settled(hass)
    _with_battery(coord, door)

    row = _steady(coord)["Door Laundry"]
    assert (row["cell"], row["lithium"]) == ("2× AAA", None)


async def test_one_answer_names_every_device_of_the_model(hass: HomeAssistant):
    """The pencil on one device answers for its model (rule DEV-06)."""
    coord = await setup_coordinator(hass)
    first, _ = register_device(hass, "m1", "Leak Sink")
    second, _ = register_device(hass, "m2", "Leak Bath")
    for device in (first, second):
        dr.async_get(hass).async_update_device(device.id, manufacturer="Maker", model="Leak One")
    await registry_settled(hass)
    coord.page_set_power(first.id, "CR2032", 1)
    _with_battery(coord, first, second)

    assert _steady(coord)["Leak Bath"]["cell"] == "CR2032"


async def test_a_battery_nobody_knows_has_no_cell(hass: HomeAssistant):
    """No answer and no library entry: the panel says Not set."""
    coord = await setup_coordinator(hass)
    unknown, _ = register_device(hass, "u1", "Motion Hall")
    await registry_settled(hass)
    _with_battery(coord, unknown)

    row = _steady(coord)["Motion Hall"]
    assert (row["cell"], row["lithium"]) == (None, None)


async def test_a_wired_answer_reads_as_its_power_row_does(hass: HomeAssistant):
    """A device with a battery reading that its owner called mains
    powered shows those words, as its Power row does."""
    coord = await setup_coordinator(hass)
    plug, _ = register_device(hass, "w1", "Plug Desk")
    await registry_settled(hass)
    coord.page_set_power(plug.id, "Mains Powered")
    _with_battery(coord, plug)

    row = _steady(coord)["Plug Desk"]
    assert (row["cell"], row["lithium"]) == ("Mains Powered", None)
