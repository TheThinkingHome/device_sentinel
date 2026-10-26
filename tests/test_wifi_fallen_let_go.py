# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_fallen_let_go.py, Version: 0.27.5 (2026-10-26)

"""Fallen trackers that can never come home are let go (rule UP-16).

Ruled by James, 26 October 2026: a fallen tracker of an open outage
with no usable state (none, Home Assistant's placeholder, or unavailable
or unknown) for two hours is let go as if removed from the registry,
and the outage closes on the trackers left, or ends if none are left.
The two hours run from the first check that finds it without a usable
state, or from the resume.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    DATA_WIFI_OUTAGE,
    STARTUP_GRACE_SECONDS,
    WIFI_FALLEN_UNUSABLE_SECONDS,
    WIFI_OUTAGE_FALLEN,
)
from tests.outage_helpers import restart, tick
from tests.test_wifi_outage import _declared, _house

HOURS = int(WIFI_FALLEN_UNUSABLE_SECONDS // 3600)


async def test_resumed_outage_router_never_reachable_closes(
    hass: HomeAssistant, freezer
):
    """Home Assistant restarts during the outage and the router
    integration never reaches the router again: its trackers read plain
    unavailable. They are let go after two hours and the outage ends."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)

    def unreachable():
        for tracker in trackers:
            hass.states.async_set(tracker, "unavailable", {})

    coord = await restart(hass, freezer, down=120, before_setup=unreachable)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=600, n=6 * HOURS - 2)
    assert coord.wifi_down_at is not None, "let go before two hours"
    await tick(hass, freezer, step=600, n=3)
    assert coord.wifi_down_at is None, (
        f"returned {coord.wifi_returned_count} of {len(coord.wifi_fallen_set)}"
    )


async def test_resumed_outage_router_integration_disabled_closes(
    hass: HomeAssistant, freezer
):
    """The fallen trackers' router integration is disabled while Home
    Assistant is down: their entries stay, disabled, with no state."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)

    def disabled():
        for tracker in trackers:
            hass.states.async_remove(tracker)
            registry.async_update_entity(
                tracker, disabled_by=er.RegistryEntryDisabler.CONFIG_ENTRY
            )

    coord = await restart(hass, freezer, down=120, before_setup=disabled)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=600, n=6 * HOURS + 1)
    assert coord.wifi_down_at is None, sorted(coord.wifi_fallen_set)
    assert DATA_WIFI_OUTAGE not in coord.data


async def test_live_outage_router_integration_disabled_closes(
    hass: HomeAssistant, freezer
):
    """Inside one run the router integration is disabled mid-outage:
    its trackers leave the state machine and stay in the registry."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)
    for tracker in trackers:
        hass.states.async_remove(tracker)
        registry.async_update_entity(
            tracker, disabled_by=er.RegistryEntryDisabler.CONFIG_ENTRY
        )
    await hass.async_block_till_done()
    await tick(hass, freezer, step=600, n=6 * HOURS + 1)
    assert coord.wifi_down_at is None, sorted(coord.wifi_fallen_set)


async def test_a_tracker_still_away_is_not_let_go(
    hass: HomeAssistant, freezer
):
    """Away is a usable state: three hours away keeps the outage open
    and every fallen tracker in it."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    await tick(hass, freezer, step=600, n=6 * HOURS + 6)
    assert coord.wifi_down_at is not None
    assert coord.wifi_fallen_set == set(trackers[:3])


async def test_one_tracker_let_go_leaves_the_rest_to_decide(
    hass: HomeAssistant, freezer
):
    """Only the tracker without a usable state is let go, and the stored
    outage loses it; the others still away keep the outage open."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    hass.states.async_remove(trackers[0])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=600, n=6 * HOURS + 1)
    assert coord.wifi_down_at is not None
    assert coord.wifi_fallen_set == set(trackers[1:3])
    assert set(coord.data[DATA_WIFI_OUTAGE][WIFI_OUTAGE_FALLEN]) == set(trackers[1:3])


async def test_a_usable_state_restarts_the_two_hours(
    hass: HomeAssistant, freezer
):
    """A tracker that reads a usable state again, however briefly, has
    its two hours counted afresh from the next time it has none."""
    coord, trackers, _d, _u = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    attrs = dict(hass.states.get(trackers[0]).attributes)
    hass.states.async_set(trackers[0], "unavailable", {})
    await hass.async_block_till_done()
    await tick(hass, freezer, step=600, n=6 * HOURS - 3)
    hass.states.async_set(trackers[0], "not_home", attrs)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=1)
    hass.states.async_set(trackers[0], "unavailable", {})
    await hass.async_block_till_done()
    await tick(hass, freezer, step=600, n=6)
    assert trackers[0] in coord.wifi_fallen_set
