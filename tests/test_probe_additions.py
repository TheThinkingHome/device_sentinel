# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_probe_additions.py, Version: 0.23.11 (2026-09-27)

"""What the probe records from 0.23.11 (ruled 27 September 2026).

From the second fleet's capture of 26 September. Devices woken for a
few seconds left no trace, because the probe read state once a minute;
the Z-Wave library announces wake up, sleep, dead and alive as they
happen. Z-Wave keeps each node's route, the repeaters its messages
last travelled through, and a controller's health counters and
background noise. A muted device read "reporting" in the probe's
Device Sentinel column. For Thread, the upstream to build, the probe
records border routers appearing and disappearing, as Home Assistant's
own Thread discovery reports them, and each Thread device's network ID.
Recording only throughout: nothing is sent to any network.

The fakes carry the shapes the libraries carry: zwave-js-server-python
0.73.1 keeps a route as statistics.lwr with its raw data holding
"repeaters" and "routeFailedBetween", and a controller's noise as
"backgroundRSSI" by channel; a Thread node's network ID is attribute
0/53/4.
"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_STUDY_HARDWARE,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    STUDIABLE,
)
from custom_components.device_sentinel.study_stacks import thread_network_id, zwave_route

from .helpers import register_device, setup_coordinator


class _Node:
    """A Z-Wave node: status, statistics with a route, and listeners."""

    def __init__(self, node_id: int, status: int = 4, route=None):
        self.node_id = node_id
        self.status = status
        self.is_controller_node = False
        self.is_listening = True
        self.listeners: dict[str, list] = {}
        self.statistics = SimpleNamespace(
            lwr=None if route is None else SimpleNamespace(data=route),
        )

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)
        return lambda: self.listeners[event].remove(handler)

    def fire(self, event):
        for handler in list(self.listeners.get(event, [])):
            handler({"event": event, "node": self})


def _zwave(hass, nodes, counters=None, noise=None):
    stats = SimpleNamespace(**(counters or {}), data={"backgroundRSSI": noise} if noise else {})
    controller = SimpleNamespace(home_id=1, nodes={n.node_id: n for n in nodes}, status=0, statistics=stats)
    client = SimpleNamespace(driver=SimpleNamespace(controller=controller), connected=True)
    entry = MockConfigEntry(domain="zwave_js", title="Z-Wave")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(client=client)
    return controller


def _lines(coord, stack=None):
    return [line for line in coord._probe_recent if stack is None or f"| {stack} |" in line]


async def _study(hass, *labels):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[label] for label in labels]})


# ------------------------------------------------------------------ routes


def test_a_route_reads_as_its_repeaters_or_direct_or_failed():
    assert zwave_route(_Node(5, route={"repeaters": [16, 21]})) == "route via 16, 21"
    assert zwave_route(_Node(5, route={"repeaters": []})) == "route direct"
    assert zwave_route(_Node(5, route={"repeaters": [16], "routeFailedBetween": [16, 5]})) == (
        "route failed between 16 and 5"
    )
    assert zwave_route(_Node(5)) == ""


async def test_a_route_change_writes_a_line(hass: HomeAssistant):
    node = _Node(5, route={"repeaters": [16]})
    _zwave(hass, [node])
    coord = await _study(hass, "zwave_js")
    coord.probe_tick(1000.0)
    first = _lines(coord, "zwave_js")
    assert any("route via 16" in line for line in first), first
    node.statistics.lwr.data = {"repeaters": [21]}
    coord.probe_tick(1060.0)
    changed = _lines(coord, "zwave_js")[len(first):]
    assert len(changed) == 1, changed
    assert "route changed from route via 16" in changed[0] and "route via 21" in changed[0]
    coord.probe_tick(1120.0)
    assert len(_lines(coord, "zwave_js")) == len(first) + 1, "an unchanged route wrote again"


# ------------------------------------------------------------------ events


async def test_node_events_are_written_as_they_arrive(hass: HomeAssistant):
    node = _Node(7, status=1)
    _zwave(hass, [node])
    coord = await _study(hass, "zwave_js")
    coord.probe_tick(1000.0)
    before = len(_lines(coord, "zwave_js"))
    node.fire("wake up")
    node.fire("sleep")
    node.fire("dead")
    heard = _lines(coord, "zwave_js")[before:]
    assert [line.split("|")[6].strip() for line in heard] == ["event: wake up", "event: sleep", "event: dead"], heard
    assert all(" at " in line for line in heard)


async def test_a_node_is_listened_to_once_and_let_go_at_stop(hass: HomeAssistant):
    node = _Node(7)
    _zwave(hass, [node])
    coord = await _study(hass, "zwave_js")
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    assert all(len(node.listeners.get(event, [])) == 1 for event in ("wake up", "sleep", "dead", "alive"))
    await coord.async_probe_stop()
    assert all(not node.listeners.get(event) for event in ("wake up", "sleep", "dead", "alive"))


async def test_a_replaced_node_object_is_listened_to_afresh(hass: HomeAssistant):
    """The driver reconnecting replaces every node object."""
    old = _Node(7)
    controller = _zwave(hass, [old])
    coord = await _study(hass, "zwave_js")
    coord.probe_tick(1000.0)
    new = _Node(7)
    controller.nodes = {7: new}
    coord.probe_tick(1060.0)
    assert not old.listeners.get("dead") and len(new.listeners.get("dead", [])) == 1


async def test_a_throwing_listener_leaves_the_tick_running(hass: HomeAssistant):
    node = _Node(7)

    def _broken(event, handler):
        raise RuntimeError("listener refused")

    node.on = _broken
    _zwave(hass, [node])
    coord = await _study(hass, "zwave_js")
    coord.probe_tick(1000.0)
    await coord._on_render_tick(None)


# --------------------------------------------------------- controller health


async def test_the_controller_health_line_carries_the_day_and_the_noise(hass: HomeAssistant):
    counters = {"messages_tx": 100, "messages_dropped_tx": 2, "nak": 1, "can": 0, "timeout_ack": 0}
    noise = {"channel0": {"average": -95, "current": -94}, "channel1": {"average": -97, "current": -96}}
    controller = _zwave(hass, [_Node(5)], counters, noise)
    coord = await _study(hass, "zwave_js")
    coord.probe_fold(1000.0)
    first = [line for line in _lines(coord, "zwave_js") if "| health |" in line]
    assert len(first) == 1 and "nak +1" in first[0] and "noise ch0 -95 dBm, ch1 -97 dBm" in first[0], first
    controller.statistics.nak = 4
    controller.statistics.messages_tx = 160
    coord.probe_fold(87400.0)
    second = [line for line in _lines(coord, "zwave_js") if "| health |" in line][-1]
    assert "nak +3" in second and "messages_tx +60" in second, second


# ---------------------------------------------------------- the column says


async def test_a_muted_device_reads_muted_not_reporting(hass: HomeAssistant):
    device, _ = register_device(hass, "s81", "S81 Smoke alarm sensor")
    coord = await setup_coordinator(hass, {CONF_FREEZE_MUTED_DEVICES: [device.id]})
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 1)
    record[DEV_EVENT_COUNT] = 80
    record[DEV_LAST_ACTIVITY] = 990.0
    views = coord._probe_views({"stack": "zwave_js", "node": "26", "device_id": device.id, "now": "dead"}, 1000.0)
    assert views["sentinel"] == "muted"
    assert views["agrees"] == ""


async def test_a_device_still_learning_reads_learning(hass: HomeAssistant):
    device, _ = register_device(hass, "d48", "D48 Water shutoff")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0]
    record[DEV_EVENT_COUNT] = 38
    record[DEV_LAST_ACTIVITY] = 990.0
    views = coord._probe_views({"stack": "zwave_js", "node": "24", "device_id": device.id, "now": "alive"}, 1000.0)
    assert views["sentinel"] == "learning"
    assert views["agrees"] == ""


# ------------------------------------------------------------------ Thread


def test_a_thread_network_id_reads_as_sixteen_hex_digits():
    assert thread_network_id(0x1234ABCD5678EF00) == "1234abcd5678ef00"
    assert thread_network_id("1234ABCD5678EF00") == "1234abcd5678ef00"
    assert thread_network_id(True) == ""
    assert thread_network_id("not an id") == ""
    assert thread_network_id(None) == ""


async def test_a_thread_node_carries_its_network_id(hass: HomeAssistant):
    node = SimpleNamespace(
        node_id=22, available=True,
        node_data=SimpleNamespace(attributes={"0/53/1": 5, "0/53/4": 0xDEAD00BEEF001234}),
    )
    client = SimpleNamespace(get_nodes=lambda: [node], connection=SimpleNamespace(connected=True))
    entry = MockConfigEntry(domain="matter", title="Matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=client))
    with _thread_package(_Discovery):
        coord = await _study(hass, "matter")
        coord.probe_tick(1000.0)
    lines = _lines(coord, "matter")
    assert any("thread network dead00beef001234" in line for line in lines), lines


def _thread_package(discovery_class):
    """Home Assistant's Thread package as far as the probe imports it.

    The real one needs python-otbr-api, which only a house with the
    Thread integration installed has; the probe's import is guarded for
    the house without it, and that path is tested at the end.
    """
    package = ModuleType("homeassistant.components.thread")
    module = ModuleType("homeassistant.components.thread.discovery")
    module.ThreadRouterDiscovery = discovery_class
    package.discovery = module
    return patch.dict(sys.modules, {
        "homeassistant.components.thread": package,
        "homeassistant.components.thread.discovery": module,
    })


class _Discovery:
    """Home Assistant's ThreadRouterDiscovery, as far as the probe uses it."""

    made: list["_Discovery"] = []

    def __init__(self, hass, found, gone):
        self.found, self.gone, self.stopped = found, gone, False
        _Discovery.made.append(self)

    async def async_start(self):
        return None

    async def async_stop(self):
        self.stopped = True


def _router(network="MyHome", pan="DEAD00BEEF001234", vendor="SMLIGHT", model="SMHUB"):
    return SimpleNamespace(
        network_name=network, extended_pan_id=pan, vendor_name=vendor, model_name=model,
        instance_name="SMHUB-1",
    )


async def test_border_routers_appearing_and_going_are_written(hass: HomeAssistant):
    _Discovery.made.clear()
    with _thread_package(_Discovery):
        coord = await _study(hass, "matter")
        coord.probe_tick(1000.0)
        await hass.async_block_till_done()
        assert len(_Discovery.made) == 1
        discovery = _Discovery.made[0]
        discovery.found("aa11", _router())
        discovery.found("aa11", _router())  # the same announcement again
        discovery.found("bb22", _router(vendor="Apple", model="HomePod"))
        discovery.gone("aa11")
        discovery.gone("aa11")  # already gone
        await hass.async_block_till_done()
    lines = _lines(coord, "thread")
    states = [line.split("|")[6].strip() for line in lines]
    assert states == ["present", "present", "gone"], lines
    assert "network MyHome" in lines[0] and "network id dead00beef001234" in lines[0]
    assert "SMLIGHT SMHUB" in lines[0] and "Apple HomePod" in lines[1]
    assert "SMLIGHT SMHUB" in lines[2], "a gone line names the router it was"


async def test_discovery_starts_once_and_stops_with_device_sentinel(hass: HomeAssistant):
    _Discovery.made.clear()
    with _thread_package(_Discovery):
        coord = await _study(hass, "matter")
        for minute in range(3):
            coord.probe_tick(1000.0 + 60 * minute)
            await hass.async_block_till_done()
        assert len(_Discovery.made) == 1
        await coord.async_probe_stop()
    assert _Discovery.made[0].stopped


async def test_a_house_without_thread_starts_nothing_and_breaks_nothing(hass: HomeAssistant):
    class _Refuses(_Discovery):
        async def async_start(self):
            raise RuntimeError("zeroconf is not set up")

    with _thread_package(_Refuses):
        coord = await _study(hass, "matter")
        coord.probe_tick(1000.0)
        await hass.async_block_till_done()
        await coord._on_render_tick(None)
    assert coord._thread_discovery is None
    assert coord._thread_failed, "it would ask again every minute"


async def test_a_house_without_the_thread_library_breaks_nothing(hass: HomeAssistant):
    """The real import, where python-otbr-api is not installed."""
    coord = await _study(hass, "matter")
    coord.probe_tick(1000.0)
    await hass.async_block_till_done()
    await coord._on_render_tick(None)
    assert coord._thread_discovery is None
