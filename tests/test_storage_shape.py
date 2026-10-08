# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_shape.py, Version: 0.25.0 (2026-10-08)

"""The shape check reports and touches nothing; last-good follows it.

Ruling #278. An adversarial pass planted a storage file whose devices
key was a string and setup would not start, then one record whose
daily_max was None and the fold raised on it and skipped every device
after. This release watches for both without acting on either: the
check names what does not fit, and the last-good copy is refreshed
only when it names nothing. The release that repairs waits until a
week of loads and folds has shown the checks quiet on good data.

Added at 0.15.3, the taint tests. The 118-record fixture below holds
tainted as False on every record, because nothing was tainted the
minute it was captured, so it recorded a boolean for a field #164 had
already made False or one of four reason strings. A snapshot cannot
show a field whose type depends on what the fleet was doing, so the
reasons are walked from the TAINT_REASONS tuple instead: a fifth
reason added later fails the suite rather than the fleet.

The two tests that matter most are the last two. One proves the check
is silent on a record shaped exactly as the code writes it, which is
the false-positive case that would make the whole thing dangerous.
The other proves it is silent on the reference fleet's real file, 118
records read off disk, which is the same claim on data nobody wrote
for a test.
"""

from __future__ import annotations

import copy
import json
import math
import os
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BACKUP_LAST_GOOD_SUFFIX,
    CLOCK_FIELDS,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    SIGNAL_SCALE_LQI,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_KIND,
    SYS_STORAGE_REPAIR,
    SYS_STORAGE_SHAPE,
    TAINT_REASONS,
)
from custom_components.device_sentinel.detect_signal import _new_alt_block
from custom_components.device_sentinel.normalise import (
    TABLES,
    check_containers,
    check_records,
    check_storage,
    damaged_rows,
)
from custom_components.device_sentinel.records import _new_device_record
from custom_components.device_sentinel.store import StorageMixin
from tests.conftest import FLEET_ABSENT, fleet_param, fleet_path
from tests.helpers import setup_coordinator

from .helpers import register_device, setup_entry

# A real moment for the fixtures' stamps: the storage check refuses
# a time before 2020 as impossible (ruling #544).
TIME_BASE = 1_780_000_000.0



@pytest.fixture(autouse=True)
def _clean_storage_files(hass: HomeAssistant):
    """The harness mocks Store in memory and shares one config
    directory across tests. These tests write real files, so they
    start and end with none of theirs present."""
    def _sweep():
        directory = hass.config.path(STORAGE_DIR)
        if not os.path.isdir(directory):
            return
        for name in os.listdir(directory):
            if name.startswith(STORAGE_KEY) or name.startswith(STORAGE_CLOCKS_KEY):
                os.remove(os.path.join(directory, name))
    _sweep()
    yield
    _sweep()


def _plant(hass: HomeAssistant, key: str, body: str) -> None:
    path = os.path.join(hass.config.path(STORAGE_DIR), key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def _last_good(hass: HomeAssistant, key: str) -> Path:
    return Path(hass.config.path(STORAGE_DIR)) / f"{key}.{BACKUP_LAST_GOOD_SUFFIX}"


def _shape_events(coord) -> list[dict]:
    """Storage events of either kind: a repair (#370) or a writer
    fault named by the seam."""
    return [
        e for e in coord.data.get(DATA_SYSTEM_EVENTS) or []
        if e.get(SYS_KIND) in (SYS_STORAGE_SHAPE, SYS_STORAGE_REPAIR)
    ]


# ---------------------------------------------------------------- unit


def test_a_fresh_record_has_no_faults():
    """The template must pass its own check, or every new device fires."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", None)
    assert check_records({"d1": rec}) == []


def test_a_learned_record_has_no_faults():
    """A record shaped as the estimators actually write it: p5 state as a
    list, count and rail series as ints, everything else float."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    rec[DEV_DAILY_MAX] = [60.0, 61.5, 59.0]
    rec[DEV_TODAY_MAX] = 62.0
    rec[DEV_EVENT_COUNT] = 4321
    rec["signal_p5_state"] = [1.0, 2.0, 3.0, 4.0, 5.0]
    rec["signal_p50_state"] = [1.0, 2.0, 3.0, 4.0, 5.0]
    rec["signal_daily_count"] = [400, 512, 380]
    rec["signal_daily_rail"] = [0, 0, 1]
    rec["battery_since"] = "2026-08-01T00:00:00+00:00"
    rec["frozen_category"] = "frozen"
    assert check_records({"d1": rec}) == []


def test_every_planted_corruption_is_named():
    """The faults the adversarial pass planted, and a few more."""
    good = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    cases = {
        "series_none": (DEV_DAILY_MAX, None),
        "series_string": (DEV_DAILY_MAX, "sixty"),
        "series_with_nan": (DEV_DAILY_MAX, [1.0, math.nan]),
        "series_with_inf": (DEV_DAILY_MAX, [1.0, math.inf]),
        "series_with_string": (DEV_SIGNAL_DAILY_P50, [1.0, "x"]),
        "series_with_bool": (DEV_DAILY_MAX, [1.0, True]),
        "scalar_nan": (DEV_TODAY_MAX, math.nan),
        "scalar_string": (DEV_TODAY_MAX, "5"),
        "int_as_float": (DEV_EVENT_COUNT, 3.0),
        "int_as_bool": (DEV_EVENT_COUNT, True),
        "bool_as_int": (DEV_TAINTED, 1),
    }
    for label, (field, value) in cases.items():
        rec = dict(good)
        rec[field] = value
        faults = check_records({"d1": rec})
        assert faults, f"{label}: no fault reported"
        assert any(f[1] == field for f in faults), f"{label}: wrong field named"

    # a whole record that is not a dict, and a devices map that is not
    assert check_records({"d1": "garbage"})[0][1] == "*"
    assert check_records("garbage")[0][1] == "devices"


def test_a_missing_and_a_retired_field_are_both_named():
    """A retired field is damage; a newer version's field is not (#189,
    amended 28 September 2026): it is kept, unread, so going back a
    release and forward again loses nothing."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    del rec[DEV_TAINTED]
    rec["signal_sum"] = 1
    rec["a_newer_versions_field"] = {"kept": True}
    faults = check_records({"d1": rec})
    named = {(f, w) for _d, f, w in faults}
    assert (DEV_TAINTED, "missing") in named
    assert ("signal_sum", "retired field") in named
    assert not [f for f, _w in named if f == "a_newer_versions_field"]


def test_the_check_changes_nothing():
    """The whole point of the first release."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    rec[DEV_DAILY_MAX] = None
    rec[DEV_TODAY_MAX] = math.nan
    before = json.dumps(rec, sort_keys=True, default=str)
    check_records({"d1": rec})
    assert json.dumps(rec, sort_keys=True, default=str) == before


# ---------------------------------------------------- integration level


async def test_a_clean_save_rotates_live_to_last_good(hass: HomeAssistant):
    """The Store is mocked in memory, so the on-disk file is planted
    by hand; what is under test is the rotation of ruling #370: a
    clean save renames the live main file to last-good, and the
    clocks file gets no copy at all."""
    register_device(hass, "ok1", name="Fine")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    _plant(hass, STORAGE_KEY, "main-v1")
    _plant(hass, STORAGE_CLOCKS_KEY, "clocks-v1")
    coord._rotation_armed = True

    await coord._save_main()

    assert _last_good(hass, STORAGE_KEY).read_text() == "main-v1"
    assert not _last_good(hass, STORAGE_CLOCKS_KEY).exists(), (
        "the retired clocks last-good file was written"
    )
    assert not _shape_events(coord)


async def test_a_faulty_save_repairs_and_leaves_last_good_alone(
    hass: HomeAssistant,
):
    """Ruling #370: a save that found a fault repairs at that moment
    and writes the live file without rotating, so last-good stays
    the last clean file."""
    register_device(hass, "bad1", name="Broken")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    _plant(hass, STORAGE_KEY, "main-v1")
    coord._rotation_armed = True
    await coord._save_main()
    assert _last_good(hass, STORAGE_KEY).read_text() == "main-v1"

    # the file on disk moves on, and one record in memory goes bad
    _plant(hass, STORAGE_KEY, "main-v2-corrupt")
    device_id = next(iter(coord.data[DATA_DEVICES]))
    coord.data[DATA_DEVICES][device_id][DEV_DAILY_MAX] = None
    await coord._save_main()

    events = _shape_events(coord)
    assert events, "the repair wrote no system event"
    assert DEV_DAILY_MAX in str(events[-1]["detail"])
    # last-good still holds the clean copy, not the corrupt file
    assert _last_good(hass, STORAGE_KEY).read_text() == "main-v1"
    # and the record was repaired to its default, not left poisoned
    assert coord.data[DATA_DEVICES][device_id][DEV_DAILY_MAX] == []
    assert coord._repair_notice, "the repair raised no notice"


async def test_the_reference_fleet_is_clean():
    """118 real records off the Panorama's disk. Not a fixture.

    The file is a snapshot from 16 August and the schema has moved
    since, so the reconciler's job is done here first: a record that
    predates a field arrives at the check with the field filled, not
    missing. Filling from the template rather than by name keeps this
    from having to be edited every time the schema gains something.
    """
    here = Path(__file__).parent / "fixtures" / "panorama_records_2026-08-16.json"
    if not here.exists():
        return
    devices = json.loads(here.read_text())
    assert len(devices) >= 100
    template = _new_device_record("2026-08-16T00:00:00+00:00", None)
    for record in devices.values():
        for field in [k for k in record if k not in template]:
            # The reconciler removes schema-dropped keys before the
            # check runs in production (ruling #256); the erased
            # signal fields (ruling #322) are in this snapshot.
            del record[field]
        for field, blank in template.items():
            record.setdefault(field, blank)
    # The load converts a device on Zigbee's raw battery scale before
    # the boundary (ruling #545), and so does this: LUX Outdoors read
    # 200 down to 178 under a "%" unit. It is the one device converted.
    from custom_components.device_sentinel.detect_battery import (
        mark_raw_battery,
        raw_battery_history,
    )

    raw = [did for did, record in devices.items() if raw_battery_history(record)]
    for did in raw:
        mark_raw_battery(devices[did])
    assert len(raw) == 1, raw
    assert check_records(devices) == []


async def test_a_second_scale_block_is_checked_inside():
    """The alternate block is one field, so the record still holds
    exactly the same field count and nothing became optional
    (ruling #286). What is inside it is checked by the same table
    that checks the primary."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    assert rec[DEV_SIGNAL_ALT] is None
    assert check_records({"d1": rec}) == []

    good = _new_alt_block(SIGNAL_SCALE_LQI)
    rec[DEV_SIGNAL_ALT] = good
    assert check_records({"d1": rec}) == [], "a fresh block was reported"

    # A wrong type inside the block is named with its field.
    for field, wrong in (
        (DEV_SIGNAL_VALUE, "loud"),
        (DEV_SIGNAL_DAILY_P50, "not a series"),
        (DEV_SIGNAL_READS, 3.5),
    ):
        bad = dict(good)
        bad[field] = wrong
        rec[DEV_SIGNAL_ALT] = bad
        faults = check_records({"d1": rec})
        assert faults, f"{field} was accepted"
        assert field in faults[0][2], faults

    # Structural damage to the block itself.
    for wrong in ("a string", 7, [], True):
        rec[DEV_SIGNAL_ALT] = wrong
        assert check_records({"d1": rec}), f"{wrong!r} was accepted"

    short = dict(good)
    del short[DEV_SIGNAL_VALUE]
    rec[DEV_SIGNAL_ALT] = short
    assert "missing from the block" in check_records({"d1": rec})[0][2]

    extra = dict(good)
    extra["signal_dwell_daily_pct"] = []
    rec[DEV_SIGNAL_ALT] = extra
    assert "unknown field(s)" in check_records({"d1": rec})[0][2]


def test_every_taint_reason_passes_the_check():
    """The fault of 17 August, asserted so it cannot return.

    The reason field is False or one of the four constants (ruling
    #164), and the check called it a boolean because the file the
    shapes were read from had no live taint in it. Walking the tuple
    rather than naming the four means a fifth reason fails here rather
    than costing a boot its last-good copy.
    """
    for reason in TAINT_REASONS:
        rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
        rec[DEV_TAINTED] = reason
        assert check_records({"d1": rec}) == [], f"{reason} reported"


def test_the_exact_record_that_fired_on_17_august():
    """Temperature Outdoors, tainted 'unknown' at 04:22 and still
    tainted when the 08:14 load checked it."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    rec[DEV_TAINTED] = "unknown"
    assert check_records({"efb080fd7ba6963b0c93eedd78dde4f8": rec}) == []


def test_a_clean_record_is_false_and_not_merely_falsy():
    """False passes; the falsy things that are not it do not.

    The field was a boolean flag before #164 and every read of it is
    a truthiness test, so a 0 or a 1 written by something that still
    thinks it is one would go unnoticed everywhere else. This is the
    one place it should be caught, and the existing bool_as_int case
    above is the same assertion from the other side.
    """
    rec = _new_device_record("2026-08-17T00:00:00+00:00", TIME_BASE)
    assert rec[DEV_TAINTED] is False
    assert check_records({"d1": rec}) == []
    for wrong in (0, 1, True, "", "sometimes", None, ["unknown"]):
        bad = dict(rec)
        bad[DEV_TAINTED] = wrong
        faults = check_records({"d1": bad})
        assert any(
            field == DEV_TAINTED for _d, field, _w in faults
        ), f"{wrong!r} was accepted"


# ------------- an open episode across a fold raises nothing (#364)


async def test_an_open_episode_saves_with_no_fault_and_no_repair(
    hass: HomeAssistant,
):
    """Tim's false card, driven through the live path.

    Four devices silent past their basis at the moment of a save
    produced eight faults and a repair card naming nothing wrong.
    The same four now pass the save seam untouched: no repair, no
    event, every row still in the table.
    """
    register_device(hass, "quiet1", name="Quiet One")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.data["silence_episodes"] = [
        {
            "device_id": f"open{index}",
            "name": f"Quiet {index}",
            "since": 1786000000.0,
            "basis": 600.0,
            "window": 1800.0,
            "ended": None,
            "at": None,
            "lag": None,
            "learned": None,
            "taint_seconds": None,
            "signal": None,
        }
        for index in range(4)
    ]

    await coord._save_main()

    assert coord._repair_notice is None
    assert not _shape_events(coord)
    assert len(coord.data["silence_episodes"]) == 4


async def test_a_save_fault_copies_the_evidence(hass: HomeAssistant):
    """Ruling #340, carried into #370: a repair at save copies the
    evidence before the file is rewritten, so the folder a person is
    pointed at exists and holds the original."""
    register_device(hass, "bad2", name="Broken")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    _plant(hass, STORAGE_KEY, "main-v1")
    device_id = next(iter(coord.data[DATA_DEVICES]))
    coord.data[DATA_DEVICES][device_id][DEV_DAILY_MAX] = None

    await coord._save_main()

    copies = Path(hass.config.path("device_sentinel/trim_backups"))
    assert copies.is_dir(), "the repair took no evidence copy"
    assert list(copies.iterdir()), "the copy folder is empty"


async def test_the_shape_check_runs_after_every_migration_step(
    hass: HomeAssistant,
):
    """A file is judged only once it has been upgraded.

    Nothing enforces the order but the order itself: if the check
    ever moved above the reconciler or the accumulator migration, an
    old file would raise a card for being old rather than for being
    damaged. This pins the order so a future step cannot land below
    it unnoticed.
    """
    import inspect

    from custom_components.device_sentinel import coordinator as cmod

    source = inspect.getsource(cmod.DeviceSentinelCoordinator.async_setup)
    check = source.index("gate_faults = check_records")
    for step in (
        "_migrate_signal_accumulators",
        "_clear_mixed_signal",
        "_reconcile_records",
    ):
        assert source.index(step) < check, (
            f"{step} now runs after the gate, so an unmigrated "
            "file would be judged"
        )


# Damage anywhere in the stored document, the repair gates, and a restore from last-good (0.19.x campaign).


FLEETS = [
    fleet_param(
        "reference", "device_sentinel.storage", id="james",
        clocks=("reference", "device_sentinel.clocks"),
    ),
    fleet_param(
        "second", "device_sentinel_storage.json", id="tim",
        clocks=("second", "device_sentinel_clocks.json"),
    ),
    fleet_param(
        "fourth", "device_sentinel_storage.json", id="fourth",
        clocks=("fourth", "device_sentinel_clocks.json"),
    ),
]

POISONS = [None, "junk", [1, 2], {"x": 1}, True, -7, 4.1e18, "", 3.5, [], {}]

def _fleet(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]

def _clocks(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]

def _plant_hostile(hass_storage, data: dict, clocks: dict | None = None) -> None:
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
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
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
        _plant_hostile(hass_storage, data, _clocks(clocks_path))
        coord = await setup_coordinator(hass)
        entry = coord.entry
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        _plant_hostile(hass_storage, data, _clocks(clocks_path))
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
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died"
    ok, why = _clean(coord)
    assert ok, why

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

    _plant_hostile(hass_storage, broken, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, "setup died with a damaged last-good copy"
    ok, why = _clean(coord)
    assert ok, why

async def test_a_crash_between_the_rename_and_the_write(
    hass: HomeAssistant, real_disk
):
    """The one window the rotation opens, on the real disk.

    The live file is renamed to last-good and the process dies
    before the new one is written, so the next start finds a copy
    and no live file. Measured for finding 4: the missing-file
    restore answers it, no record is lost, and the first save writes
    the live file again.
    """
    device, _ = register_device(hass, "crash_dev")
    coord = await setup_coordinator(hass)
    coord._rotation_armed = True
    await coord._save_main()
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    live = os.path.join(real_disk, "device_sentinel.storage")
    copy_path = live + ".last-good"
    with open(live, encoding="utf-8") as handle:
        devices_before = set(json.load(handle)["data"].get(DATA_DEVICES) or {})
    os.replace(live, copy_path)  # the rename lands, then the crash
    assert not os.path.exists(live)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, (
        "setup died after a crash mid-rotation"
    )
    coord2 = entry.runtime_data
    assert device.id in coord2.data[DATA_DEVICES], "the device record was lost"
    assert devices_before <= set(coord2.data[DATA_DEVICES]), "records were lost"
    assert coord2._restored_from is not None, "the copy was not restored from"
    ok, why = _clean(coord2)
    assert ok, why
    assert os.path.exists(live), "the first save did not re-create the live file"

async def test_a_crash_with_the_copy_damaged(hass: HomeAssistant, real_disk):
    """The worst case of the window: the crash lands and the only file
    left is damaged. Setup must still come up: restore, then gate 1."""
    register_device(hass, "crash_bad")
    coord = await setup_coordinator(hass)
    coord._rotation_armed = True
    await coord._save_main()
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    live = os.path.join(real_disk, "device_sentinel.storage")
    copy_path = live + ".last-good"
    os.replace(live, copy_path)
    with open(copy_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["data"]["incidents"] = "garbage"
    with open(copy_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, (
        "setup died with only a damaged copy on disk"
    )
    coord2 = entry.runtime_data
    assert coord2._container_notice, "gate 1 did not repair the damaged copy"
    ok, why = _clean(coord2)
    assert ok, why

@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_repeated_damage_and_repair_converges(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a repair that leaves the document dirtier than it
    found it, or a rotation that eventually copies damage forward."""
    _plant_hostile(hass_storage, copy.deepcopy(_fleet(path)), _clocks(clocks_path))
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

@pytest.mark.parametrize("path,clocks_path", FLEETS)
async def test_the_repair_keeps_every_good_row(
    hass: HomeAssistant, hass_storage, path, clocks_path
):
    """Would catch: a repair that drops good rows alongside the bad,
    which would quietly erase a person's history.

    The true invariant, measured for finding 3: after a repair a
    table holds every good row it had, plus the one system event
    that records the repair. The first draft of this test required
    the count to be level, which was the test asking the wrong
    question; the extra row is the log doing its job.
    """
    data = copy.deepcopy(_fleet(path))
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    before = {
        t: len(coord.data[t])
        for t in TABLES
        if isinstance(coord.data.get(t), list)
    }
    populated = [t for t, n in before.items() if n]
    if not populated:
        pytest.skip("this fleet snapshot has no populated tables")
    good_rows = {t: list(coord.data[t]) for t in populated}
    for table in populated:
        coord.data[table].insert(0, "junk")
    await coord._save_main()
    for table in populated:
        after = coord.data[table]
        for row in good_rows[table]:
            assert row in after, f"{table}: a good row was dropped by the repair"
        expected = before[table] + (1 if table == "system_events" else 0)
        assert len(after) == expected, (
            f"{table}: {before[table]} good rows became {len(after)}; "
            "only system_events may grow, by the repair's own event"
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
        _plant_hostile(hass_storage, copy.deepcopy(data), shape)
        coord = await setup_coordinator(hass)
        entry = coord.entry
        assert coord is not None, f"setup died on clocks={shape!r}"
        ok, why = _clean(coord)
        assert ok, f"clocks={shape!r}: {why}"
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

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
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant_hostile(hass_storage, data, _clocks(clocks_path))
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

async def test_gate_two_repair_does_not_share_a_template_object(
    hass: HomeAssistant,
):
    """Would catch: gate 2's record repair assigning the template's
    own list to several records, which finding 2 named. Gate 1 owns
    the nine container fields, so this drives gate 2's path directly
    on a field gate 1 does not check, by making the check see it as
    damaged through a type the schema refuses."""
    from custom_components.device_sentinel.normalise import check_records

    first, _ = register_device(hass, "tmpl_one")
    second, _ = register_device(hass, "tmpl_two")
    coord = await setup_coordinator(hass)
    ids = [first.id, second.id]
    # The tainted field takes False or a reason string; an int is a
    # gate 2 fault and not a container fault, so gate 1 leaves it.
    for device_id in ids:
        coord.data[DATA_DEVICES][device_id]["tainted"] = 7
    assert check_records(coord.data[DATA_DEVICES])
    dropped, reset = coord._repair_records()
    assert not dropped
    assert {d for d, _f in reset} == set(ids)
    # For a scalar default the object identity cannot matter; the
    # claim is proven on a list-valued field by driving the same
    # path with the series faulted through a wrong element type.
    for device_id in ids:
        coord.data[DATA_DEVICES][device_id]["daily_max"] = ["x"]
    faults = check_records(coord.data[DATA_DEVICES])
    assert any(f[1] == "daily_max" for f in faults), "the series was not faulted"
    coord._repair_records()
    one = coord.data[DATA_DEVICES][ids[0]]["daily_max"]
    two = coord.data[DATA_DEVICES][ids[1]]["daily_max"]
    assert one == [] and two == []
    assert one is not two, "gate 2 handed two records the same list"
    one.append(1.0)
    assert coord.data[DATA_DEVICES][ids[1]]["daily_max"] == []

async def test_gate_one_restores_from_the_copy_rather_than_emptying(
    hass: HomeAssistant, real_disk
):
    """Ruling #372: a damaged devices map with a usable copy is
    answered by restoring, not by emptying. Would catch the 0.19.10
    behaviour, where every record was lost to a repair while the copy
    one save back held them all."""
    device, _ = register_device(hass, "restore_first")
    coord = await setup_coordinator(hass)
    coord._rotation_armed = True
    await coord._save_main()
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    live = os.path.join(real_disk, "device_sentinel.storage")
    copy_path = live + ".last-good"
    assert os.path.exists(copy_path), "no copy to restore from"
    with open(live, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["data"][DATA_DEVICES] = "garbage"
    with open(live, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2._restored_from is not None, "gate 1 repaired instead"
    assert device.id in coord2.data[DATA_DEVICES], (
        "the record was lost; the copy held it"
    )
    ok, why = _clean(coord2)
    assert ok, why

async def test_gate_one_repairs_when_the_copy_carries_the_same_fault(
    hass: HomeAssistant, real_disk
):
    """The other half of #372: a copy checked and refused. Restoring
    to the same fault would cost a file copy and prove nothing, so
    the repair runs instead."""
    register_device(hass, "same_fault")
    coord = await setup_coordinator(hass)
    coord._rotation_armed = True
    await coord._save_main()
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    live = os.path.join(real_disk, "device_sentinel.storage")
    copy_path = live + ".last-good"
    for path in (live, copy_path):
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["data"]["incidents"] = "garbage"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2._restored_from is None, (
        "gate 1 restored to a copy carrying the same fault"
    )
    assert coord2._container_notice, "gate 1 neither restored nor repaired"
    ok, why = _clean(coord2)
    assert ok, why

async def test_gate_one_repairs_when_there_is_no_copy(
    hass: HomeAssistant, real_disk
):
    """A first install with no copy yet: repair in place, as before."""
    register_device(hass, "no_copy")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    live = os.path.join(real_disk, "device_sentinel.storage")
    copy_path = live + ".last-good"
    if os.path.exists(copy_path):
        os.remove(copy_path)
    with open(live, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["data"]["incidents"] = "garbage"
    with open(live, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2._restored_from is None
    assert coord2._container_notice
    ok, why = _clean(coord2)
    assert ok, why


# The writers and the shape check agree on the real fleets.


JAMES = fleet_path("reference", "device_sentinel.storage")

# The second fleet's committed house. Until 8 October 2026 this read a
# capture of 26 August that was never committed, so its cases skipped
# everywhere and only the reference fleet was checked.
TIM = fleet_path("second", "device_sentinel_storage.json")

OBSERVED = "2026-07-08T00:00:00+00:00"

STEPS = 60

CLOCKS_FOR = {
    "device_sentinel.storage": "device_sentinel.clocks",
    "device_sentinel_storage.json": "device_sentinel_clocks.json",
}

def _fleet_checker(path: Path) -> list[dict]:
    """The fleet's records as the load path presents them: the main
    file with the companion clocks merged in."""
    with open(path, encoding="utf-8") as handle:
        devices = json.load(handle)["data"]["devices"]
    with open(path.parent / CLOCKS_FOR[path.name], encoding="utf-8") as h:
        clocks = json.load(h)["data"].get("clocks") or {}
    merged_all: dict[str, dict] = {}
    for device_id, record in devices.items():
        if not isinstance(record, dict):
            continue
        merged = dict(record)
        fields = clocks.get(device_id) or {}
        for field in CLOCK_FIELDS:
            if field in fields:
                merged[field] = fields[field]
        merged_all[device_id] = merged
    # The load path reconciles every stored record against the
    # current schema before anything reads it, filling fields a
    # newer version added and dropping ones it retired. A fleet file
    # from an earlier release is what the reconciler exists for, and
    # a campaign that skipped it would fail on every field added
    # since the file was written (ruling #397 added two).
    StorageMixin._reconcile_records(merged_all, "")
    return list(merged_all.values())

def _faults(coord) -> list:
    """Every fault the check would raise on the live document."""
    return check_records(coord.data.get(DATA_DEVICES)) + check_storage(
        coord.data
    )

async def _campaign(hass: HomeAssistant, path: Path, seed: int) -> dict:
    rng = random.Random(seed)
    records = _fleet_checker(path)
    owner = MockConfigEntry(domain="campaign_stack", title="Campaign")
    owner.add_to_hass(hass)
    registry = dr.async_get(hass)

    # A dozen watched devices with entities and learned rhythms, two
    # with no entities at all, all carrying real fleet records.
    watched = []
    for index in range(12):
        device, _ = register_device(hass, f"c{seed}_{index}")
        watched.append(device)
    bare = [
        registry.async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={("campaign_stack", f"bare-{seed}-{i}")},
            name=f"Bare {seed} {i}",
        )
        for i in range(2)
    ]
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    for index, device in enumerate(watched):
        base = dict(rng.choice(records))
        base[DEV_DAILY_MAX] = [float(rng.randint(600, 7200))] * 14
        base[DEV_EVENT_COUNT] = rng.randint(1, 500)
        base[DEV_LAST_ACTIVITY] = now - rng.uniform(0, 300)
        base[DEV_FROZEN_CATEGORY] = None
        base[DEV_FROZEN_SINCE] = None
        coord.data[DATA_DEVICES][device.id] = base
    for device in bare:
        rec = coord.data[DATA_DEVICES].setdefault(device.id, {})
        rec[DEV_EVENT_COUNT] = 0
        rec[DEV_LAST_ACTIVITY] = None
        rec[DEV_FIRST_OBSERVED] = OBSERVED
    for index, record in enumerate(records[:80]):
        coord.data[DATA_DEVICES].setdefault(f"bg{seed}_{index}", dict(record))
    coord._rebuild_registry_view()

    operations = 0
    worst = 0
    for step in range(STEPS):
        op = rng.choice(
            [
                "silent", "resume", "restart_open", "restart_close",
                "leave", "rejoin", "ack", "delete", "fold", "judge",
                "battery", "sweep",
            ]
        )
        device = rng.choice(watched)
        rec = coord.data[DATA_DEVICES][device.id]
        if op == "silent":
            rec[DEV_LAST_ACTIVITY] = (
                dt_util.utcnow().timestamp()
                - rng.uniform(1.5, 6.0) * rec[DEV_DAILY_MAX][0]
            )
        elif op == "resume":
            coord._record_activity(device.id, coord.entry.entry_id)
        elif op == "restart_open":
            coord._grace_until = dt_util.utcnow().timestamp() + 300.0
            coord._rebuild_registry_view()
        elif op == "restart_close":
            coord._grace_until = 0.0
            coord._rebuild_registry_view()
        elif op == "leave":
            coord._watched.pop(device.id, None)
            coord._clear_verdicts_for_set_aside(
                {device.id: ("n", "campaign", "x")}
            )
        elif op == "rejoin":
            coord._watched[device.id] = "campaign_stack"
        elif op == "ack":
            for item in coord.data.get("todo_items", []):
                if item["device_id"] == device.id:
                    item["status"] = "completed"
        elif op == "delete":
            coord.data["todo_items"] = [
                i for i in coord.data.get("todo_items", [])
                if i["device_id"] != device.id
            ]
            coord._hand_deleted.add(device.id)
        elif op == "fold":
            coord._note_silences(dt_util.utcnow().timestamp())
            coord._trim_episodes(dt_util.utcnow().timestamp())
        elif op == "battery":
            rec["battery_value"] = rng.choice([100.0, 45.0, 8.0, None])
        elif op == "sweep":
            coord._note_silences(dt_util.utcnow().timestamp())
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
        operations += 1
        faults = _faults(coord)
        worst = max(worst, len(faults))
        assert faults == [], (
            f"seed {seed} step {step} op {op}: the check disagrees with "
            f"the writer: {faults[:3]}"
        )
    return {"seed": seed, "operations": operations, "worst": worst}

@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(25))
async def test_writer_and_checker_agree_james(hass: HomeAssistant, seed):
    await _campaign(hass, JAMES, 30_000 + seed)

@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(25))
async def test_writer_and_checker_agree_tim(hass: HomeAssistant, seed):
    await _campaign(hass, TIM, 40_000 + seed)


# The save seam: every writer goes through it, and a fault is repaired at the moment it is made.


POISONS_boundary = [None, "junk", [1, 2], {"x": 1}, True, -7, 4.1e18, "", 3.5]

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
                    rows[index][field] = rng.choice(POISONS_boundary)
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
         "when": TIME_BASE + 1.0, "cause": None, "duration": None}
    ]}
    assert check_storage(clean) == []
    assert damaged_rows(clean) == {}
    dirty = copy.deepcopy(clean)
    dirty["incidents"][0]["when"] = "x"
    assert check_storage(dirty) != []
    assert damaged_rows(dirty) == {"incidents": [0]}

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
        row = {field: rng.choice(POISONS_boundary) for field in shape}
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


# A damaged record is repaired at load (#370).


SENSOR_PROPERTIES = [
    "awaiting_enable_counts", "battery_falling_count", "battery_falling_list",
    "battery_low_count", "battery_low_list", "bridge_stacks",
    "broker_attributes", "broker_state", "classification_breakdown",
    "deviceless_count", "frozen_devices_count", "frozen_devices_list", "last_good_taken",
    "learning_buckets", "recording_depth", "set_aside_count",
    "signal_problem_count", "signal_problem_list",
    "signal_weak_count",
    "signal_weak_list", "storage_healthy", "storage_load_faulty",
    "todo_items", "watched_count",
]

HELD_POISONS = [
    ("daily_max", None), ("daily_max", "rotten"), ("daily_max", {"x": 1}),
    ("signal_daily_p5", "x"),
    ("battery_daily_value", None), ("signal_daily_count", -1),
    ("first_observed", 7),
]

@pytest.mark.parametrize("field,poison", HELD_POISONS)
async def test_a_damaged_record_is_repaired_at_load(
    hass: HomeAssistant, hass_storage, field, poison
):
    """The #370 rule through the real load path: a damaged record
    field is repaired at the gate, every surface then runs on the
    repaired fleet, and the field itself checks clean afterwards."""
    from custom_components.device_sentinel.const import STORAGE_KEY
    from custom_components.device_sentinel.normalise import check_records

    device, _ = register_device(hass, "held_surface")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    stored["data"][DATA_DEVICES][device.id][field] = poison
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty, f"{field}={poison!r} not repaired"
    assert not check_records(coord2.data[DATA_DEVICES]), (
        f"{field}={poison!r} still faulty after the gate"
    )
    # Either gate may be the one that answers, depending on the
    # field: gate 1 owns the container fields, gate 2 the rest
    # (ruling #371).
    assert coord2._repair_notice or coord2._container_notice, (
        "the repair raised no notice"
    )
    failures = []
    for name in SENSOR_PROPERTIES:
        try:
            value = getattr(coord2, name)
            if callable(value):
                value = value()
        except Exception as err:  # noqa: BLE001 - reporting every failure
            failures.append(f"{name}: {err!r}")
    for stack in coord2.bridge_stacks:
        try:
            coord2.bridge_state(stack)
        except Exception as err:  # noqa: BLE001
            failures.append(f"bridge_state({stack}): {err!r}")
    assert not failures, "\n".join(failures)
    written = await coord2.async_regenerate_reports()
    assert written, "reports did not render with a held record present"


# Every stored value held to what is possible (ruling #544).


@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("last_activity", TIME_BASE, 1.0),
        ("last_activity", TIME_BASE, 9.2e18),
        ("frozen_since", TIME_BASE, 4.2e9),
        ("battery_value", 55.0, 178.0),
        ("battery_value", 0.0, -5.0),
        ("signal_value", -80.0, -1e308),
        ("signal_value", 255.0, 300.0),
        ("today_max", 3600.0, 400 * 86400.0),
        ("event_count", 3_300_000, -1),
        ("event_count", 3_300_000, 10**13),
    ],
)
def test_a_value_outside_its_kind_is_a_fault(field, good, bad):
    """Found on 29 September 2026: a finite value no device and no
    clock can produce passed the type check and failed later, turned
    into a date or raised to a power."""
    record = _new_device_record("2026-09-01T00:00:00+00:00", TIME_BASE)
    record[field] = good
    assert not [f for f in check_records({"d": record}) if f[1] == field]
    record[field] = bad
    faults = [f for f in check_records({"d": record}) if f[1] == field]
    assert faults, f"{field} = {bad!r} passed"


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("daily_max", [3600.0, 400 * 86400.0]),
        ("battery_daily_value", [80.0, 250.0]),
        ("signal_daily_p5", [-70.0, -1e308]),
        ("signal_daily_sd", [3.0, 1e9]),
        ("flap_drops", [TIME_BASE, 1.0]),
        ("signal_daily_count", [10, -3]),
    ],
)
def test_a_series_with_one_impossible_day_is_a_fault(field, bad):
    record = _new_device_record("2026-09-01T00:00:00+00:00", TIME_BASE)
    record[field] = bad
    assert [f for f in check_records({"d": record}) if f[1] == field]


def test_the_edges_of_every_range_pass():
    from custom_components.device_sentinel.normalise import (
        MOMENT_HIGHEST,
        MOMENT_LOWEST,
        SPAN_HIGHEST,
    )

    record = _new_device_record("2026-09-01T00:00:00+00:00", MOMENT_LOWEST)
    record["frozen_since"] = MOMENT_HIGHEST
    record["today_max"] = SPAN_HIGHEST
    record["daily_max"] = [0.0, SPAN_HIGHEST]
    record["battery_value"] = 100.0
    record["battery_daily_value"] = [0.0, 100.0]
    record["signal_value"] = -130.0
    record["signal_daily_p50"] = [-130.0, 255.0, None]
    assert check_records({"d": record}) == []


# The adversarial round's map, 29 September 2026: an impossible value
# in these stored places stopped Device Sentinel starting, or broke the
# brief, the reports or a dashboard page. Each is planted in turn in a
# small house with every table populated, which must start and write
# its reports.
_PLANTED = [
    ("incidents", "when"), ("incidents", "duration"),
    ("silence_episodes", "at"), ("silence_episodes", "since"),
    ("system_events", "when"), ("system_events", "duration"),
    ("todo_items", "kinds"), ("devices", "last_activity"),
    ("devices", "battery_value"), ("devices", "signal_daily_p5"),
    ("devices", "daily_max"), ("devices", "battery_daily_value"),
]


@pytest.mark.parametrize("value", [1e308, 9.2e18, -9.2e18])
@pytest.mark.parametrize(("table", "field"), _PLANTED)
async def test_an_impossible_stored_value_never_stops_a_start(hass, hass_storage, freezer, table, field, value):
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        STORAGE_CLOCKS_KEY,
        STORAGE_KEY,
    )

    device, (entity_id,) = register_device(hass, "fz", name="Fuzz Probe")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    record = coord.data[DATA_DEVICES][device.id]
    record["daily_max"] = [600.0] * 30
    record["battery_value"] = 50.0
    record["battery_daily_value"] = [60.0, 55.0, 50.0]
    record["signal_daily_p5"] = [-80.0, -79.0, -81.0]
    coord.data["incidents"] = [{"device_id": device.id, "name": "Fuzz Probe", "kind": "frozen", "event": "opened", "when": now - 3600, "cause": None, "duration": None, "superseded": None}]
    coord.data["silence_episodes"] = [{"device_id": device.id, "name": "Fuzz Probe", "since": now - 7200, "basis": 600.0, "window": 900.0, "at": now - 3600, "ended": "resumed", "lag": None, "learned": "yes", "taint_seconds": None, "signal": None}]
    coord.data["system_events"] = [{"kind": "restart", "when": now - 600, "scope": "system", "detail": None, "duration": 30.0}]
    coord.data["todo_items"] = [{"uid": "u1", "device_id": device.id, "summary": "Fuzz Probe: frozen", "description": None, "status": "needs_action", "acked_at": None, "sort_name": "Fuzz Probe", "kinds": {"frozen": now - 3600}}]
    await coord._save_now()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    data = hass_storage[STORAGE_KEY]["data"]
    if table == "devices":
        stored = data["devices"][device.id]
        if field == "last_activity":
            hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"][device.id][field] = value
        elif isinstance(stored.get(field), list):
            stored[field] = [*stored[field][:-1], value]
        else:
            stored[field] = value
    else:
        row = data[table][0]
        row[field] = {"frozen": value} if field == "kinds" else value

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state.name == "LOADED", f"{table}.{field} = {value:g} stopped the start"
    coord = entry.runtime_data
    coord._grace_until = 0.0
    freezer.tick(60)
    await coord._on_render_tick(None)
    await coord._on_midnight(None)
    await hass.async_add_executor_job(coord._write_reports)
    await hass.async_block_till_done(wait_background_tasks=True)
    json.dumps(coord.dashboard_device(device.id), default=str)
    json.dumps(coord.dashboard_status(), default=str)
    json.dumps(coord.battery_trends(), default=str)
    json.dumps(coord.dashboard_integrations(), default=str)


async def test_a_retired_signal_clock_leaves_a_stored_record(hass, hass_storage):
    """signal_last_change, the dwell timer's clock, retired in 0.23.19
    as ruling #310 scheduled: a record written before loses it at load,
    in its own fields and in a second scale's block, and a field a newer
    version wrote is still kept (#189, amended)."""
    from custom_components.device_sentinel.const import DATA_DEVICES, STORAGE_KEY

    device, _ = register_device(hass, "old", name="Written By 0.23.18")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    await coord._save_now()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage[STORAGE_KEY]["data"]["devices"][device.id]
    stored["signal_last_change"] = TIME_BASE
    stored["signal_alt"] = {"signal_scale": "rssi", "signal_last_change": TIME_BASE}
    stored["a_field_from_a_newer_version"] = 1
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert "signal_last_change" not in record
    assert "signal_last_change" not in (record.get("signal_alt") or {})
    assert record.get("a_field_from_a_newer_version") == 1
