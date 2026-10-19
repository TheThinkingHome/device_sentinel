# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_freeze_unavailable_split.py, Version: 0.26.6 (2026-10-18)

"""Freeze and unavailable, muted apart (James, 17 October 2026).

A freeze mute silences only what is judged from silence: frozen and
never reported. Unavailable has its own mute, set on a device only. A
device's main entities, the ones Home Assistant puts in no category,
decide whether it is down, and unknown counts as nothing. Every test
here that tells the new rule from the old fails on 0.26.5; the rest
guard what stays the same.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
)

from custom_components.device_sentinel.dashboard_api import mutes_for_kinds

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk
from .test_zwave_dead_node import _house as _zwave_house

HOUR = 3600.0


def _sensor(hass, uid, *, main="binary_sensor", extras=(("sensor", EntityCategory.DIAGNOSTIC),), domain="test"):
    """A device with one main entity and some categorized ones, as a
    Zigbee motion or door sensor is: the motion or contact entity, then
    battery and signal (diagnostic), a setting (config), a firmware
    notice (update)."""
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Sensor {uid}")
    reg = er.async_get(hass)
    ids = {"main": reg.async_get_or_create(main, domain, f"{uid}_main", device_id=device.id, config_entry=source).entity_id}
    for index, (entity_domain, category) in enumerate(extras):
        ids[f"x{index}"] = reg.async_get_or_create(
            entity_domain, domain, f"{uid}_x{index}", device_id=device.id, config_entry=source,
            entity_category=category).entity_id
    return source, device, ids


async def _ready(hass, freezer, uid, options=None, **kwargs):
    freezer.move_to(PIN)
    source, device, ids = _sensor(hass, uid, **kwargs)
    for key, eid in ids.items():
        hass.states.async_set(eid, "off" if key == "main" else "87")
    if options is not None:
        options = {k: [device.id] if v == "SELF" else v for k, v in options.items()}
    coord = await setup_coordinator(hass, options)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    # The device reports once, so its clock runs from now.
    hass.states.async_set(ids["main"], "on")
    await hass.async_block_till_done()
    return coord, device, ids, record


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]


# ---------------------------------------------------- the mutes, apart


async def test_a_freeze_muted_device_is_reported_when_it_goes_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "fm1", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert [i["kinds"] for i in coord.todo_items if i["device_id"] == device.id] == [{"unavailable": record["frozen_since"]}] or any(
        i["device_id"] == device.id for i in coord.todo_items)
    for key, eid in ids.items():
        hass.states.async_set(eid, "on" if key == "main" else "86")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert len(_mine(faults, device.id)) == 1 and len(_mine(back, device.id)) == 1


async def test_a_freeze_muted_device_is_never_frozen(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "fm2", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)


async def test_a_freeze_mute_by_integration_still_reports_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "fm3", {CONF_FREEZE_MUTED_INTEGRATIONS: ["test"]})
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_freeze_muted_device_is_never_called_never_reported(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "fm4", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    now = dt_util.utcnow().timestamp() + 30 * 86400
    assert coord._device_down_category(device.id, record, now) is None
    hass.config_entries.async_update_entry(coord.entry, options={})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    assert coord._device_down_category(device.id, record, now) == FREEZE_CATEGORY_NEVER_REPORTED


async def test_an_unavailable_muted_device_is_silent_when_it_goes(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "um1", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None, "a TV off at the wall is neither unavailable nor frozen"
    assert not _mine(faults, device.id)


async def test_an_unavailable_muted_device_is_still_called_frozen(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "um2", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_a_device_muted_for_both_gets_no_verdict(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(
        hass, freezer, "bm1", {CONF_FREEZE_MUTED_DEVICES: "SELF", CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None


async def test_the_unavailable_mute_is_set_from_the_device_page_and_leaves_silently(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "um3")
    back = record_events(hass, EVENT_RECOVERED)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert any(i["device_id"] == device.id for i in coord.todo_items)
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 120)
    assert not any(i["device_id"] == device.id for i in coord.todo_items)
    assert not _mine(back, device.id), "a mute is not a recovery (#537)"
    assert coord.page_mutes(device.id)["unavailable"] == {"on": True, "source": "device", "here": True}
    assert "unavailable" in coord.mute_text(device.id)


# ------------------------------------------- the main entities decide


async def test_a_motion_sensor_whose_motion_entity_goes_is_unavailable(hass: HomeAssistant, freezer):
    """James's example: the motion entity unavailable, battery and signal
    still holding values, a setting and a firmware notice too."""
    coord, device, ids, record = await _ready(
        hass, freezer, "mo1",
        extras=(("sensor", EntityCategory.DIAGNOSTIC), ("sensor", EntityCategory.DIAGNOSTIC),
                ("select", EntityCategory.CONFIG), ("update", None)))
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_door_sensor_whose_contact_goes_is_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "do1")
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_held_battery_on_a_freeze_muted_dead_sensor_does_not_hide_it(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "do2", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert len(_mine(faults, device.id)) == 1


async def test_a_diagnostic_going_alone_says_nothing(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "do3")
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None


async def test_a_device_with_no_main_entity_is_read_on_all(hass: HomeAssistant, freezer):
    """A button or a Zigbee router has only categorized entities."""
    coord, device, ids, record = await _ready(
        hass, freezer, "bt1", main="sensor",
        extras=(("sensor", EntityCategory.DIAGNOSTIC),))
    er.async_get(hass).async_update_entity(ids["main"], entity_category=EntityCategory.DIAGNOSTIC)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None, "one entity still holds a value"
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# ---------------------------------------------- unknown counts as nothing


async def test_every_entity_unknown_is_not_down(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "uk1")
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)


async def test_an_unknown_main_entity_with_its_diagnostics_gone_is_unavailable(hass: HomeAssistant, freezer):
    """A Zigbee action sensor reads unknown until pressed; its battery
    and signal going unavailable say the device is gone."""
    coord, device, ids, record = await _ready(hass, freezer, "uk2", main="sensor")
    hass.states.async_set(ids["main"], "unknown")
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_unknown_beside_unavailable_is_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(
        hass, freezer, "uk3", extras=(("binary_sensor", None), ("sensor", EntityCategory.DIAGNOSTIC)))
    hass.states.async_set(ids["main"], "unavailable")
    hass.states.async_set(ids["x0"], "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_an_unknown_problem_standing_at_the_upgrade_waits_for_the_device(hass: HomeAssistant, freezer):
    """No new unknown is raised; one standing from 0.26.5 is held until
    the device reports, as any down problem is (#529)."""
    coord, device, ids, record = await _ready(hass, freezer, "uk4")
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNKNOWN
    record["frozen_since"] = dt_util.utcnow().timestamp()
    await walk(hass, freezer, 10 * 60)
    hass.states.async_set(ids["main"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None


# ------------------------------------------------ stacks and dropping out


async def test_a_freeze_muted_z_wave_node_marked_dead_is_reported(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _zwave_house(hass, freezer)
    hass.config_entries.async_update_entry(coord.entry, options={CONF_FREEZE_MUTED_DEVICES: [device.id]})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    faults = record_events(hass, EVENT_FAULT)
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(_mine(faults, device.id)) == 1


async def test_an_unavailable_muted_z_wave_node_marked_dead_is_silent(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _zwave_house(hass, freezer)
    hass.config_entries.async_update_entry(coord.entry, options={CONF_UNAVAILABLE_MUTED_DEVICES: [device.id]})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None


def test_the_problem_list_offers_the_mute_that_matches_each_kind():
    assert mutes_for_kinds({"unavailable": 1.0}) == ["unavailable"]
    assert mutes_for_kinds({"flapping": 1.0}) == ["unavailable"]
    assert mutes_for_kinds({"unknown": 1.0}) == ["unavailable"]
    assert mutes_for_kinds({"frozen": 1.0}) == ["freeze"]
    assert mutes_for_kinds({"never_reported": 1.0}) == ["freeze"]
    assert mutes_for_kinds({"frozen": 1.0, "low_battery": 2.0}) == ["freeze", "battery"]
