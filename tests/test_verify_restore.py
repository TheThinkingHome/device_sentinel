# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_verify_restore.py, Version: 0.19.9 (2026-08-31)

# Tests for the repair at the point of detection (ruling #370).
#
# A file that will not parse restores automatically (ruling #345,
# unchanged). A file that loads with damage is repaired at the load:
# from last-good when one is usable, in place otherwise, with the
# evidence copy first and one buttonless notice after. A damaged
# clocks file is discarded, not repaired (ruling #356, unchanged).
# The three-option card, quarantine and held records these tests
# once covered are retired; what stands is the promise they served,
# that the load survives whatever the file holds.

import json

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DOMAIN,
    REPAIR_STORAGE_REPAIRED,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_KIND,
    SYS_STORAGE_REPAIR,
)

from .helpers import register_device, setup_coordinator


# ------------------------------------------------- the notice card


async def test_a_clean_session_raises_no_notice(hass: HomeAssistant) -> None:
    """Nothing repaired, nothing raised, and the evaluation clears
    a notice a previous session might have left."""
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    before = json.dumps(coord.data, sort_keys=True, default=str)
    coord._evaluate_repairs("grace")
    assert coord._repair_notice is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_STORAGE_REPAIRED)
        is None
    )
    assert json.dumps(coord.data, sort_keys=True, default=str) == before


async def test_a_repair_raises_the_notice_and_it_acknowledges(
    hass: HomeAssistant,
) -> None:
    """The notice names what was repaired and where the originals
    are, offers nothing but acknowledgement, and Submit clears it
    (ruling #370)."""
    from homeassistant.components.repairs import ConfirmRepairFlow

    from custom_components.device_sentinel import repairs as rmod

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord.data.setdefault("incidents", []).append("junk")
    await coord._save_main()
    assert coord._repair_notice, "the repair raised no notice"
    coord._evaluate_repairs("grace")
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, REPAIR_STORAGE_REPAIRED
    )
    assert issue is not None
    assert issue.translation_placeholders["what"]
    assert issue.translation_placeholders["where"]
    flow = await rmod.async_create_fix_flow(
        hass, REPAIR_STORAGE_REPAIRED, {"entry_id": coord.entry.entry_id}
    )
    assert isinstance(flow, ConfirmRepairFlow)


# ------------------------------------------- the load-path repairs


async def test_a_non_dict_record_no_longer_kills_setup(
    hass: HomeAssistant, hass_storage
) -> None:
    """Reproduced on 27 August: a registered device's record
    corrupted to a string died in the clocks merge with a TypeError.
    The gate now drops it as damage (ruling #370, amending #357):
    setup lives, the record is gone, the notice says so, and the
    device relearns from its next report."""
    device, _eids = register_device(hass, "victim")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    stored["data"].setdefault(DATA_DEVICES, {})[device.id] = "garbage"
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    record = coord2.data[DATA_DEVICES].get(device.id)
    assert record is None or isinstance(record, dict), (
        "the garbage record survived the gate"
    )
    assert coord2._repair_notice, "the repair raised no notice"


async def test_a_faulted_record_is_repaired_and_setup_survives(
    hass: HomeAssistant, hass_storage
) -> None:
    """The second adversarial round proved a poisoned series took
    setup down. The gate now repairs the field to its default
    (ruling #370): setup lives, the record stays watched, and the
    series is a series again."""
    device, _eids = register_device(hass, "repaired_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    record = stored["data"][DATA_DEVICES].get(device.id)
    assert isinstance(record, dict)
    record["daily_max"] = "rotten"
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, (
        "a reported fault still killed setup"
    )
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    repaired = coord2.data[DATA_DEVICES].get(device.id)
    assert isinstance(repaired, dict)
    assert repaired["daily_max"] == [], "the poison was not repaired"
    coord2._grace_until = 0.0
    coord2._rebuild_registry_view()
    watched = [d for d, _r in coord2.watched_records() if d == device.id]
    assert watched, "a repaired record was still held out of judgment"


async def test_the_fold_runs_on_a_repaired_record(
    hass: HomeAssistant,
) -> None:
    """The fold no longer skips anything (ruling #370): a record the
    gate repaired folds like any other, because the poison is gone
    rather than held."""
    device, _eids = register_device(hass, "fold_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].get(device.id)
    assert record is not None
    record["daily_max"] = "rotten"
    record["today_max"] = 5.0
    coord._repair_records()
    await coord._on_midnight(None)
    assert record["daily_max"] == [5.0], (
        "the repaired record did not fold"
    )


# ------------------------------------- the clocks rules, unchanged


async def test_a_damaged_clocks_file_is_discarded_not_healed(
    hass: HomeAssistant, hass_storage
) -> None:
    """Ruling #356: a clocks file that fails its shape is treated as
    missing. The session latches and the event says so."""
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    clocks = hass_storage.get(STORAGE_CLOCKS_KEY)
    assert clocks, "no clocks file written"
    # A record that is not a record is damage; a missing field is
    # not (an upgrade adding a clock field looks exactly like that
    # on its first boot) and must never trigger the discard.
    clocks["data"]["clocks"] = {"someone": "garbage"}
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    events = [
        e
        for e in coord2.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
        and "clocks" in str(e.get("detail"))
    ]
    assert len(events) == 1
    assert "discarded" in str(events[0].get("detail"))


async def test_a_clocks_file_missing_a_field_is_not_discarded(
    hass: HomeAssistant, hass_storage
) -> None:
    """The other half of ruling #356: schema evolution merges."""
    device, _eids = register_device(hass, "evolve_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    clocks = hass_storage.get(STORAGE_CLOCKS_KEY)
    assert clocks
    stored = clocks["data"].get("clocks") or {}
    target = stored.get(device.id)
    assert isinstance(target, dict) and target, "no clock record to thin"
    field = sorted(target)[0]
    del target[field]
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    events = [
        e
        for e in coord2.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
        and "discarded" in str(e.get("detail"))
    ]
    assert events == [], "a missing field triggered the discard"
