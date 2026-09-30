# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_privacy.py, Version: 0.23.19 (2026-09-30)

"""Network addresses leave the diagnostics download (0.23.19).

Testers attach the download to public GitHub issues. On the reference
rig it carried 23 MAC addresses and the router's address. Each distinct
address becomes a numbered stand-in, the same wherever it appears, so a
device still reads as the same device in every section; a MAC keeps the
half that names its maker. Versions spelled as four dotted numbers stay
whole, because a version is what a fault report needs most.
"""

from __future__ import annotations

import json
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.diagnostics import (
    _redact_addresses,
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_entry

FULL_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")


def test_a_mac_keeps_its_maker_and_one_stand_in_throughout():
    out = _redact_addresses(
        {
            "a": "20:f8:3b:09:97:53",
            "b": ["seen as 20:F8:3B:09:97:53", "20-F8-3B-09-97-53"],
            "c": {"ec:71:db:98:ad:44": "another device"},
        }
    )
    assert out["a"] == "20:F8:3B:MAC-01"
    assert out["b"] == ["seen as 20:F8:3B:MAC-01", "20:F8:3B:MAC-01"]
    assert out["c"] == {"EC:71:DB:MAC-02": "another device"}


def test_home_network_addresses_go_and_versions_stay():
    out = _redact_addresses(
        {
            "router": "http://192.168.68.1",
            "again": "192.168.68.1",
            "vlan": "10.0.30.14",
            "docker": "172.20.1.5",
            "cloud": "https://52.3.9.1/api",
            "versions": ["12.4.0.3", "24.10.24.1 (ESP)", "Appliance=45.0.7.6/Wifi=0.5.15.162"],
            "outside": "172.32.1.1",
        }
    )
    assert out["router"] == "http://IP-01"
    assert out["again"] == "IP-01"
    assert out["vlan"] == "IP-02"
    assert out["docker"] == "IP-03"
    assert out["cloud"] == "https://IP-04/api"
    assert out["versions"] == ["12.4.0.3", "24.10.24.1 (ESP)", "Appliance=45.0.7.6/Wifi=0.5.15.162"]
    assert out["outside"] == "172.32.1.1"


def test_nothing_but_addresses_changes():
    payload = {"n": 3, "f": 1.5, "t": True, "none": None, "text": "Door Master", "list": [1, "x"]}
    assert _redact_addresses(payload) == {**payload, "list": [1, "x"]}


async def test_the_download_carries_no_address(hass: HomeAssistant):
    device, _ = register_device(hass, "net", name="Plug With A MAC 20:F8:3B:09:97:53")
    dr.async_get(hass).async_update_device(
        device.id,
        new_connections={(dr.CONNECTION_NETWORK_MAC, "20:f8:3b:09:97:53")},
        configuration_url="http://192.168.68.40",
    )
    entry = await setup_entry(hass)
    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry), default=str)
    assert not FULL_MAC.search(text)
    assert "192.168.68.40" not in text
    assert "20:F8:3B:MAC-" in text


def test_every_spelling_of_one_mac_is_one_stand_in():
    """Found in the 0.23.19 adversarial round: the study snapshot's
    identifiers carried MACs with no separators, which the colon rule
    missed. A plain run of digits and a registry id are left alone."""
    out = _redact_addresses(
        {
            "colon": "20:F8:3B:09:97:53",
            "bare": "20f83b099753",
            "dotted": "20f8.3b09.9753",
            "digits": "123456789012",
            "device_id": "0da64bc9d25530d0f144e0b0bc8e2d11",
            "entry_id": "01KX781WVRSH9TNTNCD8R6DF09",
            "z2m": "zigbee2mqtt_0x282c02bfffeafa5b",
        }
    )
    assert out["colon"] == out["bare"] == out["dotted"] == "20:F8:3B:MAC-01"
    assert out["digits"] == "123456789012"
    assert out["device_id"] == "0da64bc9d25530d0f144e0b0bc8e2d11"
    assert out["entry_id"] == "01KX781WVRSH9TNTNCD8R6DF09"
    assert out["z2m"] == "zigbee2mqtt_0x282c02bfffeafa5b"
