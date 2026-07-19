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

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_DAILY_MIN,
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


async def test_tracked_signals_sensor_exists(hass: HomeAssistant):
    await _setup(hass)
    state = hass.states.get("sensor.device_sentinel_tracked_signals")
    assert state is not None
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
    state = hass.states.get("sensor.device_sentinel_tracked_signals")
    assert int(state.state) == 1
    assert state.attributes["lqi"] == 1
    assert state.attributes["rssi"] == 0
