# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_declaration_fleet.py, Version: 0.21.11 (2026-09-16)

"""Rulings #419 and #421, driven through the shipped code on both fleets.

Everything measured for 0.21.0 came from replaying the probe logs
with a separate model of the rules. A model that agrees with itself
proves nothing about `router_ties.py`, so these cases drive the real
coordinator instead: real fleet storage, real registry devices, the
real tie ladder, and the real burst counter in
`_on_wifi_tracker_change`.

Three things are asserted.

1. The self-tie bar on real fleet records. A device published by the
   integration that supplies the trackers is not tied, and a device
   from any other integration on the same tracker set still is.
2. The declaration threshold against each fleet's real tie count.
3. The staged outage of 12 September, its fall sequence taken from
   the second fleet's own probe, declares exactly once through the
   shipped counter, while the same fleet's measured churn does not.

Skips whole when the fleet files are absent, as every fleet case does.
Each case loads a whole fleet, so the file runs at about fifty
seconds a case: run it alone, or in pairs, like the other fleet
files.
"""

from __future__ import annotations

import math
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    WIFI_BURST_FLOOR,
    WIFI_BURST_SHARE,
)

from tests.conftest import FLEET_ABSENT
from tests.fleet_house import JAMES, JAMES_SHAPE, TIM, TIM_SHAPE, _fleet
from tests.helpers import add_mac

ROUTER = "tplink_router"

# The second fleet's staged outage of 12 September, from its own
# probe: how many tied trackers fell in each minute of the fall, and
# the churn the same fleet produces on an ordinary day.
STAGED_FALL = (14, 0, 0, 29, 3, 10)
MEASURED_CHURN = 3


def _tracker_for(hass, index: int, platform: str = ROUTER) -> tuple[str, str]:
    """One router tracker, and the MAC it publishes."""
    mac = f"aa:bb:cc:dd:{index // 256:02x}:{index % 256:02x}"
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", platform, f"wt{platform}{index}"
    )
    hass.states.async_set(
        entry.entity_id,
        "home",
        {"source_type": "router", "mac": mac.upper().replace(":", "-")},
    )
    return entry.entity_id, mac


def _tie(hass, device, index: int) -> str:
    """Give one real fleet device a MAC and a tracker carrying it."""
    tracker, mac = _tracker_for(hass, index)
    add_mac(hass, device, mac)
    return tracker


def _devices_behind(behind) -> list:
    out = []
    for _domain, members in behind.items():
        for device, _record in members:
            out.append(device)
    return out


async def _fall(hass, tracker: str) -> None:
    state = hass.states.get(tracker)
    hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()


# ------------------------------------------------------- #419


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_a_router_own_device_is_not_tied_on_a_real_fleet(
    hass: HomeAssistant,
):
    """The shape the second fleet actually has: the router publishes
    a registry device per client, carrying the same MAC as that
    client's tracker. Without the bar it ties to itself."""
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)

    tracker, mac = _tracker_for(hass, 900)
    # The router's own config entry, which is what makes its client
    # devices read as the router integration's rather than some
    # hub's. The bar compares the device's own integration against
    # the tracker's, so the entry domain is the whole point.
    source = MockConfigEntry(domain=ROUTER, title="router")
    source.add_to_hass(hass)
    own = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(ROUTER, "client900")},
        connections={(dr.CONNECTION_NETWORK_MAC, mac)},
        name="Client 900",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", ROUTER, "client900", device_id=own.id, config_entry=source,
    )
    coord._rebuild_registry_view()

    assert own.id not in coord._wifi_ties
    assert tracker not in coord._wifi_device_of


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_other_integrations_on_that_fleet_still_tie(
    hass: HomeAssistant,
):
    """The control. The bar is about who published the device, so the
    fleet's own hardware ties exactly as before."""
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)

    devices = _devices_behind(behind)[:20]
    for index, device in enumerate(devices):
        _tie(hass, device, index)
    coord._rebuild_registry_view()

    assert len(coord._wifi_ties) == len(devices)


# ------------------------------------------------------- #421


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_reference_fleet_threshold_is_unchanged(
    hass: HomeAssistant,
):
    """Twelve tied trackers, so the floor governs and nothing about
    this fleet's behaviour moves."""
    coord, _entries, behind, _now = await _fleet(hass, JAMES, JAMES_SHAPE)

    for index, device in enumerate(_devices_behind(behind)[:12]):
        _tie(hass, device, index)
    coord._rebuild_registry_view()

    assert len(coord._wifi_ties) == 12
    assert coord._wifi_burst_needed() == WIFI_BURST_FLOOR


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_second_fleet_threshold_rises_with_its_size(
    hass: HomeAssistant,
):
    """Sixty-two tied trackers, the count that fleet has once the
    router's own client devices are barred, so the share governs."""
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)

    for index, device in enumerate(_devices_behind(behind)[:62]):
        _tie(hass, device, index)
    coord._rebuild_registry_view()

    assert len(coord._wifi_ties) == 62
    assert coord._wifi_burst_needed() == math.ceil(WIFI_BURST_SHARE * 62)
    assert coord._wifi_burst_needed() == 7


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_measured_churn_does_not_declare(
    hass: HomeAssistant,
):
    """Three falls together is the most this fleet's ordinary churn
    produces, 4.8 percent of its tied set. Before this release it
    declared an outage."""
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)
    coord._grace_until = 0.0

    trackers = [
        _tie(hass, device, index)
        for index, device in enumerate(_devices_behind(behind)[:62])
    ]
    coord._rebuild_registry_view()

    for tracker in trackers[:MEASURED_CHURN]:
        await _fall(hass, tracker)

    assert coord._wifi_hold_since is None
    assert coord.wifi_down_at is None


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_staged_outage_declares_exactly_once(
    hass: HomeAssistant,
):
    """The 12 September outage's first minute, fourteen tied trackers
    falling together, driven through the shipped burst counter. It
    clears a threshold of seven and is held once."""
    coord, _entries, behind, _now = await _fleet(hass, TIM, TIM_SHAPE)
    coord._grace_until = 0.0

    trackers = [
        _tie(hass, device, index)
        for index, device in enumerate(_devices_behind(behind)[:62])
    ]
    coord._rebuild_registry_view()
    assert len(coord._wifi_ties) == 62

    for tracker in trackers[:STAGED_FALL[0]]:
        await _fall(hass, tracker)

    assert coord._wifi_burst_needed() == 7
    assert len(coord._wifi_burst) == STAGED_FALL[0]
    held = coord._wifi_hold_since
    assert held is not None

    # A further fall inside the same burst does not start a second
    # hold: the outage is one event, not one per wave.
    for tracker in trackers[STAGED_FALL[0]:STAGED_FALL[0] + 5]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since == held
