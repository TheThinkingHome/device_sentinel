# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_study.py, Version: 0.20.10 (2026-09-06)

"""Volunteered hardware study (#393).

The shapes here are UniFi's, read from the Home Assistant source: a
connected client publishes `essid`, `radio`, `radio_proto`, `ap_mac`
and more, and a disconnected one drops to `mac`, `name` and `oui`.
That difference is the thing a study exists to confirm on a real
fleet rather than infer from somebody else's code, and it is the same
difference that cost two releases on the reference fleet when a
router relabelled its away clients (#389).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    STUDY_SHAPE_CAP,
)

from tests.helpers import setup_coordinator

UNIFI = "Router: UniFi"

# What UniFi publishes for a connected wireless client.
WIRELESS = {
    "source_type": "router", "essid": "IoT", "radio": "ng",
    "radio_proto": "ax", "ap_mac": "aa:bb:cc:00:11:22", "vlan": 30,
    "ip": "10.0.30.14", "mac": "20:f8:3b:09:97:53", "oui": "Espressif",
}
# A connected wired client: no essid, no radio, no ap_mac.
WIRED = {
    "source_type": "router", "vlan": 10, "ip": "10.0.10.5",
    "mac": "ec:71:db:98:ad:44", "oui": "Reolink",
}
# And what it drops to while away.
AWAY = {"source_type": "router", "mac": "20:f8:3b:09:97:53",
        "oui": "Espressif"}


async def _studying(hass, chosen=(UNIFI,)):
    return await setup_coordinator(
        hass, {CONF_STUDY_HARDWARE: list(chosen)}
    )


def _tracker(hass, uid: str, state: str, attrs: dict,
             platform: str = "unifi") -> str:
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", platform, uid
    )
    hass.states.async_set(entry.entity_id, state, attrs)
    return entry.entity_id


def _shapes(coord, integration="unifi"):
    return list(
        (coord.study_diagnostics.get("shapes") or {}).get(integration, [])
    )


# ------------------------------------------------------ off by default


async def test_nothing_is_collected_unless_volunteered(
    hass: HomeAssistant
):
    """The whole screen is opt in, so the default must gather nothing."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entity = _tracker(hass, "u1", "home", WIRELESS)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    assert coord.studied == set()
    assert coord.study_diagnostics == {}


async def test_only_the_volunteered_integration_is_watched(
    hass: HomeAssistant
):
    """A person volunteering UniFi has not volunteered everything."""
    for domain in ("unifi", "netgear"):
        source = MockConfigEntry(domain=domain, title=domain)
        source.add_to_hass(hass)
    mine = _tracker(hass, "u1", "home", WIRELESS)
    theirs = _tracker(hass, "n1", "home", WIRELESS, platform="netgear")
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    hass.states.async_set(mine, "not_home", AWAY)
    hass.states.async_set(theirs, "not_home", AWAY)
    await hass.async_block_till_done()

    assert coord.studied == {"unifi"}
    assert len(_shapes(coord)) == 1
    assert _shapes(coord, "netgear") == []


# ------------------------------------------- the transition, not a photo


async def test_it_keeps_what_a_client_publishes_while_away(
    hass: HomeAssistant
):
    """The fault a snapshot cannot see.

    A client that publishes nine fields while home and three while
    away is two shapes, and the difference is what a medium rule can
    or cannot be built on. On the reference fleet the away reading
    was not merely thinner, it was wrong, and reading it cost two
    releases (#389).
    """
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entity = _tracker(hass, "u1", "home", WIRELESS)
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    hass.states.async_set(entity, "home", WIRELESS)
    await hass.async_block_till_done()

    shapes = _shapes(coord)
    assert len(shapes) == 2, shapes
    leaving = next(s for s in shapes if s["to"] == "not_home")
    returning = next(s for s in shapes if s["to"] == "home")
    assert "essid" not in leaving["keys"]
    assert "essid" in returning["keys"]
    assert returning["values"]["essid"] == "IoT"
    assert returning["values"]["ap_mac_present"] is True


async def test_wired_and_wireless_are_different_shapes(
    hass: HomeAssistant
):
    """The question UniFi support turns on: it publishes no wired
    marker, so a wired client can only be told by what it lacks."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    wireless = _tracker(hass, "u1", "home", WIRELESS)
    wired = _tracker(hass, "u2", "home", WIRED)
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    hass.states.async_set(wireless, "not_home", AWAY)
    hass.states.async_set(wired, "not_home", AWAY)
    await hass.async_block_till_done()
    hass.states.async_set(wireless, "home", WIRELESS)
    hass.states.async_set(wired, "home", WIRED)
    await hass.async_block_till_done()

    homes = [s for s in _shapes(coord) if s["to"] == "home"]
    assert len(homes) == 2
    keysets = {tuple(s["keys"]) for s in homes}
    assert len(keysets) == 2
    assert any("essid" in keys for keys in keysets)
    assert any("essid" not in keys for keys in keysets)


async def test_a_repeated_shape_is_counted_not_stored_again(
    hass: HomeAssistant
):
    """Twelve devices leaving in one outage, a hundred times over,
    must not grow the file. Only kinds are kept."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entities = [
        _tracker(hass, f"u{i}", "home", WIRELESS) for i in range(12)
    ]
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    for _round in range(10):
        for entity in entities:
            hass.states.async_set(entity, "not_home", AWAY)
        await hass.async_block_till_done()
        for entity in entities:
            hass.states.async_set(entity, "home", WIRELESS)
        await hass.async_block_till_done()

    shapes = _shapes(coord)
    assert len(shapes) == 2, [s["keys"] for s in shapes]
    assert sum(s["count"] for s in shapes) == 240


async def test_a_richer_example_replaces_a_poorer_one(
    hass: HomeAssistant
):
    """Same shape, better example: values where the stored one held
    nulls, so the file keeps the more informative of the two."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    thin = dict(WIRELESS, essid=None, radio=None)
    entity = _tracker(hass, "u1", "home", thin)
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    hass.states.async_set(entity, "home", thin)
    await hass.async_block_till_done()
    stored = next(s for s in _shapes(coord) if s["to"] == "home")
    assert stored["values"]["essid"] is None

    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    hass.states.async_set(entity, "home", WIRELESS)
    await hass.async_block_till_done()
    stored = next(s for s in _shapes(coord) if s["to"] == "home")
    assert stored["values"]["essid"] == "IoT"
    assert stored["count"] == 2


async def test_the_cap_holds_and_says_so(hass: HomeAssistant):
    """A varied fleet cannot grow the file without bound, and the cap
    is recorded rather than silently dropping."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    coord = await _studying(hass)
    for index in range(STUDY_SHAPE_CAP + 20):
        coord.study_transition(
            f"device_tracker.u{index}", "unifi", "home", "not_home",
            {"source_type": "router", f"odd_{index}": index},
        )
    assert len(_shapes(coord)) == STUDY_SHAPE_CAP
    assert coord.study_diagnostics["capped"] == ["unifi"]


# ------------------------------------------------------- the snapshot


async def test_the_snapshot_carries_what_a_tie_would_need(
    hass: HomeAssistant
):
    """Whether a tie can be made, and by which rung, is the first
    thing support for a router needs."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    _tracker(hass, "u1", "home", WIRELESS)
    coord = await _studying(hass)
    coord._rebuild_registry_view()

    snapshot = coord.study_diagnostics["snapshot"]
    assert len(snapshot["trackers"]) == 1
    tracker = snapshot["trackers"][0]
    assert tracker["integration"] == "unifi"
    assert tracker["state"] == "home"
    assert "essid" in tracker["keys"]
    assert "watched_devices" in snapshot


# ------------------------------------------------- ending it (#393)


async def test_unticking_stops_collection_at_once(hass: HomeAssistant):
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entity = _tracker(hass, "u1", "home", WIRELESS)
    coord = await _studying(hass)
    coord._rebuild_registry_view()
    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    assert _shapes(coord)

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_STUDY_HARDWARE: []}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()

    hass.states.async_set(entity, "home", WIRELESS)
    await hass.async_block_till_done()
    assert coord.studied == set()
    # Collection has stopped; what was gathered goes at the fold.
    assert len(_shapes(coord)) == 1


async def test_the_fold_removes_what_is_no_longer_volunteered(
    hass: HomeAssistant
):
    """Retained the way everything else here is retained: a person
    who changes their mind is not left carrying the readings."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entity = _tracker(hass, "u1", "home", WIRELESS)
    coord = await _studying(hass)
    coord._rebuild_registry_view()
    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()
    assert _shapes(coord)

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_STUDY_HARDWARE: []}
    )
    await hass.async_block_till_done()
    coord.study_fold()
    assert _shapes(coord) == []
    assert coord.study_diagnostics == {}


async def test_a_study_still_running_survives_the_fold(
    hass: HomeAssistant
):
    """The fold removes what was withdrawn, and nothing else."""
    source = MockConfigEntry(domain="unifi", title="UniFi")
    source.add_to_hass(hass)
    entity = _tracker(hass, "u1", "home", WIRELESS)
    coord = await _studying(hass)
    coord._rebuild_registry_view()
    hass.states.async_set(entity, "not_home", AWAY)
    await hass.async_block_till_done()

    coord.study_fold()
    assert len(_shapes(coord)) == 1
