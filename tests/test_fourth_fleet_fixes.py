# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_fourth_fleet_fixes.py, Version: 0.22.4 (2026-09-19)

"""Fixes found in the fourth fleet's files of 19 September.

1. A never-reported device was "recovered" at each of three restarts
   and flagged again five minutes later. While a device is held
   (its integration still loading after a restart, or a Wi-Fi burst
   waiting for the router), its row leaves the problem source, and the
   list read the absence as a recovery.
2. A repeated battery problem was told as "went silent".
3. A battery that had come back up read "battery read low, now 55%".
4. The Integrations tab counted "1 are muted" (tested in the page).
5. Two diagnostics fields came out empty.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DEV_BATTERY_VALUE,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_NEVER_REPORTED,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KINDS,
)

from tests.helpers import register_device, setup_coordinator


# ------------------------------------------- 1. held is not recovered


async def _never_reported(hass):
    device, _ = register_device(hass, "aqara", name="0x00158d000806884c")
    coord = await setup_coordinator(hass)
    # Past the startup grace, so the problem is raised (ruling #369).
    coord._grace_until = 0.0
    record = coord.data["devices"][device.id]
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = "2026-09-17T23:55:26+00:00"
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_NEVER_REPORTED
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 2 * 86400
    coord._sync_problem_list()
    items = coord.data[DATA_TODO_ITEMS]
    assert len(items) == 1 and TODO_KIND_NEVER_REPORTED in items[0][TODO_KINDS]
    return coord, device


def _resolved(coord, device_id):
    return [
        row for row in coord.data.get(DATA_INCIDENTS) or []
        if row.get(INC_DEVICE_ID) == device_id and row.get(INC_EVENT) == INCIDENT_RESOLVED
    ]


def _opened(coord, device_id):
    return [
        row for row in coord.data.get(DATA_INCIDENTS) or []
        if row.get(INC_DEVICE_ID) == device_id and row.get(INC_EVENT) == INCIDENT_OPENED
    ]


async def test_a_device_held_while_its_integration_loads_keeps_its_problem(
    hass: HomeAssistant, monkeypatch
):
    """The fourth fleet's restart, step by step: held, then released."""
    coord, device = await _never_reported(hass)
    opened_before = len(_opened(coord, device.id))

    monkeypatch.setattr(coord, "loading_held", lambda: {device.id})
    coord._sync_problem_list()
    items = coord.data[DATA_TODO_ITEMS]
    assert len(items) == 1, "held is not recovered"
    assert TODO_KIND_NEVER_REPORTED in items[0][TODO_KINDS]
    assert _resolved(coord, device.id) == []

    monkeypatch.setattr(coord, "loading_held", lambda: set())
    coord._sync_problem_list()
    assert len(coord.data[DATA_TODO_ITEMS]) == 1
    assert len(_opened(coord, device.id)) == opened_before, "not raised a second time"


async def test_a_device_held_in_a_wifi_burst_keeps_its_problem(hass: HomeAssistant, monkeypatch):
    coord, device = await _never_reported(hass)
    monkeypatch.setattr(coord, "wifi_burst_held", lambda: {device.id})
    coord._sync_problem_list()
    assert len(coord.data[DATA_TODO_ITEMS]) == 1
    assert _resolved(coord, device.id) == []


async def test_a_real_recovery_still_closes_the_problem(hass: HomeAssistant):
    coord, device = await _never_reported(hass)
    record = coord.data["devices"][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()
    assert coord.data[DATA_TODO_ITEMS] == []
    assert len(_resolved(coord, device.id)) == 1


# --------------------------------------- 2. a repeated battery problem


def _flap(kind, duration):
    return [
        ({INC_KIND: kind, INC_NAME: "Christopher's iPhone", INC_DEVICE_ID: "p"},
         {INC_DURATION: duration}),
        ({INC_KIND: kind, INC_NAME: "Christopher's iPhone", INC_DEVICE_ID: "p"},
         {INC_DURATION: duration}),
    ]


async def test_a_repeated_low_battery_is_told_as_one(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    sentence = coord._compose_flapping(_flap(TODO_KIND_LOW_BATTERY, 810.0))
    assert "battery read low twice and recovered each time, low for 27m in total" in sentence
    assert "silent" not in sentence


async def test_a_repeated_falling_battery_is_told_as_one(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    sentence = coord._compose_flapping(_flap(TODO_KIND_FALLING_BATTERY, 600.0))
    assert "battery fell twice" in sentence
    assert "silent" not in sentence


# ------------------------------------ 3. a battery that came back up


async def test_a_battery_still_low_says_its_level(hass: HomeAssistant):
    device, _ = register_device(hass, "cell", name="Door Sensor")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id][DEV_BATTERY_VALUE] = 8.0
    assert coord._battery_phrase(device.id, False) == "battery fell to 8%"


async def test_a_battery_back_up_says_recovered(hass: HomeAssistant):
    device, _ = register_device(hass, "cell", name="Door Sensor")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id][DEV_BATTERY_VALUE] = 55.0
    assert coord._battery_phrase(device.id, False) == "battery read low, since recovered"


async def test_a_battery_near_full_says_replaced_or_recharged(hass: HomeAssistant):
    device, _ = register_device(hass, "cell", name="Door Sensor")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id][DEV_BATTERY_VALUE] = 100.0
    assert coord._battery_phrase(device.id, False) == (
        "battery read low, since replaced or recharged"
    )


# ------------------------------------------------- 5. diagnostics fields


async def test_diagnostics_names_a_set_aside_devices_integration(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, _ = register_device(hass, "sp", name="Repairs")
    coord = await setup_coordinator(hass)
    domain = coord._watched.pop(device.id)
    coord._set_aside = {device.id: ("Repairs", "spook", "excluded")}
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    row = diagnostics["devices"][device.id]
    assert row["integration"] == "spook"
    assert domain != "spook", "the watched map did not answer"


async def test_the_study_snapshot_names_a_bluetooth_devices_integration(hass: HomeAssistant):
    """SwitchBot devices carry only a Bluetooth connection, no identifier,
    and the fourth fleet's snapshot listed them with no integration."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE

    entry = MockConfigEntry(domain="switchbot", title="SwitchBot")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={("bluetooth", "E5:42:03:2B:51:AA")},
        name="Dining Room Curtain",
    )
    er.async_get(hass).async_get_or_create(
        "cover", "switchbot", "curtain", device_id=device.id, config_entry=entry
    )
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: ["Z-Wave"]})
    rows = coord.study_snapshot()["watched_devices"]
    curtain = next(row for row in rows if row["name"] == "Dining Room Curtain")
    assert curtain["integration"] == "switchbot"
