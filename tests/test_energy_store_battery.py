# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_energy_store_battery.py, Version: 0.30.12 (2026-11-27)

"""A power station's charge is not a device's battery (rule BAT-01).

An EcoFlow DELTA 2 Max reports seven battery sensors, each the charge of
a store of energy that is used and refilled. Read as a cell, it would be
called low each time it was drained. Its battery sensors are not read; a
device of another integration is read as before.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DEV_BATTERY_LOW, ENERGY_STORE_INTEGRATIONS

from .helpers import registry_settled, setup_coordinator


def _station(hass, domain, uid):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Station {uid}",
    )
    registry = er.async_get(hass)
    entities = []
    for name in ("battery_level", "main_battery_level", "slave_1_battery_level"):
        entity = registry.async_get_or_create(
            "sensor", domain, f"{uid}_{name}", device_id=device.id, config_entry=source,
            original_device_class="battery", suggested_object_id=f"{uid}_{name}",
        ).entity_id
        hass.states.async_set(entity, "8", {"device_class": "battery", "unit_of_measurement": "%"})
        entities.append(entity)
    return device, entities


@pytest.mark.parametrize("domain", sorted(ENERGY_STORE_INTEGRATIONS))
async def test_a_drained_power_station_is_not_a_low_battery(hass: HomeAssistant, domain):
    device, entities = _station(hass, domain, "delta")
    other, _ = _station(hass, "test", "remote")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    assert device.id not in coord._battery_entity
    for entity in entities:
        hass.states.async_set(entity, "5", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert not coord.data["devices"].get(device.id, {}).get(DEV_BATTERY_LOW)
    assert other.id in coord._battery_entity, "any other device's battery is read as before"
