# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_bridge_restart_handback.py, Version: 0.28.12 (2026-11-11)

"""A Zigbee2MQTT restart shorter than the minute check (rule UNAV-05).

Real Home Assistant: Zigbee2MQTT publishes bridge/state "offline" as it
stops and "online" when it is back. Every Zigbee2MQTT entity lists
bridge/state among its availability topics, so it writes unavailable,
and on "online" writes back the value it already held, with no message
from any device. The MQTT client keeps the broker, so the broker's
hand-back does not apply, and a restart of 20 to 40 seconds is often
never seen down by a minute check.

The value written back is the bridge handing back its cache. A device
that is silent must keep its clock, or one that died just before a
Zigbee2MQTT update is not listed until a whole new window has passed.
A device that really reports after the minute that follows is heard.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    STACK_Z2M,
)
from custom_components.device_sentinel.stack_z2m import Z2MBridgeReader

from tests.helpers import register_device, setup_entry
from tests.test_bridge_hold import _minutes


def _msg(payload: str) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


async def _silent_lamp(hass: HomeAssistant, freezer):
    device, entities = register_device(hass, "lamp", name="Lamp")
    entity_id = entities[0]
    hass.states.async_set(entity_id, "21.5")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[device.id] = "mqtt"
    coord._stack_for_device = lambda device_id: STACK_Z2M if device_id == device.id else None
    reader = Z2MBridgeReader(hass)
    reader._on_state(_msg("online"))
    coord._bridge_readers[STACK_Z2M] = reader

    def record():
        return coord.data[DATA_DEVICES][device.id]

    # Reports about every 10 minutes; last heard 6 minutes ago.
    record()[DEV_EVENT_COUNT] = 5000
    record()[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    record()[DEV_LAST_ACTIVITY] = (dt_util.utcnow() - timedelta(minutes=6)).timestamp()
    await _minutes(hass, coord, freezer, 1)
    assert record()[DEV_FROZEN_CATEGORY] is None
    return coord, reader, entity_id, record


async def _restart(hass: HomeAssistant, freezer, reader, entity_id) -> None:
    freezer.tick(15)
    reader._on_state(_msg("offline"))
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(25)
    reader._on_state(_msg("online"))
    hass.states.async_set(entity_id, "21.5")
    await hass.async_block_till_done()


async def test_a_short_bridge_restart_does_not_move_a_silent_devices_clock(
    hass: HomeAssistant, freezer
):
    coord, reader, entity_id, record = await _silent_lamp(hass, freezer)
    heard = record()[DEV_LAST_ACTIVITY]
    await _restart(hass, freezer, reader, entity_id)
    await _minutes(hass, coord, freezer, 1)
    assert record()[DEV_LAST_ACTIVITY] == heard


async def test_the_value_written_before_the_bridge_says_online_is_handed_back(
    hass: HomeAssistant, freezer
):
    """Each entity hears bridge/state on its own, so one may write before
    Device Sentinel's reader hears "online"."""
    coord, reader, entity_id, record = await _silent_lamp(hass, freezer)
    heard = record()[DEV_LAST_ACTIVITY]
    freezer.tick(15)
    reader._on_state(_msg("offline"))
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(25)
    hass.states.async_set(entity_id, "21.5")
    await hass.async_block_till_done()
    reader._on_state(_msg("online"))
    await _minutes(hass, coord, freezer, 1)
    assert record()[DEV_LAST_ACTIVITY] == heard


async def test_a_device_reporting_after_the_minute_is_heard(hass: HomeAssistant, freezer):
    coord, reader, entity_id, record = await _silent_lamp(hass, freezer)
    await _restart(hass, freezer, reader, entity_id)
    await _minutes(hass, coord, freezer, 2)
    hass.states.async_set(entity_id, "22.0")
    await hass.async_block_till_done()
    assert record()[DEV_LAST_ACTIVITY] == dt_util.utcnow().timestamp()


async def test_an_unavailable_from_before_the_restart_is_not_handed_back(
    hass: HomeAssistant, freezer
):
    """A device that went unavailable on its own before the bridge
    restarted, and comes back after, is a device speaking."""
    coord, reader, entity_id, record = await _silent_lamp(hass, freezer)
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(30)
    await _restart(hass, freezer, reader, entity_id)
    assert record()[DEV_LAST_ACTIVITY] == dt_util.utcnow().timestamp()
