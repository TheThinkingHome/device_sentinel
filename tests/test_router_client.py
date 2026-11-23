"""A router's entry for a Wi-Fi client is set aside (rule WATCH-03).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_router_client.py, Version: 0.30.3 (2026-11-23)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

TP-Link Omada makes a registry device for each Wi-Fi client it tracks,
holding only that client's tracker, and switches the tracker off until
a person switches it on. Watched, each one was a "never reported" row
about a thermostat or a phone that its own integration already watches.
Set aside, its tracker still ties the real device to the Wi-Fi.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import SET_ASIDE_ROUTER_CLIENT

from .helpers import setup_coordinator

MAC = "aa:bb:cc:dd:ee:01"


def _client(hass, uid, mac=MAC, tracker_off=True, extra=None):
    source = MockConfigEntry(domain="tplink_omada", title="Omada")
    source.add_to_hass(hass)
    connections = {(dr.CONNECTION_NETWORK_MAC, mac)} if mac else set()
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("tplink_omada", uid)},
        connections=connections, name=f"Client {uid}",
    )
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "device_tracker", "tplink_omada", f"{uid}_tracker", device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION if tracker_off else None,
    )
    if extra:
        reg.async_get_or_create(extra, "tplink_omada", f"{uid}_{extra}", device_id=device.id, config_entry=source)
    return device


async def test_a_client_entry_with_its_tracker_off_is_set_aside(hass: HomeAssistant):
    device = _client(hass, "c1")
    coord = await setup_coordinator(hass)
    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_ROUTER_CLIENT
    assert all(item["device_id"] != device.id for item in coord.todo_items), "no never-reported row"


async def test_a_client_entry_with_its_tracker_on_is_set_aside_too(hass: HomeAssistant):
    device = _client(hass, "c2", tracker_off=False)
    coord = await setup_coordinator(hass)
    assert coord._set_aside[device.id][2] == SET_ASIDE_ROUTER_CLIENT


async def test_a_tracker_with_no_network_address_stays_watched(hass: HomeAssistant):
    """A tracker-only device with no network address is not a router's
    client entry: a GPS tag, for one, is judged as before."""
    device = _client(hass, "c3", mac=None, tracker_off=False)
    coord = await setup_coordinator(hass)
    assert device.id in coord._watched


async def test_a_device_with_more_than_a_tracker_stays_watched(hass: HomeAssistant):
    """An access point or a switch has sensors of its own: it is the
    router's hardware, not a client entry."""
    device = _client(hass, "c4", tracker_off=False, extra="sensor")
    coord = await setup_coordinator(hass)
    assert device.id in coord._watched
