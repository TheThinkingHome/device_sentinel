# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_empty_fallen_set.py, Version: 0.27.10 (2026-10-27)

"""A Wi-Fi outage with nothing in its fallen set (rule UP-16).

A Wi-Fi outage ends when the devices that dropped with it come back;
with none dropped, it ends when the network is heard again. Otherwise
an outage the scan declared before any tied tracker left would stay
open until the next restart, its row reading "waiting for 0 devices to
reconnect", and claim every non-radio device that failed meanwhile
instead of listing it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    EVENT_UPSTREAM_DOWN,
    EVENT_UPSTREAM_RESTORED,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_UP,
    WIFI_KEY,
)

from tests.helpers import record_labelled, register_device, setup_coordinator
from tests.outage_helpers import walk
from tests.test_wifi_outage import _house, _rise


def _pairs(hass):
    return record_labelled(hass, {
        EVENT_UPSTREAM_DOWN: "down",
        EVENT_UPSTREAM_RESTORED: "restored",
    })


async def test_an_outage_with_no_ties_ends_when_the_network_is_heard(
    hass: HomeAssistant, freezer
):
    """A chosen network with no ties at all. The network comes back, the
    outage ends, and a device that fails afterwards for its own reasons
    is listed on its own.
    """
    device, _ = register_device(hass, "plug", "Plug Later Broken")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    heard = _pairs(hass)
    now = dt_util.utcnow().timestamp()
    coord._wifi_scan_down_at = now - 120
    coord.on_wifi_scan_down(now - 120, ["Home"])
    assert coord._wifi_down_at is not None
    assert not coord._wifi_fallen

    coord._wifi_scan_restore(now)
    await hass.async_block_till_done()
    assert coord._wifi_down_at is None
    assert [label for label, _data in heard] == ["down", "restored"]
    kinds = [row["kind"] for row in coord.data[DATA_SYSTEM_EVENTS]]
    assert SYS_WIFI_UP in kinds
    # Nothing to reconnect, so no recovering phase is written.
    assert SYS_WIFI_RECOVERING not in kinds

    await walk(hass, freezer, 3600)
    rec = coord.data[DATA_DEVICES][device.id]
    rec[DEV_FROZEN_CATEGORY] = "unavailable"
    rec[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp()
    assert coord.upstream_down_since(device.id) is None
    assert WIFI_KEY not in coord.suppressed_down_counts


async def test_a_tied_house_whose_trackers_never_left_ends_on_hearing(
    hass: HomeAssistant, freezer
):
    """The network is back before the router marked anyone away. The
    row never reads "waiting for 0 devices", because the outage is
    over."""
    coord, _trackers, _devices, _untied = await _house(hass, 6)
    now = dt_util.utcnow().timestamp()
    coord._wifi_scan_down_at = now - 90
    coord.on_wifi_scan_down(now - 90, ["Home"])
    assert coord.wifi_down_at is not None
    coord._sample_wifi(now - 30)
    # Still down: the network has not been heard.
    assert coord.wifi_down_at is not None

    coord._wifi_scan_restore(now)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    summaries = [item.get("summary") or "" for item in coord.todo_items]
    assert not any("waiting for 0" in s for s in summaries)


async def test_an_outage_with_fallen_trackers_still_waits_for_them(
    hass: HomeAssistant, freezer
):
    """The control: with trackers in the fallen set, hearing the
    network starts the recovery and does not end the outage."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    now = dt_util.utcnow().timestamp()
    for tracker in trackers[:3]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()
    coord._wifi_scan_down_at = now
    coord.on_wifi_scan_down(now, ["Home"])
    assert len(coord.wifi_fallen_set) == 3

    coord._wifi_scan_restore(now + 60)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is not None
    assert coord.wifi_recovering_at is not None

    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(now + 120)
    assert coord.wifi_down_at is None
