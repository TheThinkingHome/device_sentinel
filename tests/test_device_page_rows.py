"""Tests for the device page's rows: no data, no row (0.25.5).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_device_page_rows.py, Version: 0.25.5 (2026-10-10)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

A row with nothing to show is left out (James, 10 October 2026). The
server sends None for a registry field that is empty or only zeros,
Connects only for a device that does not report on the local network
as changes happen, and each address under the name of its kind.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONNECTS_WORDS, DATA_DEVICES
from custom_components.device_sentinel.device_addresses import addresses, shown

from .helpers import registry_settled, setup_coordinator


# ------------------------------------------------------------ shown


@pytest.mark.parametrize("value", [None, "", "  ", "0", "0.0", "0.0.0", "00", " 0 "])
def test_nothing_or_only_zeros_is_nothing(value):
    assert shown(value) is None


@pytest.mark.parametrize("value,expected", [
    ("2", "2"), ("1.0", "1.0"), ("0x0", "0x0"), ("v0", "v0"), (" Aqara ", "Aqara"), (3, "3"), (0, None),
])
def test_anything_else_is_shown(value, expected):
    assert shown(value) == expected


# ------------------------------------------------------------ addresses


def _device(connections=(), identifiers=()):
    return SimpleNamespace(connections=set(connections), identifiers=set(identifiers))


def test_each_connection_kind_has_its_own_row():
    rows = addresses(_device(connections={
        ("mac", "aa:bb:cc:dd:ee:ff"), ("zigbee", "00:15:8d:00:01"),
        ("bluetooth", "11:22:33:44:55:66"), ("upnp", "uuid:abc"),
    }))
    assert rows == [
        {"label": "MAC Address", "value": "aa:bb:cc:dd:ee:ff"},
        {"label": "Zigbee Address", "value": "00:15:8d:00:01"},
        {"label": "Bluetooth Address", "value": "11:22:33:44:55:66"},
        {"label": "UPnP ID", "value": "uuid:abc"},
    ]


def test_zigbee2mqtt_gives_its_address_in_its_identifier():
    rows = addresses(_device(identifiers={("mqtt", "zigbee2mqtt_0x00158d0001a2b3c4")}))
    assert rows == [{"label": "Zigbee Address", "value": "0x00158d0001a2b3c4"}]


def test_a_zwave_device_shows_its_node():
    rows = addresses(_device(identifiers={("zwave_js", "3967510042-14"), ("zwave_js", "3967510042-14-271:4099:12801")}))
    assert rows == [{"label": "Z-Wave Node", "value": "14"}]


def test_a_matter_device_shows_its_serial_number():
    rows = addresses(_device(identifiers={("matter", "serial_SN12345"), ("matter", "deviceid_ABC-0000000000000004-MatterNodeDevice")}))
    assert rows == [{"label": "Serial Number", "value": "SN12345"}]


def test_one_row_per_kind_and_no_repeats():
    rows = addresses(_device(connections={("mac", "aa:bb"), ("mac", "AA:BB"), ("mac", "cc:dd")}))
    assert rows == [{"label": "MAC Address", "value": "AA:BB, cc:dd"}]


def test_nothing_known_is_no_rows():
    assert addresses(_device()) == []
    assert addresses(None) == []
    assert addresses(_device(connections={("ieee", "x"), ("mac", ""), ("mac", 5)})) == []


def test_odd_registry_values_do_not_raise():
    assert addresses(SimpleNamespace(connections=5, identifiers=7)) == []
    assert addresses(SimpleNamespace(connections={("mac",)}, identifiers={("matter",), ("zwave_js", 4)})) == []


# ------------------------------------------------------------ the page


def _registered(hass, domain, uid, **fields):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"{domain} {uid}", **fields
    )
    er.async_get(hass).async_get_or_create("sensor", domain, uid, device_id=device.id, config_entry=source)
    return device


async def test_zeros_and_blanks_reach_the_page_as_nothing(hass: HomeAssistant):
    device = _registered(hass, "test", "z1", manufacturer="  ", model="0", model_id="", hw_version="0.0")
    coord = await setup_coordinator(hass)
    identity = coord.dashboard_device(device.id)["identity"]
    assert (identity["manufacturer"], identity["model"], identity["model_id"], identity["hw_version"]) == (None,) * 4
    assert identity["addresses"] == []


async def test_connects_only_where_it_says_something(hass: HomeAssistant):
    for domain in ("tuya", "zha", "mqtt"):
        await async_get_integration(hass, domain)
    pushed = _registered(hass, "mqtt", "c1")
    polled = _registered(hass, "zha", "c2")
    cloud = _registered(hass, "tuya", "c3")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    assert coord.dashboard_device(pushed.id)["identity"]["connects"] is None
    assert coord.dashboard_device(polled.id)["identity"]["connects"] == CONNECTS_WORDS["local_polling"]
    assert coord.dashboard_device(cloud.id)["identity"]["connects"] == CONNECTS_WORDS["cloud_push"]


def test_the_assumed_state_sentence():
    assert CONNECTS_WORDS["assumed_state"] == "It can't report back, so Home Assistant shows what it last told it."


async def test_a_zigbee2mqtt_device_shows_its_address_on_the_page(hass: HomeAssistant):
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x00158d0001a2b3c4")}, name="Door"
    )
    er.async_get(hass).async_get_or_create("sensor", "mqtt", "door", device_id=device.id, config_entry=source)
    coord = await setup_coordinator(hass)
    identity = coord.dashboard_device(device.id)["identity"]
    assert identity["addresses"] == [{"label": "Zigbee Address", "value": "0x00158d0001a2b3c4"}]


async def test_a_held_device_has_no_page(hass: HomeAssistant):
    """Removed from Home Assistant, its record held (ruling #622): a
    page would offer actions on a device that is not there."""
    device = _registered(hass, "test", "h1")
    coord = await setup_coordinator(hass)
    dr.async_get(hass).async_remove_device(device.id)
    await registry_settled(hass)
    assert device.id in coord.data[DATA_DEVICES]
    assert coord.dashboard_device(device.id) is None
