# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_settings_list_names.py, Version: 0.27.10 (2026-10-27)

"""Every Settings list names a device "Name (integration)", once (rule
DEV-04).

The Low Battery list names the device, not its battery entity, and
two devices sharing a name read "Name (test)" on the Low Battery and
Signal Strength lists, never "Name (test) (test)".
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_SIGNAL_VALUE,
)

from .helpers import flat_schema, register_device, setup_entry


async def _house(hass, names=("Bluetooth Proxy", "Bluetooth Proxy")):
    devices = []
    reg = er.async_get(hass)
    for index, name in enumerate(names):
        uid = f"bp{index}"
        device, (eid,) = register_device(hass, uid, name=name)
        source = hass.config_entries.async_get_entry(reg.async_get(eid).config_entry_id)
        reg.async_get_or_create("sensor", "test", f"{uid}_rssi", device_id=device.id,
                                config_entry=source,
                                original_device_class="signal_strength", unit_of_measurement="dBm")
        reg.async_get_or_create("sensor", "test", f"{uid}_battery", device_id=device.id,
                                config_entry=source,
                                original_device_class="battery", unit_of_measurement="%")
        devices.append(device)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    for device in devices:
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_VALUE] = -60.0
    return entry


async def _labels(hass, entry, step, key):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    schema = flat_schema(result["data_schema"].schema)
    field = next(k for k in schema if str(k) == key)
    return sorted(opt["label"] for opt in schema[field].config["options"])


async def test_the_battery_list_names_the_integration_not_the_entity(hass: HomeAssistant):
    entry = await _house(hass, names=("Kitchen Plug", "Hall Motion"))
    labels = await _labels(hass, entry, "battery", CONF_BATTERY_MUTED_DEVICES)
    assert labels == ["Hall Motion (test)", "Kitchen Plug (test)"]


async def test_a_shared_name_on_the_battery_list_carries_the_integration_once(hass: HomeAssistant):
    entry = await _house(hass)
    labels = await _labels(hass, entry, "battery", CONF_BATTERY_MUTED_DEVICES)
    assert labels == ["Bluetooth Proxy (test)"] * 2


async def test_a_shared_name_on_the_signal_list_carries_the_integration_once(hass: HomeAssistant):
    entry = await _house(hass)
    labels = await _labels(hass, entry, "signal", CONF_SIGNAL_MUTED_DEVICES)
    assert labels == ["Bluetooth Proxy (test)"] * 2
