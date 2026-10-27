# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: push_helpers.py, Version: 0.27.7 (2026-10-27)

"""Devices, a phone and a bus listener for the push tests (rules LIST-03, LIST-06, NOTE-08)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES, DEV_BATTERY_LOW, DEV_BATTERY_SINCE, DEV_BATTERY_VALUE, DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY, DEV_FROZEN_SINCE, DEV_LAST_ACTIVITY,
)


def device(hass, uid, name, battery=False):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=name)
    reg = er.async_get(hass)
    ent = reg.async_get_or_create("sensor", "test", f"{uid}_0", device_id=dev.id, config_entry=source)
    if battery:
        reg.async_get_or_create("sensor", "test", f"{uid}_pct", device_id=dev.id,
                                config_entry=source, original_device_class="battery")
    hass.states.async_set(ent.entity_id, "21.5")
    ENTITY[dev.id] = ent.entity_id
    return dev


ENTITY: dict[str, str] = {}


def unavailable(hass, dev):
    """Make the device's entity read unavailable, as Home Assistant would."""
    hass.states.async_set(ENTITY[dev.id], "unavailable")


def phone(hass):
    calls = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", "phone", handler)
    return calls


def bus(hass, *types):
    seen = []
    for event_type in types:
        @callback
        def _rec(event: Event, _t=event_type):
            seen.append((_t, dict(event.data)))
        hass.bus.async_listen(event_type, _rec)
    return seen


def down(coord, dev, category, ago=600.0):
    rec = coord.data[DATA_DEVICES][dev.id]
    rec.setdefault(DEV_DAILY_MAX, [])
    rec[DEV_FROZEN_CATEGORY] = category
    rec[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - ago
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - ago - 100


def up(coord, dev):
    rec = coord.data[DATA_DEVICES][dev.id]
    rec[DEV_FROZEN_CATEGORY] = None
    rec[DEV_FROZEN_SINCE] = None
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()


def battery_low(coord, dev, on=True):
    rec = coord.data[DATA_DEVICES][dev.id]
    rec[DEV_BATTERY_LOW] = on
    rec[DEV_BATTERY_VALUE] = 12.0 if on else 90.0
    rec[DEV_BATTERY_SINCE] = dt_util.utcnow().isoformat() if on else None


async def sync(hass, coord):
    coord._sync_problem_list()
    await hass.async_block_till_done()


def messages(calls):
    return [c["message"] for c in calls]
