# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_upstream_outage_row.py, Version: 0.27.4 (2026-10-25)

"""An upstream outage on a healthy house is reported (rules UP-05, UP-08,
UP-09, UP-11).

A device's verdict is held while its upstream is down, so on a house
that was healthy when the broker, a bridge or an integration went, no
device behind it was ever judged, and the row, its push and its count,
all built from verdicts, never appeared. The count is now what the
devices read: each one behind the upstream reading unavailable counts,
devices muted for unavailable included, while the devices themselves
stay off the list. The push reads the row's words, and the recovery
push says how long the upstream was down.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    LEARNING_MIN_DAYS,
    STACK_Z2M,
)

from tests.helpers import setup_coordinator
from tests.outage_helpers import PIN, arm, past_grace, walk
from tests.test_bridge_hold import _switch
from tests.test_bridge_pairing import _Stub
from tests.test_outage_pairs_and_counts import DOM, _all, _down, _entry, _up


def _rows(coord):
    return [i.get("summary") for i in coord.todo_items]


def _messages(phone):
    return [c.data.get("message") for c in phone]


async def test_integration_outage_of_a_healthy_house(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    devices = [d for d, _ in _all([a])]
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    phone = async_mock_service(hass, "notify", "phone")
    coord = await setup_coordinator(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
            CONF_UNAVAILABLE_MUTED_DEVICES: [devices[2].id],
        },
    )
    records = [arm(coord, d.id, rhythm=600.0) for d in devices]
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for k in range(6):
        for _, ids in _all([a]):
            hass.states.async_set(ids[1], str(10 + k))
        await walk(hass, freezer, 600)
    phone.clear()

    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)

    # One row for the integration, counting all three, the muted one
    # included; no device row of its own.
    assert _rows(coord) == [f"{DOM} down: 3 of 3 total devices unavailable"]
    assert [r.get(DEV_FROZEN_CATEGORY) for r in records] == [None, None, None]
    # One push, in the row's words.
    assert _messages(phone) == [f"{DOM} down: 3 of 3 total devices unavailable."]

    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    # The recovering row, while its devices rejoin: all three are back.
    assert _rows(coord) == [f"{DOM} recovering: 0 of the 3 devices that went down remain unavailable"]
    await walk(hass, freezer, 14 * 60)
    assert _rows(coord) == []

    # The recovery push gives how long it was down, in the brief's words.
    messages = _messages(phone)
    assert len(messages) == 2
    assert messages[1].startswith(f"The {DOM} integration came back at ")
    assert "after 20m." in messages[1]
    assert messages[1].endswith("3 of its 3 devices went down.")
    back = [
        r for r in coord.data[DATA_SYSTEM_EVENTS]
        if r.get("scope") == DOM and r.get("kind") == "integration_up"
    ]
    assert back and back[-1].get("worst") == 3


async def _z2m_house(hass, n=3, options=None):
    devs = [_switch(hass, f"sw{i}", f"Switch {i}") for i in range(n)]
    now = dt_util.utcnow().isoformat()
    for _, value, seen in devs:
        hass.states.async_set(value, "56")
        hass.states.async_set(seen, now)
    phone = async_mock_service(hass, "notify", "phone")
    coord = await setup_coordinator(
        hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"], **(options or {})}
    )
    coord._grace_until = 0.0
    for device, _, _ in devs:
        coord._watched[device.id] = "mqtt"
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_EVENT_COUNT] = 5000
        record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._stacks.add(STACK_Z2M)
    return coord, devs, phone


async def _minutes(hass, coord, freezer, count, devs=None):
    for _ in range(count):
        # The registry here holds no Zigbee2MQTT bridge, so a rebuild
        # would forget the stack the test drives by hand.
        coord._stacks.add(STACK_Z2M)
        freezer.tick(60)
        for _, _, seen in devs or ():
            hass.states.async_set(seen, dt_util.utcnow().isoformat())
        await coord._on_render_tick(None)
        await hass.async_block_till_done()


async def test_bridge_outage_of_a_healthy_house(hass: HomeAssistant, freezer):
    coord, devs, phone = await _z2m_house(hass)
    await _minutes(hass, coord, freezer, 5, devs)
    records = [coord.data[DATA_DEVICES][d.id] for d, _, _ in devs]
    phone.clear()

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    # Before any device reads down, the row is there and says so.
    await _minutes(hass, coord, freezer, 1)
    assert _rows(coord) == ["Zigbee2MQTT down: 0 of 3 total devices unavailable"]
    for _, value, seen in devs[:2]:
        hass.states.async_set(value, "unavailable")
        hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 15)
    assert [r.get(DEV_FROZEN_CATEGORY) for r in records] == [None] * 3
    assert _rows(coord) == ["Zigbee2MQTT down: 2 of 3 total devices unavailable"]
    # Named as a person would, never by the key "z2m".
    assert _messages(phone) == ["Zigbee2MQTT down: 2 of 3 total devices unavailable."]

    # Back, with one device still to rejoin: the recovering row counts it.
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(devs[0][1], "57")
    hass.states.async_set(devs[0][2], dt_util.utcnow().isoformat())
    await _minutes(hass, coord, freezer, 1)
    assert _rows(coord) == [
        "Zigbee2MQTT recovering: 1 of the 2 devices that went down remains unavailable"
    ]
    assert len(_messages(phone)) == 1  # the recovering phase sends nothing
    hass.states.async_set(devs[1][1], "57")
    hass.states.async_set(devs[1][2], dt_util.utcnow().isoformat())
    await _minutes(hass, coord, freezer, 5)
    messages = _messages(phone)
    assert len(messages) == 2
    assert messages[1].startswith("The Zigbee2MQTT bridge came back at ")
    assert " after " in messages[1]
    assert messages[1].endswith("2 of its 3 devices went down.")


async def test_broker_outage_of_a_healthy_house(hass: HomeAssistant, freezer):
    coord, devs, phone = await _z2m_house(hass)
    coord._bridge_readers.clear()  # a broker-only house, as Tasmota over MQTT
    await _minutes(hass, coord, freezer, 5, devs)
    phone.clear()
    coord._broker_down_at = dt_util.utcnow().timestamp()
    for _, value, seen in devs:
        hass.states.async_set(value, "unavailable")
        hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 15)
    assert _rows(coord) == ["MQTT broker down: 3 of 3 total devices unavailable"]
    assert _messages(phone) == ["MQTT broker down: 3 of 3 total devices unavailable."]


async def test_push_counts_a_device_muted_for_unavailable(hass: HomeAssistant, freezer):
    coord, devs, phone = await _z2m_house(
        hass, n=2, options={}
    )
    muted = devs[1][0].id
    coord._unavailable_muted = lambda device_id: device_id == muted
    await _minutes(hass, coord, freezer, 3, devs)
    phone.clear()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    for _, value, seen in devs:
        hass.states.async_set(value, "unavailable")
        hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 5)
    assert coord._upstream_devices(STACK_Z2M) == 2
    assert _messages(phone) == ["Zigbee2MQTT down: 2 of 2 total devices unavailable."]
