# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_recovery_fleet.py, Version: 0.21.11 (2026-09-16)

"""The recovery rule, driven through the shipped code on real fleets.

The numbers behind #408, #409 and #422 to #426 came from replaying
the probe logs with a separate model of the rule. A model that agrees
with itself proves nothing about `router_ties.py`, so these cases
drive the real coordinator: real fleet storage, the real tie ladder,
the real burst counter and the real recovery sweep.

Two shapes are asserted, both taken from the second fleet's staged
outage of 12 September.

1. The shape that used to hang. Devices fall, all but three return,
   and three unrelated ones stay away. Under the shipped rule of
   0.21.0 that outage stood open for five and a half hours against a
   real event of ten minutes. It now closes.
2. The device that was never in it. One tracker leaves before the
   outage begins and stays away throughout. It is not a casualty and
   must not appear in the fallen set or hold the recovery open.

Each case loads a whole fleet, so the file runs at about fifty
seconds a case: run it alone, or in pairs, like the other fleet
files.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import WIFI_BURST_FLOOR

from tests.conftest import FLEET_ABSENT
from tests.fleet_house import TIM, TIM_SHAPE, _fleet
from tests.helpers import add_mac

ROUTER = "tplink_router"

# The staged outage, in its own numbers: how many tied trackers fell,
# and how many of them were still away when the capture was taken.
FELL = 51
STILL_AWAY = 3


def _tie(hass, device, index: int) -> str:
    mac = f"aa:bb:cc:dd:{index // 256:02x}:{index % 256:02x}"
    add_mac(hass, device, mac)
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", ROUTER, f"wr{index}"
    )
    hass.states.async_set(
        entry.entity_id,
        "home",
        {"source_type": "router", "mac": mac.upper().replace(":", "-")},
    )
    return entry.entity_id


def _devices_behind(behind) -> list:
    out = []
    for _domain, members in behind.items():
        for device, _record in members:
            out.append(device)
    return out


async def _move(hass, tracker: str, state: str) -> None:
    current = hass.states.get(tracker)
    hass.states.async_set(tracker, state, dict(current.attributes))
    await hass.async_block_till_done()


async def _sweep(coord, hass, start: float, count: int) -> float:
    """Run `count` coordinator ticks a minute apart."""
    for step in range(count):
        coord._sample_wifi(start + step * 60.0)
        await hass.async_block_till_done()
    return start + count * 60.0


async def _tied_fleet(hass, how_many: int):
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)
    coord._grace_until = 0.0
    trackers = [
        _tie(hass, device, index)
        for index, device in enumerate(_devices_behind(behind)[:how_many])
    ]
    coord._rebuild_registry_view()
    assert len(coord._wifi_ties) == how_many
    return coord, trackers


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_outage_that_hung_for_five_hours_now_closes(
    hass: HomeAssistant,
):
    """Fifty-one fall, forty-eight return, three stay away. Under the
    old rule this stood open until those three came back, which on
    the second fleet took hours. Judged against the set that fell, it
    closes on the settle."""
    coord, trackers = await _tied_fleet(hass, 62)

    for tracker in trackers[:FELL]:
        await _move(hass, tracker, "not_home")
    hold = coord._wifi_hold_since
    assert hold is not None
    now = await _sweep(coord, hass, hold + 65.0, 1)
    assert coord.wifi_down_at is not None
    assert len(coord.wifi_fallen_set) == FELL

    for tracker in trackers[STILL_AWAY:FELL]:
        await _move(hass, tracker, "home")

    # One sweep announces, two quiet sweeps close it.
    now = await _sweep(coord, hass, now, 3)

    assert coord.wifi_down_at is None
    # The three that never came back are still away, and are now
    # per-device problems rather than the network's (#426).
    assert len(coord._wifi_not_home) == STILL_AWAY


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_a_device_away_beforehand_never_joins_the_outage(
    hass: HomeAssistant,
):
    """The tablet that left forty-nine minutes early and was one of
    three holding an outage open for five and a half hours. It is not
    a casualty, so it neither joins the fallen set nor delays the
    recovery."""
    coord, trackers = await _tied_fleet(hass, 62)

    early = trackers[61]
    await _move(hass, early, "not_home")
    # Forty-nine minutes pass. Every fall in this harness lands in
    # the same millisecond, so "before the outage" and "during its
    # first wave" cannot be told apart without moving the clock. The
    # standing not_home is backdated and the burst emptied, which is
    # exactly what the sixty second prune does once the time has
    # really elapsed.
    coord._wifi_not_home[early] -= 49 * 60.0
    coord._wifi_burst = []

    for tracker in trackers[:10]:
        await _move(hass, tracker, "not_home")
    hold = coord._wifi_hold_since
    assert hold is not None
    now = await _sweep(coord, hass, hold + 65.0, 1)
    assert coord.wifi_down_at is not None

    assert early not in coord.wifi_fallen_set
    assert len(coord.wifi_fallen_set) == 10

    for tracker in trackers[:10]:
        await _move(hass, tracker, "home")
    await _sweep(coord, hass, now, 3)

    # Closed even though the early leaver is still away, which is
    # more than WIFI_BURST_FLOOR minus one and would have held the
    # old rule open on its own.
    assert coord.wifi_down_at is None
    assert early in coord._wifi_not_home
    assert WIFI_BURST_FLOOR >= 3
