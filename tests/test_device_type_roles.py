# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_type_roles.py, Version: 0.25.2 (2026-10-09)

"""Types the entities cannot show (0.25.2).

A model James checked, what a device is to its network (a coordinator,
a controller, a border router), and last what its integration says for
a device whose entities name nothing. Answers James ruled on 9 October
2026 from the reference house.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import device_type as dt
from custom_components.device_sentinel.const import STACK_Z2M
from custom_components.device_sentinel.device_type import type_for_device

from .helpers import MULTI_OWNER_POSSIBLE, setup_coordinator


def _e(domain, device_class=None, category=None):
    return SimpleNamespace(domain=domain, device_class=None, original_device_class=device_class,
                           entity_category=category, disabled_by=None)


# ------------------------------------------------------------ the pure order

def test_a_known_model_wins_over_its_entities():
    model = ("Third Reality", "Zigbee / BLE smart plug", "3RSP019BZ")
    assert type_for_device([_e("switch")], model=model) == ("Plug", "known model")
    assert type_for_device([_e("switch")], model=("Third Reality", "Zigbee / BLE smart plug", "OTHER")) == (
        "Switch", "entities")


def test_a_role_wins_over_entities():
    assert type_for_device([_e("sensor", "temperature")], role=dt.ZWAVE_CONTROLLER) == ("Z-Wave Controller", "role")


@pytest.mark.parametrize(("kwargs", "entities", "expected"), [
    ({"domain": "brother"}, [_e("sensor")], "Printer"),
    ({"domain": "ipp"}, [], "Printer"),
    ({"domain": "esphome", "bluetooth_proxy": True}, [_e("sensor", "signal_strength")], "Bluetooth Proxy"),
    ({"domain": "esphome"}, [_e("sensor", "signal_strength")], "ESPHome Device"),
    # An ESPHome board whose entities say what it is keeps that.
    ({"domain": "esphome", "bluetooth_proxy": True}, [_e("sensor", "temperature")], "Temperature Sensor"),
    ({"domain": "esphome"}, [_e("switch")], "Switch"),
    ({"domain": "mqtt", "zigbee_router": True}, [_e("sensor", "signal_strength")], "Zigbee Router"),
    ({"domain": "mqtt", "zigbee_router": True}, [_e("switch"), _e("sensor", "power")], "Plug"),
    ({"domain": "zwave_js"}, [_e("sensor", "signal_strength", "diagnostic")], "Z-Wave Repeater"),
    ({"domain": "zwave_js"}, [_e("lock")], "Lock"),
    ({"domain": "zha", "hub": True}, [], "Zigbee Coordinator (ZHA)"),
    ({"domain": "matter", "hub": True}, [], "Matter Bridge"),
    ({"domain": "hue", "hub": True}, [], "Hub"),
    ({"domain": "hue", "hub": True}, [_e("light")], "Light"),
    ({"domain": "hue"}, [], None),
])
def test_the_integration_answers_last(kwargs, entities, expected):
    words, source = type_for_device(entities, **kwargs)
    assert words == expected
    if expected is None:
        assert source is None


def test_every_type_the_rules_give_is_a_choice():
    given = set(dt.KNOWN_MODEL_TYPES.values()) | {
        dt.ZIGBEE_COORDINATOR_Z2M, dt.ZIGBEE_COORDINATOR_ZHA, dt.ZWAVE_CONTROLLER, dt.THREAD_BORDER_ROUTER,
        dt.MATTER_BRIDGE, dt.ZIGBEE_ROUTER, dt.ZWAVE_REPEATER, dt.HUB, dt.PRINTER, dt.BLUETOOTH_PROXY,
        dt.ESPHOME_DEVICE,
    }
    assert given <= set(dt.TYPE_CHOICES)


# ------------------------------------------------------ on a running system

_entries: dict[tuple[int, str], MockConfigEntry] = {}


def _source(hass, domain, data=None):
    key = (id(hass), domain)
    if key not in _entries:
        entry = MockConfigEntry(domain=domain, title=domain, data=data or {})
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        _entries[key] = entry
    return _entries[key]


def _device(hass, domain, uid, name, entities=(("sensor", "signal_strength"),), **fields):
    source = _source(hass, domain)
    if "via_device_id" in fields and MULTI_OWNER_POSSIBLE:
        # Before 2026.8 the parent is named by its identifier.
        parent = dr.async_get(hass).async_get(fields.pop("via_device_id"))
        fields["via_device"] = next(iter(parent.identifiers))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=name, **fields,
    )
    for index, (edomain, device_class) in enumerate(entities):
        er.async_get(hass).async_get_or_create(edomain, domain, f"{uid}_{index}", device_id=device.id,
                                               config_entry=source, original_device_class=device_class)
    return device


@pytest.fixture(autouse=True)
def _clear():
    _entries.clear()


def _with_reader(coord, reader):
    """Put a stand-in Zigbee2MQTT reader in place; the real dict goes
    back before unload, which stops each reader it holds."""
    if not hasattr(coord, "_saved_readers"):
        coord._saved_readers = coord._bridge_readers
    coord._bridge_readers = {**coord._saved_readers, STACK_Z2M: reader}


def _put_back(coord):
    coord._bridge_readers = coord._saved_readers


async def test_zwave_node_one_is_the_controller_and_other_nodes_are_not(hass: HomeAssistant):
    controller = _device(hass, "zwave_js", "3967665212-1", "Zooz stick")
    repeater = _device(hass, "zwave_js", "3967665212-14", "Range extender",
                       entities=(("sensor", "signal_strength"),))
    coord = await setup_coordinator(hass)
    assert coord._type_auto(controller.id) == ("Z-Wave Controller", "role")
    words, _ = coord._type_auto(repeater.id)
    assert words != "Z-Wave Controller"


async def test_the_thread_border_router_and_a_coordinator_found_by_its_address(hass: HomeAssistant):
    _source(hass, "otbr", {"url": "http://192.168.1.60:8081"})
    _source(hass, "zha", {"device": {"path": "socket://192.168.1.50:6638"}})
    otbr = _device(hass, "otbr", "otbr1", "OpenThread Border Router")
    smlight = _device(hass, "smlight", "slzb", "SLZB-06M", configuration_url="http://192.168.1.50/")
    border = _device(hass, "smlight", "slzb-mr", "SLZB-MR1", configuration_url="http://192.168.1.60/")
    other = _device(hass, "smlight", "slzb2", "SLZB other", configuration_url="http://192.168.1.99/")
    coord = await setup_coordinator(hass)
    assert coord._type_auto(otbr.id) == ("Thread Border Router", "role")
    assert coord._type_auto(smlight.id) == ("Zigbee Coordinator (ZHA)", "role")
    assert coord._type_auto(border.id) == ("Thread Border Router", "role")
    assert coord._type_auto(other.id)[0] is None


async def test_the_zigbee2mqtt_serial_port_names_its_coordinator(hass: HomeAssistant):
    smlight = _device(hass, "smlight", "slzb", "SLZB-06M", configuration_url="http://192.168.1.50")
    coord = await setup_coordinator(hass)
    _with_reader(coord, SimpleNamespace(serial_port="tcp://192.168.1.50:6638", zigbee_role=lambda ieee: None))
    assert coord._type_auto(smlight.id) == ("Zigbee Coordinator (Zigbee2MQTT)", "role")
    # A port that is a local path names no host, and nothing is guessed.
    _with_reader(coord, SimpleNamespace(serial_port="/dev/ttyUSB0", zigbee_role=lambda ieee: None))
    assert coord._type_auto(smlight.id)[0] is None
    _put_back(coord)


async def test_a_bad_address_never_breaks_a_type(hass: HomeAssistant):
    _source(hass, "zha", {"device": "not a dict"})
    _source(hass, "otbr", {"url": 7})
    odd = _device(hass, "smlight", "x", "Odd", configuration_url="homeassistant://config/zha")
    coord = await setup_coordinator(hass)
    assert dt._host("http://[::1/") is None and dt._host(None) is None and dt._host("/dev/ttyACM0") is None
    assert coord._type_auto(odd.id)[0] is None


async def test_a_zigbee2mqtt_router_is_named_from_its_network_role(hass: HomeAssistant):
    radio = _device(hass, "mqtt", "zigbee2mqtt_0x00124b0029aa0001", "Repeater hall")
    coord = await setup_coordinator(hass)
    coord._stack_keys = {radio.id: (STACK_Z2M, "0x00124b0029aa0001")}
    roles = {"0x00124b0029aa0001": "Router"}
    _with_reader(coord, SimpleNamespace(serial_port=None, zigbee_role=roles.get))
    assert coord._type_auto(radio.id) == ("Zigbee Router", "role")
    roles["0x00124b0029aa0001"] = "EndDevice"
    assert coord._type_auto(radio.id)[0] is None

    def broken(_ieee):
        raise RuntimeError("bridge went away")

    _with_reader(coord, SimpleNamespace(serial_port=None, zigbee_role=broken))
    assert coord._type_auto(radio.id)[0] is None
    _put_back(coord)


async def test_an_esphome_board_with_a_bluetooth_adapter_is_a_bluetooth_proxy(hass: HomeAssistant):
    proxy = _device(hass, "esphome", "p1", "Office proxy", entities=(("sensor", "signal_strength"),
                                                                    ("button", "restart")))
    _device(hass, "bluetooth", "bt1", "Office proxy adapter", entities=(), via_device_id=proxy.id)
    board = _device(hass, "esphome", "p2", "Garage board")
    stove = _device(hass, "esphome", "p3", "Stove relay", entities=(("switch", None),))
    coord = await setup_coordinator(hass)
    assert coord._type_auto(proxy.id) == ("Bluetooth Proxy", "role")
    assert coord._type_auto(board.id) == ("ESPHome Device", "role")
    assert coord._type_auto(stove.id) == ("Switch", "entities")


async def test_a_hub_others_hang_from_is_named_by_its_integration(hass: HomeAssistant):
    bridge = _device(hass, "matter", "b1", "Bridge", entities=())
    _device(hass, "matter", "b1c", "Bridged light", entities=(("light", None),), via_device_id=bridge.id)
    hub = _device(hass, "hue", "h1", "Hue Bridge", entities=(("sensor", "signal_strength"),))
    hub_entity = er.async_get(hass).async_get_entity_id("sensor", "hue", "h1_0")
    er.async_get(hass).async_update_entity(hub_entity, entity_category=EntityCategory.DIAGNOSTIC)
    _device(hass, "hue", "h1c", "Hue bulb", entities=(("light", None),), via_device_id=hub.id)
    coord = await setup_coordinator(hass)
    assert coord._type_auto(bridge.id) == ("Matter Bridge", "role")
    assert coord._type_auto(hub.id) == ("Hub", "role")


async def test_a_known_model_reads_from_the_registry(hass: HomeAssistant):
    waterer = _device(hass, "mqtt", "w1", "Monstera", entities=(("switch", None),),
                      manufacturer="Third Reality", model="Smart watering kit", model_id="3RWK0148Z")
    coord = await setup_coordinator(hass)
    assert coord._type_auto(waterer.id) == ("Plant Waterer", "known model")
    view = coord.type_of(waterer.id)
    assert view["words"] == "Plant Waterer"


# ------------------------------------------------ the Zigbee2MQTT reader (0.25.2)

def _reader_msg(topic, payload):
    import json
    return SimpleNamespace(topic=topic, payload=json.dumps(payload) if not isinstance(payload, str) else payload)


def test_the_reader_keeps_the_serial_port_and_each_devices_role():
    import json
    import pathlib

    from custom_components.device_sentinel import stack_z2m

    fixtures = pathlib.Path(__file__).parent / "fixtures"
    devices = json.loads((fixtures / "z2m_bridge_devices.json").read_text())
    reader = stack_z2m.Z2MBridgeReader(None)
    assert reader.serial_port is None
    reader._on_info(_reader_msg("zigbee2mqtt/bridge/info", {"config": {"serial": {"port": "tcp://192.168.1.50:6638"}}}))
    reader._on_devices(_reader_msg("zigbee2mqtt/bridge/devices", devices))
    assert reader.serial_port == "tcp://192.168.1.50:6638"
    router = next(d["ieee_address"] for d in devices if d.get("type") == "Router")
    end = next(d["ieee_address"] for d in devices if d.get("type") == "EndDevice")
    assert reader.zigbee_role(router) == "Router"
    assert reader.zigbee_role(end) == "EndDevice"
    assert reader.zigbee_role("0xnothere") is None
    # A payload without the port, or a broken one, leaves the last good reading.
    reader._on_info(_reader_msg("zigbee2mqtt/bridge/info", {"config": {"serial": {"port": 5}}}))
    reader._on_info(_reader_msg("zigbee2mqtt/bridge/info", {"config": {}}))
    reader._on_info(_reader_msg("zigbee2mqtt/bridge/info", "not json"))
    assert reader.serial_port == "tcp://192.168.1.50:6638"


async def test_home_assistants_own_address_names_no_coordinator(hass: HomeAssistant):
    """Found by review: an add-on coordinator shares Home Assistant's
    address with every other add-on, such as a camera's."""
    await hass.config.async_update(internal_url="http://192.168.1.10:8123")
    _source(hass, "otbr", {"url": "http://192.168.1.10:8081"})
    _source(hass, "zha", {"device": {"path": "socket://127.0.0.1:6638"}})
    camera = _device(hass, "frigate", "f1", "Frigate", configuration_url="http://192.168.1.10:5000/")
    local = _device(hass, "frigate", "f2", "Frigate local", configuration_url="http://127.0.0.1:5000/")
    coord = await setup_coordinator(hass)
    assert coord._type_auto(camera.id)[0] != "Thread Border Router"
    assert coord._type_auto(local.id)[0] != "Zigbee Coordinator (ZHA)"


async def test_clearing_an_answer_names_device_sentinels_own_answer(hass: HomeAssistant):
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_DEVICE_PAGE, SYS_KIND

    waterer = _device(hass, "mqtt", "w1", "Monstera", entities=(("switch", None),),
                      manufacturer="Third Reality", model="Smart watering kit", model_id="3RWK0148Z")
    coord = await setup_coordinator(hass)
    coord.page_set_type(waterer.id, "Plug")
    coord.page_set_type(waterer.id, None)
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    phrase = coord._system_event_phrase(rows[-1])
    assert phrase.startswith("type entry removed, Device Sentinel's Plant Waterer used"), phrase
