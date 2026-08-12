"""Characterization tests for the state-change handler's edges.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_state_change_edges.py, Version: 0.13.0 (2026-08-12)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Two branches of _on_state_changed that the suite has never executed:
the guard for an event carrying no new state, and the path where a
taint is raised inside the startup grace window. They are written
against the code as it stands, before any refactoring of that
handler, so that a later change to its shape has something to be
identical to. Neither describes new behavior; both record behavior
that already exists and was never pinned.
"""

from datetime import timedelta

from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    EP_LEARNED,
    FREEZE_ARMING_DAYS,
    TAINT_UNAVAILABLE,
)

from .helpers import register_device, setup_coordinator


async def test_an_event_with_no_new_state_is_ignored(
    hass: HomeAssistant,
):
    """A removed entity dispatches a change whose new state is None.

    Home Assistant sends one when an entity leaves the machine, and
    the handler returns before it touches the record. Asserted on the
    event count, which every real reading advances, so a regression
    that let the None through would either raise or count a reading
    that never happened.
    """
    device, (entity_id,) = register_device(hass, "edge1", "Edge Device")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    before = coord.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT]

    coord._on_state_changed(
        Event(
            "state_changed",
            {"entity_id": entity_id, "new_state": None, "old_state": None},
        )
    )

    assert coord.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT] == before


async def test_a_taint_raised_inside_grace_is_also_held_in_the_grace_set(
    hass: HomeAssistant, freezer
):
    """A device that went unavailable during the startup grace window.

    The taint lands exactly as it would at any other time, and the
    device id is also held in the grace set, which is what lets the
    grace release treat it differently from a taint the house earned
    while running. The other branch of that same test logs instead,
    and the two differ only in bookkeeping, so nothing existing would
    notice a refactor collapsing them.

    Read through the episode rather than the record, because the
    taint is set and spent inside one event handler and is not
    observable from outside it; the grace set is the one piece that
    outlives the handler.
    """
    device, (entity_id,) = register_device(hass, "edge2", "Grace Device")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()

    # The startup grace suppresses judgment, so it is cleared to open
    # the episode and re-armed below for the branch under test.
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 7200.0
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1

    # Wide enough to still be open when the device recovers, which is
    # the moment the branch is decided.
    coord._grace_until = dt_util.utcnow().timestamp() + 86400.0
    hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=7200))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()

    assert coord.data[DATA_EPISODES][0][EP_LEARNED] == (
        f"no ({TAINT_UNAVAILABLE})"
    )
    assert device.id in coord._grace_taints
