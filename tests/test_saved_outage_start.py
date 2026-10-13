# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_saved_outage_start.py, Version: 0.26.0 (2026-10-12)

"""The start of an outage, saved with the device's record (ruling #647).

When a device goes down as a whole, every one of its own entities
unavailable or unknown or its ESPHome connection dropped, Device
Sentinel saves the moment with the device's record. A restart inside the outage cannot lose it: the gap spanning
an outage longer than the taint debounce is not learned, whatever
restarts happen inside it. Device Sentinel's own stops inside the
outage are taken out of its length, as they are out of a gap (#541),
so an ordinary restart, with entities written unavailable as Home
Assistant stops and back as it starts, costs no gap.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DOWN_SINCE,
    DEV_DAILY_MAX,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
)
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator


async def _minutes(hass, freezer, n):
    for _ in range(n):
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def _device(hass, freezer, uid):
    freezer.move_to("2026-10-12 12:00:00+00:00")
    device, (eid,) = register_device(hass, uid, f"Device {uid}")
    coord = await setup_coordinator(hass)
    await _minutes(hass, freezer, STARTUP_GRACE_SECONDS // 60 + 1)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    record[DEV_TODAY_MAX] = None
    return coord, device, eid


def _entry(hass):
    return hass.config_entries.async_entries("device_sentinel")[0]


async def test_the_start_is_saved_with_the_record(hass: HomeAssistant, freezer):
    coord, device, eid = await _device(hass, freezer, "saved1")
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    held = coord.data[DATA_DEVICES][device.id][DEV_DOWN_SINCE]
    assert held is not None and held[1] == "unavailable"
    assert not check_records(coord.data[DATA_DEVICES]), "the saved shape passes the storage check"


async def test_an_outage_across_a_reload_is_not_learned(hass: HomeAssistant, freezer):
    """Two hours unavailable, Device Sentinel reloaded inside it, the
    device back a minute after the reload: the outage is not taught as
    the device's quiet."""
    coord, device, eid = await _device(hass, freezer, "saved2")
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _minutes(hass, freezer, 120)
    assert await hass.config_entries.async_reload(_entry(hass).entry_id)
    await hass.async_block_till_done()
    coord = _entry(hass).runtime_data
    await _minutes(hass, freezer, 1)
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_TODAY_MAX] is None, record[DEV_TODAY_MAX]
    assert record[DEV_DOWN_SINCE] is None


async def test_an_ordinary_restart_costs_no_gap(hass: HomeAssistant, freezer):
    """Entities written unavailable as Home Assistant stops, a ten-minute
    stop, and back as it starts: the stop is Device Sentinel's own, not
    the device's outage, so the gap is learned with the stop taken out."""
    coord, device, eid = await _device(hass, freezer, "saved3")
    await _minutes(hass, freezer, 30)
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    entry = _entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=20))
    hass.states.async_set(eid, "1")  # the value restored as it starts
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_DOWN_SINCE] is None and record[DEV_TAINTED] is False
    await _minutes(hass, freezer, STARTUP_GRACE_SECONDS // 60 + 1)
    hass.states.async_set(eid, "2")  # its next real report
    await hass.async_block_till_done()
    assert record[DEV_TAINTED] is False
    assert record[DEV_TODAY_MAX] is not None, "the gap across a plain restart was learned"


def test_a_fresh_record_holds_no_outage():
    record = _new_device_record("", None)
    assert record[DEV_DOWN_SINCE] is None


def test_the_starts_are_written_with_each_routine_save():
    """A start cleared in memory is written with the routine save, not
    only with the main file, so a power cut cannot bring it back
    (adversarial round of 12 October 2026)."""
    from custom_components.device_sentinel.const import CLOCK_FIELDS

    assert DEV_DOWN_SINCE in CLOCK_FIELDS


async def test_a_damaged_saved_start_costs_only_that_start(hass: HomeAssistant, hass_storage, freezer):
    """One device's saved outage start damaged in the clocks file clears
    that start; the file is kept, so no other device's clock restarts
    (adversarial round of 12 October 2026)."""
    from custom_components.device_sentinel.const import DEV_LAST_ACTIVITY, STORAGE_CLOCKS_KEY

    coord, device, eid = await _device(hass, freezer, "damaged1")
    other, (other_eid,) = register_device(hass, "damaged2", "Device damaged2")
    await hass.async_block_till_done()
    entry = _entry(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    hass.states.async_set(other_eid, "5")
    await hass.async_block_till_done()
    await _minutes(hass, freezer, 2)
    kept = coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"][other.id][DEV_DOWN_SINCE] = [1e300, "unavailable"]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] == kept, "the clocks file was discarded"
    assert coord.data[DATA_DEVICES][other.id][DEV_DOWN_SINCE] is None
