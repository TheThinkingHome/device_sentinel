# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_held_values_storage.py, Version: 0.27.10 (2026-10-27)

"""The held values on disk (rule WATCH-12).

Kept in the main file, not with the clocks: written in the verdict's
own immediate save, cleared when the verdict ends, shape-checked at the
storage boundary with a damaged entry dropped alone, and absent from an
older file without fault.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_HELD_VALUES,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
    STORAGE_KEY,
)
from custom_components.device_sentinel.normalise import (
    check_records,
    drop_damaged_held_values,
)
from custom_components.device_sentinel.records import _new_device_record

from tests.helpers import record_events, register_device, setup_coordinator
from tests.outage_helpers import PIN, _quiet, arm, entry_of, past_grace, rec, restart, walk
from tests.test_freeze_unavailable_split import _mine


async def _frozen(hass, freezer, uid="door"):
    freezer.move_to(PIN)
    device, (eid,) = register_device(hass, uid, uid.title())
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    key = er.async_get(hass).async_get(eid).id
    return coord, device, eid, key


def _on_disk(hass_storage, device_id):
    return hass_storage[STORAGE_KEY]["data"][DATA_DEVICES][device_id]


def test_held_values_live_in_the_main_file():
    assert DEV_HELD_VALUES not in CLOCK_FIELDS
    assert _new_device_record("2026-10-26T00:00:00+00:00", None)[DEV_HELD_VALUES] is None


async def test_written_in_the_verdicts_own_save(hass: HomeAssistant, freezer, hass_storage):
    """Keyed by the entity's registry id, so a rename keeps it."""
    coord, device, eid, key = await _frozen(hass, freezer)
    stored = _on_disk(hass_storage, device.id)
    assert stored[DEV_FROZEN_CATEGORY] == "frozen"
    assert stored[DEV_HELD_VALUES] == {key: "on"}


async def test_cleared_at_recovery(hass: HomeAssistant, freezer, hass_storage):
    coord, device, eid, key = await _frozen(hass, freezer)
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_HELD_VALUES] is None
    # Past the routine save: a recovery landing during a save already in
    # flight waits for the next main-file save.
    await walk(hass, freezer, coord.coalesce_seconds + 120)
    stored = _on_disk(hass_storage, device.id)
    assert (stored[DEV_FROZEN_CATEGORY], stored[DEV_HELD_VALUES]) == (None, None)


async def test_cleared_when_the_device_is_set_aside(hass: HomeAssistant, freezer):
    coord, device, eid, key = await _frozen(hass, freezer)
    record = rec(coord, device.id)
    coord._clear_verdicts_for_set_aside({device.id: None})
    assert record[DEV_HELD_VALUES] is None
    assert device.id not in coord._on_watch


async def test_a_power_cut_keeps_them(hass: HomeAssistant, freezer):
    """The machine loses power after the verdict: nothing more is
    written, and the start still holds the value and arms the watch."""
    coord, device, eid, key = await _frozen(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    entry = entry_of(hass)
    coord._stopped = True
    for name in ("_save_now", "_routine_save", "_save_routine_main",
                 "async_flush_answers", "async_probe_stop"):
        setattr(coord, name, _quiet)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_remove(eid)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert rec(coord, device.id)[DEV_HELD_VALUES] == {key: "on"}
    assert coord._on_watch[device.id] == {key}
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 7 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert not _mine(recovered, device.id)


def test_the_shape_check():
    record = _new_device_record("2026-10-26T00:00:00+00:00", None)
    devices = {"d": record}
    for good in (None, {}, {"abc": "on"}, {"abc": "21.5", "def": "x" * 255}):
        record[DEV_HELD_VALUES] = good
        assert not check_records(devices), good
    for bad in ([], "on", 5, {"abc": 5}, {"abc": "unavailable"}, {"abc": ""},
                {"abc": "x" * 256}, {"": "on"}, {"abc": None}):
        record[DEV_HELD_VALUES] = bad
        faults = check_records(devices)
        assert [f[1] for f in faults] == [DEV_HELD_VALUES], bad


def test_damaged_entries_are_dropped_alone():
    devices = {
        "a": {DEV_HELD_VALUES: {"k1": "on", "k2": 7, "k3": "unknown"}},
        "b": {DEV_HELD_VALUES: {"k4": None}},
        "c": {DEV_HELD_VALUES: "not a mapping"},
        "d": "not a record",
    }
    assert drop_damaged_held_values(devices) == 3
    assert devices["a"][DEV_HELD_VALUES] == {"k1": "on"}
    assert devices["b"][DEV_HELD_VALUES] is None
    # Left for the record check, which resets the field.
    assert devices["c"][DEV_HELD_VALUES] == "not a mapping"


async def test_damage_on_disk_costs_only_the_damaged_entry(
    hass: HomeAssistant, freezer, hass_storage
):
    coord, device, eid, key = await _frozen(hass, freezer)

    def damage():
        _on_disk(hass_storage, device.id)[DEV_HELD_VALUES] = {key: "on", "bad": 12}

    coord = await restart(hass, freezer, before_setup=damage)
    assert rec(coord, device.id)[DEV_HELD_VALUES] == {key: "on"}
    assert coord._load_faulty is False
    await walk(hass, freezer, 7 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"


async def test_a_field_that_is_not_a_mapping_is_reset(
    hass: HomeAssistant, freezer, hass_storage
):
    coord, device, eid, key = await _frozen(hass, freezer)

    def damage():
        _on_disk(hass_storage, device.id)[DEV_HELD_VALUES] = ["on"]

    coord = await restart(hass, freezer, before_setup=damage)
    assert rec(coord, device.id)[DEV_HELD_VALUES] is None
    assert device.id not in coord._on_watch


async def test_first_start_after_the_upgrade_from_0_27_5(
    hass: HomeAssistant, freezer, hass_storage
):
    """A file written before held values existed loads clean, and a
    verdict standing from it holds nothing."""
    coord, device, eid, key = await _frozen(hass, freezer)

    def as_0275():
        for stored in hass_storage[STORAGE_KEY]["data"][DATA_DEVICES].values():
            stored.pop(DEV_HELD_VALUES, None)

    coord = await restart(hass, freezer, before_setup=as_0275)
    assert coord._load_faulty is False
    assert rec(coord, device.id)[DEV_HELD_VALUES] is None
    assert coord._on_watch == {}


async def test_values_with_no_verdict_behind_them_go_at_the_start(
    hass: HomeAssistant, freezer, hass_storage
):
    freezer.move_to(PIN)
    device, (eid,) = register_device(hass, "lamp", "Lamp")
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    key = er.async_get(hass).async_get(eid).id

    def plant():
        _on_disk(hass_storage, device.id)[DEV_HELD_VALUES] = {key: "on"}

    coord = await restart(hass, freezer, before_setup=plant)
    assert rec(coord, device.id)[DEV_HELD_VALUES] is None
    assert coord._on_watch == {}


async def test_a_renamed_entity_keeps_its_held_value(hass: HomeAssistant, freezer):
    coord, device, eid, key = await _frozen(hass, freezer)
    er.async_get(hass).async_update_entity(eid, new_entity_id="sensor.front_door")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    coord = await restart(hass, freezer)
    assert coord._on_watch[device.id] == {key}
    assert coord._held_keys["sensor.front_door"] == key


async def test_the_diagnostics_count_them(hass: HomeAssistant, freezer):
    coord, device, eid, key = await _frozen(hass, freezer)
    assert coord.held_diagnostics() == {"devices_with_held_values": 1, "entities_on_watch": 0}
    coord = await restart(hass, freezer)
    assert coord.held_diagnostics() == {"devices_with_held_values": 1, "entities_on_watch": 1}
