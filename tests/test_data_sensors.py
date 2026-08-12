"""Tests for the three Data sensors (ruling #255).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_data_sensors.py, Version: 0.12.20 (2026-08-12)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

The sensors answer one question that previously needed a diagnostics
download and somebody to read it: how much complete history stands
behind each area of judgment. Complete is the whole difficulty, so
the tests concentrate there: a set that gained a series yesterday has
one day of complete history however deep its older members run, and
the count restarts even though nothing was deleted.
"""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    AREA_BATTERY,
    AREA_FREEZE,
    AREA_SIGNAL,
    DATA_DEVICES,
    DATA_SERIES_STAMPS,
    DATA_STATE_LEARNED,
    DATA_STATE_TRACKING,
    DEV_BATTERY_DAILY,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    SERIES_VERSION_SIGNAL,
)
from custom_components.device_sentinel.sensor import (
    DeviceSentinelDataBatterySensor,
    DeviceSentinelDataFreezeSensor,
    DeviceSentinelDataSignalSensor,
)

from .helpers import register_device, setup_coordinator


def _age_stamp(coord: Any, area: str, days: int) -> None:
    """Backdate one area's stamp by whole days."""
    stamps = coord.data[DATA_SERIES_STAMPS]
    stamps[area]["since"] = (
        dt_util.utcnow() - timedelta(days=days, minutes=1)
    ).isoformat()


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
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataSignalSensor(coord)

    _age_stamp(coord, AREA_SIGNAL, 4)
    assert sensor.native_value == "4 of 7"

    _age_stamp(coord, AREA_SIGNAL, 12)
    assert sensor.native_value == "Armed, 12 of 30"
    assert sensor.extra_state_attributes["target_days"] == 30

    _age_stamp(coord, AREA_SIGNAL, 30)
    assert sensor.native_value == DATA_STATE_LEARNED


async def test_freeze_matures_at_the_judgment_window(hass: HomeAssistant):
    """Freeze arms at seven and is Learned at fourteen, which is the
    rhythm window every freeze verdict reads (DAILY_MAX_KEEP), not
    the retention setting."""
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataFreezeSensor(coord)

    _age_stamp(coord, AREA_FREEZE, 9)
    assert sensor.native_value == "Armed, 9 of 14"

    _age_stamp(coord, AREA_FREEZE, 14)
    assert sensor.native_value == DATA_STATE_LEARNED


async def test_battery_is_two_phase_and_says_tracking(hass: HomeAssistant):
    """The battery slope reads a fixed seven days
    (BATTERY_SLOPE_DAYS) and has no second milestone, so inventing a
    middle phase to match the other two would be decoration."""
    coord = await setup_coordinator(hass)
    sensor = DeviceSentinelDataBatterySensor(coord)

    _age_stamp(coord, AREA_BATTERY, 3)
    assert sensor.native_value == "3 of 7"

    _age_stamp(coord, AREA_BATTERY, 7)
    assert sensor.native_value == DATA_STATE_TRACKING


async def test_a_changed_recording_set_restarts_the_count(
    hass: HomeAssistant,
):
    """The ruling's whole point, and the 0.12.19 case exactly.

    Storage carrying an older signal version has its stamp reset at
    load, so the sensor reads zero complete days even though the
    minima series behind it is deep. Nothing was deleted; the
    complete set is simply new.
    """
    coord = await setup_coordinator(hass)
    _age_stamp(coord, AREA_SIGNAL, 40)
    assert DeviceSentinelDataSignalSensor(coord).native_value == (
        DATA_STATE_LEARNED
    )

    loaded = dict(coord.data)
    loaded[DATA_SERIES_STAMPS] = {
        AREA_SIGNAL: {
            "version": SERIES_VERSION_SIGNAL - 1,
            "since": (dt_util.utcnow() - timedelta(days=40)).isoformat(),
        },
    }
    coord._reconcile_series_stamps(loaded)
    coord.data[DATA_SERIES_STAMPS] = loaded[DATA_SERIES_STAMPS]

    assert DeviceSentinelDataSignalSensor(coord).native_value == "0 of 7"
    assert (
        loaded[DATA_SERIES_STAMPS][AREA_SIGNAL]["version"]
        == SERIES_VERSION_SIGNAL
    )


async def test_an_unchanged_set_keeps_its_stamp(hass: HomeAssistant):
    """A release that records nothing new must not restart anything,
    which is why the versions are per area rather than the manifest
    version."""
    coord = await setup_coordinator(hass)
    _age_stamp(coord, AREA_FREEZE, 20)
    before = coord.data[DATA_SERIES_STAMPS][AREA_FREEZE]["since"]

    coord._reconcile_series_stamps(coord.data)

    assert coord.data[DATA_SERIES_STAMPS][AREA_FREEZE]["since"] == before
    assert DeviceSentinelDataFreezeSensor(coord).native_value == (
        DATA_STATE_LEARNED
    )


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
    """Days older than retention are gone whatever the stamp says, so
    the reading is capped rather than claiming history that is no
    longer stored."""
    coord = await setup_coordinator(hass)
    _age_stamp(coord, AREA_SIGNAL, 400)
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
