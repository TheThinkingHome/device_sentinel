# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_gap_bounds.py, Version: 0.24.4 (2026-10-04)

"""A learned gap may not be negative or exceed the watch (ruling #403)."""

from __future__ import annotations

import time

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STATS_EPOCH,
    STORAGE_KEY,
)
from custom_components.device_sentinel.normalise import check_records

from .helpers import register_device, setup_entry

NOW = time.time()
WATCH_DAYS = 25
FIRST_OBSERVED = time.strftime(
    "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - WATCH_DAYS * 86400.0)
)


def _disk(hass_storage, device_id, series):
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {
                device_id: {
                    DEV_LAST_ACTIVITY: NOW - 60.0,
                    DEV_TODAY_MAX: 30.0,
                    DEV_EVENT_COUNT: 100,
                    DEV_FIRST_OBSERVED: FIRST_OBSERVED,
                    DEV_TAINTED: False,
                    DEV_DAILY_MAX: series,
                }
            },
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: NOW - 10.0,
            DATA_EPISODES: [],
            DATA_TODO_ITEMS: [],
            DATA_FIRST_INSTALLED: "2026-07-11T00:00:00+00:00",
            "clean_stop": True,
        },
    }


def test_a_negative_gap_is_a_shape_fault():
    faults = check_records({"d": {DEV_DAILY_MAX: [30.0, -5.0, 40.0]}})
    assert any(f[1] == DEV_DAILY_MAX and "negative" in f[2] for f in faults)


def test_a_healthy_series_is_not():
    faults = check_records({"d": {DEV_DAILY_MAX: [30.0, 0.0, 40.0]}})
    assert not any(f[1] == DEV_DAILY_MAX for f in faults)


async def test_a_negative_series_is_reset_at_load(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "neg", "Negative")
    _disk(hass_storage, device.id, [-5.0] * 10)
    entry = await setup_entry(hass)
    assert entry.runtime_data.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] == []


async def test_a_gap_wider_than_the_watch_is_forgotten(
    hass: HomeAssistant, hass_storage
):
    """The second fleet's 1,076 days against 25 days watched, at load.

    Nobody was listening for the part of that gap before the watch
    began, so it is forgotten (rulings #403 and #549, 0.24.4), not
    bounded to the watch as it was under #399's reasoning, and the day
    it held reads as skipped in the history's dates.
    """
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.device_sentinel.daily_dates import FAMILY_GAP, dates_for

    device, _ = register_device(hass, "wide", "Wide")
    _disk(hass_storage, device.id, [30.0, 1076.4 * 86400.0, 40.0])
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert record[DEV_DAILY_MAX] == [30.0, 40.0]
    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    assert dates_for(record, FAMILY_GAP, 2, yesterday) == [yesterday - timedelta(days=2), yesterday]


async def test_astronomical_gaps_are_all_forgotten(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "astro", "Astronomical")
    _disk(hass_storage, device.id, [1e308, 1e308, 1e308])
    entry = await setup_entry(hass)
    assert entry.runtime_data.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] == []


async def test_a_series_inside_the_watch_is_untouched(hass: HomeAssistant, hass_storage):
    """The control: healthy learning is byte-identical after load."""
    device, _ = register_device(hass, "ok", "Healthy")
    healthy = [30.0, 3600.0, 86400.0, 7 * 86400.0, 20 * 86400.0]
    _disk(hass_storage, device.id, list(healthy))
    entry = await setup_entry(hass)
    assert entry.runtime_data.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] == healthy
