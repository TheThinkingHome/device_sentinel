# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_mac_addresses.py, Version: 0.29.8 (2026-11-20)

"""Every MAC address leaves the diagnostics download, however it is
written beside other text (rule STOR-21).

Home Assistant writes a device's connections as "mac:" followed by the
address, and integrations add words to an address in their ids, such
as "_rssi" or "-adapter". The "ac" of "mac" and the "ad" of "adapter"
read as hex pairs, so a pattern that took them for a seventh pair kept
the whole address, as it keeps a Zigbee address. The Extended
Diagnostics study lists each watched device's connections, so turning
on any Hardware to Study choice put every address in the download.
"""

from __future__ import annotations

import json
import re

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE, STUDIABLE
from custom_components.device_sentinel.diagnostics import (
    _redact_addresses,
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_entry, share_names_off

ADDRESSES = ("b4:22:00:12:34:56", "ec:71:db:65:43:21", "20:f8:3b:ab:cd:ef")


def _carries(text: str, address: str) -> bool:
    """Whether the address is in the text whole, in any spelling."""
    flat = re.sub(r"[^0-9a-f]", "", text.lower())
    return address.replace(":", "") in flat


@pytest.mark.parametrize(
    ("written", "hidden"),
    [
        ("mac:b4:22:00:12:34:56", "mac:B4:22:00:MAC-01"),
        ("(mac:b4:22:00:12:34:56)", "(mac:B4:22:00:MAC-01)"),
        ("B4:22:00:12:34:56_rssi", "B4:22:00:MAC-01_rssi"),
        ("b4-22-00-12-34-56-adapter", "B4:22:00:MAC-01-adapter"),
        ("bluetooth:B4:22:00:12:34:56", "bluetooth:B4:22:00:MAC-01"),
        ("B4:22:00:12:34:56:aid:1", "B4:22:00:MAC-01:aid:1"),
        ("light_b4:22:00:12:34:56", "light_B4:22:00:MAC-01"),
    ],
)
def test_an_address_beside_a_word_is_hidden(written: str, hidden: str):
    assert _redact_addresses(written) == hidden


@pytest.mark.parametrize(
    "zigbee",
    [
        "00:12:4b:00:1c:a1:b2:c3",
        "zigbee:00:12:4b:00:1c:a1:b2:c3",
        "zigbee_00:12:4b:00:1c:a1:b2:c3",
        "ieee 00-12-4b-00-1c-a1-b2-c3.",
    ],
)
def test_a_zigbee_address_beside_a_word_is_kept_whole(zigbee: str):
    assert _redact_addresses(zigbee) == zigbee


@pytest.mark.parametrize("share_names", [True, False])
async def test_no_address_reaches_the_download_with_every_study_choice_on(
    hass: HomeAssistant, share_names: bool
):
    device, _ = register_device(hass, "plug", name="Plug")
    dr.async_get(hass).async_update_device(
        device.id,
        new_connections={
            (dr.CONNECTION_NETWORK_MAC, ADDRESSES[0]),
            (dr.CONNECTION_BLUETOOTH, ADDRESSES[1]),
        },
        new_identifiers={("test", "plug"), ("test", f"{ADDRESSES[2].upper()}_rssi")},
    )
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: list(STUDIABLE.values())})
    if not share_names:
        share_names_off(hass, entry)
    entry.runtime_data._rebuild_registry_view()

    download = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(download, default=str)

    # The study did list the device, so the test reads what leaked before.
    assert "watched_devices" in text
    for address in ADDRESSES:
        assert not _carries(text, address), address
    # Each keeps its maker's half.
    assert "B4:22:00:MAC-" in text
    assert "EC:71:DB:MAC-" in text
    assert "20:F8:3B:MAC-" in text
