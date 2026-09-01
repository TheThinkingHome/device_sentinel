# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_attack_storage_boundary.py, Version: 0.19.11 (2026-08-31)

"""Attack the storage boundary of ruling #370.

Two boundaries and one promise. On the way in, the load gate checks
every record and every table row after migration and repairs what it
finds, from last-good when one is usable and in place otherwise. On
the way out, the write seam refuses a row the writer got wrong the
instant it is made, and the save checks the whole outgoing document
and repairs at that moment. The promise is that no reader ever meets
a damaged row, that a repair never overwrites the clean last-good
copy, and that the person is told rather than asked.

The attack damages random rows in random tables in random ways,
loads through the real path, drives readers, sensors and reports,
saves through the seam, and checks the contract on every round. Then
it pushes random writer faults through every seam. Then it disables
the gate and requires the attack to fail, because a test that cannot
fail proves nothing.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import STORAGE_KEY
from custom_components.device_sentinel.normalise import (
    TABLES,
    check_records,
    check_storage,
    damaged_rows,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import register_device, setup_coordinator

JAMES = fleet_path("james", "2026-08-29", "device_sentinel.storage")
TIM = fleet_path("tim", "2026-08-29", "device_sentinel_storage.json")
POISONS = [None, "junk", [1, 2], {"x": 1}, True, -7, 4.1e18, "", 3.5]
ROUNDS = 40


def _fleet_tables(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)["data"]
    return {key: data.get(key) for key in TABLES if isinstance(data.get(key), list)}


def _damage(tables: dict, rng: random.Random) -> tuple[dict, int]:
    """Damage a random handful of rows across the tables. Returns the
    damaged copy and how many rows were made unusable."""
    doc = copy.deepcopy(tables)
    hits = 0
    for key, rows in doc.items():
        if not rows:
            continue
        for _ in range(rng.randint(0, 3)):
            index = rng.randrange(len(rows))
            choice = rng.random()
            if choice < 0.2:
                rows[index] = rng.choice(["not a row", 7, None, [1]])
            elif isinstance(rows[index], dict) and rows[index]:
                field = rng.choice(list(rows[index]))
                if choice < 0.6:
                    rows[index][field] = rng.choice(POISONS)
                else:
                    del rows[index][field]
    for key, rows in doc.items():
        hits += len(damaged_rows({key: rows}).get(key, []))
    return doc, hits


async def _round(hass, hass_storage, path: Path, seed: int) -> dict:
    rng = random.Random(seed)
    tables = _fleet_tables(path)
    damaged, expected_hits = _damage(tables, rng)

    register_device(hass, f"b{seed}")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    for key, rows in damaged.items():
        stored["data"][key] = rows
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, f"seed {seed}: setup died"
    coord2 = entry.runtime_data
    coord2._grace_until = 0.0

    # 1. No reader meets a damaged row or record: the gate repaired.
    assert damaged_rows(coord2.data) == {}, (
        f"seed {seed}: damaged rows reached the working document"
    )
    assert not check_records(coord2.data.get("devices")), (
        f"seed {seed}: a damaged record reached the working document"
    )
    if expected_hits:
        assert coord2.storage_load_faulty, (
            f"seed {seed}: damage was repaired without latching"
        )
        assert coord2._repair_notice or coord2._restored_from is not None, (
            f"seed {seed}: damage was answered with neither a repair "
            "notice nor a restore"
        )

    # 2. Readers, sensors and reports run on the repaired document.
    coord2._judge_all_devices()
    coord2._sync_problem_list()
    await hass.async_block_till_done()
    for name in ("learning_buckets", "recording_depth", "todo_items",
                 "frozen_devices_list", "battery_low_list",
                 "signal_problem_list", "classification_breakdown"):
        getattr(coord2, name)
    assert await coord2.async_regenerate_reports()

    # 3. The save through the seam writes a clean document. The
    # no-rotation rule for a repaired session is proven by the
    # dedicated rotation tests below, where the rename is spied on.
    out = coord2._data_to_save()
    assert damaged_rows(out) == {}, (
        f"seed {seed}: the outgoing document carries damage"
    )
    return {"seed": seed, "damaged": expected_hits}


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(ROUNDS))
async def test_boundary_james(hass: HomeAssistant, hass_storage, seed):
    await _round(hass, hass_storage, JAMES, 80_000 + seed)


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(ROUNDS))
async def test_boundary_tim(hass: HomeAssistant, hass_storage, seed):
    await _round(hass, hass_storage, TIM, 90_000 + seed)


# ------------------------------------------------ the save seam


async def test_a_fault_at_save_is_repaired_at_that_moment(
    hass: HomeAssistant,
):
    """An in-place edit the seam never saw is caught by the save
    check and repaired then (ruling #370): the row is dropped, the
    event and the notice say so, and last-good is left alone."""
    coord = await setup_coordinator(hass)
    events_before = len(coord.data.get("system_events") or [])
    coord.data.setdefault("incidents", []).append(
        {"device_id": "x", "name": "n", "kind": "frozen",
         "event": "opened", "when": "not a moment", "cause": None,
         "duration": None}
    )
    coord._rotation_armed = True
    await coord._save_main()
    assert damaged_rows(coord.data) == {}, "the fault survived the save"
    assert not any(
        isinstance(r, dict) and r.get("when") == "not a moment"
        for r in coord.data["incidents"]
    ), "the damaged row is still in the working table"
    events = coord.data.get("system_events") or []
    assert len(events) > events_before, "the repair wrote no system event"
    assert coord._repair_notice, "the repair raised no notice"
    # The save that repaired arms the next rotation, because the
    # file it wrote is the repaired, clean one.
    assert coord._rotation_armed


async def test_a_repaired_save_does_not_rotate(
    hass: HomeAssistant, monkeypatch
):
    """A save that repaired something writes the live file and
    leaves last-good alone (ruling #370)."""
    from custom_components.device_sentinel import store as smod

    rotations = []

    async def spy(_hass):
        rotations.append(True)
        return True

    monkeypatch.setattr(smod, "async_rotate_last_good", spy)
    coord = await setup_coordinator(hass)
    rotations.clear()  # setup's own clean save legitimately rotated
    coord._rotation_armed = True
    coord.data.setdefault("incidents", []).append("junk")
    await coord._save_main()
    assert rotations == [], "a repaired save rotated into last-good"
    # The next save is clean, the live file was written clean by the
    # repair, and the rotation runs.
    await coord._save_main()
    assert rotations == [True], "the clean save after a repair did not rotate"


async def test_a_clean_save_rotates_only_from_a_clean_live_file(
    hass: HomeAssistant, monkeypatch
):
    """The first save after a load that needed repair writes without
    rotating, because the live file on disk at that moment is the
    damaged original (ruling #370)."""
    from custom_components.device_sentinel import store as smod

    rotations = []

    async def spy(_hass):
        rotations.append(True)
        return True

    monkeypatch.setattr(smod, "async_rotate_last_good", spy)
    coord = await setup_coordinator(hass)
    rotations.clear()  # setup's own clean save legitimately rotated
    coord._rotation_armed = False
    await coord._save_main()
    assert rotations == [], "an unarmed save rotated"
    assert coord._rotation_armed, "a clean save did not arm the rotation"
    await coord._save_main()
    assert rotations == [True]


async def test_a_clean_save_holds_nothing_and_records_nothing(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    coord._judge_all_devices()
    coord._sync_problem_list()
    before = len(coord.data.get("system_events") or [])
    await coord._save_main()
    assert len(coord.data.get("system_events") or []) == before
    assert coord._repair_notice is None


# --------------------------------------------------- control runs


class TestControlGateOff:
    """The control run, in its own class so the lingering-timer
    waiver reaches it alone: when setup dies mid-way on purpose,
    the render tick it registered before dying has no unload to
    cancel it. That leak belongs to the crash the gate prevents,
    not to this release."""

    @pytest.fixture
    def expected_lingering_timers(self) -> bool:
        return True

    async def test_control_the_load_gate_catches_what_it_claims(
        self, hass: HomeAssistant, hass_storage, monkeypatch
    ):
        """With the load gate blinded, a damaged row reaches the working
        document. Proves the gate is what keeps them out."""
        from custom_components.device_sentinel import coordinator as cmod
        from custom_components.device_sentinel import store as smod

        monkeypatch.setattr(cmod, "damaged_rows", lambda _data: {})
        monkeypatch.setattr(smod, "damaged_rows", lambda _data: {})
        register_device(hass, "ctl")
        coord = await setup_coordinator(hass)
        entry = coord.entry
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        hass_storage.get(STORAGE_KEY)["data"]["incidents"] = [
            {"device_id": "x", "name": "n", "kind": "k", "event": "opened",
             "when": "x", "cause": None, "duration": None}
        ]
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        from custom_components.device_sentinel.normalise import (
            damaged_rows as real_damaged_rows,
        )
        # With the gate off, the attack must succeed one way or the
        # other: either setup died on the damage, which is what the
        # reference run produced when the brief compared a string
        # timestamp, or the damage sits in the working document where a
        # reader will meet it.
        if entry.state is ConfigEntryState.LOADED:
            coord2 = entry.runtime_data
            assert real_damaged_rows(coord2.data) != {}, (
                "the control run passed with the gate off, so the test "
                "proves nothing"
            )
        else:
            # Setup died on the damage, which is the control succeeding.
            # The entry is removed so teardown does not trip over a
            # setup-error state this test created on purpose.
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()


def test_the_shape_check_and_the_boundary_agree_on_clean_data():
    """A document with no faults repairs to itself; a document with
    a damaged row is faulted by the check and named by the walk."""
    clean = {"incidents": [
        {"device_id": "a", "name": "n", "kind": "k", "event": "opened",
         "when": 1.0, "cause": None, "duration": None}
    ]}
    assert check_storage(clean) == []
    assert damaged_rows(clean) == {}
    dirty = copy.deepcopy(clean)
    dirty["incidents"][0]["when"] = "x"
    assert check_storage(dirty) != []
    assert damaged_rows(dirty) == {"incidents": [0]}


# ------------------------------------------------ the write seam


@pytest.mark.parametrize("seed", range(30))
async def test_a_writer_fault_is_dropped_the_instant_it_is_made(
    hass: HomeAssistant, seed
):
    """Random bad rows pushed through every writer seam: none reaches
    the working table, each is dropped at once with the notice
    raised, and the writer keeps running."""
    rng = random.Random(100_000 + seed)
    coord = await setup_coordinator(hass)
    tables = list(TABLES)
    refused = 0
    for _ in range(25):
        table = rng.choice(tables)
        shape, _opt = TABLES[table]
        row = {field: rng.choice(POISONS) for field in shape}
        if rng.random() < 0.2:
            row = rng.choice(["junk", 7, None])
        ok = coord._append_row(table, row)
        if not ok:
            refused += 1
            assert row not in (coord.data.get(table) or []), (
                f"seed {seed}: a refused {table} row reached the working table"
            )
    assert refused, "the attack never produced a refused row"
    assert damaged_rows(coord.data) == {}, "damage reached the working document"
    assert coord._repair_notice, "a writer fault raised no notice"
    # The writer is still alive: a good row goes straight in.
    good = {"device_id": "d", "name": "n", "kind": "k", "event": "opened",
            "when": 1_788_000_000.0, "cause": None, "duration": None}
    assert coord._append_row("incidents", good)
    assert good in coord.data["incidents"]


async def test_every_real_writer_goes_through_the_seam(hass: HomeAssistant):
    """Drive the real writers and require every row they produce to
    fit its shape, which is what the seam demands of them."""
    device, _ = register_device(hass, "seam_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    notice_before = coord._repair_notice
    rec = coord.data["devices"].setdefault(device.id, {})
    rec["event_count"] = 0
    rec["last_activity"] = None
    rec["first_observed"] = "2026-07-08T00:00:00+00:00"
    coord._judge_all_devices()
    coord._sync_problem_list()
    coord._record_system_event("restart", duration=3.0)
    coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert coord._repair_notice == notice_before, (
        "a real writer produced a row the shape refuses: "
        f"{coord._repair_notice}"
    )
    assert damaged_rows(coord.data) == {}
