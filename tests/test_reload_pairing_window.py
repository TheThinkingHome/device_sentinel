# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_reload_pairing_window.py, Version: 0.28.12 (2026-11-11)

"""A Zigbee2MQTT pairing window open when Device Sentinel is reloaded
must not stay open in the record for ever (rules STOR-18, UP-06,
BRIEF-05).

A reload is SYS_RELOAD, which ends no outage. The pairing state lives in
memory (_pairing_seen, _pairing_open_at); the new run starts with
neither, so its first sample of the bridge sees "closed" with no earlier
state and writes no SYS_PAIRING_CLOSED. The reload itself ends the
window, or every Zigbee2MQTT device's silence and recovery for weeks
would be put down to "a Zigbee2MQTT pairing window".
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import attribution
from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    STACK_Z2M,
    SYS_PAIRING_OPEN,
)

from tests.helpers import setup_entry


async def test_a_pairing_window_open_at_a_reload_does_not_stay_open(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    # Pairing opened a minute ago, as the bridge sampler records it.
    coord._pairing_seen[STACK_Z2M] = True
    coord._pairing_open_at[STACK_Z2M] = now - 60.0
    coord._record_system_event(SYS_PAIRING_OPEN, scope=STACK_Z2M, when=now - 60.0)
    coord._mark_cold_dirty()

    # The person reloads Device Sentinel while the window is open.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    two_days_later = now + 2 * 86400.0
    events = coord.data.get(DATA_SYSTEM_EVENTS) or []
    still_open = [
        window
        for window in attribution.windows(events)
        if window.kind == SYS_PAIRING_OPEN and window.in_effect_at(two_days_later)
    ]
    assert still_open == [], (
        "a pairing window open at a reload is still in effect two days "
        "later, so it explains and credits every Zigbee2MQTT recovery"
    )
    # And so a Zigbee2MQTT device going quiet two days later is not put
    # down to that pairing window.
    window = attribution.attribute(
        attribution.windows(events), "mqtt", STACK_Z2M, two_days_later, None
    )
    assert window is None or window.kind != SYS_PAIRING_OPEN
