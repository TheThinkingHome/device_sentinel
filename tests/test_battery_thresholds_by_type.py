# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery_thresholds_by_type.py, Version: 0.30.0 (2026-11-21)

"""A low line for each battery type (rule BAT-03).

Alkaline cells at 10%, lithium and other batteries at 20% (and a coin
cell at about 2.9 V resting), rechargeable batteries at 20%. A battery
whose type is not known is judged as lithium and other.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_LAST_VERSION,
    DATA_SYSTEM_EVENTS,
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_LOW,
    DEV_BATTERY_VOLTS_TODAY_HIGH,
    SETTINGS_BATTERY_BY_TYPE,
    SYS_DETAIL,
    SYS_KIND,
    SYS_SETTINGS_CHANGED,
)
from custom_components.device_sentinel.power_source import battery_group

from .helpers import registry_settled, setup_coordinator


@pytest.mark.parametrize(("battery", "group"), [
    ("AA", "alkaline"), ("AAA", "alkaline"), ("aaa", "alkaline"), ("LR6", "alkaline"),
    ("AAA Lithium", "lithium"), ("CR2032", "lithium"), ("CR123A", "lithium"),
    ("Rechargeable", "rechargeable"), ("USB-C Rechargeable", "rechargeable"),
    ("LIR2450", "rechargeable"), ("18650", "rechargeable"),
    ("PP3", "lithium"), ("Irreplaceable", "lithium"), (None, "lithium"),
])
def test_each_type_finds_its_line(battery, group):
    assert battery_group(battery) == group


async def _cell(hass: HomeAssistant, uid: str):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=uid,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_battery", device_id=device.id, config_entry=source,
        original_device_class="battery", suggested_object_id=f"{uid}_battery",
    ).entity_id
    hass.states.async_set(entity, "90", {"device_class": "battery", "unit_of_measurement": "%"})
    return device, entity


async def _read(hass, coord, device, entity, level):
    hass.states.async_set(entity, str(level), {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return bool(coord.data["devices"][device.id].get(DEV_BATTERY_LOW))


async def test_each_type_is_low_at_its_own_line(hass: HomeAssistant):
    alkaline, alk = await _cell(hass, "door")
    coin, cr = await _cell(hass, "leak")
    blind, rch = await _cell(hass, "blind")
    unknown, unk = await _cell(hass, "button")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(alkaline.id, "AAA", 2)
    coord.page_set_power(coin.id, "CR2032", 1)
    coord.page_set_power(blind.id, "Rechargeable", 1)

    assert not await _read(hass, coord, alkaline, alk, 12), "12% leaves an alkaline cell weeks"
    assert await _read(hass, coord, alkaline, alk, 10)
    assert await _read(hass, coord, coin, cr, 19)
    assert await _read(hass, coord, blind, rch, 20)
    assert await _read(hass, coord, unknown, unk, 20), "a type not known is judged at 20%"
    assert not await _read(hass, coord, unknown, unk, 24), "clears above 20 plus 3"


async def test_a_coin_cell_is_low_at_its_resting_voltage(hass: HomeAssistant):
    """An Aqara sensor on Zigbee2MQTT reads 33% at 2.9 V: low by its voltage."""
    coin, cr = await _cell(hass, "door_aqara")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(coin.id, "CR1632", 1)
    record = coord.data["devices"][coin.id]

    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.95
    assert not await _read(hass, coord, coin, cr, 66)
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.9
    assert await _read(hass, coord, coin, cr, 33), "2.9 V resting is low"
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.93
    assert await _read(hass, coord, coin, cr, 53), "not cleared by 30 mV"
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.96
    assert not await _read(hass, coord, coin, cr, 73), "clears above 2.95 V"


async def test_a_sag_today_is_not_the_resting_voltage(hass: HomeAssistant):
    """The first reading after midnight caught in a transmit's sag: the
    last day's high still stands for its rest."""
    coin, cr = await _cell(hass, "motion")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(coin.id, "CR2450", 1)
    record = coord.data["devices"][coin.id]
    record[DEV_BATTERY_DAY_RANGES] = [["2026-11-20", 60.0, 66.0, 2.93, 2.97]]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.86
    assert not await _read(hass, coord, coin, cr, 60)


async def test_two_coin_cells_or_an_aa_lithium_have_no_voltage_line(hass: HomeAssistant):
    pair, two = await _cell(hass, "remote")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(pair.id, "CR2032", 2)
    coord.data["devices"][pair.id][DEV_BATTERY_VOLTS_TODAY_HIGH] = 5.6
    assert not await _read(hass, coord, pair, two, 60)


async def test_an_upgraded_house_is_told_once(hass: HomeAssistant, hass_storage):
    """The morning after the upgrade, the Daily Brief says the thresholds
    changed, as a breaking change; a second start says nothing more."""
    from custom_components.device_sentinel.const import STORAGE_KEY

    hass_storage[STORAGE_KEY] = {
        "version": 1, "minor_version": 1, "key": STORAGE_KEY,
        "data": {DATA_LAST_VERSION: "0.29.8", "devices": {"x": {}}},
    }
    coord = await setup_coordinator(hass)
    told = [row for row in coord.data[DATA_SYSTEM_EVENTS] if row.get(SYS_KIND) == SYS_SETTINGS_CHANGED]
    assert [row[SYS_DETAIL] for row in told] == [SETTINGS_BATTERY_BY_TYPE]
    sentence = coord._system_event_sentence_plain(told[0])
    assert sentence == (
        "Breaking change: alkaline batteries, and lithium and rechargeable batteries, "
        "now have their own low thresholds, 10% and 20% respectively. Changes can be "
        "made in Settings, Low Battery."
    )
    assert coord._battery_types_notice is False


async def test_a_new_install_is_not_told(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert not [row for row in coord.data[DATA_SYSTEM_EVENTS] if row.get(SYS_KIND) == SYS_SETTINGS_CHANGED]
