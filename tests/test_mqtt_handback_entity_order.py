# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_mqtt_handback_entity_order.py, Version: 0.28.12 (2026-11-11)

"""MQTT's hand-back after a broker reconnect, in the
order a real Home Assistant runs it.

In a real house every MQTT entity connects its own target to the
"mqtt_connection_state" signal when it is added, and that target is a
callback that writes the entity's state at once
(MqttAvailabilityMixin.async_mqtt_connection_state_changed). The
dispatcher calls targets in the order they connected, and the state
write fires state_changed to Device Sentinel's callback listener
synchronously. So for every MQTT entity added before Device Sentinel
connected its own target (any entity after a reload of Device
Sentinel, most of them at a real start), the value is handed back
BEFORE _on_mqtt_connection sets _mqtt_reconnected_at.

The shipped test sends the signal first and sets the state after it,
which a real Home Assistant never does for those entities.

Asserts the correct behaviour: the hand-back does not move a frozen
device's clock.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_RUNNING,
    BROKER_RUNNING,
    DATA_BROKER_SEEN,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    STACK_Z2M,
)

from .helpers import register_device, setup_entry
from .test_bridge_hold import _minutes
from .test_bridge_pairing import _Stub
from .test_broker_reconnect_handback import _broker


async def test_hand_back_from_an_entity_older_than_device_sentinel(
    hass: HomeAssistant, freezer
):
    device, entities = register_device(hass, "lamp", name="Lamp")
    entity_id = entities[0] if isinstance(entities, list) else entities
    held = {"value": "on"}
    hass.states.async_set(entity_id, "on")

    # The MQTT entity, added before Device Sentinel set up: its own
    # target on the signal, a callback writing its state at once.
    @callback
    def _entity_target(connected: bool) -> None:
        hass.states.async_set(entity_id, held["value"] if connected else "unavailable")

    async_dispatcher_connect(hass, "mqtt_connection_state", _entity_target)

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[device.id] = "mqtt"
    coord._stack_for_device = lambda device_id: STACK_Z2M if device_id == device.id else None
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 5000
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    record[DEV_LAST_ACTIVITY] = (dt_util.utcnow() - timedelta(hours=5)).timestamp()

    start = dt_util.utcnow().timestamp() - 86400
    coord._broker_reader = _broker(start, regressed=False)
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING, "started": start}
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    heard = record[DEV_LAST_ACTIVITY]

    # Mosquitto restarts between two minute checks. MQTT sends its
    # signal; the entity's target runs first, as it connected first.
    freezer.tick(20)
    async_dispatcher_send(hass, "mqtt_connection_state", False)
    await hass.async_block_till_done()
    freezer.tick(10)
    async_dispatcher_send(hass, "mqtt_connection_state", True)
    await hass.async_block_till_done()
    coord._broker_reader = _broker(dt_util.utcnow().timestamp() - 5, regressed=True)

    await _minutes(hass, coord, freezer, 3)
    assert record[DEV_LAST_ACTIVITY] == heard, "the broker's hand-back moved the clock"
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "a broker restart revived a frozen device"
