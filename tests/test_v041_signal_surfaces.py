# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.1 (2026-07-18)

"""0.4.1 tests: the signal surfaces.

Two sensors built ahead of their engine, the pattern the whole
integration follows: Signals Tracked counts devices with a learned
floor, Signals Frozen counts signals stuck flat while their device
keeps reporting. They report real numbers today; the notifications
those numbers will feed are still soaking. Named, united, and
integer-valued per the device-page rulings of 0.3.12.
"""

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_DAILY_MAX,
    DEV_SIGNAL_REPEAT_COUNT,
    DEV_SIGNAL_VALUE,
    SIGNAL_FROZEN_REPEAT_COUNT,
    SIGNAL_RAIL_LQI,
    UNIT_SIGNALS,
)

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"Signal {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_both_signal_sensors_exist(hass: HomeAssistant):
    await _setup(hass)
    for entity_id in (
        "sensor.device_sentinel_signals_tracked",
        "sensor.device_sentinel_signals_frozen",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["unit_of_measurement"] == UNIT_SIGNALS


async def test_tracked_counts_armed_devices_and_splits_by_scale(
    hass: HomeAssistant,
):
    device = _register_device(hass, "tracked")
    entry = await _setup(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88, 80, 104, 92, 80]
    coord._notify()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_signals_tracked")
    assert int(state.state) == 1
    assert state.attributes["lqi"] == 1
    assert state.attributes["rssi"] == 0


async def test_only_a_rail_freeze_is_counted(hass: HomeAssistant):
    """Frozen is the rail case only (ruled 2026-07-19 eve). A device
    at the rail counts; a device holding a plausible value steady does
    not, because a steady real reading is a healthy stable link. Both
    are set up identically except for the held value."""
    rail = _register_device(hass, "railed")
    real = _register_device(hass, "flatreal")
    entry = await _setup(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()

    for device, value in ((rail, SIGNAL_RAIL_LQI), (real, 80.0)):
        record = coord.data["devices"][device.id]
        record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88, 80, 104, 92, 80]
        record[DEV_SIGNAL_VALUE] = value
        record[DEV_SIGNAL_REPEAT_COUNT] = SIGNAL_FROZEN_REPEAT_COUNT
        record[DEV_DAILY_MAX] = [3600.0, 3500.0, 3400.0, 3600.0,
                                 3550.0, 3400.0, 3600.0]
        record[DEV_LAST_ACTIVITY] = now - 60
    coord._notify()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_signals_frozen")
    # Only the rail device is frozen; the flat plausible one is not.
    assert int(state.state) == 1
    devices = state.attributes["devices"]
    assert len(devices) == 1
    assert devices[0]["at_rail"] is True


async def test_frozen_reads_zero_on_a_healthy_fleet(hass: HomeAssistant):
    await _setup(hass)
    state = hass.states.get("sensor.device_sentinel_signals_frozen")
    assert int(state.state) == 0
    assert state.attributes["devices"] == []
