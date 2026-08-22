# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_incident_settling.py, Version: 0.16.20 (2026-08-22)

"""The recorder's cooling-off, and the phone's (ruling #318).

Two rules from one fleet's data. A propane sensor whose battery
reading swings wrote 3,637 incident rows in five days, 94 percent of
that fleet's whole history, because every threshold crossing wrote a
pair and nothing stopped it. And a coordinator unplugged for four
days pushed at every restart, because the verdict moved between two
ways of saying the same thing and the correction registered as a new
problem arriving.
"""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_INCIDENT_SETTLE,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_EVENT,
    INC_KIND,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_UNAVAILABLE,
)
from tests.helpers import register_device, setup_coordinator


def _rows(coord, device_id):
    return [
        row
        for row in coord.data[DATA_INCIDENTS]
        if row["device_id"] == device_id
    ]


async def test_a_crossing_back_inside_the_window_resumes_the_episode(
    hass: HomeAssistant,
):
    """One episode, not three, when a reading crosses and returns."""
    device, _ = register_device(hass, "c1", "Propane Sensor")
    coord = await setup_coordinator(hass)

    coord._record_incident(
        device.id, "Propane Sensor", TODO_KIND_LOW_BATTERY, INCIDENT_OPENED
    )
    coord._record_incident(
        device.id,
        "Propane Sensor",
        TODO_KIND_LOW_BATTERY,
        INCIDENT_RESOLVED,
        duration=8.0,
    )
    coord._record_incident(
        device.id, "Propane Sensor", TODO_KIND_LOW_BATTERY, INCIDENT_OPENED
    )

    rows = _rows(coord, device.id)
    assert [row[INC_EVENT] for row in rows] == [INCIDENT_OPENED]


async def test_a_recovery_that_holds_is_recorded(hass: HomeAssistant):
    """The rule must not swallow a real recovery.

    A resolution older than the window is left alone, so a device
    that comes back and stays back keeps its ending.
    """
    device, _ = register_device(hass, "c2", "Door Sensor")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()

    coord.data[DATA_INCIDENTS] = [
        {
            "device_id": device.id,
            "name": "Door Sensor",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            "when": now - 7200.0,
            "cause": None,
            "duration": None,
        },
        {
            "device_id": device.id,
            "name": "Door Sensor",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_RESOLVED,
            "when": now - 3600.0,
            "cause": None,
            "duration": 3600.0,
        },
    ]
    coord._record_incident(
        device.id, "Door Sensor", TODO_KIND_UNAVAILABLE, INCIDENT_OPENED
    )

    rows = _rows(coord, device.id)
    assert [row[INC_EVENT] for row in rows] == [
        INCIDENT_OPENED,
        INCIDENT_RESOLVED,
        INCIDENT_OPENED,
    ]


async def test_another_kind_is_not_swallowed(hass: HomeAssistant):
    """The window is per kind. A battery clearing and a freeze
    opening a second later are two different things."""
    device, _ = register_device(hass, "c3", "Mixed Device")
    coord = await setup_coordinator(hass)

    coord._record_incident(
        device.id, "Mixed Device", TODO_KIND_LOW_BATTERY, INCIDENT_OPENED
    )
    coord._record_incident(
        device.id,
        "Mixed Device",
        TODO_KIND_LOW_BATTERY,
        INCIDENT_RESOLVED,
        duration=5.0,
    )
    coord._record_incident(
        device.id, "Mixed Device", TODO_KIND_FROZEN, INCIDENT_OPENED
    )

    kinds = [(row[INC_KIND], row[INC_EVENT]) for row in _rows(coord, device.id)]
    assert kinds == [
        (TODO_KIND_LOW_BATTERY, INCIDENT_OPENED),
        (TODO_KIND_LOW_BATTERY, INCIDENT_RESOLVED),
        (TODO_KIND_FROZEN, INCIDENT_OPENED),
    ]


async def test_another_device_is_not_swallowed(hass: HomeAssistant):
    """And per device, so a fleet-wide event keeps every row."""
    first, _ = register_device(hass, "c4", "First")
    second, _ = register_device(hass, "c5", "Second")
    coord = await setup_coordinator(hass)

    coord._record_incident(
        first.id, "First", TODO_KIND_UNAVAILABLE, INCIDENT_OPENED
    )
    coord._record_incident(
        first.id,
        "First",
        TODO_KIND_UNAVAILABLE,
        INCIDENT_RESOLVED,
        duration=4.0,
    )
    coord._record_incident(
        second.id, "Second", TODO_KIND_UNAVAILABLE, INCIDENT_OPENED
    )

    assert len(_rows(coord, first.id)) == 2
    assert len(_rows(coord, second.id)) == 1


async def test_zero_switches_the_rule_off(hass: HomeAssistant):
    """A person who wants every crossing recorded can have it."""
    device, _ = register_device(hass, "c6", "Raw Device")
    coord = await setup_coordinator(hass, {CONF_INCIDENT_SETTLE: 0})

    coord._record_incident(
        device.id, "Raw Device", TODO_KIND_LOW_BATTERY, INCIDENT_OPENED
    )
    coord._record_incident(
        device.id,
        "Raw Device",
        TODO_KIND_LOW_BATTERY,
        INCIDENT_RESOLVED,
        duration=3.0,
    )
    coord._record_incident(
        device.id, "Raw Device", TODO_KIND_LOW_BATTERY, INCIDENT_OPENED
    )

    assert len(_rows(coord, device.id)) == 3


async def test_a_re_description_does_not_reach_the_phone(
    hass: HomeAssistant,
):
    """Frozen arriving on an unavailable item is the same problem.

    Both mean the device is not reporting, and which one it earns
    depends on what its entities read at that instant, so a restart
    that hides them walks the verdict from one to the other. The item
    never left the list and nothing about the device changed.
    """
    coord = await setup_coordinator(hass)

    standing = {TODO_KIND_UNAVAILABLE: dt_util.utcnow().timestamp()}
    assert not coord._worth_announcing({TODO_KIND_FROZEN}, standing)
    assert not coord._worth_announcing({TODO_KIND_UNAVAILABLE}, standing)


async def test_a_different_family_does_reach_the_phone(
    hass: HomeAssistant,
):
    """A cell dying on a device already silent is a second thing."""
    coord = await setup_coordinator(hass)

    standing = {TODO_KIND_UNAVAILABLE: dt_util.utcnow().timestamp()}
    assert coord._worth_announcing({TODO_KIND_LOW_BATTERY}, standing)
    assert coord._worth_announcing({TODO_KIND_FALLING_BATTERY}, standing)


async def test_a_first_problem_always_reaches_the_phone(
    hass: HomeAssistant,
):
    """Nothing standing means nothing has been announced."""
    coord = await setup_coordinator(hass)

    assert coord._worth_announcing({TODO_KIND_UNAVAILABLE}, {})


async def _standing_unavailable(hass: HomeAssistant):
    """A device four days silent, currently reading unavailable."""
    device, (entity_id,) = register_device(hass, "r1", "SLZB-06")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, STATE_UNAVAILABLE)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * (FREEZE_ARMING_DAYS + 2)
    record["last_activity"] = dt_util.utcnow().timestamp() - 4 * 86400
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNAVAILABLE
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 4 * 86400
    return coord, device, entity_id, record


async def test_a_device_still_loading_keeps_its_verdict(
    hass: HomeAssistant,
):
    """The restart condition, and the cause under the push.

    For the first seconds after a restart the owning integration has
    not finished setting up, so a device's entities are in the
    registry with no state objects behind them. Read as nothing to
    see, the clock alone judged a four-day-silent device frozen, and
    the correction a tick later wrote a kind onto an item that had
    not moved. The reference fleet did this at all 31 restarts.
    """
    coord, device, entity_id, record = await _standing_unavailable(hass)
    hass.states.async_remove(entity_id)
    await hass.async_block_till_done()

    verdict = coord._device_down_category(
        device.id, record, dt_util.utcnow().timestamp()
    )

    assert verdict == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_device_with_no_entities_is_still_judged_by_its_clock(
    hass: HomeAssistant,
):
    """The case that branch was written for is untouched."""
    coord, device, entity_id, record = await _standing_unavailable(hass)
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    hass.states.async_remove(entity_id)
    coord._entity_map = {}
    await hass.async_block_till_done()

    verdict = coord._device_down_category(
        device.id, record, dt_util.utcnow().timestamp()
    )

    assert verdict == FREEZE_CATEGORY_FROZEN
