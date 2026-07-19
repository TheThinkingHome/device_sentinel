# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.7 (2026-07-19)

"""0.4.7 test: frozen is the rail case only.

The plausible-value frozen flag was removed because a healthy device
with a strong stable link reports the same value across many reports,
and a family of motion-blind devices flagged falsely as a result. This
locks in that a steady real value is not frozen while a rail still is.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    SIGNAL_FROZEN_REPEAT_COUNT,
    SIGNAL_RAIL_RSSI,
    SIGNAL_RAIL_LQI,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "r47")},
        name="Rail47 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "r47",
        suggested_object_id="r47_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id


def _lively(coord, device_id):
    import homeassistant.util.dt as dt_util
    rec = coord.data["devices"][device_id]
    rec[DEV_DAILY_MAX] = [3600.0, 3500.0, 3400.0, 3600.0, 3550.0,
                          3400.0, 3600.0]
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60
    return rec


async def test_the_motion_blind_case_is_not_frozen(hass: HomeAssistant):
    """A lively device reporting a steady plausible RSSI, the exact
    motion-blind case that flagged falsely, is not frozen however many
    times it repeats."""
    coord, device_id = await _coordinator(hass)
    rec = _lively(coord, device_id)
    # A strong stable RSSI held far past the repeat threshold.
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT * 3):
        coord._feed_signal(rec, -49.0, 1000.0 + tick)
    assert rec["signal_repeat_count"] >= SIGNAL_FROZEN_REPEAT_COUNT
    assert coord.signal_frozen(rec) is False


async def test_a_rail_freeze_is_still_caught(hass: HomeAssistant):
    """The rail case still flags: an LQI pinned at 255 on a lively
    device is a stale reading and is frozen."""
    coord, device_id = await _coordinator(hass)
    rec = _lively(coord, device_id)
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT):
        coord._feed_signal(rec, SIGNAL_RAIL_LQI, 1000.0 + tick)
    assert coord.signal_frozen(rec) is True
    assert coord.signal_frozen_at_rail(rec) is True


async def test_rssi_rail_is_caught_too(hass: HomeAssistant):
    """The RSSI rail (-128) is caught the same way as the LQI rail."""
    coord, device_id = await _coordinator(hass)
    rec = _lively(coord, device_id)
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT):
        coord._feed_signal(rec, SIGNAL_RAIL_RSSI, 1000.0 + tick)
    assert coord.signal_frozen(rec) is True
