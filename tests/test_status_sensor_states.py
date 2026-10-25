# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_status_sensor_states.py, Version: 0.27.4 (2026-10-25)

"""The Status sensor reads Watching, Learning or Problem (rule CFG-07).

Home Assistant shows an enum sensor's state through its state
translations. The stored value stays the lowercase id, so an automation
testing for `watching` keeps working.
"""

from __future__ import annotations

import json
import pathlib

from homeassistant.core import HomeAssistant

from tests.helpers import setup_entry

PKG = pathlib.Path(__file__).parent.parent / "custom_components" / "device_sentinel"


async def test_status_reads_in_title_case_and_keeps_its_stored_value(hass: HomeAssistant):
    await setup_entry(hass)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_status")
    options = state.attributes.get("options")
    assert options == ["watching", "learning", "problem"]
    assert state.state in options
    for name in ("strings.json", "translations/en.json"):
        status = json.loads((PKG / name).read_text(encoding="utf-8"))["entity"]["sensor"]["status"]
        assert status["state"] == {
            "watching": "Watching",
            "learning": "Learning",
            "problem": "Problem",
        }, name
