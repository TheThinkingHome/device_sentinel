# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_zha_last_seen.py, Version: 0.27.10 (2026-10-27)

"""ZHA's own Last Seen clock (rules STACK-04, STACK-08).

ZHA keeps, for every device, when its radio last heard it. A value that
comes back after ZHA restarts or reloads is the device speaking only if
the radio heard it since its last report; otherwise it is ZHA handing
back what it kept, and a frozen device stays frozen (rule WATCH-12).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, rec, walk

H = 3600


def _zha_device(hass, uid):
    source = MockConfigEntry(domain="zha")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("zha", uid)}, name=f"Device {uid}")
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "zha", f"{uid}_t", device_id=device.id, config_entry=source)
    return device, entity.entity_id


async def _frozen(hass, freezer, monkeypatch, uid):
    """A ZHA device that reports once and dies silent until frozen."""
    heard = {"at": None}

    def last_heard(_hass, _device):
        return heard["at"]

    monkeypatch.setattr(stack_zha, "last_heard", last_heard)
    freezer.move_to(PIN)
    device, eid = _zha_device(hass, uid)
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    heard["at"] = dt_util.utcnow().timestamp()
    hass.states.async_set(eid, "21.6")
    await hass.async_block_till_done()
    record = rec(coord, device.id)
    for _ in range(5 * 60):
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            break
        await walk(hass, freezer, 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    return coord, device, eid, record, heard


@pytest.mark.parametrize("seconds", [20, 60, 120])
async def test_a_zha_restart_does_not_revive_a_frozen_device(
    hass: HomeAssistant, freezer, monkeypatch, seconds
):
    """ZHA restarts for `seconds`: its entities read unavailable, then
    come back with the kept value. The radio never heard the device, so
    it stays frozen and no recovery is told."""
    coord, device, eid, record, heard = await _frozen(hass, freezer, monkeypatch, f"z{seconds}")
    events = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=seconds))
    await walk(hass, freezer, 60)
    hass.states.async_set(eid, "21.6")
    await hass.async_block_till_done()
    await walk(hass, freezer, 180)
    assert record[DEV_FROZEN_CATEGORY] is not None, "a cached value revived a dead ZHA device"
    assert not [e for e in events if e.get("device_id") == device.id]


async def test_a_zha_device_heard_again_recovers(hass: HomeAssistant, freezer, monkeypatch):
    """The same restart, but the radio hears the device as it comes
    back: that is the device speaking, and it recovers at once."""
    coord, device, eid, record, heard = await _frozen(hass, freezer, monkeypatch, "zh")
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    heard["at"] = dt_util.utcnow().timestamp()
    hass.states.async_set(eid, "22.4")
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_LAST_ACTIVITY] >= heard["at"] - 1


async def test_the_device_page_names_zha_as_the_clock(hass: HomeAssistant, freezer, monkeypatch):
    coord, device, eid, record, heard = await _frozen(hass, freezer, monkeypatch, "zp")
    page = coord.dashboard_device(device.id)
    assert page["identity"]["clock"] == "zha"
    heard["at"] = None
    assert coord.dashboard_device(device.id)["identity"]["clock"] == "recorded"


class _Proxy:
    def __init__(self, seen):
        self.device = type("Device", (), {"last_seen": seen})()


class _Key:
    """Stands in for zigpy's EUI64, which prints as the ieee address."""

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


def _zha_data(proxies):
    gateway = type("Gateway", (), {"device_proxies": proxies})()
    return type("Data", (), {"gateway_proxy": gateway})()


async def test_zha_s_own_record_is_read_where_zha_keeps_it(hass: HomeAssistant):
    """Read from what ZHA keeps in Home Assistant's data, by the
    device's ieee address, without importing ZHA."""
    device, _ = _zha_device(hass, "00:11:22:33:44:55:66:77")
    hass.data["zha"] = _zha_data({
        _Key("aa:bb:cc:dd:ee:ff:00:11"): _Proxy(1.0e9),
        _Key("00:11:22:33:44:55:66:77"): _Proxy(1791700000.5),
    })
    assert stack_zha.last_heard(hass, device) == 1791700000.5


@pytest.mark.parametrize("data", [
    None,
    "not ZHA's data",
    _zha_data({}),
    _zha_data({_Key("00:11:22:33:44:55:66:79"): _Proxy(1.0e9)}),
    _zha_data({_Key("00:11:22:33:44:55:66:78"): _Proxy(None)}),
    _zha_data({_Key("00:11:22:33:44:55:66:78"): _Proxy(float("nan"))}),
    _zha_data({_Key("00:11:22:33:44:55:66:78"): _Proxy(True)}),
])
async def test_an_unreadable_zha_reads_as_no_clock(hass: HomeAssistant, data):
    """Anything not where it is expected (no ZHA data, another device
    only, no time or a damaged one) reads as no clock, and the device
    is judged as one without a Last Seen clock."""
    device, _ = _zha_device(hass, "00:11:22:33:44:55:66:78")
    if data is not None:
        hass.data["zha"] = data
    assert stack_zha.last_heard(hass, device) is None
