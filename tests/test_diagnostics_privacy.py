# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_privacy.py, Version: 0.27.10 (2026-10-27)

"""Network addresses leave the diagnostics download (rule STOR-21).

The download is often attached to a public GitHub issue, and a house's
download can carry dozens of MAC addresses and the router's address.
Each distinct address becomes a numbered stand-in, the same wherever it
appears, so a device still reads as the same device in every section;
a MAC keeps the half that names its maker. Versions spelled as four
dotted numbers stay whole, because a version is what a fault report
needs most.
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
    """The study snapshot's identifiers carry MACs with no separators, which
    the colon rule misses. A plain run of digits and a registry id are
    left alone.
    """
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


def test_a_zigbee_address_is_kept_whole():
    """A network (MAC) address is hidden, a Zigbee address is kept whole.
    ZHA writes its eight-pair address with colons, so a MAC pattern that
    takes its first six pairs leaves "00:12:4B:MAC-01:b2:c3", neither
    hidden nor readable (rule STOR-21)."""
    out = _redact_addresses(
        {
            "mac": "20:F8:3B:09:97:53",
            "zha": "00:12:4b:00:1c:a1:b2:c3",
            "zha_dashed": "00-12-4b-00-1c-a1-b2-c3",
            "z2m": "0x00124b001ca1b2c3",
            "in_text": "seen as 00:12:4b:00:1c:a1:b2:c3 beside 20:F8:3B:09:97:53",
        }
    )
    assert out["mac"] == "20:F8:3B:MAC-01"
    assert out["zha"] == "00:12:4b:00:1c:a1:b2:c3"
    assert out["zha_dashed"] == "00-12-4b-00-1c-a1-b2-c3"
    assert out["z2m"] == "0x00124b001ca1b2c3"
    assert out["in_text"] == "seen as 00:12:4b:00:1c:a1:b2:c3 beside 20:F8:3B:MAC-01"


async def test_the_download_keeps_zigbee_addresses_and_hides_a_mac(hass: HomeAssistant):
    """The whole download: a network address and both Zigbee forms,
    carried in device names as a person may write them."""
    register_device(hass, "net", name="Plug 20:F8:3B:09:97:53")
    register_device(hass, "zha", name="Sensor 00:12:4b:00:1c:a1:b2:c3")
    register_device(hass, "z2m", name="Sensor 0x00124b001ca1b2c4")
    entry = await setup_entry(hass)
    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry), default=str)
    assert "20:f8:3b:09:97:53" not in text.lower()
    assert "Plug 20:F8:3B:MAC-01" in text
    assert "Sensor 00:12:4b:00:1c:a1:b2:c3" in text
    assert "MAC-02" not in text
    assert "Sensor 0x00124b001ca1b2c4" in text


async def test_held_values_do_not_reach_the_download(hass: HomeAssistant, freezer):
    """The values a device holds while a verdict stands are its own states,
    and the download carries no states: only how many it holds goes
    (rule WATCH-12).
    """
    from homeassistant.util import dt as dt_util

    from custom_components.device_sentinel.const import (
        DEV_FROZEN_CATEGORY,
        DEV_HELD_VALUES,
        DEV_LAST_ACTIVITY,
    )

    from .outage_helpers import PIN, arm, entry_of, past_grace, rec, walk

    secret = "12 Example Street, Springfield"
    freezer.move_to(PIN)
    device, (eid,) = register_device(hass, "lock", "Front Door")
    hass.states.async_set(eid, secret)
    coord = (await setup_entry(hass)).runtime_data
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert rec(coord, device.id)[DEV_HELD_VALUES]
    out = await async_get_config_entry_diagnostics(hass, entry_of(hass))
    assert secret not in json.dumps(out, default=str)
    assert DEV_HELD_VALUES not in out["devices"][device.id]["statistics"]
    assert out["devices"][device.id]["held_value_count"] == 1
    assert out["classification"]["held_values"]["devices_with_held_values"] == 1
