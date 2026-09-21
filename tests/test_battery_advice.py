# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_advice.py, Version: 0.22.16 (2026-09-21)

"""The battery report's advice points at controls that exist.

Two lists told a person to "turn Battery off" or "turn Battery on"
for a device on its device page. Device Sentinel has never had such a
control. Ruled 21 September 2026, in the owner's words: mute the
device for battery in Configure, Low Battery; and for a device that
runs on batteries but reports none, press Enable Battery at the top of
the dashboard.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.helpers import register_device, setup_coordinator
from tests.test_battery_report import _page, _seed

NOT_A_PERCENTAGE = (
    "To take them out of these lists, mute them for battery in "
    "Configure, Low Battery."
)
NO_BATTERY = (
    "If one of these runs on batteries, its battery reading may be "
    "switched off: press Enable Battery at the top of the dashboard."
)


async def test_a_reading_that_is_not_a_percentage_is_muted_in_configure(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "adv1", "LUX Outdoors")
    _seed(coord, device.id, [196.0] * 16, 186.0)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)
    assert NOT_A_PERCENTAGE in page
    assert "Turn Battery off" not in page


async def test_a_device_with_no_battery_is_pointed_at_enable_battery(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    register_device(hass, "adv2", "Mains Plug")
    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _page(hass)
    assert "report no battery" in page
    assert NO_BATTERY in page
    assert "turn Battery on" not in page
    assert "device page" not in page
