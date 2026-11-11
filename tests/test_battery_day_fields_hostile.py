# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_day_fields_hostile.py, Version: 0.28.12 (2026-11-11)

"""The battery day fields under hostile input (rule BAT-06).

battery_day_levels and battery_day_counts are kept from every moment the
battery is heard (detect_battery.note_battery_sample), and at midnight
the day's range joins battery_range_lows and battery_range_highs;
battery_pending_high is held with a suspected replacement.

A device whose battery moves from a percentage entity to a binary low
flag in the middle of a day gives readings that are not levels; noting
them must never fail, and a restart the same day must still start.
Hostile states and hand-edited fields never crash a reading or the
midnight roll.

Every test asserts the safe behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import math

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAY_COUNTS,
    DEV_BATTERY_DAY_LEVELS,
    DEV_BATTERY_PENDING_HIGH,
    DEV_BATTERY_RANGE_HIGHS,
    DEV_BATTERY_RANGE_LOWS,
)

LEVEL_LISTS = (DEV_BATTERY_DAY_LEVELS, DEV_BATTERY_RANGE_LOWS, DEV_BATTERY_RANGE_HIGHS)
DAY_FIELDS = (*LEVEL_LISTS, DEV_BATTERY_DAY_COUNTS, DEV_BATTERY_PENDING_HIGH)


def _sound(record) -> bool:
    for field in LEVEL_LISTS:
        held = record[field]
        if not isinstance(held, list) or not all(
            isinstance(v, float) and math.isfinite(v) and 0.0 <= v <= 100.0 for v in held
        ):
            return False
    pending = record[DEV_BATTERY_PENDING_HIGH]
    return pending is None or (math.isfinite(pending) and 0.0 <= pending <= 100.0)


def _battery_device(hass: HomeAssistant, uid: str, percent: bool, binary: bool):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name="Door Sensor",
    )
    ent_reg = er.async_get(hass)
    plain = ent_reg.async_get_or_create(
        "sensor", "test", f"{uid}_plain", device_id=device.id, config_entry=source,
    )
    ids = {"plain": plain.entity_id}
    if percent:
        ids["pct"] = ent_reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct", device_id=device.id, config_entry=source,
            original_device_class="battery",
        ).entity_id
    if binary:
        ids["low"] = ent_reg.async_get_or_create(
            "binary_sensor", "test", f"{uid}_low", device_id=device.id, config_entry=source,
            original_device_class="battery",
        ).entity_id
    return device, ids


async def test_a_battery_that_turns_binary_mid_day_never_raises(hass: HomeAssistant):
    """Percentage readings in the morning, then the percentage entity is
    switched off and the binary low flag is elected: nothing raises."""
    from tests.helpers import registry_settled, setup_entry

    device, ids = _battery_device(hass, "bat_flip", percent=True, binary=True)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(ids["plain"], "1")
    hass.states.async_set(ids["pct"], "40")
    await hass.async_block_till_done()
    coord._evaluate_battery(device.id)
    record = coord.data[DATA_DEVICES][device.id]
    assert 40.0 in record[DEV_BATTERY_DAY_LEVELS]  # the premise
    er.async_get(hass).async_update_entity(
        ids["pct"], disabled_by=er.RegistryEntryDisabler.USER
    )
    await hass.async_block_till_done()
    await registry_settled(hass)
    coord._rebuild_registry_view()
    assert coord._battery_entity[device.id] == (ids["low"], True)  # the premise
    hass.states.async_set(ids["low"], "on")
    await hass.async_block_till_done()
    raised = None
    try:
        coord._evaluate_battery(device.id)
    except Exception as err:  # noqa: BLE001
        raised = err
    assert raised is None, repr(raised)


async def test_a_restart_the_same_day_still_starts(hass: HomeAssistant):
    """The day fields carried through a reload beside a binary battery:
    _evaluate_all_batteries runs inside async_setup, and the entry loads."""
    from tests.helpers import setup_entry

    device, ids = _battery_device(hass, "bat_restart", percent=False, binary=True)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    # What the percentage entity left this morning, before it was
    # switched off.
    record[DEV_BATTERY_DAY_LEVELS] = [40.0, 41.0]
    record[DEV_BATTERY_DAY_COUNTS] = [2, 1]
    coord._dirty = True
    await coord._save_now()
    hass.states.async_set(ids["low"], "off")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_hostile_battery_states_never_poison_the_day_fields(hass: HomeAssistant):
    """Every state a battery entity can carry """
    from tests.helpers import setup_entry

    device, ids = _battery_device(hass, "bat_hostile", percent=True, binary=False)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    for value in (
        "nan", "NaN", "inf", "-inf", "Infinity", "1e400", "-1", "-0.0", "100.0000001",
        "1e308", "0x10", " 55 ", "5_0", "", "unknown", "unavailable", "None", "50",
    ):
        hass.states.async_set(ids["pct"], value)
        await hass.async_block_till_done()
        coord._evaluate_battery(device.id)
        assert _sound(record), value
    coord._roll_battery(record, device.id)
    assert _sound(record)


async def test_hand_edited_day_fields_never_crash_and_are_named(hass: HomeAssistant):
    """A hand-edited record: each value is named by the storage check
    and none crashes the reading or the midnight roll."""
    from custom_components.device_sentinel.normalise import check_records
    from custom_components.device_sentinel.records import _new_device_record
    from tests.helpers import setup_coordinator

    coord = await setup_coordinator(hass)
    for bad in ("x", math.nan, math.inf, -5.0, 1e308, True, [1], {"a": 1}, 2**70, ["x"], [math.nan], [-5.0]):
        record = _new_device_record("2026-07-11T00:00:00+00:00", None)
        for field in DAY_FIELDS:
            record[field] = bad
        faults = {field for _, field, _ in check_records({"dev": record})}
        # A list of levels is a fault in the pending high; any other
        # value is a fault in every field.
        expected = {DEV_BATTERY_PENDING_HIGH} if bad == [1] else set(DAY_FIELDS)
        if isinstance(bad, list) and bad != [1]:
            expected = {*LEVEL_LISTS, DEV_BATTERY_PENDING_HIGH}
        assert expected <= faults, (bad, expected - faults)
        from custom_components.device_sentinel.detect_battery import note_battery_sample

        note_battery_sample(record, 50.0)
        record["battery_value"] = 50.0
        coord._roll_battery(record, "dev")
        coord._roll_battery(record, "dev")
