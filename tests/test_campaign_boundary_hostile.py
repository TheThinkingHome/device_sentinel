# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_campaign_boundary_hostile.py, Version: 0.19.9 (2026-08-31)

"""The hostile campaign against ruling #370, both real fleets.

The claim under attack is total: whatever happens to the storage
files, the load survives, no reader meets damage, the file the next
save writes is clean, and the last-good copy is never overwritten by
a worse one. The suites already in the tree damage rows and records
through the ordinary path; this one attacks the boundary itself, at
the seams where a repair can go wrong rather than where damage
starts.

Every test that finds nothing is a claim proven, so each one says
what it would have caught. Nothing here is fixed; the campaign
reports.
"""

from __future__ import annotations

import copy
import json
import os
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from custom_components.device_sentinel.normalise import (
    TABLES,
    check_containers,
    check_records,
    damaged_rows,
)

from tests.helpers import register_device, setup_coordinator

# The reference fleets are two real people's storage files and are
# deliberately not in this repository. Point FLEET_DIR at a directory
# holding them to run these cases; without it every fleet case skips,
# which is what happens in continuous integration and on anyone
# else's checkout.
FLEET_DIR = Path(
    os.environ.get("DEVICE_SENTINEL_FLEET_DIR", "/home/claude/fleets")
)
JAMES = FLEET_DIR / "james_0199" / "device_sentinel.storage"
JAMES_CLOCKS = FLEET_DIR / "james_0199" / "device_sentinel.clocks"
TIM = FLEET_DIR / "tim" / "device_sentinel_storage.json"
TIM_CLOCKS = FLEET_DIR / "tim" / "device_sentinel_clocks.json"

_ABSENT = "reference fleet file absent; set DEVICE_SENTINEL_FLEET_DIR"

FLEETS = [
    pytest.param(
        JAMES,
        JAMES_CLOCKS,
        id="james",
        marks=pytest.mark.skipif(
            not (JAMES.exists() and JAMES_CLOCKS.exists()), reason=_ABSENT
        ),
    ),
    pytest.param(
        TIM,
        TIM_CLOCKS,
        id="tim",
        marks=pytest.mark.skipif(
            not (TIM.exists() and TIM_CLOCKS.exists()), reason=_ABSENT
        ),
    ),
]

POISONS = [None, "junk", [1, 2], {"x": 1}, True, -7, 4.1e18, "", 3.5, [], {}]


def _fleet(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]


def _clocks(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]


def _plant(hass_storage, data: dict, clocks: dict | None = None) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": data,
    }
    if clocks is not None:
        hass_storage[STORAGE_CLOCKS_KEY] = {
            "version": 1, "minor_version": 1,
            "key": STORAGE_CLOCKS_KEY, "data": clocks,
        }


async def _boot(hass, entry) -> object:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data if entry.state is ConfigEntryState.LOADED else None


def _clean(coord) -> tuple[bool, str]:
    """The whole promise, asked of a running coordinator."""
    rows = damaged_rows(coord.data)
    if rows:
        return False, f"damaged rows in the working document: {rows}"
    faults = check_records(coord.data.get(DATA_DEVICES))
    if faults:
        return False, f"damaged records in the working document: {faults[:3]}"
    out = coord._data_to_save()
    rows = damaged_rows(out)
    if rows:
        return False, f"damaged rows in the outgoing document: {rows}"
    return True, ""


# ============================================ the repair's own seams


async def test_two_records_damaged_in_the_same_field_do_not_share_it(
    hass: HomeAssistant, hass_storage
):
    """Would catch: the repair handing every damaged record the same
    default object, so two repaired records share one list and a
    write into one appears in the other.

    Registered devices rather than fleet ids, because a record whose
    device the registry does not carry is pruned at load and the
    assertion would never reach the repair.
    """
    first_device, _ = register_device(hass, "share_one")
    second_device, _ = register_device(hass, "share_two")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    stored = hass_storage.get(STORAGE_KEY)["data"]
    ids = [first_device.id, second_device.id]
    for device_id in ids:
        assert isinstance(stored[DATA_DEVICES].get(device_id), dict)
        stored[DATA_DEVICES][device_id]["daily_max"] = "rotten"

    coord = await _boot(hass, entry)
    assert coord is not None, "setup died"

    first = coord.data[DATA_DEVICES][ids[0]]["daily_max"]
    second = coord.data[DATA_DEVICES][ids[1]]["daily_max"]
    assert first == [] and second == []
    assert first is not second, (
        "two repaired records share one default object: a value "
        "written into one appears in the other"
    )
    first.append(1.0)
    assert coord.data[DATA_DEVICES][ids[1]]["daily_max"] == [], (
        "writing into one repaired record changed another"
    )


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_a_record_damaged_in_many_fields_is_repaired_in_one_pass(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a repair that fixes one fault per record and
    leaves the rest, so the gate never converges."""
    data = copy.deepcopy(_fleet(path))
    device_id = next(
        d for d, r in data[DATA_DEVICES].items() if isinstance(r, dict)
    )
    record = data[DATA_DEVICES][device_id]
    for field in list(record)[:8]:
        record[field] = {"not": "valid"}
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died"
    ok, why = _clean(coord)
    assert ok, why


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_the_devices_map_itself_destroyed(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: the devices key replaced by something that is not
    a map, which every reader walks."""
    for shape in ("garbage", [1, 2, 3], 7, None):
        data = copy.deepcopy(_fleet(path))
        data[DATA_DEVICES] = shape
        _plant(hass_storage, data, _clocks(clocks_path))
        coord = await setup_coordinator(hass)
        entry = coord.entry
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        _plant(hass_storage, data, _clocks(clocks_path))
        coord = await _boot(hass, entry)
        assert coord is not None, f"setup died on devices={shape!r}"
        ok, why = _clean(coord)
        assert ok, f"devices={shape!r}: {why}"
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_every_table_replaced_by_something_that_is_not_a_list(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a table key holding a string or a map, which the
    row walk would iterate as characters or keys."""
    data = copy.deepcopy(_fleet(path))
    for index, table in enumerate(TABLES):
        data[table] = ["junk", {"a": 1}, 7, None][index % 4]
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died"
    ok, why = _clean(coord)
    assert ok, why


# ============================================ the restore's own seams


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_a_damaged_last_good_does_not_loop_or_win(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: restoring from a copy that is itself damaged and
    either looping forever or accepting the damage."""
    data = copy.deepcopy(_fleet(path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)
    live = os.path.join(directory, "device_sentinel.storage")
    copy_path = live + ".last-good"
    broken = copy.deepcopy(data)
    broken.setdefault("incidents", []).insert(0, "not a row")
    broken[DATA_DEVICES] = dict(broken.get(DATA_DEVICES) or {})
    for device_id in list(broken[DATA_DEVICES])[:3]:
        if isinstance(broken[DATA_DEVICES][device_id], dict):
            broken[DATA_DEVICES][device_id]["daily_max"] = "rotten"
    with open(copy_path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "key": STORAGE_KEY, "data": broken}, handle)
    with open(live, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "key": STORAGE_KEY, "data": broken}, handle)

    _plant(hass_storage, broken, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died with a damaged last-good copy"
    ok, why = _clean(coord)
    assert ok, why


@pytest.mark.xfail(
    reason="finding 4, open: the harness holds storage in memory, so "
    "this test never reaches the file it renames. The window is real "
    "and unproven either way; the test has to reach the real disk "
    "before it says anything.",
    strict=True,
)
async def test_a_crash_between_the_rename_and_the_write(
    hass: HomeAssistant, hass_storage
):
    """Would catch: the one window the rotation opens. The live file
    is renamed and the process dies before the new one is written,
    so the next start finds a last-good and no live file."""
    coord = await setup_coordinator(hass)
    entry = coord.entry
    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)
    live = os.path.join(directory, "device_sentinel.storage")
    with open(live, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "key": STORAGE_KEY,
                   "data": {DATA_DEVICES: {"d1": {}}, "setup_count": 5}},
                  handle)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    os.replace(live, live + ".last-good")   # the rename, then the crash
    assert not os.path.exists(live)
    hass_storage.pop(STORAGE_KEY, None)
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died after a crash mid-rotation"
    ok, why = _clean(coord)
    assert ok, why


# ============================================== the save seam's edges


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_repeated_damage_and_repair_converges(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a repair that leaves the document dirtier than it
    found it, or a rotation that eventually copies damage forward."""
    _plant(hass_storage, copy.deepcopy(_fleet(path)), _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    rng = random.Random(4242)
    tables = [t for t in TABLES if isinstance(coord.data.get(t), list)]
    for round_number in range(25):
        table = rng.choice(tables)
        coord.data.setdefault(table, []).insert(
            0, rng.choice(["junk", 7, None, {"bad": 1}, []])
        )
        known = list(coord.data[DATA_DEVICES])
        if not known:
            # The fuzz emptied the fleet, which is a legitimate
            # outcome of a repair rather than a case to skip.
            await coord._save_main()
            ok, why = _clean(coord)
            assert ok, f"round {round_number}: {why}"
            continue
        device_id = rng.choice(known)
        if isinstance(coord.data[DATA_DEVICES][device_id], dict):
            field = rng.choice(list(coord.data[DATA_DEVICES][device_id]))
            coord.data[DATA_DEVICES][device_id][field] = rng.choice(POISONS)
        await coord._save_main()
        ok, why = _clean(coord)
        assert ok, f"round {round_number}: {why}"


@pytest.mark.xfail(
    reason="finding 3, open: the repair records its own system event "
    "into the table it is repairing, so that table's count moves for "
    "a reason the notice does not name. Not damage; scheduled after "
    "ruling #371.",
    strict=True,
)
@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_the_repair_never_empties_a_healthy_table(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a repair that drops good rows alongside the bad,
    which would quietly erase a person's history."""
    data = copy.deepcopy(_fleet(path))
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    before = {
        t: len(coord.data[t])
        for t in TABLES
        if isinstance(coord.data.get(t), list)
    }
    populated = [t for t, n in before.items() if n]
    if not populated:
        pytest.skip("this fleet snapshot has no populated tables")
    for table in populated:
        coord.data[table].insert(0, "junk")
    await coord._save_main()
    for table in populated:
        assert len(coord.data[table]) == before[table], (
            f"{table}: repairing one bad row changed the count of good "
            f"rows from {before[table]} to {len(coord.data[table])}"
        )


async def test_a_repair_at_save_leaves_the_copy_alone(
    hass: HomeAssistant, monkeypatch
):
    """Would catch: the worst outcome the design exists to prevent,
    a repaired or damaged file overwriting the good copy."""
    from custom_components.device_sentinel import store as smod

    rotations: list[int] = []

    async def spy(_hass):
        rotations.append(1)
        return True

    monkeypatch.setattr(smod, "async_rotate_last_good", spy)
    coord = await setup_coordinator(hass)
    for cycle in range(6):
        rotations.clear()
        coord.data.setdefault("incidents", []).insert(0, "junk")
        await coord._save_main()
        assert rotations == [], (
            f"cycle {cycle}: a save that repaired rotated into last-good"
        )
        await coord._save_main()
        assert rotations == [1], (
            f"cycle {cycle}: the clean save after a repair did not rotate"
        )


# ============================================== clocks, the hot file


@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_a_destroyed_clocks_file_never_takes_the_load_down(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: the clocks file discarded badly, or a shape the
    merge walks into."""
    shapes = [
        {"clocks": "garbage"},
        {"clocks": {"a": "garbage"}},
        {"clocks": [1, 2, 3]},
        {"clocks": {"a": {"event_count": "many"}}},
        {},
    ]
    data = _fleet(path)
    for shape in shapes:
        _plant(hass_storage, copy.deepcopy(data), shape)
        coord = await setup_coordinator(hass)
        entry = coord.entry
        assert coord is not None, f"setup died on clocks={shape!r}"
        ok, why = _clean(coord)
        assert ok, f"clocks={shape!r}: {why}"
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


# ==================================================== the wide fuzz


@pytest.mark.parametrize("path,clocks_path", FLEETS)
@pytest.mark.parametrize("seed", range(12))
async def test_wide_fuzz_through_the_real_load(
    hass: HomeAssistant, hass_storage, path, clocks_path, seed
):
    """Damage anywhere in the document, then drive every reader.

    Would catch: any shape the gate misses, any reader that crashes
    on what the gate lets through, any repair that does not hold.
    """
    rng = random.Random(70_000 + seed)
    data = copy.deepcopy(_fleet(path))
    for _ in range(rng.randint(3, 20)):
        target = rng.random()
        if target < 0.4:
            table = rng.choice(list(TABLES))
            rows = data.get(table)
            if isinstance(rows, list) and rows:
                index = rng.randrange(len(rows))
                if rng.random() < 0.4:
                    rows[index] = rng.choice(POISONS)
                elif isinstance(rows[index], dict) and rows[index]:
                    field = rng.choice(list(rows[index]))
                    if rng.random() < 0.5:
                        rows[index][field] = rng.choice(POISONS)
                    else:
                        del rows[index][field]
            else:
                data[table] = rng.choice(["junk", 7, {}, None])
        elif target < 0.9:
            devices = data.get(DATA_DEVICES) or {}
            if devices:
                device_id = rng.choice(list(devices))
                record = devices[device_id]
                if rng.random() < 0.2 or not isinstance(record, dict):
                    devices[device_id] = rng.choice(POISONS)
                elif record:
                    field = rng.choice(list(record))
                    if rng.random() < 0.7:
                        record[field] = rng.choice(POISONS)
                    else:
                        del record[field]
        else:
            key = rng.choice(
                ["setup_count", "first_installed", "stats_epoch", "saved_at"]
            )
            data[key] = rng.choice(POISONS)

    register_device(hass, f"fuzz{seed}")
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, f"seed {seed}: setup died"
    coord._grace_until = 0.0

    ok, why = _clean(coord)
    assert ok, f"seed {seed}: {why}"

    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    for name in (
        "learning_buckets", "recording_depth", "todo_items",
        "frozen_devices_list", "battery_low_list", "signal_problem_list",
        "classification_breakdown", "set_aside_count",
    ):
        getattr(coord, name)
    assert await coord.async_regenerate_reports(), (
        f"seed {seed}: the reports died on a repaired document"
    )
    await coord._save_main()
    ok, why = _clean(coord)
    assert ok, f"seed {seed}, after the save: {why}"


# ================================================ gate 1's own card


async def test_gate_one_raises_its_own_notice(hass: HomeAssistant, hass_storage):
    """Would catch: gate 1 repairing silently, or borrowing gate 2's
    card so a person cannot tell which question was answered."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.device_sentinel.const import (
        DOMAIN,
        REPAIR_CONTAINERS_REPAIRED,
    )

    device, _ = register_device(hass, "notice_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass_storage.get(STORAGE_KEY)["data"][DATA_DEVICES][device.id][
        "daily_max"
    ] = "rotten"
    coord = await _boot(hass, entry)
    assert coord is not None
    assert coord._container_notice, "gate 1 repaired without a notice"
    assert coord._repair_notice is None, (
        "gate 2 also raised, so the two gates are not separable"
    )
    coord._grace_until = 0.0
    coord._evaluate_repairs("grace")
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, REPAIR_CONTAINERS_REPAIRED
    )
    assert issue is not None, "gate 1's card was never raised"
    assert issue.translation_placeholders["what"]
    assert issue.translation_placeholders["where"]


async def test_gate_one_is_silent_on_a_healthy_file(hass: HomeAssistant):
    """Would catch: the one real risk, gate 1 firing on a healthy
    file and repairing data nobody damaged."""
    coord = await setup_coordinator(hass)
    assert coord._container_notice is None
    assert not check_containers(coord.data)


@pytest.mark.parametrize("path,clocks_path", FLEETS)
def test_gate_one_is_silent_on_the_real_fleets(path, clocks_path):
    """The same claim against the files themselves, both fleets."""
    data = _fleet(path)
    before = json.dumps(data, sort_keys=True, default=str)
    assert check_containers(data) == []
    from custom_components.device_sentinel.normalise import repair_containers

    assert repair_containers(data) == {}
    assert json.dumps(data, sort_keys=True, default=str) == before


async def test_control_gate_one_can_fail(hass: HomeAssistant, hass_storage):
    """With gate 1 blinded, the load-time steps crash as they did
    before ruling #371. Proves the gate is what prevents it."""
    from custom_components.device_sentinel import coordinator as cmod

    register_device(hass, "ctl_g1")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass_storage.get(STORAGE_KEY)["data"][DATA_DEVICES] = "garbage"
    original = cmod.check_containers
    cmod.check_containers = lambda _data: []
    try:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is not ConfigEntryState.LOADED, (
            "the control passed with gate 1 off, so the test proves nothing"
        )
    finally:
        cmod.check_containers = original
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
