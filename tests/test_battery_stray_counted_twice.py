# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_stray_counted_twice.py, Version: 0.28.12 (2026-11-11)

"""A battery value heard at one report is one moment, through Home
Assistant's state machine (rule BAT-06).

Each test asserts the correct behaviour, so a failing test is a finding.

BAT-06: "The day's low and high count only levels heard at two moments
or more, so a value held for seconds, as a reconnect can give, decides
nothing." The shipped tests feed note_battery_sample(new level) only.
The real event path is different: _on_state_changed calls
_record_activity first, which samples the STORED level (the stray one)
when the next battery report arrives, and only then _evaluate_battery
stores and samples the new level. So a stray value reported once is
counted at its own report and again at the report that replaces it:
two moments, held, and it sets the day's low.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_RANGE_HIGHS,
    DEV_BATTERY_RANGE_LOWS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_REPLACED_PENDING,
)
from custom_components.device_sentinel.detect_battery import battery_day_range

from tests.helpers import setup_coordinator
from tests.test_battery import _battery_device


async def _device(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 81, percentage=True, binary=False)
    eids["plain"] = er.async_get(hass).async_get_or_create(
        "sensor", "test", "bat81_temp", device_id=device.id, config_entry=source,
    ).entity_id
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    return coord, device, eids


async def _set(hass, entity_id, value):
    hass.states.async_set(entity_id, value)
    await hass.async_block_till_done()


async def test_a_stray_battery_report_is_not_held_through_the_state_machine(hass: HomeAssistant):
    coord, device, eids = await _device(hass)
    await _set(hass, eids["pct"], "99")
    await _set(hass, eids["pct"], "100")
    for value in ("20.1", "20.2", "20.3"):
        await _set(hass, eids["plain"], value)
    # One stray report of 0, corrected by the very next report.
    await _set(hass, eids["pct"], "0")
    await _set(hass, eids["pct"], "100")
    for value in ("20.4", "20.5", "20.6"):
        await _set(hass, eids["plain"], value)
    record = coord.data[DATA_DEVICES][device.id]
    low, _high = battery_day_range(record)
    assert low > 0.0, "a value reported once was counted as held"


async def test_one_stray_low_on_the_new_cell_does_not_lose_the_change(hass: HomeAssistant):
    """The shipped test of the same name, driven through the state
    machine instead of note_battery_sample."""
    coord, device, eids = await _device(hass)
    await _set(hass, eids["pct"], "31")
    await _set(hass, eids["pct"], "30")
    record = coord.data[DATA_DEVICES][device.id]
    # Two whole days of the old cell at 30 are kept.
    record[DEV_BATTERY_DAILY] = [31.0, 30.0]
    record[DEV_BATTERY_RANGE_LOWS] = [30.0, 30.0]
    record[DEV_BATTERY_RANGE_HIGHS] = [30.0, 30.0]
    # The change day: the new cell reads 100.
    await _set(hass, eids["pct"], "100")
    for value in ("20.1", "20.2", "20.3"):
        await _set(hass, eids["plain"], value)
    coord._roll_battery(record, device.id)
    assert record[DEV_BATTERY_REPLACED_PENDING] is not None
    # The new cell's first whole day: one reconnect reads 0 for a moment.
    for value in ("20.4", "20.5"):
        await _set(hass, eids["plain"], value)
    await _set(hass, eids["pct"], "0")
    await _set(hass, eids["pct"], "100")
    for value in ("20.6", "20.7", "20.8"):
        await _set(hass, eids["plain"], value)
    coord._roll_battery(record, device.id)
    assert record[DEV_BATTERY_REPLACED_AT] is not None
