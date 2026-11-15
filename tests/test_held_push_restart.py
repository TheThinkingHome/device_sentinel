# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_held_push_restart.py, Version: 0.29.0 (2026-11-14)

"""A fault held for its device's debounce is pushed after a reload.

NOTE-06 holds a fault 30 percent of the device's learned gap before it
reaches a phone (an hour for a device that reports every 3 h 20 min).
The hold lives only in memory (_held_events). A reload or restart inside
the hold drops it: the item is already on the stored list, so the new
session never sees the fault "arrive" and never pushes it. The phone is
never told about that problem at all, and its later recovery is pushed
as news about a fault nobody heard of.

Asserts the correct behaviour: the fault is pushed once the hold that
began before the reload is over.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_TODO_ITEMS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_FROZEN,
)

from tests.helpers import setup_entry
from tests.outage_helpers import arm


def _device(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=name
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device, ent.entity_id


async def test_a_held_fault_is_still_pushed_after_a_reload(
    hass: HomeAssistant, freezer
):
    device, eid = _device(hass, "hr1", "Held Across Reload")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    calls: list[dict] = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", "phone", handler)
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()

    gap = 3600.0
    now = dt_util.utcnow().timestamp()
    # A learned rhythm, dated and observed for a month, as a real house
    # holds it, so the reload's load keeps it.
    record = arm(coord, device.id, gap)
    record[DEV_LAST_ACTIVITY] = now - 3 * gap
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - gap
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert calls == []
    assert coord._held_events, "the fault is held for its debounce"
    assert any(
        item.get("device_id") == device.id for item in coord.data[DATA_TODO_ITEMS]
    )

    # Ten minutes into the 18-minute hold, the entry reloads (an update,
    # an integration reload, a Home Assistant restart).
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    # Well past the hold and past the startup grace, minute by minute.
    for _ in range(40):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    still_listed = any(
        item.get("device_id") == device.id for item in coord.data[DATA_TODO_ITEMS]
    )
    assert still_listed, "precondition: the device is still frozen and listed"
    pushed = [c for c in calls if "Held Across Reload" in str(c.get("message"))]
    assert pushed, (
        "the fault held before the reload was never pushed: the phone "
        "never hears of a problem that is still on the list"
    )


async def test_a_held_fault_that_recovers_inside_the_grace_sends_nothing(
    hass: HomeAssistant, freezer
):
    device, eid = _device(hass, "hr2", "Back In The Grace")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    calls: list[dict] = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", "phone", handler)
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()

    gap = 3600.0
    now = dt_util.utcnow().timestamp()
    # A learned rhythm, dated and observed for a month, as a real house
    # holds it, so the reload's load keeps it.
    record = arm(coord, device.id, gap)
    record[DEV_LAST_ACTIVITY] = now - 3 * gap
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - gap
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert calls == []
    assert coord._held_events, "the fault is held for its debounce"
    assert any(
        item.get("device_id") == device.id for item in coord.data[DATA_TODO_ITEMS]
    )

    # Ten minutes into the 18-minute hold, the entry reloads (an update,
    # an integration reload, a Home Assistant restart).
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    # Inside the new run's startup grace the device speaks again: its
    # fault leaves the list before the hold could be armed again.
    assert coord._in_startup_grace()
    hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()

    # Well past the hold and past the startup grace, minute by minute.
    for _ in range(40):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    said = [c for c in calls if "Back In The Grace" in str(c.get("message"))]
    assert said == [], (
        "a fault the phone was never sent had its recovery pushed: " + repr(said)
    )
