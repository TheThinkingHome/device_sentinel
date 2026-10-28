# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_polled_device_returns.py, Version: 0.27.11 (2026-10-28)

"""A device whose integration polls it answers for itself (rules
WATCH-12, UP-06).

The rig's printer went out with the power at 2:12, Home Assistant
restarted at 3:42 while it was still off, and at 5:39 it answered
again, asleep, with the same page counts. Its integration polls it, so
those values are the printer answering, and it is back. A device whose
integration pushes values it kept, or restores them as Modbus does, is
still not taken at its word.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_FROZEN_CATEGORY

from .helpers import setup_entry
from .test_bridge_hold import _minutes

async def _power_cut(hass, freezer, domain):
    """The printer's night, up to its answer; returns the verdict after."""
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, "printer")}, name="HL-L2370DW",
    )
    registry = er.async_get(hass)
    status = registry.async_get_or_create(
        "sensor", domain, "status", device_id=device.id, config_entry=source).entity_id
    pages = registry.async_get_or_create(
        "sensor", domain, "pages", device_id=device.id, config_entry=source).entity_id
    hass.states.async_set(status, "sleep")
    hass.states.async_set(pages, "5749")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await _minutes(hass, coord, freezer, 20)
    hass.states.async_set(status, "printing")
    await _minutes(hass, coord, freezer, 1)
    hass.states.async_set(status, "sleep")
    await _minutes(hass, coord, freezer, 20)
    # The power goes, and the printer with it.
    hass.states.async_set(status, "unavailable")
    hass.states.async_set(pages, "unavailable")
    await _minutes(hass, coord, freezer, 10)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] == "unavailable"
    # Home Assistant restarts while the printer is still off.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    await _minutes(hass, coord, freezer, 10)
    # The power returns; the printer answers, asleep and unchanged.
    hass.states.async_set(status, "sleep")
    hass.states.async_set(pages, "5749")
    await _minutes(hass, coord, freezer, 30)
    return coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY]


async def test_a_polled_printer_back_unchanged_is_back(hass: HomeAssistant, freezer):
    assert await _power_cut(hass, freezer, "brother") is None


async def test_a_device_asked_as_it_connects_is_back(hass: HomeAssistant, freezer):
    assert await _power_cut(hass, freezer, "esphome") is None


async def test_a_value_pushed_back_unchanged_is_not_the_device(hass: HomeAssistant, freezer):
    """An integration that pushes what it kept hands the old value back."""
    assert await _power_cut(hass, freezer, "cloudpush") == "unavailable"


async def test_a_poller_that_restores_its_last_value_is_not_taken_at_its_word(hass: HomeAssistant, freezer):
    """Modbus polls, but restores its last value at a start: that value
    is not the meter answering."""
    assert await _power_cut(hass, freezer, "modbus") == "unavailable"
