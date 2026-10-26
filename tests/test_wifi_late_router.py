# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_late_router.py, Version: 0.27.5 (2026-10-26)

"""A resumed Wi-Fi outage whose router answers late (rule UP-16).

Ruled by James, 26 October 2026: a resumed outage listens to its stored
fallen trackers by entity id, apart from the ties. Home is a return,
away stays away, and no state, Home Assistant's placeholder or plain
unavailable means not known yet. A fallen tracker whose entity is gone
from the registry is dropped from the set, so a removed router
integration cannot hold an outage open for ever.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    STARTUP_GRACE_SECONDS,
    WIFI_TIE_RETRY_SECONDS,
)
from tests.helpers import register_device, setup_coordinator
from tests.outage_helpers import restart, tick
from tests.test_wifi_outage import _declared, _heard, _house, _wifi_device


async def test_router_loaded_but_unreachable_at_boot_then_back(
    hass: HomeAssistant, freezer
):
    """The router integration sets up but cannot reach the router, so
    every tracker reads a plain unavailable (no source type, no restored
    flag) through the grace. Then the router answers with every fallen
    tracker home: the outage closes, and the ties form again for the
    next outage."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    heard = _heard(hass)
    attrs = {t: dict(hass.states.get(t).attributes) for t in trackers}
    await _declared(hass, coord, trackers, freezer, count=3)

    def router_unreachable():
        for tracker in trackers:
            hass.states.async_set(tracker, "unavailable", {})

    coord = await restart(hass, freezer, down=120, before_setup=router_unreachable)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=60, n=2)
    assert coord.wifi_down_at is not None
    for tracker in trackers:
        hass.states.async_set(tracker, "home", attrs[tracker])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=5)
    assert coord._wifi_ties, "ties never formed again"
    assert coord.wifi_down_at is None, (
        f"returned {coord.wifi_returned_count} of {len(coord.wifi_fallen_set)}"
    )
    assert [label for label, _ in heard] == ["down", "restored"]
    assert coord._wifi_fallen_unsub is None


async def test_second_router_integration_late_with_ties_standing(
    hass: HomeAssistant, freezer
):
    """Two router integrations. The one whose trackers fell answers
    after the grace, Home Assistant's placeholders first; the other is
    up at boot, so the ties stand without the fallen trackers. They
    come home and the outage closes."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    registry = er.async_get(hass)
    early, late = [], []
    for platform, bucket, prefix in (
        ("tplink_router", early, "00"), ("nmap_tracker", late, "01"),
    ):
        for index in range(3):
            mac = f"AA-BB-CC-00-{prefix}-{index:02X}"
            entry = registry.async_get_or_create(
                "device_tracker", platform, f"{platform}{index}"
            )
            hass.states.async_set(
                entry.entity_id, "home", {"source_type": "router", "mac": mac}
            )
            bucket.append(entry.entity_id)
            _wifi_device(
                hass, source, f"{platform}d{index}", f"{platform} {index}",
                mac.lower().replace("-", ":"),
            )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert all(t in coord._wifi_device_of for t in early + late)
    attrs = {t: dict(hass.states.get(t).attributes) for t in late}
    heard = _heard(hass)
    await _declared(hass, coord, late, freezer, count=3)
    assert set(coord.wifi_fallen_set) == set(late)

    def late_router_not_loaded():
        for tracker in late:
            hass.states.async_remove(tracker)
            registry.async_get(tracker).write_unavailable_state(hass)

    coord = await restart(hass, freezer, down=120, before_setup=late_router_not_loaded)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=60, n=2)
    assert coord._wifi_ties
    for tracker in late:
        hass.states.async_set(tracker, "home", attrs[tracker])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=5)
    assert coord.wifi_down_at is None, (
        f"returned {coord.wifi_returned_count} of {len(coord.wifi_fallen_set)}"
    )
    assert [label for label, _ in heard] == ["down", "restored"]


async def test_router_integration_removed_while_down_across_restart(
    hass: HomeAssistant, freezer
):
    """The fallen trackers' router integration is deleted while Home
    Assistant is down. They can never come home, so they leave the
    fallen set and the resumed outage ends."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)

    def removed():
        for tracker in trackers[:3]:
            hass.states.async_remove(tracker)
            registry.async_remove(tracker)

    coord = await restart(hass, freezer, down=120, before_setup=removed)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=60, n=3)
    assert coord.wifi_down_at is None, sorted(coord.wifi_fallen_set)


async def test_router_trackers_removed_mid_outage_without_restart(
    hass: HomeAssistant, freezer
):
    """The same removal inside one run ends the outage too."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)
    for tracker in trackers[:3]:
        hass.states.async_remove(tracker)
        registry.async_remove(tracker)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=3)
    assert coord.wifi_down_at is None


async def test_one_removed_tracker_leaves_the_rest_to_decide(
    hass: HomeAssistant, freezer
):
    """Only the removed tracker leaves the set: the others still away
    keep the outage open."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)
    hass.states.async_remove(trackers[0])
    registry.async_remove(trackers[0])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=3)
    assert coord.wifi_down_at is not None
    assert coord.wifi_fallen_set == set(trackers[1:3])


async def test_tie_retry_stops_on_a_house_with_an_orphaned_tracker(
    hass: HomeAssistant, freezer
):
    """A house with no router and one orphaned tracker, reading Home
    Assistant's placeholder for ever. The tie retry stops once its
    window after setup has passed, instead of rebuilding the ladder
    every minute for the life of the run."""
    register_device(hass, "plain1", "Plain")
    registry = er.async_get(hass)
    orphan = registry.async_get_or_create("device_tracker", "life360", "old_phone")
    orphan.write_unavailable_state(hass)
    coord = await setup_coordinator(hass)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    assert coord._wifi_retry_pending
    await tick(hass, freezer, step=60, n=int(WIFI_TIE_RETRY_SECONDS // 60))
    calls = []
    real = coord._rebuild_wifi_ties
    coord._rebuild_wifi_ties = lambda: (calls.append(1), real())[1]
    await tick(hass, freezer, step=60, n=30)
    assert not coord._wifi_retry_pending
    assert calls == [], f"ladder rebuilt {len(calls)} times in 30 minutes"


async def test_a_router_after_the_retry_window_ties_at_the_next_registry_change(
    hass: HomeAssistant, freezer
):
    """A router integration answering after the retry window forms no
    ties on the tick; the next registry change forms them, as before."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    attrs = {t: dict(hass.states.get(t).attributes) for t in trackers}
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)

    def router_not_loaded():
        for tracker in trackers:
            hass.states.async_remove(tracker)
            registry.async_get(tracker).write_unavailable_state(hass)

    coord = await restart(hass, freezer, down=120, before_setup=router_not_loaded)
    await tick(hass, freezer, step=60, n=int(WIFI_TIE_RETRY_SECONDS // 60) + 2)
    assert not coord._wifi_retry_pending
    for tracker in trackers:
        hass.states.async_set(tracker, "home", attrs[tracker])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=2)
    assert not coord._wifi_ties
    # The returns were heard by the fallen listener all the same.
    assert coord.wifi_down_at is None
    coord._rebuild_registry_view()
    assert coord._wifi_ties
