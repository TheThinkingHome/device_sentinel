# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_unknown_since_the_start.py, Version: 0.27.10 (2026-10-27)

"""An entity unknown because nothing has arrived since the start counts
for nothing: it starts no unknown problem and ends none (rule LIST-06).

Repeaters that report only now and then read unknown after each
restart for over an hour. Unknown is neither down nor alive; these
tests hold that on ZHA and on another integration, with and without
Home Assistant's "unavailable" placeholders at the start.
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    DATA_TODO_ITEMS,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import setup_entry
from .outage_helpers import PIN, arm, past_grace, rec, restart, verdict, walk

SIGNAL = [
    ("rssi", {"device_class": "signal_strength", "unit_of_measurement": "dBm"}, "-70"),
    ("lqi", {}, "191"),
]


def _repeater(hass, domain):
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, "rep")}, name="Repeater Hall")
    eids = []
    for suffix, attrs, value in SIGNAL:
        entity = er.async_get(hass).async_get_or_create(
            "sensor", domain, f"rep_{suffix}", device_id=device.id, config_entry=source,
            original_device_class=attrs.get("device_class"))
        eids.append((entity.entity_id, attrs, value))
    return device, eids


async def _armed(hass, freezer, monkeypatch, domain):
    heard = {"at": None}
    monkeypatch.setattr(stack_zha, "last_heard", lambda _h, _d: heard["at"])
    freezer.move_to(PIN)
    device, eids = _repeater(hass, domain)
    for eid, attrs, value in eids:
        hass.states.async_set(eid, value, attrs)
    coord = (await setup_entry(hass)).runtime_data
    arm(coord, device.id, rhythm=36000.0)
    heard["at"] = dt_util.utcnow().timestamp()
    rec(coord, device.id)[DEV_LAST_ACTIVITY] = heard["at"]
    await past_grace(hass, freezer)
    await walk(hass, freezer, 600)
    return coord, device, eids


def _unknown(hass, eids):
    def go():
        for eid, attrs, _value in eids:
            hass.states.async_set(eid, "unknown", attrs)
    return go


@pytest.mark.parametrize("domain", ["zha", "test"])
@pytest.mark.parametrize("placeholders", [False, True])
async def test_unknown_since_the_start_starts_no_problem(
    hass: HomeAssistant, freezer, monkeypatch, domain, placeholders
):
    coord, device, eids = await _armed(hass, freezer, monkeypatch, domain)
    coord = await restart(hass, freezer, down=120, before_setup=_unknown(hass, eids),
                          placeholders=placeholders)
    for _ in range(90):
        await walk(hass, freezer, 60)
        assert verdict(rec(coord, device.id))[0] is None
    assert coord.data[DATA_TODO_ITEMS] == []


async def test_unknown_since_the_start_ends_no_problem(hass: HomeAssistant, freezer, monkeypatch):
    coord, device, eids = await _armed(hass, freezer, monkeypatch, "test")
    for eid, attrs, _value in eids:
        hass.states.async_set(eid, "unavailable", attrs)
    for _ in range(10):
        await walk(hass, freezer, 60)
    assert verdict(rec(coord, device.id))[0] == FREEZE_CATEGORY_UNAVAILABLE
    coord = await restart(hass, freezer, down=120, before_setup=_unknown(hass, eids))
    for _ in range(60):
        await walk(hass, freezer, 60)
        assert verdict(rec(coord, device.id))[0] == FREEZE_CATEGORY_UNAVAILABLE
    # It counts once it has given a value in this run.
    eid, attrs, _value = eids[0]
    hass.states.async_set(eid, "-65", attrs)
    await walk(hass, freezer, 120)
    assert verdict(rec(coord, device.id))[0] is None
