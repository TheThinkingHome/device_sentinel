# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_matter_contact_clock.py, Version: 0.30.7 (2026-11-26)

"""Device Sentinel's own contact clock for each Matter device (rule STACK-19).

While Matter is studied, any value a device sends through Home
Assistant's Matter client counts as contact, even one no entity shows.
The download sets the clock beside the device's last report through its
entities, with its check-in state and its Power Source answer. Recorded
only: no verdict changes, and nothing is stored.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import study_matter
from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE, STUDIABLE
from custom_components.device_sentinel.study_matter import check_in, power_source
from custom_components.device_sentinel.study_stacks import matter_study

from tests.helpers import setup_coordinator

FABRIC = "00000000000000AB"


class _Event:
    def __init__(self, value):
        self.value = value


def _node(number, attributes=None):
    return SimpleNamespace(
        node_id=number, available=True, is_bridge_device=False,
        node_data=SimpleNamespace(attributes=attributes or {}),
    )


class _Client:
    def __init__(self, nodes, schema=13):
        self.server_info = SimpleNamespace(schema_version=schema)
        self.nodes = nodes
        self.listeners: dict[int, list] = {}
        self.stopped: list[int] = []

    def get_nodes(self):
        return self.nodes

    def subscribe_events(self, callback, event_filter=None, node_filter=None):
        self.listeners.setdefault(node_filter, []).append(callback)

        def unsub():
            self.stopped.append(node_filter)
            self.listeners[node_filter].remove(callback)

        return unsub

    def send(self, number, what="attribute_updated"):
        for callback in list(self.listeners.get(number, [])):
            callback(_Event(what), None)

    async def get_icd_state(self, number):
        if number == 9:
            await asyncio.sleep(10)
        return SimpleNamespace(
            supported=True, lit_supported=False, registered=False, operating_mode="sit",
            awake=None, available=True, next_expected_checkin=None,
        )

    async def get_network_topology(self, refresh=False):
        return {"nodes": [], "connections": []}


def _house(hass, client):
    entry = MockConfigEntry(domain="matter", title="Matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=client))
    registry = dr.async_get(hass)
    return {
        number: registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("matter", f"deviceid_{FABRIC}-{number:016X}-MatterNodeDevice")},
            name=f"Node {number}",
        ).id
        for number in (5, 6)
    }


async def _studied(hass):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["matter"]]})


async def test_a_value_or_event_is_contact_and_a_server_update_is_not(hass: HomeAssistant, monkeypatch):
    client = _Client([_node(5), _node(6)])
    _house(hass, client)
    coord = await _studied(hass)
    clock = [1000.0]
    monkeypatch.setattr(study_matter.time, "time", lambda: clock[0])
    coord._matter_contact_clear()
    coord._matter_contact_tick(1000.0)
    assert set(client.listeners) == {5, 6}
    coord._matter_contact_tick(1060.0)
    assert all(len(found) == 1 for found in client.listeners.values()), "listened to once"
    clock[0] = 1600.0
    client.send(5)
    client.send(5, "node_removed")
    clock[0] = 1700.0
    client.send(5, "node_event")
    # The server marking it unavailable sends a whole-node update: counted
    # apart, never contact, or a dead device would read as heard.
    clock[0] = 1800.0
    client.send(6, "node_updated")
    client.send(6, "subscription_report")
    clock[0] = 1700.0
    view = coord.matter_contact_view()
    assert view[5]["heard"] == 2 and view[5]["last_seconds_ago"] == 0
    assert view[6]["server_updates"] == 1
    assert view[5]["longest_silence_seconds"] == 600, "from listening to the first value"
    assert view[6]["heard"] == 0 and view[6]["last_seconds_ago"] is None
    assert view[6]["longest_silence_seconds"] == 700, "a silence still running counts"


async def test_cleared_when_matter_is_not_studied_or_the_client_changes(hass: HomeAssistant):
    client = _Client([_node(5)])
    _house(hass, client)
    coord = await _studied(hass)
    coord._matter_contact_clear()
    coord._matter_contact_tick(1000.0)
    other = _Client([_node(5)])
    hass.config_entries.async_entries("matter")[0].runtime_data = SimpleNamespace(
        adapter=SimpleNamespace(matter_client=other)
    )
    coord._matter_contact_tick(1060.0)
    assert client.stopped == [5] and 5 in other.listeners, "a reloaded Matter gets new listeners"
    coord._matter_contact_clear()
    assert other.stopped == [5] and coord.matter_contact_view() == {}


async def test_a_listener_never_raises(hass: HomeAssistant):
    client = _Client([_node(5), SimpleNamespace(node_id="x"), SimpleNamespace()])
    _house(hass, client)
    coord = await _studied(hass)
    coord._matter_contact_clear()
    coord._matter_contact_tick(1000.0)
    coord._contact_state()["nodes"].clear()
    client.send(5)  # its row is gone: ignored
    client.send(5, object())

    def broken():
        raise RuntimeError("client gone")

    client.get_nodes = broken
    coord._matter_contact_tick(1060.0)


def test_power_source_from_the_device():
    node = _node(5, {
        "1/47/65532": 0b1010, "1/47/20": "AA", "1/47/31": 2, "1/47/19": "x" * 90,
        "0/47/65532": True, "2/6/65532": 1,
    })
    found = power_source(node)["sources"]
    assert found == [{
        "endpoint": "1", "wired": False, "battery": True, "rechargeable": False, "replaceable": True,
        "ansi": "AA", "quantity": 2, "replacement": "x" * 60,
    }]
    assert power_source(_node(6, {"1/47/65532": 1}))["sources"][0]["wired"] is True
    assert power_source(_node(7)) is None and power_source(SimpleNamespace()) is None


async def test_check_in_needs_schema_12_and_gives_up_in_time(hass: HomeAssistant, monkeypatch):
    client = _Client([])
    assert (await check_in(client, 5))["operating_mode"] == "sit"
    monkeypatch.setattr(study_matter, "CHECK_IN_SECONDS", 0.05)
    assert await check_in(client, 9) == {"error": "TimeoutError"}
    # One slow answer and the rest of the download is not kept waiting.
    budget: dict = {}
    assert await check_in(client, 9, budget) == {"error": "TimeoutError"}
    assert await check_in(client, 5, budget) == {"error": "skipped"}
    client.server_info = SimpleNamespace(schema_version=11)
    assert await check_in(client, 5) is None


async def test_the_download_sets_the_clock_beside_the_entities(hass: HomeAssistant):
    client = _Client([_node(5, {"1/47/65532": 1}), _node(6)])
    devices = _house(hass, client)
    coord = await _studied(hass)
    coord._matter_contact_clear()
    coord._matter_contact_tick(1000.0)
    client.send(5)
    study = await matter_study(hass, coord)
    rows = {row["node_id"]: row for row in study["fabrics"][0]["node_rows"]}
    assert rows[5]["contact"]["heard"] == 1 and rows[5]["check_in"]["supported"] is True
    assert rows[5]["power_source"]["sources"][0]["wired"] is True and rows[6]["power_source"] is None
    assert "entities_last_seconds_ago" in rows[5] and devices
    assert "thread_map" in study
    # Without the coordinator the study is as before.
    bare = await matter_study(hass)
    assert "contact" not in bare["fabrics"][0]["node_rows"][0] and "thread_map" not in bare
