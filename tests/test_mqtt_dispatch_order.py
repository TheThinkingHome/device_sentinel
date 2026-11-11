# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_mqtt_dispatch_order.py, Version: 0.28.12 (2026-11-11)

"""The MQTT reconnect hand-back depends on dispatcher order.

Real Home Assistant: every MQTT entity connects its own target to the
"mqtt_connection_state" signal in async_added_to_hass
(MqttAvailabilityMixin), and the dispatcher calls Callback targets in the
order they were connected, synchronously. Its target writes the state,
and the bus runs Device Sentinel's @callback state listener at once,
inside that write. So for every entity added before Device Sentinel
connected its own target (MQTT is an after_dependency, so entities known
at boot usually are, and every entity is after a reload of Device
Sentinel), the hand-back write reaches _on_state_changed BEFORE
_on_mqtt_connection has set _mqtt_reconnected_at.

The shipped test sends the signal first and writes the state after,
which is the one order a real house does not guarantee. Here the
entity's own target is connected before Device Sentinel starts, as on a
real boot. The frozen clockless device must stay frozen (rule UNAV-05).
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

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

from tests.helpers import register_device, setup_entry
from tests.test_bridge_hold import _minutes
from tests.test_bridge_pairing import _Stub


def _broker(started_at, regressed):
    return SimpleNamespace(
        state=BROKER_RUNNING,
        started_at=started_at,
        stopped_at=None,
        loaded=True,
        regressed_since=lambda known: regressed,
        async_stop=lambda: None,
    )


async def test_hand_back_from_an_entity_connected_before_device_sentinel(
    hass: HomeAssistant, freezer
):
    device, entities = register_device(hass, "lamp", name="Lamp")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "on")

    # The MQTT entity's own target, connected as MqttAvailabilityMixin
    # does in async_added_to_hass, before Device Sentinel sets up.
    @callback
    def entity_target(connected: bool) -> None:
        hass.states.async_set(entity_id, "on" if connected else "unavailable")

    async_dispatcher_connect(hass, "mqtt_connection_state", entity_target)

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

    # Mosquitto restarts between two minute checks.
    freezer.tick(20)
    async_dispatcher_send(hass, "mqtt_connection_state", False)
    await hass.async_block_till_done()
    freezer.tick(10)
    async_dispatcher_send(hass, "mqtt_connection_state", True)
    await hass.async_block_till_done()
    coord._broker_reader = _broker(dt_util.utcnow().timestamp() - 5, regressed=True)

    await _minutes(hass, coord, freezer, 3)
    assert record[DEV_LAST_ACTIVITY] == heard, (
        "the hand-back of an entity connected before Device Sentinel moved the clock"
    )
    assert record[DEV_FROZEN_CATEGORY] == "frozen", (
        "a broker restart revived a frozen device when the entity's target ran first"
    )
