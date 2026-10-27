# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_load_repairs_counted.py, Version: 0.27.8 (2026-10-27)

"""Every repair at the start is told and counted (rule STOR-12). The
history cut back to the storage file's days writes a repair event, an
answers restore reads Problem on Status, a discarded clocks file counts,
and repairs at load counts rows, records and fields, not only restarted
clocks. The first save after any of them keeps the last good copy."""

from __future__ import annotations

import json
import os
import time

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_STORAGE_REPAIR,
)
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator, setup_entry
from .test_history_file import restart_with
from .test_history_file_disk import HIST, HIST_COPY, LIVE, LIVE_COPY, house, snapshot


async def test_a_history_drop_is_a_repair(hass: HomeAssistant, real_disk):
    entry, coord, ids = await house(hass)
    before = len(coord.data[DATA_SYSTEM_EVENTS])

    def lose_both():
        os.remove(os.path.join(real_disk, HIST))
        os.remove(os.path.join(real_disk, HIST_COPY))

    coord2 = await restart_with(hass, entry, lose_both)
    assert len(coord2.data[DATA_DEVICES][ids[0]]["daily_max"]) == 30
    new = coord2.data[DATA_SYSTEM_EVENTS][before:]
    repairs = [r for r in new if r.get("kind") == SYS_STORAGE_REPAIR]
    assert any("history" in str(r.get("detail", "")).lower() for r in repairs)
    assert coord2.storage_load_faulty is True
    assert coord2.repairs_at_load >= 1
    assert coord2._history_drop_note is None   # told once


async def test_an_answers_restore_reads_problem(hass: HomeAssistant, hass_storage):
    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)
    copy = os.path.join(directory, ANSWERS_STORE_KEY + ".last-good")
    with open(copy, "w", encoding="utf-8") as h:
        json.dump({"version": 1, "minor_version": 1, "key": ANSWERS_STORE_KEY,
                   "data": {"power": {"models": {}, "devices": {}},
                            "types": {"models": {}, "devices": {}}}}, h)
    try:
        coord = await setup_coordinator(hass)
        details = [str(row) for row in coord.data[DATA_SYSTEM_EVENTS]]
        assert any("restored from their backup" in d for d in details)
        assert coord.storage_load_faulty is True
        assert coord.repairs_at_load >= 1
    finally:
        os.remove(copy)


async def test_a_field_reset_at_load_is_counted(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "dev_c")
    record = _new_device_record("2026-08-17T00:00:00+00:00", time.time())
    record[DEV_FIRST_OBSERVED] = 12345
    hass_storage[STORAGE_KEY] = {"version": 1, "key": STORAGE_KEY,
                                 "data": {DATA_DEVICES: {device.id: record}}}
    coord = await setup_coordinator(hass)
    assert coord._repair_notice and "field(s) reset" in coord._repair_notice["what"]
    assert coord.storage_load_faulty is True
    assert coord.repairs_at_load >= 1


async def test_a_clean_start_counts_nothing(hass: HomeAssistant):
    register_device(hass, "dev_ok")
    coord = await setup_coordinator(hass)
    assert coord.repairs_at_load == 0
    assert coord.storage_load_faulty is False


async def test_a_discarded_clocks_file_is_counted(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "dev_k")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord._critical = True
    await coord._save_now()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    clocks = hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]
    assert device.id in clocks
    clocks[device.id][DEV_LAST_ACTIVITY] = "junk"
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    told = [r for r in coord2.data[DATA_SYSTEM_EVENTS]
            if r.get("kind") == SYS_STORAGE_REPAIR and "discarded" in str(r.get("detail"))]
    assert told, "precondition: the discard was told"
    assert coord2.storage_load_faulty is True
    assert coord2.repairs_at_load >= 1


async def test_a_history_drop_keeps_the_last_good_copy(hass: HomeAssistant, real_disk):
    entry, _coord, _ids = await house(hass)
    held = {}

    def lose_both():
        os.remove(os.path.join(real_disk, HIST))
        os.remove(os.path.join(real_disk, HIST_COPY))
        held["copy"] = snapshot(real_disk)[LIVE_COPY]
        assert snapshot(real_disk)[LIVE] != held["copy"]

    coord2 = await restart_with(hass, entry, lose_both)
    assert coord2.storage_load_faulty is True
    # The saves of a start that repaired something keep the last good copy.
    assert snapshot(real_disk)[LIVE_COPY] == held["copy"]


def _edit(path, change):
    with open(path) as h:
        doc = json.load(h)
    change(doc["data"])
    with open(path, "w") as h:
        json.dump(doc, h)


async def _damaged_start(hass, real_disk, clocks_too):
    entry, coord, ids = await house(hass)
    await coord._save_now()
    before = len(coord.data[DATA_SYSTEM_EVENTS])

    def damage():
        _edit(os.path.join(real_disk, LIVE),
              lambda d: d[DATA_DEVICES][ids[0]].__setitem__(DEV_FIRST_OBSERVED, 12345))
        if clocks_too:
            _edit(os.path.join(real_disk, STORAGE_CLOCKS_KEY),
                  lambda d: d["clocks"][ids[0]].__setitem__(DEV_LAST_ACTIVITY, "junk"))

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._restored_from is not None   # answered from the last good copy
    return coord2, before


async def test_a_restore_from_the_last_good_copy_counts_one(hass: HomeAssistant, real_disk):
    coord2, _ = await _damaged_start(hass, real_disk, False)
    assert coord2.storage_load_faulty is True
    assert coord2.repairs_at_load == 1


async def test_a_clocks_discard_with_a_restore_counts_each_once(hass: HomeAssistant, real_disk):
    coord2, before = await _damaged_start(hass, real_disk, True)
    told = [r for r in coord2.data[DATA_SYSTEM_EVENTS][before:]
            if r.get("kind") == SYS_STORAGE_REPAIR and "clocks file" in str(r.get("detail"))]
    assert len(told) == 1
    assert coord2.repairs_at_load == 2
