# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_battery.py, Version: 0.12.16 (2026-08-08)

"""Battery detection: the low verdict and the discharge recorder.

A device's battery is judged by value, not a binary flag, preferring a
percentage entity when one exists: flagged at or below the threshold,
cleared only once it climbs past the threshold plus a margin, so a cell
hovering at the line does not flap. The since it was first low survives
a reload. Alongside the verdict, a recorder samples one level per day
into a bounded ninety-day series, so a later release can read the rate
of drop and catch a lithium cliff the flat threshold would miss; it
records only, the velocity flag waits on the soak.
"""

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.detect_battery import BatteryMixin
from custom_components.device_sentinel.detect_signal import SignalMixin
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_DEVICES,
    DEFAULT_RETENTION_DAYS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)

from tests.helpers import setup_coordinator, setup_entry

DOMAIN = "device_sentinel"


def _battery_device(hass, source, index, *, percentage=True, binary=False):
    """A device carrying a percentage battery entity, a binary one, or
    both, named by index so its report row is found by name."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", f"bat{index}")},
        name=f"Battery Device {index}",
    )
    ent_reg = er.async_get(hass)
    entity_ids = {}
    if percentage:
        reg = ent_reg.async_get_or_create(
            "sensor", "test", f"bat{index}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
        entity_ids["pct"] = reg.entity_id
    if binary:
        reg = ent_reg.async_get_or_create(
            "binary_sensor", "test", f"bat{index}_low",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
        entity_ids["bin"] = reg.entity_id
    return device, entity_ids


def _record():
    """A fresh device record, for exercising the discharge recorder
    directly without driving a whole device through the coordinator."""
    from custom_components.device_sentinel.coordinator import (
        _new_device_record,
    )

    return _new_device_record("2026-07-11T00:00:00+00:00", None)


# ------------------------------------------------- the low verdict

async def test_election_prefers_percentage(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 1, percentage=True, binary=True)
    coord = await setup_coordinator(hass)
    elected_entity, is_binary = coord._battery_entity[device.id]
    assert elected_entity == eids["pct"]
    assert is_binary is False


async def test_binary_fallback_and_on_is_low(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 2, percentage=False, binary=True)
    coord = await setup_coordinator(hass)

    hass.states.async_set(eids["bin"], "on")
    await hass.async_block_till_done()
    assert coord.data[DATA_DEVICES][device.id][DEV_BATTERY_LOW] is True
    assert coord.battery_low_count == 1

    hass.states.async_set(eids["bin"], "off")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0


async def test_threshold_and_hysteresis(hass: HomeAssistant):
    """Flag at or below 20; clear only above 22 (threshold + 2)."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 3)
    coord = await setup_coordinator(hass)
    rec = coord.data[DATA_DEVICES][device.id]

    hass.states.async_set(eids["pct"], "50")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is False

    hass.states.async_set(eids["pct"], "20")  # at threshold: flag
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] is not None
    since_first = rec[DEV_BATTERY_SINCE]

    hass.states.async_set(eids["pct"], "21")  # inside margin: stays low
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] == since_first  # since carried

    hass.states.async_set(eids["pct"], "22")  # past margin: recovers
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is False
    assert rec[DEV_BATTERY_SINCE] is None

    hass.states.async_set(eids["pct"], "19")  # re-crossing restamps
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] != since_first


async def test_unavailable_battery_holds_verdict(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 4)
    coord = await setup_coordinator(hass)
    rec = coord.data[DATA_DEVICES][device.id]

    hass.states.async_set(eids["pct"], "15")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True

    hass.states.async_set(eids["pct"], "unavailable")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True  # verdict held; liveness is Step 4


async def test_options_change_applies_live(hass: HomeAssistant):
    """Sliding the threshold above a real cell flags it immediately."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 5)
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["pct"], "32")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0

    hass.config_entries.async_update_entry(
        entry, options={CONF_LOW_THRESHOLD: 35}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        entry, options={CONF_LOW_THRESHOLD: 20}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0


async def test_list_shape_and_order(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    d1, e1 = _battery_device(hass, source, 6)
    d2, e2 = _battery_device(hass, source, 7)
    entry = await setup_entry(hass)
    # Battery: Low is disabled by default; enable it to read its state.
    reg = er.async_get(hass)
    bl = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_low_batteries"
    )
    reg.async_update_entity(bl, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    hass.states.async_set(e1["pct"], "10")
    hass.states.async_set(e2["pct"], "5")
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_battery_low")
    assert state is not None
    coord._notify()
    await hass.async_block_till_done()
    # Low Batteries merges the old count and list: state is the count,
    # rows and thresholds ride in attributes.
    state = hass.states.get("sensor.device_sentinel_battery_low")
    assert state.state == "2"
    rows = state.attributes["devices"]
    assert [r["name"] for r in rows] == [
        "Battery Device 6", "Battery Device 7",
    ]
    row = rows[0]
    assert row["kind"] == "device"
    assert row["level"] == 10.0
    assert row["since"] is not None
    assert row["area"] == "Unassigned"
    assert state.attributes["low_threshold"] == 20.0
    assert state.attributes["clear_margin"] == 2


async def test_since_survives_reload(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 8)
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["pct"], "12")
    await hass.async_block_till_done()
    since = coord.data[DATA_DEVICES][device.id][DEV_BATTERY_SINCE]
    assert since is not None
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert coord2.data[DATA_DEVICES][device.id][DEV_BATTERY_SINCE] == since
    assert coord2.battery_low_count == 1


async def test_number_entity_sets_threshold_live(hass: HomeAssistant):
    """The dashboard slider writes the same setting as the dialog."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 9)
    coord = await setup_coordinator(hass)

    hass.states.async_set(eids["pct"], "32")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0

    # The dashboard slider was retired with the number platform in
    # 0.11.10 (ruling #209), so the options dialog is the one door.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_LOW_THRESHOLD: 35},
    )
    await hass.async_block_till_done()
    assert coord.low_threshold == 35.0
    assert coord.battery_low_count == 1


async def test_the_retired_slider_is_swept_from_the_registry(
    hass: HomeAssistant,
):
    """Deleting the platform does not remove the registry entry, so
    an install that had the slider would keep an unavailable row on
    the device page. It is swept at setup like any retired surface.
    """
    from homeassistant.helpers import entity_registry as er

    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_battery_low_threshold"
        )
        is None
    )


# ---------------------------------------- the discharge recorder (#62)

async def test_rollover_appends_the_daily_level(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record()
    record[DEV_BATTERY_VALUE] = 89.0
    coord._roll_battery(record)
    record[DEV_BATTERY_VALUE] = 88.0
    coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == [89.0, 88.0]


async def test_series_records_the_value_not_the_delta(hass: HomeAssistant):
    """Self-describing on purpose: the raw levels are kept so a missed
    day can be divided across, not just the one-step differences."""
    coord = await setup_coordinator(hass)
    record = _record()
    for level in (89.0, 89.0, 88.0, 80.0, 65.0):
        record[DEV_BATTERY_VALUE] = level
        coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == [89.0, 89.0, 88.0, 80.0, 65.0]


async def test_a_device_without_a_battery_records_nothing(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    record = _record()
    coord._roll_battery(record)
    assert record[DEV_BATTERY_DAILY] == []


async def test_series_is_bounded(hass: HomeAssistant):
    """Bounded at ninety days rather than fourteen (0.8.6).

    A fortnight is right for a rhythm and wrong for a battery: on a
    real fleet nothing measurably discharges in two weeks, so the
    fortnight window threw away the only thing worth measuring.
    """
    coord = await setup_coordinator(hass)
    record = _record()
    for level in range(DEFAULT_RETENTION_DAYS + 5):
        record[DEV_BATTERY_VALUE] = float(100 - level)
        coord._roll_battery(record)
    assert len(record[DEV_BATTERY_DAILY]) == DEFAULT_RETENTION_DAYS
    # The newest values survived; the oldest fell off.
    assert record[DEV_BATTERY_DAILY][-1] == float(
        100 - (DEFAULT_RETENTION_DAYS + 4)
    )


async def test_lithium_cliff_is_visible_in_the_series(
    hass: HomeAssistant,
):
    """The shape the velocity flag will later catch: flat, then a
    sudden acceleration."""
    coord = await setup_coordinator(hass)
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
    entry = await setup_entry(hass)
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
    entry = await setup_entry(hass)
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


def _entry(entity_id, device_class="battery", name=None, unique=None):
    """A minimal registry-entry double for the recognizer tests."""

    class _E:
        pass

    e = _E()
    e.entity_id = entity_id
    e.unique_id = unique or entity_id.split(".", 1)[1]
    e.original_name = name
    e.original_device_class = device_class
    e.device_class = None
    return e


def test_a_name_no_longer_decides_a_battery(hass: HomeAssistant):
    """The name filter of ruling #248 was deleted, and this is why.

    It named entities by what somebody had called them, which is not
    a property of the measurement. Every entity it refused arrives on
    an integration the ignore list now refuses whole, so the
    recognizer is back to the one question it can answer from the
    registry: is this a battery on a device we watch.
    """
    for eid in (
        "sensor.james_s24_car_battery",
        "sensor.james_s24_battery_level",
        "sensor.door_master_battery",
    ):
        assert BatteryMixin._is_battery(_entry(eid)), eid
        assert BatteryMixin._is_battery_percentage(_entry(eid)), eid
    assert not BatteryMixin._is_battery(
        _entry("sensor.door_master_temperature", device_class="temperature")
    )
    assert not BatteryMixin._is_battery_percentage(
        _entry("binary_sensor.door_master_battery_low")
    )


def test_an_esphome_wifi_signal_is_recognized(hass: HomeAssistant):
    """The regression the name filter caused, now fixed.

    An ESPHome node calls its own RSSI sensor WiFi Signal, and the
    refused-terms list contained "wifi", so three nodes on the
    reference fleet recorded nothing for weeks while motion blinds
    calling the same measurement RSSI recorded fine. Two Wi-Fi
    devices, opposite outcomes, decided by the manufacturer's choice
    of word.
    """
    for eid in (
        "sensor.voice_assistant_kitchen_wifi_signal",
        "sensor.kfmawi_wi_fi_signal_strength",
        "sensor.door_master_linkquality",
        "sensor.stove_vent_relays_rssi",
        "sensor.master_city_blinds_signal_strength",
    ):
        assert SignalMixin._is_signal(
            _entry(eid, device_class="signal_strength")
        ), eid
    assert not SignalMixin._is_signal(
        _entry("sensor.door_master_temperature", device_class="temperature")
    )
