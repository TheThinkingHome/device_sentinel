# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_open_outage_learning.py, Version: 0.24.1 (2026-10-03)

"""A gap across an outage still open is not learned.

#536 keeps a gap across an upstream's outage out of learning, reading
the outages from the stored returns. A return is stored when Device
Sentinel next reads the upstream, and Zigbee2MQTT's devices start
reporting the moment the bridge is back: on 1 October the reference
rig's Leak Sink Bath Main finished a 201-minute gap across the bridge's
outage before its return was recorded, and learned it as its own
silence. A gap is learned only if Device Sentinel can trust it, so an
outage still open on the device's path, by the same ladder the holds
read, keeps the gap out of learning exactly as a stored one does.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    STACK_Z2M,
    SYS_BRIDGE_DOWN,
    SYS_DURATION,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
)

from .test_bridge_hold import _house

HOUR = 3600.0


async def _silent_four_hours(hass, freezer):
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    now = dt_util.utcnow()
    record = coord.data[DATA_DEVICES][device.id]
    last = (now - timedelta(hours=4, minutes=10)).timestamp()
    record[DEV_LAST_ACTIVITY] = last
    record[DEV_TODAY_MAX] = None
    coord.data[DATA_SYSTEM_EVENTS] = []
    return coord, device, record, seen, now, last


async def _speak(hass, seen, now):
    hass.states.async_set(seen, now.isoformat())
    await hass.async_block_till_done()


async def test_with_no_outage_the_gap_is_learned(hass: HomeAssistant, freezer):
    """The control: the same four hours with nothing on the path are learned."""
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    await _speak(hass, seen, now)
    assert record[DEV_LAST_ACTIVITY] > last
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 4 * HOUR


async def test_a_bridge_still_marked_down_keeps_the_gap_out(hass: HomeAssistant, freezer):
    """The night of 1 October: the bridge fell, came back, and its first
    reports arrived before Device Sentinel next read the bridge."""
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    fell = last + 60
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: STACK_Z2M, SYS_WHEN: fell, SYS_DURATION: None, "detail": None}
    ]
    coord._bridge_down_at[STACK_Z2M] = fell
    await _speak(hass, seen, now)
    assert record[DEV_LAST_ACTIVITY] > last
    assert record[DEV_TODAY_MAX] is None, "the gap across a bridge outage still open was learned"


async def test_a_broker_still_marked_down_keeps_the_gap_out(hass: HomeAssistant, freezer):
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    coord._broker_down_at = last + 60
    coord._rides_the_broker = lambda device_id: True
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "the gap across a broker outage still open was learned"


async def test_an_integration_still_down_keeps_the_gap_out(hass: HomeAssistant, freezer):
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    coord._stack_for_device = lambda device_id: None
    coord.integration_down_since = lambda device_id: ("zwave_js", last + 60)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "the gap across an integration outage still open was learned"


async def test_a_wifi_network_still_down_keeps_the_gap_out(hass: HomeAssistant, freezer):
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    coord._stack_for_device = lambda device_id: None
    coord.wifi_down_since = lambda device_id: ("wifi", last + 60)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "the gap across a Wi-Fi outage still open was learned"


async def test_an_outage_that_began_after_the_device_spoke_does_not_hide_it(hass: HomeAssistant, freezer):
    """An outage open now but begun after this gap ended is no reason to
    forget the gap: the device was already heard. Here the bridge fell a
    minute ago; the gap ran four hours before that."""
    coord, device, record, seen, now, last = await _silent_four_hours(hass, freezer)
    coord._bridge_down_at[STACK_Z2M] = now.timestamp() + 1
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 4 * HOUR
