# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_bridge_restart_between_checks.py, Version: 0.28.12 (2026-11-11)

"""A Zigbee2MQTT restart that falls between two minute checks.

Real Home Assistant: Zigbee2MQTT publishes bridge/state "offline" when it
stops and "online" when it is back. Every Zigbee2MQTT entity lists the
bridge state as an availability topic, so it writes unavailable, and on
"online" writes back the value it already held (MqttAvailabilityMixin),
with no message from any device. The bridge reader follows bridge/state
live, but Device Sentinel only samples it on the minute check, so a
restart of 20 to 40 seconds (an add-on restart or update) is often never
seen down at all: no pending wait, no outage, no hand-back window. The
MQTT connection to the broker never drops, so the broker hand-back does
not apply either.

Rule UNAV-05: a value handed back through a stack restart is not the
device speaking. A frozen device with no Last Seen clock (Zigbee2MQTT's
default) must stay frozen.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    STACK_Z2M,
)

from tests.test_bridge_hold import _minutes
from tests.test_bridge_pairing import _Stub
from tests.test_recovery_one_way import _clockless


async def test_a_short_bridge_restart_between_checks_does_not_revive(
    hass: HomeAssistant, freezer
):
    coord, device, entity_id, record = await _clockless(hass, freezer)
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    heard = record[DEV_LAST_ACTIVITY]

    # Between two checks: the reader follows bridge/state live.
    freezer.tick(15)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(25)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(entity_id, "on")  # the held value written back
    await hass.async_block_till_done()

    await _minutes(hass, coord, freezer, 3)
    assert record[DEV_LAST_ACTIVITY] == heard, "the bridge's hand-back moved the clock"
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "a Zigbee2MQTT restart revived a frozen device"
