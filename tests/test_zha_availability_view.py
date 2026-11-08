# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_zha_availability_view.py, Version: 0.28.5 (2026-11-08)

"""ZHA's own view beside a verdict (rule STACK-04).

ZHA keeps its own judgment of each device: whether it is available, when
its radio last heard it, and how long it waits before marking it
unavailable, 6 hours for a battery device and 2 hours for a mains one by
default. Read from ZHA's own objects, it is told beside a verdict as
Zigbee2MQTT's Availability is; anything ZHA does not hold where expected
is no opinion, and the sentence is left out.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.interventions import zha_phrase

from .helpers import setup_coordinator
from .outage_helpers import PIN

IEEE = "00:15:8d:00:01:02:03:04"
NOW = 1_794_000_000.0


def _zha(hass, options=None):
    source = MockConfigEntry(domain="zha", options=options or {})
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("zha", IEEE)}, name="Door Hall",
    )
    entity = er.async_get(hass).async_get_or_create(
        "binary_sensor", "zha", f"{IEEE}-1-1280", device_id=device.id, config_entry=source,
    )
    return device, entity.entity_id


def _radio(hass, available=True, mains=False, last_seen=NOW - 180):
    zha_device = SimpleNamespace(available=available, is_mains_powered=mains, last_seen=last_seen)
    hass.data["zha"] = SimpleNamespace(
        gateway_proxy=SimpleNamespace(device_proxies={IEEE.upper(): SimpleNamespace(device=zha_device)})
    )


async def test_a_battery_device_carries_the_six_hour_default(hass: HomeAssistant):
    device, _ = _zha(hass)
    _radio(hass)
    view = stack_zha.availability_view(hass, device)
    assert view == {"available": True, "last_seen": NOW - 180, "class": "battery", "timeout_seconds": 21600}


async def test_zha_settings_change_the_timeout(hass: HomeAssistant):
    options = {"custom_configuration": {"zha_options": {
        "consider_unavailable_battery": 3600, "consider_unavailable_mains": 1800}}}
    device, _ = _zha(hass, options)
    _radio(hass, mains=True)
    assert stack_zha.availability_view(hass, device)["timeout_seconds"] == 1800
    _radio(hass, mains=False)
    assert stack_zha.availability_view(hass, device)["timeout_seconds"] == 3600


async def test_zha_holding_nothing_where_expected_is_no_opinion(hass: HomeAssistant):
    device, _ = _zha(hass)
    assert stack_zha.availability_view(hass, device) is None
    hass.data["zha"] = SimpleNamespace(gateway_proxy=SimpleNamespace(device_proxies={}))
    assert stack_zha.availability_view(hass, device) is None
    _radio(hass, available="yes")
    assert stack_zha.availability_view(hass, device) is None


def test_the_sentences():
    battery = {"available": True, "last_seen": NOW - 180, "class": "battery", "timeout_seconds": 21600}
    assert zha_phrase(battery, NOW) == (
        "ZHA reads it as available and last heard from it 3 minutes ago. "
        "ZHA waits 6 hours of silence from a battery device before it marks it unavailable."
    )
    mains = {"available": True, "last_seen": NOW - 20, "class": "mains", "timeout_seconds": 7200}
    assert zha_phrase(mains, NOW) == (
        "ZHA reads it as available and last heard from it less than a minute ago. "
        "ZHA waits 2 hours of silence from a mains device before it marks it unavailable."
    )
    assert zha_phrase({"available": False}, NOW) == "ZHA confirms it is unavailable."
    unheard = {"available": True, "last_seen": None, "class": "battery", "timeout_seconds": 21600}
    assert zha_phrase(unheard, NOW).startswith("ZHA reads it as available. ZHA waits 6 hours")
    assert zha_phrase(None, NOW) is None


async def test_the_sentence_reaches_the_verdict(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, eid = _zha(hass)
    hass.states.async_set(eid, "off")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    _radio(hass, last_seen=dt_util.utcnow().timestamp() - 600)
    phrase = coord.reachability_phrase(device.id)
    assert phrase.startswith("ZHA reads it as available and last heard from it 10 minutes ago.")
    # ZHA unreadable: the verdict stands alone.
    hass.data.pop("zha")
    assert coord.reachability_phrase(device.id) is None
