# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_power_from_zigbee.py, Version: 0.30.7 (2026-11-26)

"""Mains power taken from the device's own Zigbee coordinator (rule DEV-06).

Zigbee2MQTT and ZHA each know a mains device from a battery one. Where
the owner has given no answer and Battery Notes' library knows nothing,
a device either coordinator reports as mains is Mains Powered, shown as
reported by it, and leaves Power Not Set. A battery device still needs
its battery named, and a device reporting a battery level is never taken
as mains on the coordinator's word.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_BATTERY_VALUE, STACK_Z2M
from custom_components.device_sentinel.power_source import SOURCE_OWNER, SOURCE_STACK

from tests.helpers import register_device, setup_coordinator


class _Z2M:
    def __init__(self, said):
        self.said = said
        self.asked = 0

    def async_stop(self):
        """Stopped at unload, as a real reader is."""

    def power_source(self, key):
        self.asked += 1
        if isinstance(self.said, Exception):
            raise self.said
        return self.said.get(key)


def _z2m(coord, device_id, ieee, said):
    reader = _Z2M(said)
    coord._stack_keys = {**coord._stack_keys, device_id: (STACK_Z2M, ieee)}
    coord._bridge_readers = {**coord._bridge_readers, STACK_Z2M: reader}
    coord._stack_mains_cache = None
    return reader


def _power_card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "power"), None)


async def test_zigbee2mqtt_mains_is_mains_powered(hass: HomeAssistant):
    plug, _ = register_device(hass, "plug", name="Plug")
    coord = await setup_coordinator(hass)
    _z2m(coord, plug.id, "0x01", {"0x01": "Mains (single phase)"})
    known = coord.power_of(plug.id)
    assert known["source"] == SOURCE_STACK and known["kind"] == "mains" and known["words"] == "Mains Powered"
    assert known["reported_by"] == "Zigbee2MQTT"
    card = _power_card(coord)
    assert card is None or plug.id not in [row["device_id"] for row in card["devices"]]
    assert coord.power_view(plug.id)["reported_by"] == "Zigbee2MQTT"


async def test_a_battery_or_dc_source_is_left_to_the_owner(hass: HomeAssistant):
    device, _ = register_device(hass, "sensor", name="Sensor")
    coord = await setup_coordinator(hass)
    reader = _z2m(coord, device.id, "0x02", {})
    for said in ("Battery", "DC Source", "Unknown", None, 3):
        reader.said = {"0x02": said}
        coord._stack_mains_cache = None
        assert coord.power_of(device.id) is None, said


async def test_zha_mains_is_mains_powered(hass: HomeAssistant):
    plug, _ = register_device(hass, "zplug", name="ZHA Plug")
    sensor, _ = register_device(hass, "zsensor", name="ZHA Sensor")
    registry = dr.async_get(hass)
    registry.async_update_device(plug.id, new_identifiers={("zha", "00:11:22:33:44:55:66:77")})
    registry.async_update_device(sensor.id, new_identifiers={("zha", "00:11:22:33:44:55:66:88")})
    hass.data["zha"] = SimpleNamespace(gateway_proxy=SimpleNamespace(device_proxies={
        "00:11:22:33:44:55:66:77": SimpleNamespace(device=SimpleNamespace(is_mains_powered=True)),
        "00:11:22:33:44:55:66:88": SimpleNamespace(device=SimpleNamespace(is_mains_powered=False)),
    }))
    coord = await setup_coordinator(hass)
    coord._stack_mains_cache = None
    assert coord.power_of(plug.id)["reported_by"] == "ZHA"
    assert coord.power_of(sensor.id) is None
    hass.data.pop("zha", None)


async def test_zha_objects_of_another_shape_say_nothing(hass: HomeAssistant):
    plug, _ = register_device(hass, "zplug", name="ZHA Plug")
    dr.async_get(hass).async_update_device(plug.id, new_identifiers={("zha", "00:11")})
    coord = await setup_coordinator(hass)
    for data in (None, SimpleNamespace(), SimpleNamespace(gateway_proxy=SimpleNamespace(device_proxies={"00:11": object()}))):
        hass.data["zha"] = data
        coord._stack_mains_cache = None
        assert coord.power_of(plug.id) is None
    hass.data.pop("zha", None)


async def test_a_device_reporting_a_battery_is_not_taken_as_mains(hass: HomeAssistant):
    plug, _ = register_device(hass, "plug", name="Plug")
    coord = await setup_coordinator(hass)
    _z2m(coord, plug.id, "0x01", {"0x01": "Mains (single phase)"})
    coord.data[DATA_DEVICES].setdefault(plug.id, {})[DEV_BATTERY_VALUE] = 80.0
    assert coord.power_of(plug.id) is None


async def test_the_owners_answer_comes_first(hass: HomeAssistant):
    plug, _ = register_device(hass, "plug", name="Plug")
    coord = await setup_coordinator(hass)
    _z2m(coord, plug.id, "0x01", {"0x01": "Mains (single phase)"})
    coord.page_set_power(plug.id, "USB Powered")
    known = coord.power_of(plug.id)
    assert known["source"] == SOURCE_OWNER and known["type"] == "USB Powered"


async def test_a_reader_that_fails_says_nothing_and_is_asked_once_a_minute(hass: HomeAssistant):
    plug, _ = register_device(hass, "plug", name="Plug")
    coord = await setup_coordinator(hass)
    reader = _z2m(coord, plug.id, "0x01", RuntimeError("broken"))
    assert coord.power_of(plug.id) is None
    reader.said = {"0x01": "Mains (single phase)"}
    assert coord.power_of(plug.id) is None, "the word is kept for a minute"
    assert reader.asked == 1
    coord._stack_mains_cache = None
    assert coord.power_of(plug.id)["reported_by"] == "Zigbee2MQTT"
