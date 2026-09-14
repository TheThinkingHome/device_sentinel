# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_medium.py, Version: 0.21.4 (2026-09-14)

"""What a tracker's medium is, and how it is remembered.
Rulings #415, #417, #418, #427 and #428.

Written before the change, and every case here fails against 0.21.3.

Today the medium is judged from the latest reading taken while a
tracker is home, remembered in a plain dictionary that is empty
again after every restart, and read from two attribute spellings that
TP-Link does not use. On the reference fleet that leaves 29 of 40
trackers unknown and marks eight of twelve tied devices wired for one
sample at every router restart, which the next sample happens to
undo. On the second fleet, which restarts often, the census is a
snapshot of whatever was seen home since the last boot.

#415 The medium is scored from repeated evidence, wired and wireless
     counted separately, rather than fixed by one reading.
#417 What a router states outright is read as stated: TP-Link's
     `connection` carrying the network's own name, and `band`.
#418 The scores survive a restart.
#427 A tracker whose minority evidence reaches a tenth of the whole
     goes to unknown, not to its majority. Unknown keeps the tie.
#428 A reading the scoring rejects is counted per tracker and
     published, so the case for a source-restart grace can be
     measured rather than felt.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_WIFI_MEDIUM
from custom_components.device_sentinel.router_ties import (
    MEDIUM_MINORITY_SHARE,
    tracker_medium,
)

from tests.helpers import setup_coordinator
from tests.test_wifi_outage import _house


_TICKS = {}


def _home(hass, tracker: str, **attrs) -> None:
    """One reading of a tracker at home, carrying these attributes.

    A sample is one state update. Home Assistant treats a write with
    identical state and attributes as no update at all, so a loop of
    identical readings would count as one; a real router changes its
    packet counters on every poll, and this does the same.
    """
    state = hass.states.get(tracker)
    base = dict(state.attributes) if state else {"source_type": "router"}
    base.update(attrs)
    _TICKS[tracker] = _TICKS.get(tracker, 0) + 1
    base["packets_sent"] = _TICKS[tracker]
    hass.states.async_set(tracker, "home", base)


# ------------------------------------------------------------- #417


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"connection": "wired", "band": "None"}, "wired"),
        ({"connection": "IoT", "band": "2G"}, "wireless"),
        ({"connection": "host", "band": "5G"}, "wireless"),
        ({"connection": "guest"}, "wireless"),
        ({"band": "2G"}, "wireless"),
        ({"essid": "15945-IOT"}, "wireless"),
        ({"radio": "ng"}, "wireless"),
        ({"ap_mac": "aa:bb:cc:dd:ee:ff"}, "wireless"),
        ({"connection_type": "lan"}, "wired"),
        ({}, "unknown"),
        ({"band": "None"}, "unknown"),
    ],
)
def test_a_reading_is_taken_as_the_router_states_it(attrs, expected):
    """TP-Link spells the network's name into `connection` and the
    band into `band`. UniFi spells it `essid` and `radio`. Both are
    the router saying outright which medium the client is on, and
    both are read as stated. Measured on the reference fleet: 8,815
    tracker lines, zero occurrences of the UniFi spellings, 29 of 40
    trackers left unknown by reading only those."""
    assert tracker_medium({"source_type": "router", **attrs}) == expected


# ------------------------------------------------------------- #415


async def test_the_medium_is_scored_not_fixed(hass: HomeAssistant):
    """Twelve readings say wireless, one says wired. The one is what
    every router restart on the reference fleet produces, for every
    client at once, and last-reading-wins marked the device wired
    until the next sample happened to undo it."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    tracker = trackers[0]

    for _ in range(12):
        _home(hass, tracker, connection="IoT", band="2G")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()
    _home(hass, tracker, connection="wired", band="None")
    await hass.async_block_till_done()
    coord._rebuild_wifi_ties()

    assert coord.wifi_medium_of(tracker) == "wireless"
    assert tracker not in coord._wifi_wired_skipped


async def test_a_wired_device_stays_wired_across_many_readings(
    hass: HomeAssistant,
):
    """The control. A camera that reads wired every time is wired."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    tracker = trackers[0]

    for _ in range(12):
        _home(hass, tracker, connection="wired", band="None")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()

    assert coord.wifi_medium_of(tracker) == "wired"
    assert tracker in coord._wifi_wired_skipped


# ------------------------------------------------------------- #427


async def test_a_real_contradiction_goes_to_unknown(hass: HomeAssistant):
    """Six wireless, four wired. That is not a router restart, it is
    a device that cannot be told, and unknown keeps the tie."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    tracker = trackers[0]

    for _ in range(6):
        _home(hass, tracker, connection="IoT", band="2G")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()
    for _ in range(4):
        _home(hass, tracker, connection="wired", band="None")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()

    assert coord.wifi_medium_of(tracker) == "unknown"
    assert tracker not in coord._wifi_wired_skipped


def test_the_minority_line_is_a_tenth():
    """Measured, not chosen: the tightest contradiction on either
    fleet is 2 against 22, the next 1 against 52. A tenth discards
    every one of the thirteen false readings and is reached by none
    of them."""
    assert MEDIUM_MINORITY_SHARE == 0.10


# ------------------------------------------------------------- #418


async def test_the_scores_survive_a_restart(hass: HomeAssistant):
    """The whole of this release for the second fleet. Its memory
    was a snapshot of whatever had been seen home since the last
    boot, and it boots often."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    tracker = trackers[0]

    for _ in range(5):
        _home(hass, tracker, connection="wired", band="None")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()
    assert coord.wifi_medium_of(tracker) == "wired"
    await coord._save_now()

    # The tracker is home with no attributes at all after the
    # restart, which is what a router that has not polled yet looks
    # like. Without persistence that reads as unknown.
    hass.states.async_set(tracker, "home", {"source_type": "router"})
    await hass.async_block_till_done()
    fresh = await setup_coordinator(hass)
    fresh._rebuild_wifi_ties()

    assert fresh.data[DATA_WIFI_MEDIUM][tracker]["wired"] == 5
    assert fresh.wifi_medium_of(tracker) == "wired"


# ------------------------------------------------------------- #428


async def test_rejected_readings_are_counted(hass: HomeAssistant):
    """The condition that makes the grace question measurable. Two
    false readings against sixty true ones are discarded, and the
    discarding leaves a record."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    tracker = trackers[0]

    for _ in range(60):
        _home(hass, tracker, connection="IoT", band="2G")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()
    for _ in range(2):
        _home(hass, tracker, connection="wired", band="None")
        await hass.async_block_till_done()
        coord._rebuild_wifi_ties()

    published = coord.wifi_attributes
    assert published["medium_rejected"] == 2
    assert coord.wifi_medium_rejected[tracker] == 2
