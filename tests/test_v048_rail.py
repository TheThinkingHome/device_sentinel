# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v048_rail.py, Version: 0.4.8 (2026-07-19)

"""0.4.8 tests: the rail is confirmed over three days, from the series.

The live repeat counter and the plausible-value frozen judgment were
removed. A rail is now the daily low sitting at the fill value for
three consecutive days, read from the series the report already keeps.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_DAILY_MIN,
    RAIL_CONFIRM_DAYS,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "rail48")},
        name="Rail48 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rail48",
        suggested_object_id="rail48_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id


async def test_three_rail_days_confirm_a_rail(hass: HomeAssistant):
    """The daily low at the fill value for three days running is a
    rail."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [88.0, 92.0, SIGNAL_RAIL_LQI,
                                 SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is True


async def test_two_rail_days_do_not_confirm(hass: HomeAssistant):
    """Fewer than three consecutive rail days is not yet a rail: a
    rail that comes and goes within a day or two never confirms."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [88.0, SIGNAL_RAIL_LQI, 92.0,
                                 SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is False


async def test_a_recovered_rail_clears(hass: HomeAssistant):
    """Three rail days then a real reading is not a rail: the most
    recent three days are not all rail."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI,
                                 SIGNAL_RAIL_LQI, 88.0, 90.0]
    assert coord.signal_railed(rec) is False


async def test_rssi_rail_confirms_too(hass: HomeAssistant):
    """The RSSI rail (-128) confirms the same way as the LQI rail."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_RSSI] * RAIL_CONFIRM_DAYS
    assert coord.signal_railed(rec) is True


async def test_a_steady_plausible_value_is_not_a_rail(hass: HomeAssistant):
    """The motion-blind case: a steady plausible value, however long
    it holds, is never a rail. Only the fill value is."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [-49.0, -49.0, -49.0, -49.0, -49.0]
    assert coord.signal_railed(rec) is False


async def test_short_history_is_not_a_rail(hass: HomeAssistant):
    """Fewer than three days of history cannot confirm a rail."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is False
