# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_clone_identifiers.py, Version: 0.25.6 (2026-10-11)

"""An identifier that is another device's address (0.25.6, ruling #624).

Tim Plas's 0.25.3 files showed no clones on any of his seven proxies.
BlueSight records no connection: it registers each proxy as
("bluesight", "<the proxy's Bluetooth address>"), the address Home
Assistant's Bluetooth integration records as the connection of the
proxy's adapter device. The shapes below are his, from his
classification report and BlueSight's source: D11's adapter is
"d11 Grumpy BT proxy (1C:9D:C2:C3:42:72)" and BlueSight's entities for
it are named d11_1c_9d_c2_c3_42_72_*. His two RTOS nanos carry their
network address in BlueSight's identifier instead.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import SET_ASIDE_COPY
from custom_components.device_sentinel.hardware_copies import find_groups, mac_of

from .helpers import MULTI_OWNER_POSSIBLE, setup_entry

IOT = {"esphome": "local_push", "bluesight": "local_polling", "bluetooth": "local_push",
       "hue": "local_push", "zha": "local_push", "tracker": "local_polling"}
_entries: dict[tuple[int, str], MockConfigEntry] = {}

needs_split = pytest.mark.skipif(MULTI_OWNER_POSSIBLE, reason="one device per box before Home Assistant 2026.8")


@pytest.fixture(autouse=True)
def _iot(monkeypatch):
    from custom_components.device_sentinel.coordinator import DeviceSentinelCoordinator
    monkeypatch.setattr(DeviceSentinelCoordinator, "iot_class_of", lambda self, domain: IOT.get(domain))
    _entries.clear()


def _source(hass, domain):
    key = (id(hass), domain)
    if key not in _entries:
        entry = MockConfigEntry(domain=domain, title=domain)
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        _entries[key] = entry
    return _entries[key]


def _device(hass, domain, identifier, name, entities=(("sensor", "signal_strength"),), connections=(), via=None):
    source = _source(hass, domain)
    extra = {"via_device_id": via} if via is not None else {}
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, identifier)}, name=name,
        connections=set(connections), **extra,
    )
    for index, (edomain, device_class) in enumerate(entities):
        er.async_get(hass).async_get_or_create(edomain, domain, f"{identifier}_{index}", device_id=device.id,
                                               config_entry=source, original_device_class=device_class)
    return dr.async_get(hass).async_get(device.id)


def _tims_proxy(hass, tag, network, bluetooth):
    """A proxy as Tim's registry holds it: ESPHome by network address,
    the Bluetooth adapter under it by Bluetooth address, and BlueSight
    by an identifier holding the Bluetooth address and no connection."""
    esphome = _device(hass, "esphome", f"e{tag}", f"{tag} BT proxy",
                      entities=(("sensor", "signal_strength"), ("button", "restart")),
                      connections={(dr.CONNECTION_NETWORK_MAC, network.lower())})
    adapter = _device(hass, "bluetooth", f"bt{tag}", f"{tag} ({bluetooth.upper()})", entities=(),
                      connections={(dr.CONNECTION_BLUETOOTH, bluetooth.upper())}, via=esphome.id)
    bluesight = _device(hass, "bluesight", bluetooth.lower(), f"{tag} BT proxy (BlueSight)",
                        entities=(("binary_sensor", "connectivity"),))
    return esphome, adapter, bluesight


# ------------------------------------------------------------- the shape


@pytest.mark.parametrize("value, expected", [
    ("1C:9D:C2:C3:42:72", "1c9dc2c34272"),
    ("1c-9d-c2-c3-42-72", "1c9dc2c34272"),
    ("1c9dc2c34272", "1c9dc2c34272"),
    (" 1C:9D:C2:C3:42:72 ", "1c9dc2c34272"),
    ("1c:9d-c2:c3-42:72", None),          # mixed separators
    ("1c:9d:c2:c3:42", None),             # five pairs
    ("00:15:8d:00:01:02:b1:b9", None),    # a Zigbee IEEE, eight pairs
    ("00158d000102b1b9", None),
    ("00:00:00:00:00:00", None),          # unset
    ("ff:ff:ff:ff:ff:ff", None),          # broadcast
    ("service", None),
    ("1C:9D:C2:MAC-147", None),           # an anonymised diagnostics value
    ("zigbee2mqtt_0x00158d0001b1b9", None),
    (None, None),
    (12, None),
])
def test_what_counts_as_an_address(value, expected):
    assert mac_of(value) == expected


def _fake(device_id, domain, connections=(), identifiers=(), via=None):
    return SimpleNamespace(id=device_id, connections=set(connections), identifiers=set(identifiers),
                           via_device_id=via, primary_config_entry=None, config_entries=set(), _domain=domain)


def _groups(devices):
    return sorted(sorted(g) for g in find_groups(devices, lambda d: d._domain))


def test_a_bluesight_identifier_joins_the_adapter_and_its_proxy():
    devices = [
        _fake("e", "esphome", {("mac", "1c:9d:c2:c3:42:70")}),
        _fake("a", "bluetooth", {("bluetooth", "1C:9D:C2:C3:42:72")}, via="e"),
        _fake("b", "bluesight", identifiers={("bluesight", "1c:9d:c2:c3:42:72")}),
    ]
    assert _groups(devices) == [["a", "b", "e"]]


def test_an_identifier_matching_a_network_address_joins():
    devices = [
        _fake("e", "esphome", {("mac", "42:83:6f:08:2f:19")}),
        _fake("b", "bluesight", identifiers={("bluesight", "42:83:6F:08:2F:19")}),
    ]
    assert _groups(devices) == [["b", "e"]]


def test_an_identifier_in_a_later_part_counts():
    devices = [
        _fake("e", "esphome", {("mac", "aa:bb:cc:dd:ee:01")}),
        _fake("h", "hon", identifiers={("hon", "washer", "AA-BB-CC-DD-EE-01")}),
    ]
    assert _groups(devices) == [["e", "h"]]


def test_an_address_one_integration_gives_two_devices_joins_nothing():
    """A hub named by its address and a child holding it as a connection
    are not copies, and the identifier never brings the hub into a group
    with a third integration. (The child and the tracker share a
    connection, which is rule 1's business and unchanged.)"""
    devices = [
        _fake("hub", "hue", identifiers={("hue", "aa:bb:cc:dd:ee:01")}),
        _fake("bulb", "hue", {("mac", "aa:bb:cc:dd:ee:01")}),
    ]
    assert _groups(devices) == []
    devices.append(_fake("t", "tracker", {("mac", "aa:bb:cc:dd:ee:01")}))
    assert all("hub" not in group for group in _groups(devices))


def test_two_identifiers_of_one_integration_join_nothing():
    devices = [
        _fake("b1", "bluesight", identifiers={("bluesight", "aa:bb:cc:dd:ee:01")}),
        _fake("b2", "bluesight", identifiers={("bluesight", "aa:bb:cc:dd:ee:01")}),
    ]
    assert _groups(devices) == []


def test_an_identifier_matching_nothing_joins_nothing():
    devices = [
        _fake("e", "esphome", {("mac", "aa:bb:cc:dd:ee:01")}),
        _fake("b", "bluesight", identifiers={("bluesight", "aa:bb:cc:dd:ee:02")}),
        _fake("s", "bluesight", identifiers={("bluesight", "service")}),
    ]
    assert _groups(devices) == []


def test_two_identifiers_alike_in_different_integrations_join():
    """Two integrations naming the box by the same address are rule 1's
    evidence with no connection at all."""
    devices = [
        _fake("b", "bluesight", identifiers={("bluesight", "aa:bb:cc:dd:ee:01")}),
        _fake("o", "other", identifiers={("other", "AABBCCDDEE01")}),
    ]
    assert _groups(devices) == [["b", "o"]]


def test_connections_of_different_kinds_alike_are_left_to_rule_one():
    """With no identifier holding the address, a network address and a
    Bluetooth address that read alike join nothing, as before 0.25.6."""
    devices = [
        _fake("w", "wifi_thing", {("mac", "aa:bb:cc:dd:ee:01")}),
        _fake("b", "ble_thing", {("bluetooth", "AA:BB:CC:DD:EE:01")}),
    ]
    assert _groups(devices) == []


def test_an_unreadable_identifier_never_stops_the_grouping():
    class Odd:
        def __iter__(self):
            raise TypeError("not a set")

    devices = [
        _fake("e", "esphome", {("mac", "aa:bb:cc:dd:ee:01")}),
        SimpleNamespace(id="x", connections=set(), identifiers=Odd(), via_device_id=None,
                        primary_config_entry=None, config_entries=set(), _domain="odd"),
        _fake("b", "bluesight", identifiers={("bluesight", "aa:bb:cc:dd:ee:01")}),
    ]
    assert _groups(devices) == [["b", "e"]]


# -------------------------------------------------------- Tim's registry


@needs_split
async def test_tims_proxies_show_their_bluesight_clones(hass: HomeAssistant):
    d11 = _tims_proxy(hass, "D11", "1c:9d:c2:c3:42:70", "1C:9D:C2:C3:42:72")
    d12 = _tims_proxy(hass, "D12", "1c:9d:c2:c2:37:c8", "1C:9D:C2:C2:37:CA")
    coord = (await setup_entry(hass)).runtime_data
    for esphome, adapter, bluesight in (d11, d12):
        assert esphome.id in coord._watched
        assert bluesight.id not in coord._watched
        assert coord._set_aside[bluesight.id][2] == SET_ASIDE_COPY
        assert coord._copy_of[bluesight.id] == esphome.id
        same = coord.same_hardware(esphome.id)
        assert {row["device_id"] for row in same["devices"]} == {esphome.id, adapter.id, bluesight.id}
    assert len(coord._hardware_groups) == 2


@needs_split
async def test_tims_rtos_nano_shows_its_bluesight_clone(hass: HomeAssistant):
    esphome = _device(hass, "esphome", "d72", "d72-smhub-house", entities=(("sensor", "signal_strength"),),
                      connections={(dr.CONNECTION_NETWORK_MAC, "42:83:6f:08:2f:19")})
    bluesight = _device(hass, "bluesight", "42:83:6F:08:2F:19", "d72-rtos-nano-082f19 (42:83:6F:08:2F:19)",
                        entities=(("binary_sensor", "connectivity"),))
    coord = (await setup_entry(hass)).runtime_data
    assert coord._copy_of == {bluesight.id: esphome.id}


@needs_split
async def test_the_esphome_copy_is_kept_over_a_busier_bluesight(hass: HomeAssistant):
    """Real BlueSight gives each proxy five entities and pushes locally,
    and a plain ESPHome proxy may have fewer. The copy that records the
    box's address is kept (found by review)."""
    esphome = _device(hass, "esphome", "e", "D12 BT proxy", entities=(("sensor", "signal_strength"),),
                      connections={(dr.CONNECTION_NETWORK_MAC, "1c:9d:c2:c2:37:c8")})
    _device(hass, "bluetooth", "bt", "d12 (1C:9D:C2:C2:37:CA)", entities=(),
            connections={(dr.CONNECTION_BLUETOOTH, "1C:9D:C2:C2:37:CA")}, via=esphome.id)
    bluesight = _device(hass, "bluesight", "1c:9d:c2:c2:37:ca", "D12 Basement BT proxy",
                        entities=(("binary_sensor", "connectivity"), ("sensor", None), ("sensor", None),
                                  ("sensor", None), ("sensor", None)))
    IOT["bluesight"] = "local_push"
    try:
        coord = (await setup_entry(hass)).runtime_data
    finally:
        IOT["bluesight"] = "local_polling"
    assert coord._copy_of == {bluesight.id: esphome.id}


@needs_split
async def test_the_bluesight_service_device_stays_watched(hass: HomeAssistant):
    _tims_proxy(hass, "D11", "1c:9d:c2:c3:42:70", "1C:9D:C2:C3:42:72")
    service = _device(hass, "bluesight", "service", "BlueSight service", entities=(("sensor", None),))
    coord = (await setup_entry(hass)).runtime_data
    assert service.id in coord._watched
    assert service.id not in coord._copy_of
