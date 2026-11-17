# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_tables.py, Version: 0.29.5 (2026-11-17)

"""The download carries the tables a fault report is read from (rule STOR-21).

How each router-tracked device was classed, wired or wireless, decides
which devices a Wi-Fi outage claims, and an integration's daily storm
tally is the evidence for the noisy-integration advice. A report about
either is read from these tables, so the download carries both. A
tracker is named after a hostname, often a person's, so each one leaves
by its stand-in.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_STORM_DAYS,
    DATA_WIFI_MEDIUM,
    DATA_WIFI_MEDIUM_REJECTED,
)
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from .helpers import setup_entry


async def test_the_download_carries_the_wifi_classing_with_trackers_hidden(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_WIFI_MEDIUM] = {
        "device_tracker.janes_iphone": {"wired": 13, "wireless": 1507},
        "device_tracker.printer_hallway": {"wired": 900, "wireless": 0},
    }
    coord.data[DATA_WIFI_MEDIUM_REJECTED] = {"device_tracker.janes_iphone": 4}
    out = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(out, default=str)
    assert "janes_iphone" not in text
    assert "printer_hallway" not in text
    medium = out["classification"]["wifi_medium"]
    assert sorted(medium.values(), key=lambda v: v["wired"]) == [
        {"wired": 13, "wireless": 1507},
        {"wired": 900, "wireless": 0},
    ]
    assert all(key.startswith("device_tracker.tracker_") for key in medium)
    # The same tracker keeps one stand-in across both tables.
    phone = next(key for key, v in medium.items() if v["wired"] == 13)
    assert out["classification"]["wifi_medium_rejected"] == {phone: 4}


async def test_the_download_carries_each_integrations_daily_storms(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    row = {"day": "2026-08-25", "domain": "tplink_router", "count": 696,
           "median_interval": 35.2, "median_devices": 5.0, "median_duration": 5.0}
    coord.data[DATA_STORM_DAYS] = [row]
    out = await async_get_config_entry_diagnostics(hass, entry)
    assert out["classification"]["storm_days"] == [row]
