# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_broker_loading_hold.py, Version: 0.27.5 (2026-10-26)

"""Which devices wait with a broker still loading at a start (rule UP-04).

Inside the startup grace, a broker that reads down holds only the
devices that reach Home Assistant through it: MQTT's own, Zigbee2MQTT's
among them, and those of an integration that depends on MQTT, such as
Tasmota. A ZHA or Z-Wave device does not wait with it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.device_sentinel.const import (
    BRIDGE_RUNNING,
    BROKER_DOWN,
    BROKER_RUNNING,
    DATA_BROKER_SEEN,
    STACK_Z2M,
)

from tests.helpers import register_device, setup_coordinator
from tests.test_bridge_pairing import _Stub
from tests.test_upstream_loading import _broker


async def test_a_loading_broker_holds_only_its_own_riders(hass: HomeAssistant):
    await async_get_integration(hass, "tasmota")  # its manifest names mqtt
    coord = await setup_coordinator(hass)
    made = {}
    for name, domain in (
        ("z2m", "mqtt"), ("plug", "tasmota"), ("zha", "zha"), ("zwave", "zwave_js"),
    ):
        device, _ = register_device(hass, name, name)
        coord._watched[device.id] = domain
        made[name] = device.id
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._bridge_readers["zha"] = _Stub(BRIDGE_RUNNING)
    coord._bridge_readers["zwave_js"] = _Stub(BRIDGE_RUNNING)
    # Heard in the run before, down in this one, inside the grace.
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING}
    coord._broker_reader = _broker(BROKER_DOWN, False)
    assert coord._in_startup_grace()
    assert coord._rides_the_broker(made["plug"])
    held = coord.loading_held()
    assert held == {made["z2m"], made["plug"]}, held


def _listed(coord, device_id) -> bool:
    return any(i.get("device_id") == device_id for i in coord.todo_items)


async def test_a_device_that_reports_inside_the_grace_is_not_held(
    hass: HomeAssistant, freezer
):
    """It came through the broker, so it leaves its verdict and the
    Problem List at once, whatever the broker's own reading (rules
    WATCH-10, UP-04)."""
    from homeassistant.util import dt as dt_util

    from custom_components.device_sentinel.const import (
        BRIDGE_SEEN_STATE,
        DEV_FROZEN_CATEGORY,
        DEV_LAST_ACTIVITY,
    )
    from tests.outage_helpers import arm, past_grace, rec, walk

    device, (eid,) = register_device(hass, "plug", "Plug")
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert _listed(coord, device.id)
    # A start: the device reaches Home Assistant through MQTT, and the
    # broker, heard in the run before, has not been heard loaded yet.
    coord._watched[device.id] = "mqtt"
    coord.data[DATA_BROKER_SEEN] = {BRIDGE_SEEN_STATE: BROKER_RUNNING, "started": 1.0}
    coord.upstreams_loaded_after.pop("broker", None)
    coord.upstreams_loaded_after.pop("Broker", None)
    coord._reported_at.clear()
    coord._grace_until = dt_util.utcnow().timestamp() + 280
    assert coord._in_startup_grace()
    assert device.id in coord.loading_held()
    hass.states.async_set(eid, "off")  # the device really speaks
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert device.id not in coord.loading_held()
    assert not _listed(coord, device.id)
