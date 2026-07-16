# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.9 (2026-07-15)
"""0.3.9 tests: battery-only exclusions."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
)

DOMAIN = "device_sentinel"


def _battery_device(hass, source, index):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(source.domain, f"bx{index}")},
        name=f"BatX Device {index}",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", source.domain, f"bx{index}_pct",
        device_id=device.id, config_entry=source,
        original_device_class="battery",
    )
    return device, reg.entity_id


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_device_level_battery_exclude(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    kept, kept_eid = _battery_device(hass, source, 1)
    dropped, dropped_eid = _battery_device(hass, source, 2)
    entry = await _setup(
        hass, options={CONF_BATTERY_EXCLUDED_DEVICES: [dropped.id]}
    )
    coord = entry.runtime_data

    hass.states.async_set(kept_eid, "5")
    hass.states.async_set(dropped_eid, "5")
    await hass.async_block_till_done()

    # Both judged (observation), only the kept one reported.
    assert coord.battery_low_count == 1
    assert coord.battery_low_list[0]["name"] == "BatX Device 1"


async def test_integration_level_battery_exclude(hass: HomeAssistant):
    phone_src = MockConfigEntry(domain="mobile_app")
    phone_src.add_to_hass(hass)
    zig_src = MockConfigEntry(domain="mqtt")
    zig_src.add_to_hass(hass)
    phone, phone_eid = _battery_device(hass, phone_src, 3)
    sensor, sensor_eid = _battery_device(hass, zig_src, 4)
    entry = await _setup(
        hass,
        options={CONF_BATTERY_EXCLUDED_INTEGRATIONS: ["mobile_app"]},
    )
    coord = entry.runtime_data

    hass.states.async_set(phone_eid, "5")
    hass.states.async_set(sensor_eid, "5")
    await hass.async_block_till_done()

    assert coord.battery_low_count == 1
    assert coord.battery_low_list[0]["name"] == "BatX Device 4"


async def test_battery_exclude_applies_live(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eid = _battery_device(hass, source, 5)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(eid, "5")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        entry, options={CONF_BATTERY_EXCLUDED_DEVICES: [device.id]}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0  # excluded, no restart

    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1  # undo instant, nothing lost


async def test_detected_batteries_picker_source(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _battery_device(hass, source, 7)
    _battery_device(hass, source, 6)
    entry = await _setup(hass)
    rows = entry.runtime_data.detected_batteries
    assert [r["name"] for r in rows] == ["BatX Device 6", "BatX Device 7"]
    assert all(
        r["device_id"] and r["entity_id"] and r["integration"] == "test"
        for r in rows
    )
