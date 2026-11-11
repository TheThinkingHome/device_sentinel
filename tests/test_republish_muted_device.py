# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_republish_muted_device.py, Version: 0.28.12 (2026-11-11)

"""_republished reads upstream_down_since(...)[1]
when `held` is true, but 0.28.x made `held` true in two cases where no
upstream is down: _mqtt_handing_back (the minute after MQTT reconnects)
and _held_by_upstream's _bridge_down_pending branch. For a device muted
for unavailable that went down as a whole (a broker restart writes every
MQTT entity unavailable, which saves DEV_DOWN_SINCE), the value handed
back raises TypeError ('NoneType' object is not subscriptable) inside
the state_changed callback. Once, held was
upstream_down_since(...) is not None.

Asserts the correct behaviour: no exception, and the value is judged a
republish.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
)

from .helpers import register_device, setup_entry


async def _muted_mqtt_device(hass: HomeAssistant):
    device, entities = register_device(hass, "plug", name="Plug")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "on")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[device.id] = "mqtt"
    coord._unavailable_muted = lambda device_id: device_id == device.id
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    now = dt_util.utcnow().timestamp()
    # Gone as a whole ten seconds ago, as the broker dropped.
    record[DEV_DOWN_SINCE] = [now - 10, "unavailable"]
    return coord, device, entity_id, now


async def test_mqtt_hand_back_of_a_muted_device_does_not_raise(hass: HomeAssistant):
    coord, device, entity_id, now = await _muted_mqtt_device(hass)
    assert coord.upstream_down_since(device.id) is None
    coord._mqtt_reconnected_at = now  # MQTT just reconnected
    old = State(entity_id, "unavailable")
    # Must not raise: no upstream is down, so there is nothing to index.
    result = coord._republished(device.id, old, (now - 10, "unavailable"))
    assert isinstance(result, bool)


async def test_pending_bridge_hold_of_a_muted_device_does_not_raise(hass: HomeAssistant):
    coord, device, entity_id, now = await _muted_mqtt_device(hass)
    coord._stack_for_device = lambda device_id: "z2m" if device_id == device.id else None
    coord._bridge_down_pending = {"z2m": now - 5}
    assert coord.upstream_down_since(device.id) is None
    assert coord._held_by_upstream(device.id, now)
    old = State(entity_id, "unavailable")
    result = coord._republished(device.id, old, (now - 10, "unavailable"))
    assert isinstance(result, bool)
