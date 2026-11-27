# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_coin_cell_cold_voltage.py, Version: 0.30.8 (2026-11-26)

"""A coin cell's voltage judged as it would read at 20 °C when it is cold (rule BAT-03).

A CR2032 outdoors loses about 5.5 mV a degree and gets it back when it
warms. A tester's Mopeka grill sensor read 2.844 V at -2 °C with a healthy
cell, below the 2.9 V line, and was called low and cleared again with each
cold night. Below 10 °C, with the device's own temperature beside the
reading, the voltage is corrected before it is judged; the device page
shows the reading and the corrected value. Without a temperature, or at
10 °C and warmer, the voltage is judged as read.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_EVIDENCE,
    DEV_BATTERY_LOW,
    DEV_BATTERY_TEMP_AT_VOLTS_HIGH,
    DEV_BATTERY_VOLTS_TODAY_HIGH,
)
from custom_components.device_sentinel.detect_battery import corrected_volts, note_battery_volts
from custom_components.device_sentinel.power_source import POWER_OTHER, pencil_cell

from .helpers import registry_settled, setup_coordinator


def test_the_correction_applies_only_when_cold():
    assert corrected_volts(2.844, -2.0) == (2.965, -2.0)
    assert corrected_volts(2.812, -9.0) == (2.971, -9.0)
    assert corrected_volts(2.938, 10.0) == (2.938, None), "10 °C and warmer is read as it is"
    assert corrected_volts(2.938, 9.9)[1] == 9.9
    for odd in (None, "x", True, float("nan"), float("inf"), -150.0, 200.0):
        assert corrected_volts(2.85, odd) == (2.85, None)


def test_a_repeat_reading_gives_the_days_high_its_temperature():
    """A day begun before a temperature was read gets one the next time
    the device is heard at the same voltage; a temperature kept is kept."""
    record = {}
    note_battery_volts(record, 2.844, None)
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] is None
    note_battery_volts(record, 2.844, -2.0)
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] == -2.0
    note_battery_volts(record, 2.844, 5.0)
    assert record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] == -2.0


def test_aa_and_aaa_cells_are_known_by_their_size():
    for name in ("AA", "AAA", "aaa", "LR6", "LR03", "AA Lithium", "AAA Lithium", "AAA alkaline"):
        assert pencil_cell(name), name
    for name in ("AAAA", "CR2032", "C", "D", "AA Rechargeable", "AAA NiMH", "", None, 3):
        assert not pencil_cell(name), name


async def _grill(hass: HomeAssistant):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "grill")}, name="Grill Tank",
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", "grill_battery", device_id=device.id, config_entry=source,
        original_device_class="battery", suggested_object_id="grill_battery",
    ).entity_id
    hass.states.async_set(entity, "99", {"device_class": "battery", "unit_of_measurement": "%"})
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(device.id, "CR2032", 1)
    return coord, device, entity


async def _read(hass, coord, device, entity, level):
    hass.states.async_set(entity, str(level), {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return bool(coord.data["devices"][device.id].get(DEV_BATTERY_LOW))


async def test_a_healthy_cell_on_a_frozen_day_is_not_low(hass: HomeAssistant):
    coord, device, entity = await _grill(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.844
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = -2.0
    assert not await _read(hass, coord, device, entity, 100)
    assert not await _read(hass, coord, device, entity, 99), "the 99/100 steps no longer call it low"
    view = coord.resting_volts_view(device.id, record)
    assert view == {"volts": 2.844, "corrected": 2.965, "celsius": -2.0, "judged": True}
    page = coord._page_battery(record, device.id)
    assert page["resting"]["corrected"] == 2.965


async def test_without_a_temperature_the_reading_is_judged_as_it_is(hass: HomeAssistant):
    coord, device, entity = await _grill(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.844
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = None
    assert await _read(hass, coord, device, entity, 100)
    assert coord.resting_volts_view(device.id, record)["celsius"] is None


async def test_a_cell_really_running_down_is_still_low_in_the_cold(hass: HomeAssistant):
    """2.70 V at -5 °C is 2.84 V at 20 °C: below the line, low."""
    coord, device, entity = await _grill(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.70
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = -5.0
    assert await _read(hass, coord, device, entity, 80)


async def test_the_last_days_high_uses_its_own_temperature(hass: HomeAssistant):
    """Today has only a cold sag; yesterday's high, at 0 °C, corrects to
    2.985 V and stands for the rest."""
    coord, device, entity = await _grill(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAY_RANGES] = [["2026-11-25", 99.0, 100.0, 2.80, 2.875]]
    record[DEV_BATTERY_EVIDENCE] = [["2026-11-25", 2.875, 0.0, 100, -3.0, 1.0, -3.0, 0.0]]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.78
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = -9.0
    assert not await _read(hass, coord, device, entity, 99)
    assert coord.resting_volts_view(device.id, record) == {"volts": 2.875, "corrected": 2.985, "celsius": 0.0, "judged": True}
    # A four-column evidence row has no temperature with it.
    record[DEV_BATTERY_EVIDENCE] = [["2026-11-25", 2.875, 0.0, 100]]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = None
    assert coord.resting_volts_view(device.id, record) == {"volts": 2.875, "corrected": 2.875, "celsius": None, "judged": True}


async def test_an_aaa_pack_shows_its_corrected_voltage_and_is_not_judged_by_it(hass: HomeAssistant):
    """Three AAA cells at -10 °C: 3 mV a degree a cell, 270 mV in all. The
    corrected value is shown, and the low line is still the percentage."""
    coord, device, entity = await _grill(hass)
    coord.page_set_power(device.id, POWER_OTHER, 3, other="AAA Lithium", wired=False)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 4.2
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = -10.0
    assert coord.resting_volts_view(device.id, record) == {
        "volts": 4.2, "corrected": 4.47, "celsius": -10.0, "judged": False,
    }
    assert coord.resting_volts(device.id, record) is None
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 1.0
    assert not await _read(hass, coord, device, entity, 98), "a low voltage on AAA cells calls nothing"


async def test_aa_cells_with_no_count_or_another_battery_are_not_corrected(hass: HomeAssistant):
    coord, device, entity = await _grill(hass)
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 2.8
    record[DEV_BATTERY_TEMP_AT_VOLTS_HIGH] = -10.0
    real = coord.power_of
    coord.power_of = lambda _id: {"kind": "battery", "type": "AA", "quantity": None}
    assert coord.volts_per_degree(device.id) is None, "a library row with no count"
    assert coord.resting_volts_view(device.id, record) is None
    coord.power_of = real
    coord.page_set_power(device.id, "AA", 2)
    assert coord.volts_per_degree(device.id) == 0.006
    coord.page_set_power(device.id, "Rechargeable", 2)
    assert coord.resting_volts_view(device.id, record) is None
