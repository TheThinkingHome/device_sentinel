# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_shape.py, Version: 0.15.6 (2026-08-17)

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

import json
import math
import os
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from custom_components.device_sentinel.const import (
    BACKUP_LAST_GOOD_SUFFIX,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_KIND,
    SYS_STORAGE_SHAPE,
    SYS_STORAGE_REPAIR,
    TAINT_REASONS,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_VALUE,
    SIGNAL_SCALE_LQI,
)
from custom_components.device_sentinel.detect_signal import _new_alt_block
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.records import _new_device_record

import pytest

from .helpers import register_device, setup_entry


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
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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
    good = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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


def test_a_missing_and_an_unknown_field_are_both_named():
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    del rec[DEV_TAINTED]
    rec["some_old_field"] = 1
    faults = check_records({"d1": rec})
    named = {(f, w) for _d, f, w in faults}
    assert (DEV_TAINTED, "missing") in named
    assert ("some_old_field", "unknown field") in named


def test_the_check_changes_nothing():
    """The whole point of the first release."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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
    assert check_records(devices) == []


async def test_a_second_scale_block_is_checked_inside():
    """The alternate block is one field, so the record still holds
    exactly the same field count and nothing became optional
    (ruling #286). What is inside it is checked by the same table
    that checks the primary."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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
        rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
        rec[DEV_TAINTED] = reason
        assert check_records({"d1": rec}) == [], f"{reason} reported"


def test_the_exact_record_that_fired_on_17_august():
    """Temperature Outdoors, tainted 'unknown' at 04:22 and still
    tainted when the 08:14 load checked it."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
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
