# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_lithium.py, Version: 0.27.1 (2026-10-23)

"""A lithium cell is said to be one (#736).

James's 11 Aqara coin cells on Zigbee2MQTT read exactly 100% on all 85
days of 23 October 2026: a lithium cell's percentage holds near full
until its end, so a steady reading says little about time left.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DEV_BATTERY_DAILY, DEV_BATTERY_VALUE
from custom_components.device_sentinel.power_source import lithium_cell

from .helpers import register_device, registry_settled, setup_coordinator


@pytest.mark.parametrize(
    ("battery_type", "lithium"),
    [("CR2032", True), ("cr1632", True), (" CR2450", True), ("CR123A", True), ("CR2", True),
     ("AAA", False), ("AA", False), ("Rechargeable", False), (None, False), (3, False)],
)
def test_a_cr_type_is_lithium(battery_type, lithium):
    assert lithium_cell(battery_type) is lithium


async def test_a_lithium_cell_is_said_to_be_one(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coin, _ = register_device(hass, "li1", "Door Bath Main")
    alkaline, _ = register_device(hass, "al1", "Door Kitchen")
    await registry_settled(hass)
    coord.page_set_power(coin.id, "CR1632", 1)
    coord.page_set_power(alkaline.id, "AAA", 2)
    for device in (coin, alkaline):
        record = coord.data["devices"][device.id]
        record[DEV_BATTERY_DAILY] = [100.0] * 60
        record[DEV_BATTERY_VALUE] = 100.0
    assert coord.battery_lithium(coin.id) == "CR1632"
    assert coord.battery_lithium(alkaline.id) is None
    assert coord._page_battery(coord.data["devices"][coin.id], coin.id)["lithium"] == "CR1632"
    assert coord._page_battery(coord.data["devices"][alkaline.id], alkaline.id)["lithium"] is None
    steady = {row["name"]: row for row in coord.battery_trends()["steady"]}
    assert steady["Door Bath Main"]["lithium"] == "CR1632"
    assert steady["Door Kitchen"]["lithium"] is None
