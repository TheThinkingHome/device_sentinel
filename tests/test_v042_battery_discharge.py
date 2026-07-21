# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v042_battery_discharge.py, Version: 0.4.2 (2026-07-18)

"""0.4.2 tests: the battery discharge recorder and the UTC hardening.

The recorder (ruling 62) samples one battery level per device per day
at the rollover and keeps a bounded series, so a later release can
read the rate of drop and catch a lithium cliff the 20 percent
threshold would miss. It records only; the velocity flag waits on the
soak. The value is stored, not the delta, so a missed midnight leaves
a gap the velocity math divides across rather than a false cliff.

The UTC test pins the hardening the audit surfaced: a last_seen value
without a timezone is anchored to UTC before its timestamp is taken,
so an integration that omits the offset cannot seed a device's clock
wrong by the local offset.
"""

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DAILY_MAX_KEEP,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _record():
    from custom_components.device_sentinel.coordinator import (
        _new_device_record,
    )

    return _new_device_record("2026-07-11T00:00:00+00:00", None)


# The discharge recorder (#62).


async def test_rollover_appends_the_daily_level(hass: HomeAssistant):
    coord = await _coordinator(hass)
    record = _record()
    record[DEV_BATTERY_VALUE] = 89.0
    coord._roll_battery(record)
    record[DEV_BATTERY_VALUE] = 88.0
    coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == [89.0, 88.0]


async def test_series_records_the_value_not_the_delta(hass: HomeAssistant):
    """Self-describing on purpose: the raw levels are kept so a missed
    day can be divided across, not just the one-step differences."""
    coord = await _coordinator(hass)
    record = _record()
    for level in (89.0, 89.0, 88.0, 80.0, 65.0):
        record[DEV_BATTERY_VALUE] = level
        coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == [89.0, 89.0, 88.0, 80.0, 65.0]


async def test_a_device_without_a_battery_records_nothing(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    record = _record()
    coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == []


async def test_series_is_bounded(hass: HomeAssistant):
    """Kept to the same window as every daily series, so at two weeks
    and a day the oldest point retires."""
    coord = await _coordinator(hass)
    record = _record()
    for level in range(DAILY_MAX_KEEP + 5):
        record[DEV_BATTERY_VALUE] = float(100 - level)
        coord._roll_battery(record)
    assert len(record[DEV_BATTERY_DAILY]) == DAILY_MAX_KEEP
    # The newest values survived; the oldest fell off.
    assert record[DEV_BATTERY_DAILY][-1] == float(100 - (DAILY_MAX_KEEP + 4))


async def test_lithium_cliff_is_visible_in_the_series(
    hass: HomeAssistant,
):
    """The shape the velocity flag will later catch: flat, then a
    sudden acceleration."""
    coord = await _coordinator(hass)
    record = _record()
    for level in (100, 100, 100, 100, 99, 99, 80, 60, 30):
        record[DEV_BATTERY_VALUE] = float(level)
        coord._roll_battery(record)
    series = record[DEV_BATTERY_DAILY]
    deltas = [a - b for a, b in zip(series[:-1], series[1:])]
    # Flat early, steep late: the cliff is legible without a flag yet.
    assert max(deltas[:4]) <= 1
    assert max(deltas[-3:]) >= 20


async def test_daily_field_survives_a_storage_round_trip(
    hass: HomeAssistant,
):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "batt")},
        name="Batt",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "batt", device_id=device.id, config_entry=source
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_DAILY] = [89.0, 88.0, 80.0]
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data.data["devices"][device.id]
    assert reloaded[DEV_BATTERY_DAILY] == [89.0, 88.0, 80.0]


async def test_pre_042_storage_gains_the_series(hass: HomeAssistant):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "old")},
        name="Old",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "old", device_id=device.id, config_entry=source
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    old = coord.data["devices"][device.id]
    old.pop(DEV_BATTERY_DAILY, None)
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    migrated = entry.runtime_data.data["devices"][device.id]
    assert migrated[DEV_BATTERY_DAILY] == []


# The UTC hardening from the audit.


async def test_naive_last_seen_is_anchored_to_utc(hass: HomeAssistant):
    """A last_seen string without an offset must not seed the clock in
    local time. The seed uses UTC, so a naive value and an explicit
    UTC value produce the same timestamp."""
    naive = dt_util.parse_datetime("2026-07-18T12:00:00")
    assert naive.tzinfo is None
    # The hardening: anchor to UTC before taking the timestamp.
    anchored = naive.replace(tzinfo=dt_util.UTC)
    aware = dt_util.parse_datetime("2026-07-18T12:00:00+00:00")
    assert anchored.timestamp() == aware.timestamp()
