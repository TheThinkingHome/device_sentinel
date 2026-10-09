# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_hardware_copies.py, Version: 0.25.3 (2026-10-09)

"""One piece of hardware shown as several devices (0.25.2).

Since Home Assistant 2026.8 one box is one registry device per
integration that knows it. Tim Plas's Bluetooth proxies are four each:
ESPHome, Bluetooth, BlueSight and UniFi. Device Sentinel judges the box
once, through the copy that reaches it most directly, and sets the
others aside as copies with their records kept.

Copies are found only on what Home Assistant recorded: the same address
on devices of different integrations, or a Bluetooth adapter registered
under a proxy's device. Never on a name.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_DEVICES,
    SET_ASIDE_COPY,
)
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
from custom_components.device_sentinel.hardware_copies import choose_copies, find_groups, rank_of

from .helpers import MULTI_OWNER_POSSIBLE, setup_entry

MAC = "aa:bb:cc:dd:ee:01"
IOT = {"esphome": "local_push", "bluesight": "local_polling", "unifi": "local_polling", "bluetooth": "local_push",
       "hue": "local_push", "tuyacloud": "cloud_polling", "nmap_tracker": "local_polling"}
_entries: dict[tuple[int, str], MockConfigEntry] = {}

# Before Home Assistant 2026.8 a second integration naming an address
# already held joins that device, so one box is one device and there are
# no copies to find; the registry cases run on 2026.8 and later.
needs_split = pytest.mark.skipif(MULTI_OWNER_POSSIBLE, reason="one device per box before Home Assistant 2026.8")


def _source(hass, domain):
    key = (id(hass), domain)
    if key not in _entries:
        entry = MockConfigEntry(domain=domain, title=domain)
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        _entries[key] = entry
    return _entries[key]


def _device(hass, domain, uid, name, entities=(("sensor", "signal_strength"),), connections=(), via=None):
    source = _source(hass, domain)
    # via is the parent's device id; the via_device identifier form is
    # deprecated since 2026.9.
    extra = {"via_device_id": via} if via is not None else {}
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=name,
        connections=set(connections), **extra,
    )
    for index, (edomain, device_class) in enumerate(entities):
        er.async_get(hass).async_get_or_create(edomain, domain, f"{uid}_{index}", device_id=device.id,
                                               config_entry=source, original_device_class=device_class)
    return dr.async_get(hass).async_get(device.id)


@pytest.fixture(autouse=True)
def _iot(monkeypatch):
    from custom_components.device_sentinel.coordinator import DeviceSentinelCoordinator
    monkeypatch.setattr(DeviceSentinelCoordinator, "iot_class_of", lambda self, domain: IOT.get(domain))
    _entries.clear()


def _proxy(hass, mac=MAC, tag="1"):
    """One of Tim's proxies: ESPHome, BlueSight and UniFi know it by its
    network address; Bluetooth registers its adapter under the ESPHome
    device."""
    esphome = _device(hass, "esphome", f"e{tag}", f"Proxy {tag}", entities=(("sensor", "signal_strength"),
                      ("button", "restart")), connections={(dr.CONNECTION_NETWORK_MAC, mac)})
    bluesight = _device(hass, "bluesight", f"b{tag}", f"Proxy {tag} (BlueSight)",
                        entities=(("sensor", None),), connections={(dr.CONNECTION_NETWORK_MAC, mac.upper())})
    unifi = _device(hass, "unifi", f"u{tag}", f"proxy-{tag}", entities=(("device_tracker", None),),
                    connections={(dr.CONNECTION_NETWORK_MAC, mac)})
    # On Tim's house the adapter device has no entities of its own.
    bluetooth = _device(hass, "bluetooth", f"bt{tag}", f"Proxy {tag} ({mac})", entities=(),
                        connections={(dr.CONNECTION_BLUETOOTH, mac[:-2] + f"b{tag}")}, via=esphome.id)
    return esphome, bluesight, unifi, bluetooth


@needs_split
async def test_a_proxy_is_watched_once_through_its_esphome_device(hass: HomeAssistant):
    esphome, bluesight, unifi, bluetooth = _proxy(hass)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert esphome.id in coord._watched
    assert bluesight.id not in coord._watched
    assert coord._set_aside[bluesight.id][2] == SET_ASIDE_COPY
    assert coord._copy_of[bluesight.id] == esphome.id
    # The adapter has no entities, so that is its reason; it still shows
    # in the group.
    assert coord._set_aside[bluetooth.id][2] == "no entities"
    # UniFi is excluded by default, and an exclusion keeps its own reason.
    assert coord._set_aside[unifi.id][2] == "excluded"
    assert unifi.id not in coord._copy_of
    same = coord.same_hardware(bluesight.id)
    assert same["watched_through"] == esphome.id
    assert [row["device_id"] for row in same["devices"]][0] == esphome.id
    assert {row["domain"] for row in same["devices"]} == {"esphome", "bluesight", "unifi", "bluetooth"}
    # The name shown elsewhere, not the domain (0.25.3, James's house).
    names = {row["domain"]: row["integration"] for row in same["devices"]}
    assert names["unifi"] == "UniFi Network"


@needs_split
async def test_two_proxies_stay_two_boxes(hass: HomeAssistant):
    first = _proxy(hass, "aa:bb:cc:dd:ee:01", "1")
    second = _proxy(hass, "aa:bb:cc:dd:ee:02", "2")
    coord = (await setup_entry(hass)).runtime_data
    assert first[0].id in coord._watched and second[0].id in coord._watched
    assert coord._copy_of[first[1].id] == first[0].id
    assert coord._copy_of[second[1].id] == second[0].id
    assert len(coord._hardware_groups) == 2


@needs_split
async def test_devices_of_one_integration_sharing_an_address_are_not_copies(hass: HomeAssistant):
    """A hub and its children may share the hub's address; they are not one box."""
    hub = _device(hass, "hue", "hub", "Hue Bridge", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    bulb = _device(hass, "hue", "bulb", "Hue Bulb", entities=(("light", None),),
                   connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    coord = (await setup_entry(hass)).runtime_data
    assert hub.id in coord._watched and bulb.id in coord._watched
    assert coord._copy_of == {}


@needs_split
async def test_a_name_alone_never_makes_a_copy(hass: HomeAssistant):
    one = _device(hass, "esphome", "x1", "Garage proxy")
    two = _device(hass, "bluesight", "x2", "Garage proxy")
    coord = (await setup_entry(hass)).runtime_data
    assert one.id in coord._watched and two.id in coord._watched


@needs_split
async def test_a_group_with_one_watched_device_changes_nothing(hass: HomeAssistant):
    esphome, bluesight, unifi, bluetooth = _proxy(hass)
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: ["bluesight", "unifi", "bluetooth"]})
    coord = entry.runtime_data
    assert esphome.id in coord._watched
    assert coord._copy_of == {}
    assert coord._set_aside[bluesight.id][2] == "excluded", "an exclusion keeps its own reason"
    assert coord.same_hardware(esphome.id)["watched_through"] == esphome.id


@needs_split
async def test_excluding_the_best_copy_watches_the_next(hass: HomeAssistant):
    esphome, bluesight, unifi, bluetooth = _proxy(hass)
    coord = (await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: ["esphome"]})).runtime_data
    assert bluesight.id in coord._watched
    assert esphome.id not in coord._watched
    assert unifi.id not in coord._watched
    assert coord._copy_of.get(unifi.id) in (None, bluesight.id), "a tracker was kept over the box"


@needs_split
async def test_a_bluetooth_adapter_with_entities_is_a_copy_of_its_proxy(hass: HomeAssistant):
    esphome = _device(hass, "esphome", "e", "Proxy", entities=(("sensor", "signal_strength"), ("button", "restart")),
                      connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    adapter = _device(hass, "bluetooth", "bt", "Proxy adapter", entities=(("sensor", None),),
                      connections={(dr.CONNECTION_BLUETOOTH, "aa:bb:cc:dd:ee:f1")}, via=esphome.id)
    coord = (await setup_entry(hass)).runtime_data
    assert coord._copy_of == {adapter.id: esphome.id}


@needs_split
async def test_a_network_tracker_is_never_the_copy_watched(hass: HomeAssistant):
    """A device whose only entity says it is on the network describes the
    network, not the box, even when its integration polls locally and the
    box's own integration goes through the cloud."""
    box = _device(hass, "tuyacloud", "t1", "Kettle", entities=(("switch", None),),
                  connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    tracker = _device(hass, "nmap_tracker", "n1", "kettle-wifi", entities=(("device_tracker", None),),
                      connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    coord = (await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})).runtime_data
    assert box.id in coord._watched
    assert coord._copy_of == {tracker.id: box.id}


@needs_split
async def test_the_choice_holds_across_restarts(hass: HomeAssistant):
    left = _device(hass, "esphome", "l", "Left", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    right = _device(hass, "bluesight", "r", "Right", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    entry = await setup_entry(hass)
    first = dict(entry.runtime_data._copy_of)
    for _ in range(3):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data._copy_of == first
    assert len(first) == 1 and set(first) | set(first.values()) == {left.id, right.id}


@needs_split
async def test_a_device_with_no_entities_is_never_the_copy_kept(hass: HomeAssistant):
    """While ESPHome is still loading after a restart its device has no
    entities yet; the box is not set aside in favor of BlueSight."""
    esphome = _device(hass, "esphome", "e", "Proxy", entities=(), connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    bluesight = _device(hass, "bluesight", "b", "Proxy (BlueSight)", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    coord = (await setup_entry(hass)).runtime_data
    assert coord._copy_of == {}
    assert bluesight.id in coord._watched
    assert coord._set_aside.get(esphome.id, (None, None, None))[2] != SET_ASIDE_COPY


@needs_split
async def test_a_copy_loses_its_verdict_keeps_its_record_and_returns_when_the_group_parts(hass: HomeAssistant):
    esphome = _device(hass, "esphome", "e", "Proxy", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    bluesight = _device(hass, "bluesight", "b", "Proxy (BlueSight)",
                        connections={(dr.CONNECTION_NETWORK_MAC, "11:22:33:44:55:66")})
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert bluesight.id in coord._watched, "different addresses: two boxes"
    record = coord.data[DATA_DEVICES][bluesight.id]
    record["frozen_category"] = "frozen"
    record["frozen_since"] = "2026-10-09T10:00:00+00:00"
    dr.async_get(hass).async_update_device(bluesight.id, new_connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert coord._copy_of == {bluesight.id: esphome.id}
    assert bluesight.id in coord.data[DATA_DEVICES], "the copy's record was dropped"
    assert coord.data[DATA_DEVICES][bluesight.id].get("frozen_category") is None, "a copy kept its verdict"
    dr.async_get(hass).async_update_device(bluesight.id, new_connections={(dr.CONNECTION_NETWORK_MAC, "11:22:33:44:55:77")})
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert bluesight.id in coord._watched and coord._copy_of == {}


@needs_split
async def test_the_diagnostics_show_groups_copies_and_fingerprints_not_addresses(hass: HomeAssistant):
    esphome, bluesight, unifi, bluetooth = _proxy(hass)
    coord = (await setup_entry(hass)).runtime_data
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    same = diagnostics["same_hardware"]
    assert sorted(same["groups"][0]) == sorted([esphome.id, bluesight.id, unifi.id, bluetooth.id])
    assert same["copies"] == {bluesight.id: esphome.id}
    text = str(diagnostics)
    assert MAC not in text and MAC.upper() not in text, "an address left the house"
    row = diagnostics["devices"][esphome.id]
    assert row["addresses"] and row["addresses"][0].startswith("mac:")
    if bluesight.id in diagnostics["devices"]:
        assert diagnostics["devices"][bluesight.id]["addresses"] == row["addresses"], "copies do not match"


# ------------------------------------------------------------- the pure rules


class _D:
    def __init__(self, device_id, domain, connections=(), via=None):
        self.id = device_id
        self.domain = domain
        self.connections = set(connections)
        self.via_device_id = via


def test_groups_follow_addresses_and_adapters_only():
    devices = [
        _D("a", "esphome", {("mac", "AA")}), _D("b", "unifi", {("mac", "aa")}),
        _D("c", "bluetooth", {("bluetooth", "bb")}, via="a"),
        _D("d", "esphome", {("mac", "cc")}), _D("e", "esphome", {("mac", "cc")}),
        _D("f", "bluetooth", set(), via="zz"),
    ]
    groups = find_groups(devices, lambda d: d.domain)
    assert groups == [{"a", "b", "c"}]


def test_choose_keeps_the_best_ranked_and_sets_the_rest_aside():
    ranks = {"a": (1, 1, 0, 4, 2), "b": (1, 0, 0, 3, 1), "c": (1, 1, 0, 4, 2)}
    copies = choose_copies([{"a", "b", "c"}], {"a": "x", "b": "y", "c": "z"}, lambda d: ranks[d])
    assert copies == {"b": "a", "c": "a"}, "a tie keeps the lower id"
    assert choose_copies([{"a", "b"}], {"a": "x"}, lambda d: ranks[d]) == {}


def test_rank_puts_entities_then_trackers_then_reach():
    assert rank_of("local_push", {"sensor"}, 1) > rank_of("local_polling", {"sensor"}, 5)
    assert rank_of("cloud_polling", {"switch"}, 1) > rank_of("local_push", {"device_tracker"}, 3)
    assert rank_of(None, {"sensor"}, 1) > rank_of("local_push", set(), 0)


def test_a_chain_of_addresses_never_groups_two_devices_of_one_integration():
    """Found by review: a tracker holding a hub's address, and the hub's
    child holding it too, put the hub and its child in one group."""
    shared = [_D("a", "unifi", {("mac", "aa")}), _D("b", "hue", {("mac", "aa")}), _D("c", "hue", {("mac", "aa")})]
    assert find_groups(shared, lambda d: d.domain) == []
    chained = [_D("a", "unifi", {("mac", "aa"), ("mac", "bb")}), _D("b", "hue", {("mac", "aa")}),
               _D("c", "hue", {("mac", "bb")})]
    groups = find_groups(chained, lambda d: d.domain)
    assert len(groups) == 1 and not {"b", "c"} <= groups[0]
    assert groups == find_groups(list(reversed(chained)), lambda d: d.domain), "the answer moved with the order"


@needs_split
async def test_a_copy_never_watched_has_no_link_to_a_page_it_does_not_have(hass: HomeAssistant):
    esphome, bluesight, unifi, bluetooth = _proxy(hass)
    coord = (await setup_entry(hass)).runtime_data
    rows = {row["device_id"]: row for row in coord.same_hardware(esphome.id)["devices"]}
    assert rows[esphome.id]["has_page"] is True
    assert rows[bluesight.id]["has_page"] is (bluesight.id in coord.data[DATA_DEVICES])
    assert rows[unifi.id]["has_page"] is False


@needs_split
async def test_the_fingerprints_match_inside_a_download_and_nowhere_else(hass: HomeAssistant):
    import hashlib

    esphome, bluesight, _unifi, _bluetooth = _proxy(hass)
    coord = (await setup_entry(hass)).runtime_data
    first = (await async_get_config_entry_diagnostics(hass, coord.entry))["devices"][esphome.id]["addresses"]
    second = (await async_get_config_entry_diagnostics(hass, coord.entry))["devices"][esphome.id]["addresses"]
    assert first != second, "the same fingerprint in two downloads can be looked up"
    plain = "mac:" + hashlib.sha256(MAC.encode()).hexdigest()[:10]
    assert plain not in first


@needs_split
async def test_a_disabled_entity_never_ranks_a_tracker_over_the_box(hass: HomeAssistant, monkeypatch):
    """Found by review: UniFi registers a client speed sensor, disabled,
    and counting it kept the UniFi tracker and set the ESPHome box aside."""
    esphome = _device(hass, "esphome", "e", "Proxy", entities=(("sensor", "signal_strength"), ("button", "restart"),
                                                             ("sensor", None)),
                      connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    monkeypatch.setitem(IOT, "nmap_tracker", "local_push")  # UniFi's reach, equal to ESPHome's
    # UniFi itself is excluded as a router on first sight; a tracker
    # integration that is not a router shows the same ranking.
    unifi = _device(hass, "nmap_tracker", "u", "proxy-wifi", entities=(("device_tracker", None), ("sensor", None),
                                                               ("sensor", None), ("sensor", None), ("sensor", None)),
                    connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    registry = er.async_get(hass)
    for index in range(1, 5):
        entity_id = registry.async_get_entity_id("sensor", "nmap_tracker", f"u_{index}")
        registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    coord = (await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})).runtime_data
    assert coord._copy_of == {unifi.id: esphome.id}
    assert rank_of("local_push", {"device_tracker", "sensor"}, 9) < rank_of("cloud_polling", {"sensor"}, 1)


@needs_split
async def test_every_watched_member_reads_watched(hass: HomeAssistant):
    """Found by review: in restart grace two members can be watched, and
    the row said the second was not."""
    esphome = _device(hass, "esphome", "e", "Proxy", entities=(), connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    bluesight = _device(hass, "bluesight", "b", "Proxy (BlueSight)", connections={(dr.CONNECTION_NETWORK_MAC, MAC)})
    coord = (await setup_entry(hass)).runtime_data
    rows = {row["device_id"]: row for row in coord.same_hardware(bluesight.id)["devices"]}
    for device_id, row in rows.items():
        assert row["watched"] == (device_id in coord._watched)
    assert esphome.id in rows


def test_the_copy_with_the_battery_reading_is_kept():
    """Found by review: a copy set aside takes its readings with it, so
    the one carrying the battery is the one to watch."""
    assert rank_of("local_polling", {"sensor"}, 1, battery=True) > rank_of("local_push", {"sensor"}, 6)
    assert rank_of("local_push", {"device_tracker"}, 3, battery=True) < rank_of("cloud_polling", {"sensor"}, 1)


@needs_split
async def test_a_battery_on_one_copy_decides_which_is_watched(hass: HomeAssistant):
    plain = _device(hass, "esphome", "e", "Tag", entities=(("sensor", "signal_strength"), ("sensor", "temperature"),
                                                         ("button", "restart")),
                    connections={(dr.CONNECTION_BLUETOOTH, "aa:bb:cc:dd:ee:77")})
    battery = _device(hass, "bluesight", "b", "Tag (BlueSight)", entities=(("sensor", "battery"),),
                      connections={(dr.CONNECTION_BLUETOOTH, "aa:bb:cc:dd:ee:77")})
    coord = (await setup_entry(hass)).runtime_data
    assert coord._copy_of == {plain.id: battery.id}
