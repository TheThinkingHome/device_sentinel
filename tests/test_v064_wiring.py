# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v064_wiring.py, Version: 0.6.4 (2026-07-21)

"""0.6.4 tests: the wiring the suite used to take on faith (T1).

Three tests from the third deep analysis, all exercising real plumbing
rather than calling the machinery directly. The tick-driven test lets
HA's own interval timer carry a freeze from judgment into the problem
list with no direct calls, the safety net for the coming E1 save-cadence
work. The options test drives an exclusion through the real update
listener and watches the item leave. The cap test writes the journal
past its bound and proves the oldest entry, and only the oldest, is
evicted.
"""

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
    DATA_TODO_JOURNAL,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
    TODO_JOURNAL_KEEP,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _item_for(coord, device_id):
    for record in coord.todo_items:
        if record["device_id"] == device_id:
            return record
    return None


async def test_tick_carries_a_freeze_into_the_list(
    hass: HomeAssistant, freezer
):
    """End to end on HA's own timer: a device with an armed rhythm
    goes silent, the render tick judges it frozen and the same tick
    lists it, with no test code calling the machinery directly."""
    device, entity_id = _register(hass, "t1", "Tick Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()

    # Arm the rhythm: an hourly reporter, learned past the gate. The
    # last activity is real (the state write above); the window is an
    # hour, so silence beyond it must fire on a natural tick.
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)

    # Leave the startup grace, then go silent far past the window.
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _item_for(coord, device.id) is None  # inside its window

    freezer.tick(timedelta(hours=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    item = _item_for(coord, device.id)
    assert item is not None
    assert "Tick Sensor" in item["summary"]
    assert item["status"] == "needs_action"


async def test_option_exclusion_clears_the_item(hass: HomeAssistant):
    """Through the real path: excluding a listed device by updating
    the entry's options deletes its item via the update listener, no
    direct sync call."""
    device, entity_id = _register(hass, "o1", "Excluded Later")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")

    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - 8 * 3600
    )
    coord._judge_all_devices()
    coord._sync_problem_list()
    assert _item_for(coord, device.id) is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "excluded_devices": [device.id]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _item_for(coord, device.id) is None


async def test_journal_cap_evicts_only_the_oldest(hass: HomeAssistant):
    """Entry 101 evicts entry 1 and nothing else; the bound holds at
    exactly TODO_JOURNAL_KEEP."""
    entry = await _setup(hass)
    coord = entry.runtime_data

    for n in range(TODO_JOURNAL_KEEP + 1):
        coord._journal_addition(f"dev{n}", f"Device {n}", "frozen")

    journal = coord.data[DATA_TODO_JOURNAL]
    assert len(journal) == TODO_JOURNAL_KEEP
    names = [e["name"] for e in journal]
    assert "Device 0" not in names          # the oldest, evicted
    assert names[0] == "Device 1"           # order preserved
    assert names[-1] == f"Device {TODO_JOURNAL_KEEP}"
