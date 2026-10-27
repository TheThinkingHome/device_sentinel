# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_level_text.py, Version: 0.27.10 (2026-10-27)

"""One battery level, said the same way everywhere (rule BAT-03).

The Daily Brief, both dashboards and the phone's summary once rounded
the same reading three ways: 15.5%, 16% and 15%. The level is said as
reported, one decimal at most.
"""

from __future__ import annotations

import os

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.battery_level import level_text
from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    TODO_KIND_LOW_BATTERY,
)

from .helpers import setup_coordinator
from .test_falling_surfaces import _battery_device


@pytest.mark.parametrize(
    ("level", "words"),
    [(15.5, "15.5%"), (16, "16%"), (16.0, "16%"), (100, "100%"), (0, "0%"), (0.04, "0%"),
     (15.35, "15.4%"), (15.25, "15.3%"), (99.95, "100%"), (None, ""), (True, ""),
     (float("nan"), ""), ("15", "")],
)
def test_a_level_reads_as_reported(level, words):
    assert level_text(level) == words


async def test_every_surface_says_15_5(hass: HomeAssistant):
    device, entity_id = _battery_device(hass, "Door 2nd Bedroom", 15.5)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 16.0, "persistent_enabled": True})
    coord._grace_until = 0.0
    hass.states.async_set(entity_id, "15.5", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    coord._sync_problem_list()

    # The Problem List's item and the phone's and card's summary.
    item = next(i for i in coord.data["todo_items"] if i["device_id"] == device.id)
    assert TODO_KIND_LOW_BATTERY in item["kinds"]
    assert item["summary"] == "Door 2nd Bedroom: battery 15.5%"
    summary = coord._family_summary("battery")
    assert "Door 2nd Bedroom 15.5%" in summary and "15%" not in summary.replace("15.5%", "")

    # The Daily Brief.
    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML), encoding="utf-8") as handle:
        brief = handle.read()
    assert "battery 15.5%" in brief
    assert "battery 16%" not in brief and "battery 15%" not in brief
