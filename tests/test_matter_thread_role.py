# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_matter_thread_role.py, Version: 0.30.7 (2026-11-26)

"""Each Matter device's Thread role, read from the Matter server's map (rule STACK-18).

The map is asked for at most every ten minutes and never refreshed, since
a refresh reads every device over the radio. A server too old for the
map, a missing client or a map that cannot be read leaves the page and
the Networks tab without the Thread rows, and never stops the minute.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import matter_mesh
from custom_components.device_sentinel.matter_mesh import MATTER_MAP_PATH, MESH_SECONDS, node_of, plain

from tests.helpers import setup_coordinator

FABRIC = "00000000000000AB"


def _ident(node: int) -> tuple[str, str]:
    return ("matter", f"deviceid_{FABRIC}-{node:016X}-MatterNodeDevice")


MAP = {
    "collected_at": 1,
    "nodes": [
        {"id": "br1", "kind": "border_router", "network_type": "thread", "host_name": "SMHUB Nano", "network_name": "home-thread"},
        {"id": "n5", "kind": "matter", "network_type": "thread", "node_id": 5, "role": "router", "network_name": "home-thread"},
        {"id": "n6", "kind": "matter", "network_type": "thread", "node_id": 6, "role": "sleepy_end_device", "network_name": "home-thread"},
        {"id": "n7", "kind": "matter", "network_type": "thread", "node_id": 7, "role": "end_device", "network_name": "home-thread"},
        {"id": "n8", "kind": "matter", "network_type": "wifi", "node_id": 8},
    ],
    "connections": [
        {"source": "br1", "target": "n5", "network": "thread", "strength": "strong"},
        {"source": "n5", "target": "n6", "network": "thread", "strength": "medium"},
        {"source": "n5", "target": "n7", "network": "thread", "strength": "weak"},
        {"source": "br1", "target": "n7", "network": "thread", "strength": "medium"},
        # A link with no strength is no link.
        {"source": "br1", "target": "n6", "network": "thread", "strength": "none"},
    ],
}


class _Client:
    def __init__(self, graph=MAP, schema=13):
        self.server_info = SimpleNamespace(schema_version=schema)
        self.graph = graph
        self.asked: list[bool] = []

    async def get_network_topology(self, refresh: bool = False):
        self.asked.append(refresh)
        if isinstance(self.graph, Exception):
            raise self.graph
        return self.graph


def _house(hass: HomeAssistant, client) -> dict[int, str]:
    entry = MockConfigEntry(domain="matter", title="Matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=client))
    registry = dr.async_get(hass)
    found = {}
    for node, name in ((5, "Kitchen Plug"), (6, "Door Sensor"), (7, "Lamp"), (8, "Wi-Fi Plug")):
        found[node] = registry.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={_ident(node)}, name=name,
        ).id
    # The plug has an entity, so Device Sentinel watches it and draws its page.
    plug = er.async_get(hass).async_get_or_create(
        "switch", "matter", "plug5", device_id=found[5], config_entry=entry,
    ).entity_id
    hass.states.async_set(plug, "off")
    return found


async def _read(hass, coord, now=1000.0):
    coord.mesh_tick(now)
    await hass.async_block_till_done()


def test_node_numbers_from_the_identifier():
    assert node_of({_ident(5)}) == 5
    assert node_of({("matter", f"deviceid_{FABRIC}-{26:016X}-3")}) is None, "a device behind a bridge is no node"
    assert node_of({("zha", "x"), ("matter", "deviceid_bad-zz-MatterNodeDevice")}) is None
    assert node_of(None) is None and node_of([("matter",)]) is None


def test_a_dataclass_map_reads_as_plain_data():
    @dataclasses.dataclass
    class Topology:
        collected_at: int
        nodes: list
        connections: list

    assert plain(Topology(1, [], []))["collected_at"] == 1
    assert plain("text") is None


async def test_role_carries_and_link_on_the_page(hass: HomeAssistant):
    client = _Client()
    devices = _house(hass, client)
    coord = await setup_coordinator(hass)
    await _read(hass, coord)
    assert client.asked == [False], "never refreshed by radio"
    plug = coord.device_thread(devices[5])
    assert plug["role_words"] == "Router" and plug["carries"] == 2
    assert plug["link"] == {"strength": "strong", "to": "SMHUB Nano"} and plug["map_path"] == MATTER_MAP_PATH
    door = coord.device_thread(devices[6])
    assert door["role_words"] == "Sleepy end device" and door["carries"] is None
    assert door["link"]["to"] == "Kitchen Plug", "named as the house names it"
    # The end device's best link wins.
    assert coord.device_thread(devices[7])["link"]["strength"] == "medium"
    # Wi-Fi is not Thread.
    assert coord.device_thread(devices[8]) is None
    assert coord.dashboard_device(devices[5])["identity"]["thread"]["carries"] == 2


async def test_the_networks_tab_card(hass: HomeAssistant):
    devices = _house(hass, _Client())
    coord = await setup_coordinator(hass)
    await _read(hass, coord)
    view = coord.thread_view()
    assert view["networks"] == ["home-thread"]
    assert (view["border_routers"], view["routers"], view["end_devices"], view["sleepy"]) == (1, 1, 1, 1)
    assert [row["role"] for row in view["rows"]] == ["Border router", "Router"], "border routers first"
    plug = view["rows"][1]
    assert plug["device_id"] == devices[5] and plug["carries"] == 2 and plug["link"] == "strong"


async def test_asked_once_in_ten_minutes(hass: HomeAssistant):
    client = _Client()
    _house(hass, client)
    coord = await setup_coordinator(hass)
    await _read(hass, coord, 1000.0)
    await _read(hass, coord, 1000.0 + MESH_SECONDS - 1)
    assert client.asked == [False]
    await _read(hass, coord, 1000.0 + MESH_SECONDS)
    assert client.asked == [False, False]


async def test_an_old_server_or_no_client_shows_nothing(hass: HomeAssistant):
    client = _Client(schema=12)
    devices = _house(hass, client)
    coord = await setup_coordinator(hass)
    await _read(hass, coord)
    assert client.asked == [] and coord.thread_view() is None and coord.device_thread(devices[5]) is None
    client.server_info = None
    await _read(hass, coord, 1000.0 + MESH_SECONDS)
    assert client.asked == []


async def test_a_server_that_never_answers_is_asked_again_later(hass: HomeAssistant, monkeypatch):
    import asyncio

    class Stuck(_Client):
        async def get_network_topology(self, refresh: bool = False):
            self.asked.append(refresh)
            await asyncio.sleep(60)

    client = Stuck()
    _house(hass, client)
    coord = await setup_coordinator(hass)
    monkeypatch.setattr(matter_mesh, "MESH_WAIT_SECONDS", 0.05)
    await _read(hass, coord, 1000.0)
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert coord._mesh_state()["busy"] is False
    await _read(hass, coord, 1000.0 + MESH_SECONDS)
    await asyncio.sleep(0.2)
    assert client.asked == [False, False]


async def test_a_map_that_fails_or_is_odd_never_stops_the_minute(hass: HomeAssistant):
    client = _Client(graph=RuntimeError("server gone"))
    devices = _house(hass, client)
    coord = await setup_coordinator(hass)
    await _read(hass, coord)
    assert coord.thread_view() is None and coord.device_thread(devices[5]) is None
    for odd in (
        {"nodes": "x", "connections": None},
        {"nodes": [None, 3, {"id": None}], "connections": [{"source": "a"}, "x"]},
        {"nodes": [{"id": "n5", "node_id": 5, "network_type": "thread"}], "connections": []},
    ):
        coord._mesh_state().update(graph=odd)
        coord.thread_view()
        coord.device_thread(devices[5])
    # The minute itself carries on when asking for the map throws.
    judged = []
    coord.mesh_tick = lambda now: (_ for _ in ()).throw(RuntimeError("client gone"))
    real = coord._judge_all_devices
    coord._judge_all_devices = lambda *a, **k: (judged.append(1), real(*a, **k))[1]
    await coord._on_render_tick(None)
    assert judged == [1]
