# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_router_clients.py, Version: 0.28.12 (2026-11-11)

"""A router's clients are not named in the download (rule STOR-21).

A router's client devices, "named by their hostnames,
often a person's", go out by their router and a number. The same
hostname is the tracker's entity id, and the Wi-Fi medium tables
(classification.wifi.medium_seen, medium_scores) list every router
tracker in the house that has been home, tied to a watched device or
not: every phone, by its owner's name.

Correct behaviour: a phone's tracker id does not reach the download.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry


async def test_a_phone_tracker_is_not_named_in_the_download(hass: HomeAssistant):
    reg = er.async_get(hass)
    tracker = reg.async_get_or_create(
        "device_tracker", "tplink_router", "aabbcc112233",
        suggested_object_id="janes_iphone",
    )
    assert tracker.entity_id == "device_tracker.janes_iphone"
    hass.states.async_set(
        tracker.entity_id,
        "home",
        {"source_type": "router", "mac": "AA-BB-CC-11-22-33", "band": "5G",
         "friendly_name": "Janes-iPhone"},
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_wifi_ties()
    await hass.async_block_till_done()

    text = json.dumps(
        await async_get_config_entry_diagnostics(hass, entry), default=str
    )
    assert "janes_iphone" not in text.lower()
