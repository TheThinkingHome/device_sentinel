# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_lutron_hub_down.py, Version: 0.27.5 (2026-10-25)

"""When a Lutron hub is down (rule STACK-09).

Two not-connected readings 55 seconds or more apart, dated from the
first. A reading with no opinion between them (the entry reloading, a
session that cannot be read) is not a second not-connected reading.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import DATA_DEVICES, EVENT_FAULT

from .helpers import record_events
from .test_lutron_hub import SESSION, _house, _item, _past_grace, _tick


async def test_one_reading_then_no_opinion_is_not_down(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None  # one not-connected reading
    await _tick(hass, freezer)
    h.garage.runtime_data.bridge._leap = SESSION  # back, and reloading
    h.garage.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    await _tick(hass, freezer)  # no opinion
    assert _item(h.coord, h.g_hub.id) is None
    assert h.coord.hub_down_since(h.g_hub.id) is None
    assert list(faults) == []
    # Loaded and connected again: nothing ever happened.
    h.garage.mock_state(hass, ConfigEntryState.LOADED)
    await _tick(hass, freezer, n=2)
    assert _item(h.coord, h.g_hub.id) is None
    assert list(faults) == []


async def test_a_second_reading_after_no_opinion_is_down_from_the_first(
    hass: HomeAssistant, freezer
):
    h = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    await _past_grace(hass, freezer)
    lost_at = dt_util.utcnow().timestamp()
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer)  # first not-connected reading
    h.garage.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    await _tick(hass, freezer)  # no opinion
    assert h.coord.hub_down_since(h.g_hub.id) is None
    h.garage.mock_state(hass, ConfigEntryState.LOADED)
    await _tick(hass, freezer)  # second not-connected reading
    item = _item(h.coord, h.g_hub.id)
    assert item is not None and "Hub down" in item["summary"]
    since = h.coord.data[DATA_DEVICES][h.g_hub.id]["frozen_since"]
    assert lost_at <= since <= lost_at + 62
    assert [f["device_id"] for f in faults] == [h.g_hub.id]


async def test_two_readings_closer_than_55_seconds_are_not_down(
    hass: HomeAssistant, freezer
):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    coord = h.coord
    now = dt_util.utcnow().timestamp()
    coord._sample_hubs(now)
    coord._sample_hubs(now + 30)
    assert coord.hub_down_since(h.g_hub.id, now + 60) is None
    coord._sample_hubs(now + 55)
    assert coord.hub_down_since(h.g_hub.id, now + 60) == now
