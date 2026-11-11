# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_tracker_names.py, Version: 0.28.12 (2026-11-11)

"""A router client's tracker entity id,
made from its hostname, still reaches the diagnostics download.

Rule STOR-21: "A router's client devices, named by their
hostnames, often a person's, go out by their router and a number."
The fix covers _infrastructure. But the Wi-Fi medium scoring
(router_ties._score_wifi_medium) keeps a row for every router tracker
that has been home, keyed by its entity id, and diagnostics prints that
table under classification.wifi.medium_seen and medium_scores (and
wired_skipped, medium_rejected). A router integration names a client's
tracker from its hostname: device_tracker.janes_iphone. Every house with
Fritz!Box, UniFi, TP-Link, Netgear and the like has one per phone and
laptop, with no opt-in.

Asserts the safe behaviour.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry

HOSTNAME_ID = "janes_iphone"


async def test_a_router_clients_tracker_name_does_not_reach_the_download(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        "fritz",
        "AA:BB:CC:11:22:33",
        suggested_object_id=HOSTNAME_ID,
    )
    hass.states.async_set(
        f"device_tracker.{HOSTNAME_ID}",
        "home",
        {
            "source_type": "router",
            "mac": "AA:BB:CC:11:22:33",
            "ip": "192.168.1.20",
            "host_name": "Janes-iPhone",
            "ssid": "Lander Family 5G",
        },
    )
    await hass.async_block_till_done()
    coordinator._rebuild_wifi_ties()
    data = await async_get_config_entry_diagnostics(hass, entry)
    wifi = data["classification"]["wifi"]
    # Precondition: the tracker was scored, so the table holds a row.
    assert wifi["medium_seen"], wifi
    assert HOSTNAME_ID not in json.dumps(data, default=str)
