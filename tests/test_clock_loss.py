# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_clock_loss.py, Version: 0.22.28 (2026-09-23)

"""A lost clocks file, and a startup grace that holds everything.

The owner deleted the reference rig's clocks file on 23 September to
see what a person would meet. Every clock came back empty, and an
empty clock with no events is what "never reported" means: 31 healthy
devices went on the list when the grace closed, each with a fault
event, and the watering sensor's verdict moved from unavailable to
never reported one minute into the start, closed its unavailable
incident as a recovery and pushed to the phone inside the grace.

These tests replay that start. The ones that are not guards fail on
0.22.27.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DOMAIN,
    EVENT_FAULT,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_EVENT,
    INC_KIND,
    INCIDENT_RESOLVED,
    REPAIR_CLOCKS_RESET,
    STARTUP_GRACE_SECONDS,
    STORAGE_CLOCKS_KEY,
    TODO_KINDS,
    TODO_SORT_NAME,
)

from .helpers import record_events, register_device, setup_entry

HOUR = 3600.0
FAST = "Fast Plug"
SLOW = "Slow Button"
FROZE = "Frozen Door"
DEAD = "Watering Kit"
FRESH = "New Sensor"


@pytest.fixture(autouse=True)
def _mid_afternoon(freezer):
    """1:00 PM Pacific, clear of the brief time and of midnight."""
    freezer.move_to("2026-09-23T20:00:00+00:00")


def _entity(entities):
    return entities[0] if isinstance(entities, list) else entities


async def _tick(hass, freezer, seconds: float = 60.0) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _house(hass: HomeAssistant, freezer):
    """The rig in miniature, settled past its first grace.

    A fast reporter, a slow one, a device already frozen, the watering
    kit already listed unavailable, and a device added yesterday that
    has never reported and has no history.
    """
    devices = {
        name: register_device(hass, f"cl{index}", name=name)
        for index, name in enumerate((FAST, SLOW, FROZE, DEAD, FRESH))
    }
    for name, (_device, entities) in devices.items():
        hass.states.async_set(
            _entity(entities), "unavailable" if name == DEAD else "1"
        )
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coordinator = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    long_ago = (dt_util.utcnow() - timedelta(days=60)).isoformat()
    for name, (device, _entities) in devices.items():
        record = coordinator.data[DATA_DEVICES][device.id]
        if name == FRESH:
            continue
        record[DEV_DAILY_MAX] = [
            600.0 if name == FAST else 20000.0
        ] * (FREEZE_ARMING_DAYS + 5)
        record[DEV_FIRST_OBSERVED] = long_ago
        record[DEV_EVENT_COUNT] = 500
        record[DEV_LAST_ACTIVITY] = now - (
            30 * HOUR if name in (FROZE, DEAD) else 300
        )
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 3):
        await _tick(hass, freezer)
    return entry, devices, phone


async def _lose_the_clocks(hass, hass_storage, freezer, entry):
    """Stop, delete the clocks file, start: the owner's own steps."""
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    del hass_storage[STORAGE_CLOCKS_KEY]
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _verdict(coordinator, devices, name):
    device, _entities = devices[name]
    return coordinator.data[DATA_DEVICES][device.id].get(DEV_FROZEN_CATEGORY)


def _listed(coordinator) -> dict[str, list[str]]:
    return {
        item[TODO_SORT_NAME]: sorted(item[TODO_KINDS])
        for item in coordinator.data[DATA_TODO_ITEMS]
    }


async def test_the_house_before_the_loss_is_as_the_rig_was(
    hass: HomeAssistant, freezer
):
    """Guard: the scene is set as it stood on the rig."""
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = entry.runtime_data
    assert _verdict(coordinator, devices, DEAD) == FREEZE_CATEGORY_UNAVAILABLE
    assert _verdict(coordinator, devices, FROZE) == FREEZE_CATEGORY_FROZEN
    assert _verdict(coordinator, devices, SLOW) is None


async def test_no_device_with_history_reads_never_reported(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    faults = record_events(hass, EVENT_FAULT)
    for _ in range(12):
        await _tick(hass, freezer)
    for name in (FAST, SLOW, FROZE, DEAD):
        assert _verdict(coordinator, devices, name) != (
            FREEZE_CATEGORY_NEVER_REPORTED
        ), name
    assert not [
        event for event in faults
        if event.get("kind") == FREEZE_CATEGORY_NEVER_REPORTED
        and event.get("name") != FRESH
    ]


async def test_the_clocks_restart_at_the_load(
    hass: HomeAssistant, hass_storage, freezer, caplog
):
    entry, devices, _phone = await _house(hass, freezer)
    caplog.set_level(logging.WARNING, logger="custom_components.device_sentinel")
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    loaded_at = dt_util.utcnow().timestamp()
    slow, _entities = devices[SLOW]
    clock = coordinator.data[DATA_DEVICES][slow.id][DEV_LAST_ACTIVITY]
    assert clock == pytest.approx(loaded_at, abs=5)
    said = [r.getMessage() for r in caplog.records if "clocks file" in r.getMessage()]
    assert said and "4 device clock(s) restart" in said[0], said


async def test_a_device_with_no_history_keeps_no_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: a device that has never reported must still read so."""
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    fresh, _entities = devices[FRESH]
    assert coordinator.data[DATA_DEVICES][fresh.id][DEV_LAST_ACTIVITY] is None


async def test_a_frozen_device_stays_frozen_until_it_reports(
    hass: HomeAssistant, hass_storage, freezer
):
    """A restarted clock is not a report (the owner's ruling, on #124)."""
    entry, devices, _phone = await _house(hass, freezer)
    frozen_since = entry.runtime_data.data[DATA_DEVICES][
        devices[FROZE][0].id
    ][DEV_FROZEN_SINCE]
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(12):
        await _tick(hass, freezer)
    assert _verdict(coordinator, devices, FROZE) == FREEZE_CATEGORY_FROZEN
    record = coordinator.data[DATA_DEVICES][devices[FROZE][0].id]
    assert record[DEV_FROZEN_SINCE] == frozen_since
    assert not [
        row for row in coordinator.data[DATA_INCIDENTS]
        if row["name"] == FROZE and row[INC_EVENT] == INCIDENT_RESOLVED
    ]
    # A real report ends it.
    hass.states.async_set(_entity(devices[FROZE][1]), "2")
    await _tick(hass, freezer)
    assert _verdict(coordinator, devices, FROZE) is None


async def test_nothing_is_judged_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    before = _listed(coordinator)
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) - 1):
        await _tick(hass, freezer)
        assert _listed(coordinator) == before
        assert _verdict(coordinator, devices, DEAD) == (
            FREEZE_CATEGORY_UNAVAILABLE
        )


async def test_the_unavailable_device_is_never_called_recovered(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(12):
        await _tick(hass, freezer)
    assert not [
        row for row in coordinator.data[DATA_INCIDENTS]
        if row["name"] == DEAD
        and row[INC_EVENT] == INCIDENT_RESOLVED
        and row[INC_KIND] == FREEZE_CATEGORY_UNAVAILABLE
    ]


async def test_nothing_is_pushed_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    phone.clear()
    await coordinator.async_fire_events([("freeze", "At 1:01 pm, a test.", False)])
    await hass.async_block_till_done()
    assert phone == []
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) - 1):
        await _tick(hass, freezer)
    assert phone == [], [call.data.get("message") for call in phone]


async def test_a_push_still_goes_after_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: the hold ends with the window."""
    entry, _devices, phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    phone.clear()
    await coordinator.async_fire_events([("freeze", "At 1:07 pm, a test.", False)])
    await hass.async_block_till_done()
    assert len(phone) == 1


async def test_no_upstream_is_announced_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    """Held, not dropped: its phase is not recorded, so it is owed later."""
    entry, _devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    coordinator._upstream_announced["MQTT broker"] = 3
    coordinator._broker_down_at = None
    assert coordinator._upstream_messages() == []
    coordinator._grace_until = 0.0
    assert coordinator._upstream_messages() == [("MQTT broker", 3, True)]


async def test_the_repair_card_names_the_moment(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, _phone = await _house(hass, freezer)
    await _lose_the_clocks(hass, hass_storage, freezer, entry)
    loaded_at = dt_util.as_local(dt_util.utcnow()).strftime("%-I:%M %p")
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET) is None
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    issue = registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET)
    assert issue is not None
    assert issue.translation_placeholders["time"] == loaded_at
    assert issue.severity == ir.IssueSeverity.WARNING
    assert not issue.is_fixable


async def test_a_whole_clocks_file_raises_no_card(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: an ordinary restart says nothing about clocks."""
    entry, _devices, _phone = await _house(hass, freezer)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET) is None
