# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_broker_reconnect_handback.py, Version: 0.28.12 (2026-11-11)

"""A broker restart shorter than the minute check (rules UNAV-05, WATCH-12, UP-02).

Real Home Assistant: when the MQTT client loses the broker, every MQTT
entity writes unavailable (MqttAvailabilityMixin.available reads
client.connected) and, on reconnect, writes back the value it already
held, with no message from any device. A Mosquitto add-on restart or
update takes about ten seconds, so both writes fall between two minute
checks: no broker hold is ever open, the Zigbee2MQTT bridge reader is
back to running by the next sample, and the broker reader only shows a
regression after the fact.

The value written back is the integration handing back its cache, not
the device speaking. A frozen Zigbee2MQTT device with no Last Seen
clock (Zigbee2MQTT's default) must stay frozen, and its clock must not
move.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BROKER_RUNNING,
    DATA_BROKER_SEEN,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
)

from .test_bridge_hold import _minutes
from .test_recovery_one_way import _clockless


def _broker(started_at, regressed):
    return SimpleNamespace(
        state=BROKER_RUNNING,
        started_at=started_at,
        stopped_at=None,
        loaded=True,
        regressed_since=lambda known: regressed,
        async_stop=lambda: None,
    )


async def test_a_short_broker_restart_does_not_revive_a_frozen_device(
    hass: HomeAssistant, freezer
):
    coord, device, entity_id, record = await _clockless(hass, freezer)
    start = dt_util.utcnow().timestamp() - 86400
    coord._broker_reader = _broker(start, regressed=False)
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING, "started": start}
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    heard = record[DEV_LAST_ACTIVITY]

    # Mosquitto restarts between two minute checks: the MQTT entity goes
    # unavailable (not a restored placeholder) and writes its own held
    # value back ten seconds later.
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    freezer.tick(20)
    # MQTT says so on its own signal, as the real client does.
    async_dispatcher_send(hass, "mqtt_connection_state", False)
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(10)
    async_dispatcher_send(hass, "mqtt_connection_state", True)
    hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    # The broker reader now shows the restart.
    coord._broker_reader = _broker(dt_util.utcnow().timestamp() - 5, regressed=True)

    await _minutes(hass, coord, freezer, 3)
    assert record[DEV_LAST_ACTIVITY] == heard, "the broker's hand-back moved the clock"
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "a broker restart revived a frozen device"
