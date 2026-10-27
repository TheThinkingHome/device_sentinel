# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_event_counts.py, Version: 0.27.10 (2026-10-27)

"""The devices count on a Wi-Fi outage's bus events (rule UP-10).

The devices count is the same on the down and the restored event. A
restored that carried the tie count at the close would give the pair
two different counts whenever ties were rebuilt during the outage.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.test_wifi_outage import (
    _declared,
    _fall,
    _heard,
    _house,
    _rise,
    _tracker,
    _wifi_device,
)


async def test_the_down_event_counts_only_claimed_devices_as_confirmed(
    hass: HomeAssistant, freezer
):
    """A Wi-Fi down carries how many claimed devices already read
    unavailable (rule UP-10). A tied device whose tracker was away hours
    before the outage is not claimed (rule UP-15), so its unavailable
    entity is not counted.
    """
    coord, trackers, devices, _untied = await _house(hass, 6)
    heard = _heard(hass)
    await _fall(hass, trackers[5])
    entity_id = er.async_get(hass).async_get_entity_id("sensor", "wifi_hub", "d5")
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers, freezer, count=3)
    assert coord.upstream_down_since(devices[5].id) is None
    downs = [data for label, data in heard if label == "down"]
    assert len(downs) == 1
    assert downs[0]["confirmed"] == 0, downs[0]


async def test_the_down_event_counts_a_claimed_device_reading_unavailable(
    hass: HomeAssistant, freezer
):
    """And a claimed device already unavailable is counted."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    heard = _heard(hass)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", "wifi_hub", "d0")
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    await _declared(hass, coord, trackers, freezer, count=3)
    assert coord.upstream_down_since(devices[0].id) is not None
    downs = [data for label, data in heard if label == "down"]
    assert [d["confirmed"] for d in downs] == [1]


async def test_the_restored_carries_the_count_the_down_announced(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, _untied = await _house(hass, 4)
    heard = _heard(hass)
    await _declared(hass, coord, trackers, freezer, count=3)

    # A fifth tied device appears while the network is down.
    source = MockConfigEntry(domain="wifi_hub", title="second hub")
    source.add_to_hass(hass)
    _tracker(hass, "t_new", "AA-BB-CC-00-01-FF")
    _wifi_device(hass, source, "d_new", "New Device", "aa:bb:cc:00:01:ff")
    coord._rebuild_registry_view()
    assert len(coord._wifi_ties) == 5

    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None

    pairs = [(label, data["devices"]) for label, data in heard]
    assert pairs == [("down", 4), ("restored", 4)]
