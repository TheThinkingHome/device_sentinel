# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_own_platform.py, Version: 0.20.19 (2026-09-12)

"""A reading is preferred from the device's own integration (#404)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .helpers import setup_entry


async def _house(hass, extras):
    """One zha device, plus whatever entities `extras` asks for.

    Each extra is (platform, domain, object_id, device_class).
    """
    own = MockConfigEntry(domain="zha")
    own.add_to_hass(hass)
    foreign = MockConfigEntry(domain="battery_notes")
    foreign.add_to_hass(hass)
    reg = dr.async_get(hass)
    ents = er.async_get(hass)
    device = reg.async_get_or_create(
        config_entry_id=own.entry_id,
        identifiers={("zha", "b01")},
        name="B01 Study button",
    )
    made = []
    for platform, domain, object_id, device_class in extras:
        entry = own if platform == "zha" else foreign
        made.append(
            ents.async_get_or_create(
                domain, platform, object_id,
                device_id=device.id, config_entry=entry,
                original_device_class=device_class,
            )
        )
    return device, made


async def test_the_device_s_own_battery_wins(hass: HomeAssistant, hass_storage):
    """Battery Notes gives 76 of the second fleet's devices a second
    percentage. The device's own is the one that has not been
    through anything."""
    device, _ = await _house(hass, [
        ("battery_notes", "sensor", "b01_battery_plus", "battery"),
        ("zha", "sensor", "b01_power", "battery"),
    ])
    entry = await setup_entry(hass)
    elected, is_binary = entry.runtime_data._battery_entity[device.id]
    assert elected == "sensor.zha_b01_power"
    assert is_binary is False
    assert entry.runtime_data._battery_own[device.id] is True


async def test_registry_order_does_not_decide(hass: HomeAssistant, hass_storage):
    """The same two entities, created the other way round."""
    device, _ = await _house(hass, [
        ("zha", "sensor", "b01_power", "battery"),
        ("battery_notes", "sensor", "b01_battery_plus", "battery"),
    ])
    entry = await setup_entry(hass)
    elected, _ = entry.runtime_data._battery_entity[device.id]
    assert elected == "sensor.zha_b01_power"


async def test_a_foreign_reading_is_used_when_it_is_the_only_one(
    hass: HomeAssistant, hass_storage
):
    """Better second-hand than nothing: the device publishes none."""
    device, _ = await _house(hass, [
        ("battery_notes", "sensor", "b01_battery_plus", "battery"),
    ])
    entry = await setup_entry(hass)
    elected, _ = entry.runtime_data._battery_entity[device.id]
    assert elected == "sensor.battery_notes_b01_battery_plus"
    assert entry.runtime_data._battery_own[device.id] is False


async def test_a_percentage_still_beats_a_binary(hass: HomeAssistant, hass_storage):
    """The first rung is unchanged: the binary is the last resort
    even when it is the device's own."""
    device, _ = await _house(hass, [
        ("zha", "binary_sensor", "b01_low", "battery"),
        ("battery_notes", "sensor", "b01_battery_plus", "battery"),
    ])
    entry = await setup_entry(hass)
    elected, is_binary = entry.runtime_data._battery_entity[device.id]
    assert elected == "sensor.battery_notes_b01_battery_plus"
    assert is_binary is False


async def test_two_foreign_percentages_pick_the_lower_id(
    hass: HomeAssistant, hass_storage
):
    """Among equals the entity id decides, so the choice is the same
    on every restart rather than whichever the walk reached first."""
    device, _ = await _house(hass, [
        ("battery_notes", "sensor", "zz_b01_battery_plus", "battery"),
        ("battery_notes", "sensor", "aa_b01_battery_plus", "battery"),
    ])
    entry = await setup_entry(hass)
    elected, _ = entry.runtime_data._battery_entity[device.id]
    assert elected == "sensor.battery_notes_aa_b01_battery_plus"


async def test_the_device_s_own_last_seen_wins(hass: HomeAssistant, hass_storage):
    """The same rule on the clock, which #124 makes load-bearing."""
    device, _ = await _house(hass, [
        ("battery_notes", "sensor", "b01_last_seen", "timestamp"),
        ("zha", "sensor", "b01_own_last_seen", "timestamp"),
    ])
    entry = await setup_entry(hass)
    assert (
        entry.runtime_data._last_seen_entity[device.id]
        == "sensor.zha_b01_own_last_seen"
    )
    assert entry.runtime_data._last_seen_own[device.id] is True
