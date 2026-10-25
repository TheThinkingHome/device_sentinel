# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_plain_names.py, Version: 0.27.4 (2026-10-25)

"""The Daily Brief and the railed-signal rows name a device plainly
(rule DEV-04).

Two devices sharing a name read "Bluetooth Proxy (test)" in the brief
and on the railed rows; the integration belongs on the Settings lists
only, once. The brief and the dashboard keep the plain name.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import INC_DEVICE_ID, INC_NAME

from tests.helpers import register_device, setup_coordinator


async def test_a_shared_name_reads_plainly(hass: HomeAssistant):
    one, _ = register_device(hass, "bp1", name="Bluetooth Proxy")
    two, _ = register_device(hass, "bp2", name="Bluetooth Proxy")
    coord = await setup_coordinator(hass)
    for device in (one, two):
        told = coord._told_name({INC_DEVICE_ID: device.id, INC_NAME: "Old Name"})
        assert told == "Bluetooth Proxy"
        assert coord._trim_name(device.id) == "Bluetooth Proxy"
    coord.signal_railed = lambda record: True
    names = {row["name"] for row in coord.signal_problem_list}
    assert names == {"Bluetooth Proxy"}
