# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_coin_cell_coarse_volts.py, Version: 0.30.12 (2026-11-28)

"""A coin cell reported in tenths of a volt falls a step lower (rule BAT-03).

Most Zigbee devices report their voltage in tenths, so 2.9 stands for 2.90
to 2.99 V and a healthy cell sits on the 2.9 V line. A house's four-button
switch with a CR2430 read 2.9 V and 94% and was listed low; a thermometer
with a CR2032 read 2.6 V and 59%, a cell near its end. A device heard only
in whole tenths, today and on its last three kept days since its last
firmware update, is judged at 2.8 V. One that reports millivolts is judged
just under 2.9 V. A voltage under the line is voltage falling, not low; a
low cell under it says both, "10%, 2.6 V".
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_LOW,
    DEV_BATTERY_VOLTS_FALLING_SINCE,
    DEV_BATTERY_VOLTS_TODAY_HIGH,
    DEV_BATTERY_VOLTS_TODAY_LOW,
    DEV_FIRMWARE_HISTORY,
)
from custom_components.device_sentinel.detect_battery import coin_low_volts, volts_coarse, volts_text

from .helpers import registry_settled, setup_coordinator


def test_only_whole_tenths_make_a_reporter_coarse():
    assert not volts_coarse({}), "nothing heard is not coarse"
    assert volts_coarse({DEV_BATTERY_VOLTS_TODAY_LOW: 2.9, DEV_BATTERY_VOLTS_TODAY_HIGH: 2.9})
    assert volts_coarse({DEV_BATTERY_VOLTS_TODAY_LOW: 3.0, DEV_BATTERY_VOLTS_TODAY_HIGH: 3.0})
    assert not volts_coarse({DEV_BATTERY_VOLTS_TODAY_LOW: 3.005, DEV_BATTERY_VOLTS_TODAY_HIGH: 3.015})
    rows = [["2026-11-25", 90, 94, 2.9, 3.0], ["2026-11-26", 90, 94, 2.9, 2.9]]
    assert volts_coarse({DEV_BATTERY_DAY_RANGES: rows, DEV_BATTERY_VOLTS_TODAY_HIGH: 2.9})
    rows.append(["2026-11-27", 90, 94, 2.965, 2.97])
    assert not volts_coarse({DEV_BATTERY_DAY_RANGES: rows}), "one millivolt reading on any kept day"
    assert coin_low_volts({DEV_BATTERY_VOLTS_TODAY_HIGH: 2.9}) == 2.8
    assert coin_low_volts({DEV_BATTERY_VOLTS_TODAY_HIGH: 2.905}) == 2.899
    assert coin_low_volts({}) == 2.899


def test_a_stray_millivolt_reading_ages_out():
    """Only today and the last three kept days decide."""
    rows = [
        ["2026-11-20", 90, 94, 2.965, 2.97],
        ["2026-11-24", 90, 94, 2.9, 2.9],
        ["2026-11-25", 90, 94, 2.9, 3.0],
        ["2026-11-26", 90, 94, 2.9, 2.9],
    ]
    assert volts_coarse({DEV_BATTERY_DAY_RANGES: rows, DEV_BATTERY_VOLTS_TODAY_HIGH: 2.9})


def _at(day: int) -> float:
    return datetime(2026, 11, day, 12, 0, tzinfo=dt_util.get_default_time_zone()).timestamp()


def test_readings_before_a_firmware_update_are_not_read():
    """A device that reported millivolts and, after an update, tenths is
    coarse at once; one that changed the other way is fine at once."""
    before = [["2026-11-24", 90, 94, 2.965, 2.97], ["2026-11-25", 90, 94, 2.955, 2.96]]
    after = [["2026-11-26", 90, 94, 2.9, 2.9]]
    history = [["1.0", _at(1)], ["2.0", _at(25)]]
    record = {
        DEV_BATTERY_DAY_RANGES: before + after,
        DEV_BATTERY_VOLTS_TODAY_HIGH: 2.9,
        DEV_FIRMWARE_HISTORY: history,
    }
    assert volts_coarse(record)
    record[DEV_FIRMWARE_HISTORY] = history[:1]
    assert not volts_coarse(record), "no update: the millivolt days still count"
    record = {
        DEV_BATTERY_DAY_RANGES: [["2026-11-24", 90, 94, 2.9, 2.9], ["2026-11-26", 90, 94, 2.965, 2.97]],
        DEV_FIRMWARE_HISTORY: history,
    }
    assert not volts_coarse(record)


def test_a_voltage_is_written_as_the_device_reports_it():
    assert volts_text(2.6, True) == "2.6"
    assert volts_text(2.965, False) == "2.965"
    assert volts_text(3.0, False) == "3.00"


async def _cell(hass: HomeAssistant, cell: str = "CR2430"):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "switch")}, name="Switch Four Buttons",
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", "switch_battery", device_id=device.id, config_entry=source,
        original_device_class="battery", suggested_object_id="switch_battery",
    ).entity_id
    hass.states.async_set(entity, "100", {"device_class": "battery", "unit_of_measurement": "%"})
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(device.id, cell, 1)
    return coord, device, entity


async def _read(hass, coord, device, entity, level, volts):
    """Low by percentage, and falling by voltage, after one reading."""
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_LOW] = volts
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = volts
    hass.states.async_set(entity, str(level), {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return bool(record.get(DEV_BATTERY_LOW)), record.get(DEV_BATTERY_VOLTS_FALLING_SINCE) is not None


async def test_a_healthy_cell_reported_in_tenths_is_not_falling(hass: HomeAssistant):
    """The four-button switch: 2.9 V and 94%."""
    coord, device, entity = await _cell(hass)
    assert await _read(hass, coord, device, entity, 94, 2.9) == (False, False)
    assert coord.battery_level_words(device.id, 94) == "94%"


async def test_a_cell_reported_in_tenths_falls_at_two_point_eight(hass: HomeAssistant):
    coord, device, entity = await _cell(hass)
    assert await _read(hass, coord, device, entity, 81, 2.8) == (False, True)
    assert await _read(hass, coord, device, entity, 90, 2.9) == (False, False), "back above the line clears it"


async def test_a_cell_near_its_end_says_its_voltage(hass: HomeAssistant):
    """The thermometer: 2.6 V and 59%, listed as voltage falling, not low."""
    coord, device, entity = await _cell(hass, "CR2032")
    assert await _read(hass, coord, device, entity, 59, 2.6) == (False, True)
    row = next(row for row in coord.battery_falling_list if row["device_id"] == device.id)
    assert row["volts"] is True and row["left"] is None
    assert row["words"] == "voltage is falling, 2.6 V (new 3.0, spent 2.0)"
    assert not any(row["device_id"] == device.id for row in coord.battery_low_list)
    page = coord._page_battery(coord.data["devices"][device.id], device.id)
    assert page["volts_coarse"] is True


async def test_a_millivolt_reporter_falls_just_under_two_point_nine(hass: HomeAssistant):
    coord, device, entity = await _cell(hass, "CR2032")
    assert await _read(hass, coord, device, entity, 90, 2.905) == (False, False), "2.905 V is still 2.9 V"
    assert await _read(hass, coord, device, entity, 89, 2.895) == (False, True)
    assert await _read(hass, coord, device, entity, 95, 3.005) == (False, False)
    page = coord._page_battery(coord.data["devices"][device.id], device.id)
    assert page["volts_coarse"] is False


async def test_a_low_cell_says_its_percentage_and_its_voltage(hass: HomeAssistant):
    """Low wins: one line, "10%, 2.6 V", and never falling as well."""
    coord, device, entity = await _cell(hass, "CR2032")
    assert await _read(hass, coord, device, entity, 10, 2.6) == (True, False)
    assert coord.battery_level_words(device.id, 10) == "10%, 2.6 V"
    row = next(row for row in coord.battery_low_list if row["device_id"] == device.id)
    assert row["words"] == "10%, 2.6 V", "the notification card reads these words"
    assert not any(row["device_id"] == device.id for row in coord.battery_falling_list)
