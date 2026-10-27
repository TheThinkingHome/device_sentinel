# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_coarse_page.py, Version: 0.27.7 (2026-10-27)

"""A coarse battery is judged by the low threshold alone (rule BAT-10):
the device page marks it coarse and never reads it as falling, even
after a 10-point step. The page's words are checked in
tools/panel_checks/check_battery_steps.js."""

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_BATTERY_DAILY, DEV_BATTERY_VALUE

from .helpers import register_device, setup_coordinator


async def test_a_coarse_cell_after_a_step_is_coarse_not_falling(hass: HomeAssistant):
    device, _ = register_device(hass, "coarse1", name="Office Temp/Humid")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_DAILY] = [50.0] * 14 + [40.0] * 24 + [30.0] * 4
    record[DEV_BATTERY_VALUE] = 30.0
    assert coord.battery_steps(record) == "coarse"
    battery = coord.dashboard_device(device.id)["battery"]
    assert battery["coarse"] is True
    assert battery["falling"] is False
    assert battery["left"] is None


async def test_a_smooth_cell_is_not_coarse(hass: HomeAssistant):
    device, _ = register_device(hass, "smooth1", name="Door Hall")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_DAILY] = [40.0 - 0.3 * i for i in range(42)]
    record[DEV_BATTERY_VALUE] = record[DEV_BATTERY_DAILY][-1]
    assert coord.dashboard_device(device.id)["battery"]["coarse"] is False
