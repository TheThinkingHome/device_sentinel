# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_answers.py, Version: 0.27.8 (2026-10-27)

"""The download carries the ticked recommendations and the battery
answers beside the other answers (rule STOR-21), so a fault in either
can be read from it."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from .helpers import register_device, setup_coordinator


async def test_ticks_and_battery_answers_are_in_the_download(hass: HomeAssistant):
    device, _ = register_device(hass, "dev_d")
    coord = await setup_coordinator(hass)
    coord._recommendation_acks = {
        "devices": {device.id: {"slow_reporting": "TICKMARKER"}},
        "lines": {"LINEMARKER": "2026-10-01"},
    }
    coord._battery_replacement_answers = {device.id: {"day": "1999-09-09", "set": "BATTMARKER"}}
    diag = await async_get_config_entry_diagnostics(hass, coord.entry)
    text = json.dumps(diag, default=str)
    for marker in ("TICKMARKER", "LINEMARKER", "1999-09-09", "BATTMARKER"):
        assert marker in text, marker
    answers = json.dumps(diag, default=str)
    assert '"acknowledged"' in answers and '"battery"' in answers


async def test_nothing_answered_reads_empty(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    diag = await async_get_config_entry_diagnostics(hass, coord.entry)
    text = json.dumps(diag, default=str)
    assert '"acknowledged"' in text
