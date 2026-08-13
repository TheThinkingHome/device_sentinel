"""Tests for the three Data sensors (ruling #255).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_data_sensors.py, Version: 0.13.5 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

The sensors answer one question that previously needed a diagnostics
download and somebody to read it: how much complete history stands
behind each area of judgment. Complete is the whole difficulty, so
the tests concentrate there: a set that gained a series yesterday has
one day of complete history however deep its older members run, and
the count restarts even though nothing was deleted.
"""

from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    AREA_BATTERY,
    AREA_FREEZE,
    AREA_SIGNAL,
    DATA_DEVICES,
    DATA_STATE_LEARNED,
    DATA_STATE_TRACKING,
    DEV_BATTERY_DAILY,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    SERIES_BATTERY,
    SERIES_FREEZE,
    SERIES_SIGNAL,
)
from custom_components.device_sentinel.sensor import (
    DeviceSentinelDataBatterySensor,
    DeviceSentinelDataFreezeSensor,
    DeviceSentinelDataSignalSensor,
)

from .helpers import register_device, setup_coordinator


def _record_days(coord: Any, device_id: str, area: str, days: int) -> None:
    """Give one device that many folded days in an area.

    The depth is read from the series (ruling #258), so a test that
    wants a depth writes one, which is also what the fold does.
    """
    series = {
        AREA_FREEZE: SERIES_FREEZE,
        AREA_BATTERY: SERIES_BATTERY,
        AREA_SIGNAL: SERIES_SIGNAL,
    }[area]
    record = coord.data[DATA_DEVICES][device_id]
    for field in series:
        record[field] = [1.0] * days


async def test_a_fresh_install_reads_zero_of_seven(hass: HomeAssistant):
    """Nothing recorded, nothing claimed: all three start counting
    from zero toward their arming."""
    coord = await setup_coordinator(hass)
    for sensor_class in (
        DeviceSentinelDataFreezeSensor,
        DeviceSentinelDataBatterySensor,
        DeviceSentinelDataSignalSensor,
    ):
        sensor = sensor_class(coord)
        assert sensor.native_value == "0 of 7"
        assert sensor.extra_state_attributes["armed"] is False


async def test_the_three_phases_of_a_signal_sensor(hass: HomeAssistant):
    """Counting, then Armed and still counting, then Learned.

    Signal arms at seven days and its floor window fills at thirty
    (SIGNAL_DAYS_KEEP, widened by ruling #196), so the middle phase
    is real and long: lines and dwell are live while the floor is
    still maturing, and the state says so rather than implying the
    system is either blind or finished.
    """
    device, _ = register_device(hass, "ph1", "Phase Device")
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataSignalSensor(coord)

    _record_days(coord, device.id, AREA_SIGNAL, 4)
    assert sensor.native_value == "4 of 7"

    _record_days(coord, device.id, AREA_SIGNAL, 12)
    assert sensor.native_value == "Armed, 12 of 30"
    assert sensor.extra_state_attributes["target_days"] == 30

    _record_days(coord, device.id, AREA_SIGNAL, 30)
    assert sensor.native_value == DATA_STATE_LEARNED


async def test_freeze_matures_at_the_judgment_window(hass: HomeAssistant):
    """Freeze arms at seven and is Learned at fourteen, which is the
    rhythm window every freeze verdict reads (DAILY_MAX_KEEP), not
    the retention setting."""
    device, _ = register_device(hass, "ph2", "Phase Device")
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataFreezeSensor(coord)

    _record_days(coord, device.id, AREA_FREEZE, 9)
    assert sensor.native_value == "Armed, 9 of 14"

    _record_days(coord, device.id, AREA_FREEZE, 14)
    assert sensor.native_value == DATA_STATE_LEARNED


async def test_battery_is_two_phase_and_says_tracking(hass: HomeAssistant):
    """The battery slope reads a fixed seven days
    (BATTERY_SLOPE_DAYS) and has no second milestone, so inventing a
    middle phase to match the other two would be decoration."""
    device, _ = register_device(hass, "ph3", "Phase Device")
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataBatterySensor(coord)

    _record_days(coord, device.id, AREA_BATTERY, 3)
    assert sensor.native_value == "3 of 7"

    _record_days(coord, device.id, AREA_BATTERY, 7)
    assert sensor.native_value == DATA_STATE_TRACKING


async def test_a_changed_recording_set_restarts_the_count(
    hass: HomeAssistant,
):
    """The ruling's whole point, and the 0.12.19 case exactly.

    A device with eleven days of minima and one day of percentiles
    has one day of complete signal history, and the sensor says so.
    Nothing had to be told that the set changed: the new series is
    empty, so it is the shortest, so the count is its length.
    """
    device, _ = register_device(hass, "cs1", "Changed Set")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    for field in SERIES_SIGNAL:
        record[field] = [1.0] * 40

    assert DeviceSentinelDataSignalSensor(coord).native_value == (
        DATA_STATE_LEARNED
    )

    record[DEV_SIGNAL_DAILY_P5] = [1.0]
    record[DEV_SIGNAL_DAILY_P50] = [1.0]

    assert DeviceSentinelDataSignalSensor(coord).native_value == "1 of 7"


async def test_an_untouched_area_is_unaffected(hass: HomeAssistant):
    """A release that changes one area must not reset the others,
    which the series give for free: freeze and battery read their own
    lengths whatever happened to signal.
    """
    device, _ = register_device(hass, "cs2", "Other Areas")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * 20
    record[DEV_BATTERY_DAILY] = [90.0] * 20
    for field in SERIES_SIGNAL:
        record[field] = []

    assert DeviceSentinelDataFreezeSensor(coord).native_value == (
        DATA_STATE_LEARNED
    )
    assert DeviceSentinelDataBatterySensor(coord).native_value == (
        DATA_STATE_TRACKING
    )
    assert DeviceSentinelDataSignalSensor(coord).native_value == "0 of 7"


async def test_device_days_sums_the_fleet(hass: HomeAssistant):
    """The volume figure a person has otherwise had to read out of
    diagnostics: every device's series lengths in that area, added
    up."""
    coord = await setup_coordinator(hass)
    one, _ = register_device(hass, "dd1", "First")
    two, _ = register_device(hass, "dd2", "Second")
    records = coord.data[DATA_DEVICES]
    records[one.id][DEV_DAILY_MAX] = [1.0] * 14
    records[two.id][DEV_DAILY_MAX] = [1.0] * 9
    records[one.id][DEV_BATTERY_DAILY] = [90.0] * 30
    records[one.id][DEV_SIGNAL_DAILY_MIN] = [100.0] * 12
    records[one.id][DEV_SIGNAL_DAILY_P5] = [110.0] * 12

    freeze = DeviceSentinelDataFreezeSensor(coord).extra_state_attributes
    battery = DeviceSentinelDataBatterySensor(coord).extra_state_attributes
    signal = DeviceSentinelDataSignalSensor(coord).extra_state_attributes

    assert freeze["device_days"] == 23
    assert battery["device_days"] == 30
    assert signal["device_days"] == 24


async def test_the_count_cannot_exceed_retention(hass: HomeAssistant):
    """The fold trims each series to the retention setting, so a
    longer one cannot arise in practice; the cap is belt and braces
    against a record written by a version with a wider setting."""
    device, _ = register_device(hass, "ph4", "Deep Device")
    coord = await setup_coordinator(hass)
    _record_days(coord, device.id, AREA_SIGNAL, 400)
    attrs = DeviceSentinelDataSignalSensor(coord).extra_state_attributes

    assert attrs["complete_days"] == coord.retention_days


async def test_the_attributes_publish_the_set(hass: HomeAssistant):
    """A person seeing the count restart can read which series the
    set now holds, so the reset explains itself without a wiki
    lookup."""
    coord = await setup_coordinator(hass)
    attrs = DeviceSentinelDataSignalSensor(coord).extra_state_attributes

    assert DEV_SIGNAL_DAILY_P5 in attrs["series"]
    assert DEV_SIGNAL_DAILY_MIN in attrs["series"]
    assert attrs["retention_days"] == coord.retention_days


@pytest.mark.parametrize(
    ("sensor_class", "expected"),
    (
        (DeviceSentinelDataFreezeSensor, "data_freeze"),
        (DeviceSentinelDataBatterySensor, "data_battery"),
        (DeviceSentinelDataSignalSensor, "data_signal"),
    ),
)
async def test_each_sensor_is_diagnostic_and_uniquely_typed(
    hass: HomeAssistant, sensor_class: Any, expected: str
):
    """Three entities, three unique ids, all Diagnostic: they are
    telemetry about the telemetry, not controls."""
    coord = await setup_coordinator(hass)
    sensor = sensor_class(coord)

    assert sensor.sentinel_type == expected
    assert sensor.unique_id.endswith(expected)
    assert sensor.entity_category is not None
