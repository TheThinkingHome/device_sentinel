# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_missed_fold.py, Version: 0.27.10 (2026-10-27)


"""A midnight missed while down is folded once at load (rule STOR-17)."""

from __future__ import annotations

import datetime
import math

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DATA_TODO_ITEMS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator, setup_entry


def _on_disk(hass_storage, device_id, saved_at):
    """A file saved at the given moment, mid-day, with a day banked."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {
                device_id: {
                    DEV_LAST_ACTIVITY: saved_at - 60.0,
                    DEV_TODAY_MAX: 4000.0,
                    DEV_EVENT_COUNT: 100,
                    DEV_FIRST_OBSERVED: "2026-07-11T00:00:00+00:00",
                    DEV_TAINTED: False,
                    DEV_DAILY_MAX: [3000.0] * 10,
                    DEV_BATTERY_VALUE: 80.0,
                    DEV_BATTERY_DAILY: [82.0, 81.0],
                }
            },
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: saved_at,
            DATA_EPISODES: [],
            DATA_TODO_ITEMS: [],
            DATA_FIRST_INSTALLED: "2026-07-11T00:00:00+00:00",
            "clean_stop": True,
        },
    }
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "data": {
            DATA_SAVED_AT: saved_at,
            "clocks": {
                device_id: {
                    DEV_LAST_ACTIVITY: saved_at - 60.0,
                    DEV_TODAY_MAX: 4000.0,
                }
            },
        },
    }


async def test_a_restart_across_midnight_folds_the_missed_day(
    hass: HomeAssistant, hass_storage
):
    """Saved at 23:59 yesterday, started today.

    The banked day is folded as its own sample, with its battery level,
    so a nightly restart at midnight costs no day of learning.
    """
    device, _ = register_device(hass, "m", "Midnight")
    yesterday = (
        dt_util.now().replace(hour=23, minute=59, second=0, microsecond=0)
        - datetime.timedelta(days=1)
    ).timestamp()
    _on_disk(hass_storage, device.id, yesterday)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_TODAY_MAX] is None
    assert len(record[DEV_DAILY_MAX]) == 11
    assert record[DEV_DAILY_MAX][-1] == 4000.0
    # The battery day was sampled too, which is the other half of
    # what a missed fold costs.
    assert record[DEV_BATTERY_DAILY] == [82.0, 81.0, 80.0]


async def test_a_restart_inside_the_same_day_folds_nothing(
    hass: HomeAssistant, hass_storage
):
    """The control. Ten restarts in an afternoon must fold nothing."""
    device, _ = register_device(hass, "s", "Same Day")
    today = dt_util.now().replace(
        hour=0, minute=5, second=0, microsecond=0
    ).timestamp()
    _on_disk(hass_storage, device.id, today)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_TODAY_MAX] == 4000.0
    assert len(record[DEV_DAILY_MAX]) == 10
    assert record[DEV_BATTERY_DAILY] == [82.0, 81.0]


async def test_a_week_down_folds_once_and_not_seven_times(
    hass: HomeAssistant, hass_storage
):
    """The accumulators hold one day's worth however long the gap.

    Folding once per missed midnight would append six samples no day
    produced.
    """
    device, _ = register_device(hass, "w", "Week Down")
    week_ago = (dt_util.now() - datetime.timedelta(days=7)).timestamp()
    _on_disk(hass_storage, device.id, week_ago)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert len(record[DEV_DAILY_MAX]) == 11


async def test_an_epoch_wipe_suppresses_the_missed_fold(
    hass: HomeAssistant, hass_storage
):
    """Two correct rules meeting badly.

    A change of statistics epoch wipes every rhythm (rule STOR-19). The
    missed-day fold must not then append the banked maximum the wipe has
    just declared invalid, handing back what the wipe removed.
    """
    from custom_components.device_sentinel.const import DATA_STATS_EPOCH

    device, _ = register_device(hass, "e", "Epoch")
    yesterday = (
        dt_util.now().replace(hour=23, minute=59, second=0, microsecond=0)
        - datetime.timedelta(days=1)
    ).timestamp()
    _on_disk(hass_storage, device.id, yesterday)
    hass_storage[STORAGE_KEY]["data"][DATA_STATS_EPOCH] = "an-older-epoch"

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_DAILY_MAX] == []
    assert record[DEV_TODAY_MAX] is None


async def test_a_signal_reading_that_is_not_finite_is_refused(
    hass: HomeAssistant, hass_storage
):
    """A reading that is not a number is refused, as a battery level is
    (rules SIG-04, BAT-02).

    float() accepts every one of these and raises on none, and ESPHome and
    MQTT sensors publish nan for a reading that failed. One reaching
    signal_value, both of the day's extremes and the P2 estimator would
    make every statistic computed from them nan.
    """
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._signal_entities.add("sensor.fake_lqi")
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    coord.data[DATA_DEVICES]["d"] = record

    for bad in ("nan", "inf", "-inf", "1e999", "infinity", "-Infinity"):
        coord._record_activity("d", None, "sensor.fake_lqi", bad)

    assert not [
        value
        for value in record.values()
        if isinstance(value, float) and not math.isfinite(value)
    ]
    # And a real reading after them still lands, so the guard
    # refuses the value rather than the device.
    coord._record_activity("d", None, "sensor.fake_lqi", "180")
    assert record["signal_value"] == 180.0
