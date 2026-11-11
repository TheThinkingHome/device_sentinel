# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_hostile_storage.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: a hostile .storage document at load.

Each document is what a hand edit, a restored backup from elsewhere or
a damaged write could leave. Safe: Device Sentinel still starts, starts
again after a reload (no crash loop), and the running data is clean.
"""

from __future__ import annotations

import math
import time

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DOMAIN,
    OPTIONS_MINOR_VERSION,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from tests.helpers import register_device


def _deep(depth: int):
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _documents(device_id: str) -> dict[str, object]:
    record_poison = {
        "daily_max": [math.nan, math.inf, -math.inf, "x", None, 1e308],
        "last_activity": math.nan,
        "frozen_since": "../../etc/passwd",
        "battery_daily_value": _deep(200),
        "name": "<script>alert(1)</script>",
    }
    return {
        "data_is_a_list": [1, 2, 3],
        "data_is_a_string": "junk",
        "devices_is_a_list": {"devices": [device_id]},
        "record_is_a_number": {"devices": {device_id: 7}},
        "record_poisoned": {"devices": {device_id: record_poison}},
        "every_top_level_nan": {key: math.nan for key in (
            "devices", "incidents", "episodes", "todo_items", "storms", "system_events",
            "address_changes", "expected_outages", "battery_lives", "short_drops",
        )},
        "huge_lists": {
            "devices": {device_id: {"daily_max": [3600.0] * 200_000}},
            "incidents": [{"device_id": device_id, "event": "opened"}] * 50_000,
        },
        "deep_unknown_key": {"devices": {}, "zz_unknown": _deep(200)},
        "hostile_keys": {"devices": {"../../x": {}, "x" * 100_000: {}, "": {}, device_id: {}}},
    }


async def _boot(hass: HomeAssistant, entry: MockConfigEntry):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.state


@pytest.mark.parametrize("which", list(_documents("ID").keys()))
async def test_a_hostile_document_never_stops_a_start(
    hass: HomeAssistant, hass_storage, which
):
    device, _ = register_device(hass, "storage_target", name="Hall Sensor")
    data = _documents(device.id)[which]
    hass_storage[STORAGE_KEY] = {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": data}
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1, "minor_version": 1, "key": STORAGE_CLOCKS_KEY,
        "data": {"clocks": {device.id: {"last_activity": math.nan}}, "saved_at": "never"},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options={},
        version=1, minor_version=OPTIONS_MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    started = time.perf_counter()
    assert await _boot(hass, entry) is ConfigEntryState.LOADED, which
    assert time.perf_counter() - started < 60, which
    devices = entry.runtime_data.data.get(DATA_DEVICES)
    assert isinstance(devices, dict), which
    # A reload, as Home Assistant does after a settings change, starts
    # again: no crash loop from what the first start saved.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, which
