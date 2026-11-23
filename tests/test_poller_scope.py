"""A poller known by its storms is scoped to the devices that move
together (rule UP-17).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_poller_scope.py, Version: 0.30.3 (2026-11-23)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

A Matter bridge, such as an Aqara hub, passes its own devices on all at
once, while the same integration's other devices report on their own. On
a tester's house 18 of 22 Matter devices moved together, and the note
said all of Matter did. The verdict now keeps the devices that took part
in at least half of the day's storms, its stop is judged on them, and
the note names them and leaves the rest to be judged on their own.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_POLLERS,
    DATA_STORM_DAYS,
    POLLER_DEVICES,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DEVICES,
    STORM_DAY_DOMAIN,
    STORM_DAY_DURATION,
    STORM_DAY_INTERVAL,
)

from .helpers import register_fleet, setup_coordinator
from .outage_helpers import past_grace


def _day(days_ago: int) -> str:
    return (dt_util.now().date() - timedelta(days=days_ago)).isoformat()


def _busy(domain: str) -> list[dict]:
    return [
        {STORM_DAY_DATE: _day(days_ago), STORM_DAY_DOMAIN: domain, STORM_DAY_COUNT: 60,
         STORM_DAY_INTERVAL: 1200.0, STORM_DAY_DEVICES: 18.0, STORM_DAY_DURATION: 5.0}
        for days_ago in (2, 3)
    ]


async def _house(hass, freezer, behind_hub: bool):
    source = MockConfigEntry(domain="matter")
    source.add_to_hass(hass)
    bridged = register_fleet(hass, source, 18, prefix="leak")
    own = register_fleet(hass, source, 4, prefix="plug")
    if behind_hub:
        registry = dr.async_get(hass)
        hub = registry.async_get_or_create(
            config_entry_id=source.entry_id, identifiers={("test", "m3")}, name="Aqara Hub M3",
        )
        for device, _entity in bridged:
            registry.async_update_device(device.id, via_device_id=hub.id)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    return coord, bridged, own


async def _burst(hass, freezer, fleet, value):
    for _device, entity in fleet:
        hass.states.async_set(entity, value)
    await hass.async_block_till_done()


async def _two_storms(hass, freezer, bridged, own):
    for value in ("1", "2"):
        await _burst(hass, freezer, bridged, value)
        freezer.tick(timedelta(seconds=10))
        # A device of its own reporting after the burst closes it.
        hass.states.async_set(own[0][1], value)
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=600))


async def test_the_verdict_keeps_the_devices_that_move_together(hass: HomeAssistant, freezer):
    coord, bridged, own = await _house(hass, freezer, behind_hub=False)
    await _two_storms(hass, freezer, bridged, own)
    coord.data[DATA_STORM_DAYS] = _busy("matter")
    coord._fold_pollers(_day(1))
    members = set(coord.data[DATA_POLLERS]["matter"][POLLER_DEVICES])
    assert members == {device.id for device, _ in bridged}
    assert coord.poller_devices("matter") == members
    # The stop is judged on them, not on the plugs that report alone.
    scope = coord._poller_scope(next(iter(e.entry_id for e in hass.config_entries.async_entries("matter"))), "matter")
    assert set(scope) == members


async def test_the_note_names_only_the_devices_that_move_together(hass: HomeAssistant, freezer):
    coord, bridged, own = await _house(hass, freezer, behind_hub=False)
    await _two_storms(hass, freezer, bridged, own)
    coord.data[DATA_STORM_DAYS] = _busy("matter")
    coord._fold_pollers(_day(1))
    note = dict(coord._noisy_integration_entries())["noisy:matter"]
    assert note.startswith("18 of Matter's 22 devices update together, every 20 minutes.")
    assert "Matter's other devices are judged on their own." in note
    assert "updates all its devices" not in note


async def test_the_note_names_the_hub_they_sit_behind(hass: HomeAssistant, freezer):
    coord, bridged, own = await _house(hass, freezer, behind_hub=True)
    await _two_storms(hass, freezer, bridged, own)
    coord.data[DATA_STORM_DAYS] = _busy("matter")
    coord._fold_pollers(_day(1))
    note = dict(coord._noisy_integration_entries())["noisy:matter"]
    assert note.startswith("The 18 devices behind Aqara Hub M3 update together")


async def test_a_day_with_no_storms_keeps_the_devices_found(hass: HomeAssistant, freezer):
    """After a restart the day's members are empty: the list stands."""
    coord, bridged, own = await _house(hass, freezer, behind_hub=False)
    await _two_storms(hass, freezer, bridged, own)
    coord.data[DATA_STORM_DAYS] = _busy("matter")
    coord._fold_pollers(_day(1))
    coord._fold_pollers(_day(0))
    assert set(coord.data[DATA_POLLERS]["matter"][POLLER_DEVICES]) == {device.id for device, _ in bridged}


async def test_the_note_is_scoped_before_the_verdict_too(hass: HomeAssistant, freezer):
    """A day or two of bursts, under the poller line, still gets a line:
    it names the devices that move together, not all of Matter."""
    coord, bridged, own = await _house(hass, freezer, behind_hub=False)
    await _two_storms(hass, freezer, bridged, own)
    quiet = [dict(row, **{STORM_DAY_COUNT: 12}) for row in _busy("matter")]
    coord.data[DATA_STORM_DAYS] = quiet
    coord._fold_pollers(_day(1))
    assert "matter" not in coord.data[DATA_POLLERS]
    note = dict(coord._noisy_integration_entries())["noisy:matter"]
    assert note.startswith("18 of Matter's 22 devices update together")


async def test_the_members_go_when_the_storms_stop(hass: HomeAssistant, freezer):
    coord, bridged, own = await _house(hass, freezer, behind_hub=False)
    await _two_storms(hass, freezer, bridged, own)
    coord.data[DATA_STORM_DAYS] = _busy("matter")
    coord._fold_pollers(_day(1))
    assert coord.storm_members("matter")
    coord.data[DATA_STORM_DAYS] = []
    coord._fold_pollers(_day(0))
    assert coord.storm_members("matter") == set()
