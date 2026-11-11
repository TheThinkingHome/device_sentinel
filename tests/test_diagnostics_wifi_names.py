# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_wifi_names.py, Version: 0.28.12 (2026-11-11)

"""The house's Wi-Fi name must not reach the
diagnostics download through the Problem List (rule STOR-21, since
STOR-21: "the Wi-Fi networks a house watches ... are named by
stand-ins").

The options and the scan section are hidden, but a Wi-Fi outage's row
names the network in its description ("The 'Lander Family 5G' WiFi
network became unavailable at ..."), and the download carries
todo_items raw. A person who downloads diagnostics during or right
after a Wi-Fi outage, to attach to a public issue, publishes the SSID.

Asserts the safe behaviour.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_WIFI_NETWORKS,
    DATA_TODO_ITEMS,
    TODO_DESCRIPTION,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry

OWN_SSID = "Lander Family 5G"


async def test_a_wifi_outage_row_does_not_carry_the_network_name_into_the_download(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass, {CONF_WIFI_NETWORKS: [OWN_SSID]})
    coord = entry.runtime_data
    # The row exactly as the coordinator words a Wi-Fi outage.
    summary, description = coord._wifi_item_text(7, 14, "07:12")
    assert OWN_SSID in description  # precondition: the row names it
    coord.data.setdefault(DATA_TODO_ITEMS, []).append(
        {
            TODO_UID: "upstream:wifi",
            TODO_DEVICE_ID: "upstream:wifi",
            TODO_SORT_NAME: "WiFi network",
            TODO_SUMMARY: summary,
            TODO_DESCRIPTION: description,
            TODO_KINDS: {"upstream": 1.0},
            TODO_STATUS: "needs_action",
        }
    )
    text = json.dumps(
        await async_get_config_entry_diagnostics(hass, entry), default=str
    )
    assert OWN_SSID not in text
