# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_controller_noise.py, Version: 0.28.6 (2026-11-08)

"""A Z-Wave controller's channel noise is not its signal (rule SIG-02).

Z-Wave JS gives an 800 series controller "Signal noise channel N" sensors
with the signal_strength class and a dBm unit. They measure the room's
radio noise, not a link, and were judged as the controller's signal,
earning it bad-signal days. Seen on a live house.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_VALUE,
)
from custom_components.device_sentinel.detect_signal import SignalMixin
from tests.helpers import setup_coordinator


def _ent(entity_id, unique_id, name, device_class="signal_strength", unit="dBm"):
    return SimpleNamespace(
        entity_id=entity_id, unique_id=unique_id, original_name=name,
        original_device_class=device_class, device_class=None,
        unit_of_measurement=unit, original_unit_of_measurement=unit,
        capabilities=None,
    )


def test_channel_noise_is_not_a_signal():
    noise = _ent(
        "sensor.800_series_long_range_usb_controller_signal_noise_channel_0",
        "3967834211.1.statistics_background_rssi.channel_0.current",
        "Signal noise channel 0",
    )
    average = _ent(
        "sensor.800_series_long_range_usb_controller_avg_signal_noise_channel_0",
        "3967834211.1.statistics_background_rssi.channel_0.average",
        "Avg. signal noise channel 0",
    )
    assert not SignalMixin._is_signal(noise)
    assert not SignalMixin._is_signal(average)


def test_a_link_signal_is_still_a_signal():
    """Guard: a node's own RSSI, a Zigbee link quality and a
    signal-to-noise ratio stay signals."""
    assert SignalMixin._is_signal(_ent("sensor.lock_signal_strength", "3967834211.7.rssi", "Signal strength"))
    assert SignalMixin._is_signal(_ent("sensor.door_linkquality", "0x00158d_linkquality", "Linkquality", None, "lqi"))
    assert SignalMixin._is_signal(_ent("sensor.ap_signal_to_noise", "ap_signal_to_noise", "Signal to noise", "signal_strength", "dB"))
    assert SignalMixin._is_signal(_ent("sensor.lte_signal_noise_ratio", "lte_signal_noise_ratio", "Signal noise ratio", "signal_strength", "dB"))


def test_the_translation_key_alone_is_enough():
    """A translated entity can carry no name of its own."""
    ent = _ent("sensor.stick_signal_noise_channel_3", "odd-id", None)
    ent.translation_key = "signal_noise"
    assert not SignalMixin._is_signal(ent)


def test_an_esphome_sensor_named_for_noise_keeps_its_signal():
    """Guard: ESPHome builds its unique id from the name a person writes."""
    assert SignalMixin._is_signal(_ent(
        "sensor.noise_floor_monitor_wifi_signal", "a4f9335c25a1-sensor-noise_floor_monitor_wifi_signal",
        "Noise Floor Monitor WiFi Signal"))


def test_a_device_named_for_noise_keeps_its_signal():
    """Guard: a person's name for the device is in the entity id and says
    nothing of what the entity measures."""
    assert SignalMixin._is_signal(_ent(
        "sensor.noise_floor_monitor_wifi_signal", "aa:bb:cc-wifi_signal", "WiFi Signal"))


def _zwave(hass, node: str, name: str):
    entry = MockConfigEntry(domain="zwave_js", title="Z-Wave")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zwave_js", f"3967834211-{node}")}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "zwave_js", f"3967834211.{node}.statistics_background_rssi.channel_0.current",
        device_id=device.id, config_entry=entry, original_device_class="signal_strength",
        unit_of_measurement="dBm", original_name="Signal noise channel 0",
    )
    return device


async def test_a_controller_forgets_the_signal_it_learned_from_noise(hass: HomeAssistant):
    controller = _zwave(hass, "1", "800 Series Long Range USB Controller")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    record = coordinator.data[DATA_DEVICES].get(controller.id)
    assert record is not None
    record[DEV_SIGNAL_DAILY_P50] = [-103.0] * 10
    record[DEV_SIGNAL_VALUE] = -99.0
    coordinator._rebuild_registry_view()
    assert controller.id not in coordinator._signal_devices
    assert not record[DEV_SIGNAL_DAILY_P50]
    assert record[DEV_SIGNAL_VALUE] is None


async def test_another_node_keeps_its_signal(hass: HomeAssistant):
    """Guard: only node 1, the controller, is forgotten."""
    node = _zwave(hass, "7", "Front Lock")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    record = coordinator.data[DATA_DEVICES].get(node.id)
    assert record is not None
    record[DEV_SIGNAL_DAILY_P50] = [-70.0] * 10
    coordinator._rebuild_registry_view()
    assert record[DEV_SIGNAL_DAILY_P50] == [-70.0] * 10
