# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_raw_battery_change.py, Version: 0.28.12 (2026-11-11)

"""A raw-scale battery changed must not be halved twice, nor
detected as replaced again (rules BAT-02, BAT-06).

A device on Zigbee's raw 0-200 scale is marked raw and its readings
halved. A battery change clears the mark (BAT-02), and the new cell
proves its scale again on its second day over 110. The second proof
halves the stored history once more, though it was already in percent:
the new cell's days read 50 where the cell read 100, the old cell's
kept history reads half, and the next midnight sees 50 to 99 as a new
rise, so a second false replacement is detected, which clears the mark
again and repeats every few days.
"""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from tests.helpers import register_device, setup_entry


async def _raw_house(hass):
    device, (value, battery) = register_device(hass, "lux", name="LUX Outdoors", entity_count=2)
    er.async_get(hass).async_update_entity(battery, original_device_class="battery")
    entry = await setup_entry(hass)
    return entry.runtime_data, device, battery


async def _read(hass, coord, battery, reading):
    hass.states.async_set(battery, reading, {"unit_of_measurement": "%", "device_class": "battery"})
    await hass.async_block_till_done()
    coord._evaluate_all_batteries()


async def test_a_raw_device_after_a_battery_change_is_not_halved_twice(hass, freezer):
    freezer.move_to("2026-09-29 15:00:00+00:00")
    coord, device, battery = await _raw_house(hass)
    record = coord.data["devices"][device.id]
    # The old cell, in percent, on a device proved raw.
    record["battery_raw_scale"] = True
    record["battery_daily_value"] = [31.0, 30.0, 29.0]
    record["battery_value"] = 100.0  # the new cell, raw 200 halved
    coord._roll_battery(record, device.id)
    coord._roll_battery(record, device.id)
    stamp = record["battery_replaced_at"]
    assert stamp is not None, "the real change is detected"
    assert record["battery_raw_scale"] is False
    old_cell = list(record["battery_daily_previous"])
    assert old_cell == [31.0, 30.0, 29.0]

    # Day one after the change: the new cell reads raw, ignored.
    freezer.move_to("2026-09-30 15:00:00+00:00")
    await _read(hass, coord, battery, "199")
    coord._roll_battery(record, device.id)

    # Day two: the second reading over 110 proves the scale again.
    freezer.move_to("2026-10-01 15:00:00+00:00")
    await _read(hass, coord, battery, "198")
    assert record["battery_raw_scale"] is True
    coord._roll_battery(record, device.id)

    freezer.move_to("2026-10-02 15:00:00+00:00")
    await _read(hass, coord, battery, "197")
    coord._roll_battery(record, device.id)
    freezer.move_to("2026-10-03 15:00:00+00:00")
    await _read(hass, coord, battery, "196")
    coord._roll_battery(record, device.id)

    assert record["battery_replaced_at"] == stamp, (
        "a second battery change was detected that never happened"
    )
    assert record["battery_daily_previous"][-3:] == old_cell, (
        "the old cell's history, already in percent, was halved again"
    )
    assert all(v >= 90.0 for v in record["battery_daily_value"]), (
        f"the new cell's days were halved again: {record['battery_daily_value']}"
    )
