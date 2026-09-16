# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_declaration.py, Version: 0.21.11 (2026-09-16)

"""Who is tied, and what declares an outage. Rulings #419 to #421.

Written before the change, and every case here fails against 0.20.20.

#419 A device published by the integration that supplies the trackers
     is never tied to that integration's own tracker. The second
     fleet's router registers every client on the network as its own
     registry device, so 126 of its 205 tied devices were the router's
     own records tied to the router's own trackers. The device and the
     witness were the same object, and three computers powering down
     inside a minute declared a network outage. Sixteen of nineteen
     declared outages on that fleet were this.

#420 A router integration never recorded before is excluded once, and
     after that it is the person's. New installs get it from the
     default list; an existing install gets it on first sighting. It
     fires once per integration, ever, so unexcluding it later sticks.

#421 An outage is declared by a share of the tied fleet with a floor
     of three. Three was set against churn on a twelve-tracker fleet,
     where it is a quarter of the house; on a hundred-device fleet it
     is three percent.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DEFAULT_EXCLUDED_INTEGRATIONS,
    WIFI_BURST_FLOOR,
)

from tests.helpers import setup_coordinator
from tests.test_wifi_outage import _fall, _house, _tracker

ROUTER = "tplink_router"


def _router_own_device(hass, source, uid: str, mac: str):
    """A registry device published by the router integration itself,
    which is what a client record looks like on the second fleet."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(ROUTER, uid)},
        connections={(dr.CONNECTION_NETWORK_MAC, mac)},
        name=f"Client {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", ROUTER, uid, device_id=device.id, config_entry=source,
    )
    return device


# ------------------------------------------------------------- #419


async def test_a_router_client_is_not_tied_to_its_own_tracker(
    hass: HomeAssistant,
):
    """The self-tie bar. A device the router integration published is
    never tied to a tracker that same integration published."""
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)

    mac = "AA-BB-CC-00-00-10"
    tracker = _tracker(hass, "client10", mac)
    _router_own_device(hass, router_entry, "client10",
                       mac.lower().replace("-", ":"))

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    coord._rebuild_wifi_ties()

    assert tracker not in coord._wifi_device_of, coord._wifi_ties


async def test_a_device_from_another_integration_still_ties(
    hass: HomeAssistant,
):
    """The control. The bar is about who published the device, not
    about the MAC or the tracker, so an ordinary Wi-Fi device on the
    same tracker set is tied exactly as before."""
    coord, trackers, devices, _untied = await _house(hass, 3)

    assert len(coord._wifi_ties) == 3
    for device in devices:
        assert device.id in coord._wifi_ties


# ------------------------------------------------------------- #420


async def test_a_router_integration_is_excluded_on_first_sighting(
    hass: HomeAssistant,
):
    """Seen for the first time, it joins the person's list.

    The case that matters is a system that already exists and has
    saved its exclusions, which is the second fleet exactly: thirteen
    integrations, none of them the router. An install that never saved
    its list needs nothing done, because the default already covers
    it."""
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)
    _tracker(hass, "client20", "AA-BB-CC-00-00-20")

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    # An install that predates this feature: the router is on
    # the system and has never been recorded, which is the only
    # state in which a sighting has anything to do. Setup records
    # it for a fresh install, so it is cleared here deliberately.
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_EXCLUDED_INTEGRATIONS: ["mobile_app", "ping"],
        },
    )
    await hass.async_block_till_done()

    await coord._sight_router_integrations()

    excluded = coord.entry.options.get(CONF_EXCLUDED_INTEGRATIONS)
    assert excluded is not None
    assert ROUTER in excluded
    assert ROUTER in coord.data["routers_seen"]


async def test_it_is_not_excluded_a_second_time(hass: HomeAssistant):
    """Once recorded it is never new again, so a person who
    unexcludes it keeps that choice."""
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)
    _tracker(hass, "client21", "AA-BB-CC-00-00-21")

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    # An install that predates this feature: the router is on
    # the system and has never been recorded, which is the only
    # state in which a sighting has anything to do. Setup records
    # it for a fresh install, so it is cleared here deliberately.
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_EXCLUDED_INTEGRATIONS: ["mobile_app", "ping"],
        },
    )
    await hass.async_block_till_done()
    await coord._sight_router_integrations()
    assert ROUTER in coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]

    # The person takes it off their list again.
    kept = [
        name for name in coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]
        if name != ROUTER
    ]
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: kept},
    )
    await hass.async_block_till_done()

    await coord._sight_router_integrations()
    assert ROUTER not in coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]


async def test_an_already_excluded_router_writes_nothing(
    hass: HomeAssistant,
):
    """The grow-only write. Updating options reloads the entry, so a
    sighting that adds nothing must not write at all."""
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)
    _tracker(hass, "client22", "AA-BB-CC-00-00-22")

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_EXCLUDED_INTEGRATIONS: [ROUTER, "ping"],
        },
    )
    await hass.async_block_till_done()
    before = dict(coord.entry.options)

    await coord._sight_router_integrations()

    assert dict(coord.entry.options) == before
    assert ROUTER in coord.data["routers_seen"]


async def test_a_router_integration_is_in_the_default_list():
    """New installs never see the fault at all, and neither does an
    existing install that never saved its exclusions."""
    assert ROUTER in DEFAULT_EXCLUDED_INTEGRATIONS


async def test_an_unsaved_list_is_left_alone(hass: HomeAssistant):
    """Nothing is written where the default already covers it. The
    write is grow-only because updating options reloads the entry."""
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)
    _tracker(hass, "client23", "AA-BB-CC-00-00-23")

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    before = dict(coord.entry.options)

    await coord._sight_router_integrations()

    assert dict(coord.entry.options) == before
    assert ROUTER in coord.data["routers_seen"]


# ------------------------------------------------------------- #421


@pytest.mark.parametrize(
    ("tied", "expected"),
    [
        (4, WIFI_BURST_FLOOR),      # the floor governs a small fleet
        (12, WIFI_BURST_FLOOR),     # the reference fleet, unchanged
        (30, WIFI_BURST_FLOOR),     # the floor still governs at 30
        (62, 7),                    # the second fleet after the tie work
        (100, 10),                  # the case the rule exists for
        (200, 20),
    ],
)
async def test_the_declaration_threshold_scales_with_the_fleet(
    hass: HomeAssistant, tied: int, expected: int
):
    """Three devices or ten percent of the tied set, whichever is
    more. Measured: the second fleet's churn tops out at three falls
    in a minute, 4.8 percent of its 62 tied trackers, against a staged
    outage peaking at 44 percent. The smallest real event measured
    anywhere is 25 percent."""
    coord = await setup_coordinator(hass)
    coord._wifi_ties = {f"d{i}": f"device_tracker.t{i}" for i in range(tied)}

    assert coord._wifi_burst_needed() == expected


async def test_three_falls_do_not_declare_on_a_large_fleet(
    hass: HomeAssistant,
):
    """The fault this ruling answers. On a sixty-two tracker fleet
    three computers powering down together is churn, not an outage."""
    coord, trackers, _devices, _untied = await _house(hass, 62)
    assert len(coord._wifi_ties) == 62

    for tracker in trackers[:3]:
        await _fall(hass, tracker)

    assert coord._wifi_hold_since is None, "three falls declared"


async def test_seven_falls_do_declare_on_that_fleet(
    hass: HomeAssistant,
):
    """The control, at the threshold the same fleet requires."""
    coord, trackers, _devices, _untied = await _house(hass, 62)

    for tracker in trackers[:7]:
        await _fall(hass, tracker)

    assert coord._wifi_hold_since is not None


# ---------------------------------------- the call site itself


async def test_setup_itself_performs_the_sighting(hass: HomeAssistant):
    """The hole this file had. Every other case above calls
    `_sight_router_integrations` by hand, so all of them passed while
    the call site was missing from `async_setup` and the feature
    shipped dead in 0.21.0. Found on the reference system, where
    `routers_seen` came back empty after the upgrade. A unit test
    that invokes the thing under test cannot tell you whether
    anything invokes it in production.
    """
    router_entry = MockConfigEntry(domain=ROUTER, title="router")
    router_entry.add_to_hass(hass)
    _tracker(hass, "client30", "AA-BB-CC-00-00-30")

    coord = await setup_coordinator(hass)

    assert ROUTER in coord.data["routers_seen"]


async def test_the_hold_uses_the_same_threshold_as_the_burst(
    hass: HomeAssistant,
):
    """A 0.21.0 defect. The burst scaled with the fleet and the hold
    did not, so a burst that decayed during the hold still declared
    at the bare floor of three. Found while replaying both fleets for
    0.21.1, not by any test."""
    coord, trackers, _devices, _untied = await _house(hass, 62)
    coord._grace_until = 0.0
    assert coord._wifi_burst_needed() == 7

    for tracker in trackers[:7]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is not None

    # Four come back inside the hold, leaving three away.
    for tracker in trackers[:4]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "home", dict(state.attributes))
    await hass.async_block_till_done()
    coord._sample_wifi(coord._wifi_hold_since + 65.0)
    await hass.async_block_till_done()

    assert coord.wifi_down_at is None
