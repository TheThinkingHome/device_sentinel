# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_bridge_hold.py, Version: 0.23.11 (2026-09-27)

"""A bridge going down says nothing about its devices (ruled 27 September 2026).

The reference rig, 3:40 AM on 27 September. Switch Hall Living, silent
since the afternoon and frozen, turned unavailable 0.2 seconds after
Zigbee2MQTT went down for the nightly reboot. Its frozen record closed
and unavailable opened; the bus heard it recover; at 3:47 the grace
ended and the pair swapped back, the bus hearing a second recovery; and
the brief told the one silence twice. The owner ruled: while a device's
bridge is down, it keeps what was known before, frozen, unavailable or
working, and once the bridge is back each device is judged on its own.
The hold lasts through the window #436 gives a bridge's devices to
rejoin.

The switch's clock is Zigbee2MQTT's own last seen, as it was on the
rig, so a restored value cannot revive it. A device timed by its entity
changes is #125's question, not yet ruled, and not tested here.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_HANDBACK_SECONDS,
    BRIDGE_RUNNING,
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    STACK_Z2M,
)

from .helpers import setup_entry
from .test_bridge_pairing import _Stub


def _switch(hass, uid: str, name: str):
    """A Zigbee2MQTT device with a value and a last seen, as on the rig."""
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("mqtt", uid)}, name=name,
    )
    reg = er.async_get(hass)
    value = reg.async_get_or_create(
        "sensor", "mqtt", f"{uid}_lq", device_id=device.id, config_entry=source,
    ).entity_id
    seen = reg.async_get_or_create(
        "sensor", "mqtt", f"{uid}_last_seen", device_id=device.id,
        config_entry=source, original_name="Last seen",
        suggested_object_id=f"{uid}_last_seen",
    ).entity_id
    return device, value, seen


async def _house(hass, freezer):
    device, value, seen = _switch(hass, "hall", "Switch Hall Living")
    heard = (dt_util.utcnow() - timedelta(hours=10)).isoformat()
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, heard)
    phone = async_mock_service(hass, "notify", "phone")
    bus: list[tuple[str, object]] = []
    for name in ("device_sentinel_fault", "device_sentinel_recovered"):
        hass.bus.async_listen(
            name,
            lambda event: bus.append(
                (event.event_type.rsplit("_", 1)[-1], event.data.get("kinds") or event.data.get("kind"))
            ),
        )
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[device.id] = "mqtt"
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 5000
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    return coord, device, value, seen, heard, phone, bus


async def _minutes(hass, coord, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(60)
        await coord._on_render_tick(None)
        await hass.async_block_till_done()


async def test_a_frozen_device_stays_frozen_through_its_bridge_outage(hass: HomeAssistant, freezer):
    """The switch's night: one fault, no recovery, one continuing record."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    since = record[DEV_FROZEN_SINCE]

    # 3:40: the bridge goes down and every entity reads unavailable.
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 5)
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "the bridge's outage rewrote the device"
    assert record[DEV_FROZEN_SINCE] == since

    # The bridge returns and restores the old values; the switch is
    # still silent, so its last seen is the old one.
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, heard)
    await _minutes(hass, coord, freezer, int(BRIDGE_HANDBACK_SECONDS // 60) + 10)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    assert record[DEV_FROZEN_SINCE] == since

    kinds = [(row["kind"], row["event"]) for row in coord.data[DATA_INCIDENTS]]
    assert kinds == [("frozen", "opened")], kinds
    assert bus == [("fault", ["frozen"])], bus
    messages = [call.data.get("message", "") for call in phone]
    assert len(messages) == 1 and "detected frozen" in messages[0], messages


async def test_a_healthy_device_is_not_rewritten_by_its_bridge_outage(hass: HomeAssistant, freezer):
    """Past the three-minute debounce, and still no verdict or stamp."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    now = dt_util.utcnow()
    hass.states.async_set(seen, now.isoformat())
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = now.timestamp()
    await _minutes(hass, coord, freezer, 1)
    assert record[DEV_FROZEN_CATEGORY] is None

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 8)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] is None

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    fresh = dt_util.utcnow().isoformat()
    hass.states.async_set(value, "57")
    hass.states.async_set(seen, fresh)
    await _minutes(hass, coord, freezer, 5)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not coord.data[DATA_INCIDENTS]
    assert not bus


async def test_after_the_bridge_is_back_a_device_is_judged_on_its_own(hass: HomeAssistant, freezer):
    """The hold ends with the hand-back window: a device still unavailable
    then is its own problem, as #436 already reports it."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    now = dt_util.utcnow()
    hass.states.async_set(seen, now.isoformat())
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = now.timestamp()
    await _minutes(hass, coord, freezer, 1)

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 4)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] is None, "judged inside the hand-back window"
    await _minutes(hass, coord, freezer, int(BRIDGE_HANDBACK_SECONDS // 60) + 5)
    assert record[DEV_FROZEN_CATEGORY] == "unavailable"


async def test_a_frozen_device_that_speaks_after_the_bridge_returns_recovers(hass: HomeAssistant, freezer):
    """A real return is still a recovery, heard once."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 3)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert bus == [("fault", ["frozen"]), ("recovered", "frozen")], bus
