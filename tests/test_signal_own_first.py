# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_own_first.py, Version: 0.27.9 (2026-10-27)

"""Another integration's signal reading is used only where the device has
none of its own (rule WATCH-02)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_SIGNAL_VALUE

from tests.helpers import setup_coordinator


def _device(hass, uid):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=uid,
    )
    return source, device


def _signal(hass, platform, uid, device, source=None):
    return er.async_get(hass).async_get_or_create(
        "sensor", platform, uid, device_id=device.id, config_entry=source,
        original_device_class="signal_strength", unit_of_measurement="dBm",
        suggested_object_id=uid,
    ).entity_id


async def test_the_own_reading_wins(hass: HomeAssistant):
    source, device = _device(hass, "sig")
    own = _signal(hass, "test", "sig_rssi", device, source)
    foreign = _signal(hass, "other_integration", "sig_other_rssi", device)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert own in coord._signal_entities
    assert foreign not in coord._signal_entities
    hass.states.async_set(own, "-60")
    await hass.async_block_till_done()
    hass.states.async_set(foreign, "-91")
    await hass.async_block_till_done()
    assert coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_VALUE] == -60.0


async def test_a_foreign_reading_alone_is_used(hass: HomeAssistant):
    _source, device = _device(hass, "alone")
    foreign = _signal(hass, "other_integration", "alone_other_rssi", device)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert foreign in coord._signal_entities
