# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_history_file.py, Version: 0.26.2 (2026-10-13)

"""The history file: the older part of the learned history, kept apart.

The main file keeps the newest thirty entries of each daily series and
the rows newer than the line; the history file holds the rest and is
written only when that part changes, in four steps (rulings #633, #655,
#660). These tests run on the harness's in-memory storage; the files on
disk, the stops between steps and the restores are in
test_history_file_disk.py.
"""

from __future__ import annotations

import copy
import json
import os

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import history_file
from custom_components.device_sentinel.const import (
    CONF_RETENTION_DAYS,
    CONF_TRIM_DEVICES,
    DATA_DEVICES,
    DATA_HISTORY_GENERATION,
    DATA_HISTORY_LINE,
    DATA_SIGNAL_STRESS,
    DATA_SYSTEM_EVENTS,
    DEV_SIGNAL_ALT,
    STORAGE_HISTORY_KEY,
    STORAGE_KEY,
    TRIM_BACKUP_DIR,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.device_sentinel.history_file import (
    LAST_GOOD,
    SERIES_FIELDS,
    SIGNAL_SERIES_FIELDS,
)

from .helpers import register_device, setup_entry

# A real moment: the storage check refuses a time before 2020 (#544).
NOW = 1_790_000_000.0
DAY = 86400.0


def series(field: str, n: int, offset: int = 0) -> list:
    """N valid, distinct entries for one daily series, oldest first."""
    if field == "daily_max":
        return [300.0 + i + offset for i in range(n)]
    if field.startswith("battery"):
        return [float(10 + (i + offset) % 80) for i in range(n)]
    if field in ("signal_daily_count", "signal_daily_rail"):
        return [i + offset for i in range(n)]
    if field == "signal_daily_sd":
        return [1.0 + ((i + offset) % 7) / 10 for i in range(n)]
    return [-40.0 - ((i + offset) % 50) for i in range(n)]


def alt_block(n: int) -> dict:
    """A second-scale block, LQI, with n entries in each daily series."""
    block = {
        "signal_scale": "lqi",
        "signal_value": 127.0,
        "signal_today_min": 100.0,
        "signal_today_max": 127.0,
        "signal_count": 10,
        "signal_reads": 20,
        "signal_mean_run": 120.0,
        "signal_m2": 0.0,
        "signal_p5_state": None,
        "signal_p50_state": None,
        "signal_psq_value": None,
        "signal_psq_ts": None,
        "signal_rail_count": 0,
    }
    for field in SIGNAL_SERIES_FIELDS:
        values = series(field, n)
        if field not in ("signal_daily_count", "signal_daily_rail", "signal_daily_sd"):
            values = [100.0 + i % 100 for i in range(n)]
        block[field] = values
    return block


def furnish(record: dict, n: int, alt: bool = False) -> None:
    """Give a record n days of every daily series."""
    for field in SERIES_FIELDS:
        record[field] = series(field, n)
    record["signal_scale"] = "rssi"
    # Watched long enough that no learned gap is longer than the watch
    # (rulings #403, #549).
    record["first_observed"] = "2026-01-01T00:00:00+00:00"
    if alt:
        record[DEV_SIGNAL_ALT] = alt_block(n)


def learned(coord) -> dict:
    """Every daily series and long-kept row in memory, for comparison."""
    out: dict = {"rows": {}}
    for device_id, record in coord.data[DATA_DEVICES].items():
        row = {field: copy.deepcopy(record.get(field)) for field in SERIES_FIELDS}
        alt = record.get(DEV_SIGNAL_ALT)
        if isinstance(alt, dict):
            row["alt"] = {f: copy.deepcopy(alt.get(f)) for f in SIGNAL_SERIES_FIELDS}
        out[device_id] = row
    for table in (DATA_SYSTEM_EVENTS, DATA_SIGNAL_STRESS):
        out["rows"][table] = copy.deepcopy(coord.data.get(table))
    return out


def main_file(hass_storage) -> dict:
    return hass_storage[STORAGE_KEY]["data"]


def history(hass_storage) -> dict | None:
    stored = hass_storage.get(STORAGE_HISTORY_KEY)
    return stored["data"] if stored else None


async def restart_with(hass, entry, edit=None):
    """Stop, change the files as a person or a fault would, start again."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    if edit is not None:
        edit()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def furnished(hass, n=40, alt=False, devices=2):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    ids = []
    for i in range(devices):
        device, _ = register_device(hass, f"hist{i}", f"History Device {i}")
        ids.append(device.id)
    coord._rebuild_registry_view()
    for device_id in ids:
        furnish(coord.data[DATA_DEVICES][device_id], n, alt=alt)
    return entry, coord, ids


async def test_the_main_file_keeps_the_newest_thirty_entries(
    hass: HomeAssistant, hass_storage
):
    """Forty days: thirty in the main file, ten in the history file."""
    _entry, coord, ids = await furnished(hass, n=40, alt=True)
    await coord._save_now()
    main = main_file(hass_storage)
    held = history(hass_storage)
    for device_id in ids:
        record = main[DATA_DEVICES][device_id]
        older = held["devices"][device_id]
        for field in SERIES_FIELDS:
            whole = series(field, 40)
            assert record[field] == whole[-30:]
            assert older[field] == whole[:10]
        whole_alt = alt_block(40)
        for field in SIGNAL_SERIES_FIELDS:
            assert record[DEV_SIGNAL_ALT][field] == whole_alt[field][-30:]
            assert older[DEV_SIGNAL_ALT][field] == whole_alt[field][:10]
    assert main[DATA_HISTORY_GENERATION] == held["generation"] == 1
    # Step 4: last-good holds the same history as the live file.
    assert hass_storage[LAST_GOOD]["data"] == held


async def test_memory_keeps_the_whole_record(hass: HomeAssistant, hass_storage):
    """A save cuts the file, never the record every reader sees."""
    _entry, coord, ids = await furnished(hass, n=40)
    before = learned(coord)
    await coord._save_now()
    assert learned(coord) == before
    assert len(coord.data[DATA_DEVICES][ids[0]]["daily_max"]) == 40


async def test_a_restart_joins_the_whole_history(hass: HomeAssistant, hass_storage):
    """Every series comes back day for day, in order."""
    entry, coord, _ids = await furnished(hass, n=45, alt=True)
    await coord._save_now()
    before = learned(coord)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = learned(entry.runtime_data)
    assert {k: v for k, v in after.items() if k != "rows"} == {
        k: v for k, v in before.items() if k != "rows"
    }
    state = entry.runtime_data._history_state
    assert state["joined"] == "live"
    assert state["counts"]["entries"] > 0


async def test_the_history_file_is_written_only_when_its_part_changes(
    hass: HomeAssistant, hass_storage
):
    """Saves that add nothing older leave the history file alone."""
    _entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    written = coord._history_writes
    for _ in range(5):
        coord._critical = True
        await coord._save_now()
    assert coord._history_writes == written
    # A day appended moves one more entry into the older part.
    coord.data[DATA_DEVICES][ids[0]]["daily_max"].append(999.0)
    await coord._save_now()
    assert coord._history_writes == written + 1
    assert history(hass_storage)["devices"][ids[0]]["daily_max"][-1] == 310.0
    assert main_file(hass_storage)[DATA_HISTORY_GENERATION] == history(hass_storage)["generation"]


async def test_a_short_history_writes_no_history_file(hass: HomeAssistant, hass_storage):
    """Thirty days or fewer: one file, as before, with no generation."""
    _entry, coord, _ids = await furnished(hass, n=30)
    await coord._save_now()
    assert history(hass_storage) is None
    assert DATA_HISTORY_GENERATION not in main_file(hass_storage)


async def test_rows_older_than_the_line_move_and_come_back_in_order(
    hass: HomeAssistant, hass_storage
):
    """Only the leading rows older than the line move; the join puts
    every row back where it was."""
    entry, coord, ids = await furnished(hass, n=5)
    line = NOW
    coord.data[DATA_HISTORY_LINE] = line
    events = [
        {"when": NOW - 50 * DAY, "kind": "restart", "scope": "system", "detail": None, "duration": 10.0},
        {"when": NOW - 40 * DAY, "kind": "restart", "scope": "system", "detail": None, "duration": 11.0},
        {"when": NOW + 10.0, "kind": "restart", "scope": "system", "detail": None, "duration": 12.0},
        # Arrived late and older than the line: it stays in the main
        # file, behind a newer row, so the order is kept.
        {"when": NOW - 45 * DAY, "kind": "restart", "scope": "system", "detail": None, "duration": 13.0},
    ]
    coord.data[DATA_SYSTEM_EVENTS] = copy.deepcopy(events)
    coord.data[DATA_SIGNAL_STRESS] = [
        {"device_id": ids[0], "name": "x", "since": NOW - 60 * DAY, "at": NOW - 59 * DAY, "ended": "resumed", "signal": None},
        {"device_id": ids[0], "name": "x", "since": NOW - 2 * DAY, "at": NOW - DAY + DAY * 2, "ended": "resumed", "signal": None},
    ]
    stress = copy.deepcopy(coord.data[DATA_SIGNAL_STRESS])
    await coord._save_now()
    held = history(hass_storage)
    assert held[DATA_SYSTEM_EVENTS] == events[:2]
    assert main_file(hass_storage)[DATA_SYSTEM_EVENTS] == events[2:]
    assert held[DATA_SIGNAL_STRESS] == stress[:1]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    joined = entry.runtime_data.data
    assert joined[DATA_SYSTEM_EVENTS][: len(events)] == events
    assert joined[DATA_SIGNAL_STRESS][: len(stress)] == stress


async def test_the_line_moves_only_at_the_fold(hass: HomeAssistant, hass_storage):
    """Set at the first start, then at each fold, never between."""
    _entry, coord, _ids = await furnished(hass, n=5)
    first = coord.data[DATA_HISTORY_LINE]
    assert first == history_file.fold_line()
    coord.data[DATA_HISTORY_LINE] = first - DAY
    await coord._save_now()
    assert coord.data[DATA_HISTORY_LINE] == first - DAY
    await coord._on_midnight(None)
    assert coord.data[DATA_HISTORY_LINE] == history_file.fold_line()


async def test_lowering_retention_to_thirty_removes_the_history_file(
    hass: HomeAssistant, hass_storage
):
    """Nothing older is kept, so both history files go."""
    _entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    assert history(hass_storage) is not None
    for device_id in ids:
        for field in SERIES_FIELDS:
            del coord.data[DATA_DEVICES][device_id][field][:-30]
    await coord._save_now()
    assert history(hass_storage) is None
    assert LAST_GOOD not in hass_storage
    assert DATA_HISTORY_GENERATION not in main_file(hass_storage)
    assert coord._history_generation is None


async def test_a_trim_from_advanced_erases_the_older_history_at_once(
    hass: HomeAssistant, hass_storage
):
    """The trimmed device's older part leaves the history file in the
    same save, a restart does not bring it back, and the backup copy
    holds the whole record with no generation (ruling #662)."""
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    target, keeper = ids
    assert target in history(hass_storage)["devices"]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_TRIM_DEVICES: [target]}
    )
    await hass.async_block_till_done()
    held = history(hass_storage)
    assert target not in held["devices"]
    assert keeper in held["devices"]
    assert main_file(hass_storage)[DATA_HISTORY_GENERATION] == held["generation"]
    folder = hass.config.path(TRIM_BACKUP_DIR)
    copies = [n for n in os.listdir(folder) if n.endswith(".storage.json")]
    with open(os.path.join(folder, sorted(copies)[-1]), encoding="utf-8") as handle:
        backup = json.load(handle)
    assert DATA_HISTORY_GENERATION not in backup
    assert backup[DATA_DEVICES][target]["daily_max"] == series("daily_max", 40)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data.data[DATA_DEVICES]
    assert len(again[target]["daily_max"]) == 0
    assert again[keeper]["daily_max"] == series("daily_max", 40)


async def test_a_trim_backup_put_back_loads_whole_and_doubles_nothing(
    hass: HomeAssistant, hass_storage
):
    """The copy has no generation, so it joins nothing, and the first
    save splits it again."""
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    whole = copy.deepcopy(coord._trim_backup_storage())

    def put_back():
        hass_storage[STORAGE_KEY] = {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": whole}

    coord2 = await restart_with(hass, entry, put_back)
    assert coord2.data[DATA_DEVICES][ids[0]]["daily_max"] == series("daily_max", 40)
    assert coord2._history_state["reason"] == "the storage file holds everything"
    assert len(main_file(hass_storage)[DATA_DEVICES][ids[0]]["daily_max"]) == 30


async def test_a_file_from_before_the_split_is_split_at_the_first_save(
    hass: HomeAssistant, hass_storage
):
    """A main file holding everything loads whole, and the first save
    writes the history file before the main file becomes a view."""
    entry, coord, ids = await furnished(hass, n=50)
    whole = copy.deepcopy(coord._data_to_save())
    whole.pop(DATA_HISTORY_GENERATION, None)
    before = learned(coord)

    def older_release():
        hass_storage[STORAGE_KEY] = {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": whole}
        hass_storage.pop(STORAGE_HISTORY_KEY, None)
        hass_storage.pop(LAST_GOOD, None)

    coord2 = await restart_with(hass, entry, older_release)
    assert history(hass_storage)["devices"][ids[0]]["daily_max"] == series("daily_max", 50)[:20]
    assert len(main_file(hass_storage)[DATA_DEVICES][ids[0]]["daily_max"]) == 30
    assert {k: v for k, v in learned(coord2).items() if k != "rows"} == {
        k: v for k, v in before.items() if k != "rows"
    }


async def test_a_history_file_that_does_not_read_back_leaves_the_main_file_whole(
    hass: HomeAssistant, hass_storage
):
    """Nothing is split on a write that cannot be proven."""
    entry, coord, ids = await furnished(hass, n=40)

    async def wrong(hass_, last_good):
        return {"generation": -1}, None

    original = history_file.read_copy
    history_file.read_copy = wrong
    try:
        await coord._save_now()
    finally:
        history_file.read_copy = original
    main = main_file(hass_storage)
    assert len(main[DATA_DEVICES][ids[0]]["daily_max"]) == 40
    assert DATA_HISTORY_GENERATION not in main
    # The next save tries again and splits.
    coord._critical = True
    await coord._save_now()
    assert len(main_file(hass_storage)[DATA_DEVICES][ids[0]]["daily_max"]) == 30
    assert history(hass_storage)["generation"] == main_file(hass_storage)[DATA_HISTORY_GENERATION]


async def test_a_history_copy_of_another_generation_is_never_joined(
    hass: HomeAssistant, hass_storage, caplog
):
    """No match: the main file's thirty days, said in the log, nothing
    doubled (ruling #660)."""
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()

    def other_generation():
        for key in (STORAGE_HISTORY_KEY, LAST_GOOD):
            hass_storage[key]["data"]["generation"] = 99

    await restart_with(hass, entry, other_generation)
    data = entry.runtime_data.data[DATA_DEVICES]
    assert data[ids[0]]["daily_max"] == series("daily_max", 40)[-30:]
    assert "No history file matches the storage file" in caplog.text
    assert entry.runtime_data._history_state["joined"] is None


async def test_a_damaged_live_copy_falls_back_to_last_good(
    hass: HomeAssistant, hass_storage, caplog
):
    """Same generation, damage in the live file: last-good is joined."""
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    before = learned(coord)

    def damage():
        hass_storage[STORAGE_HISTORY_KEY]["data"]["devices"][ids[0]]["daily_max"] = ["nonsense"]

    await restart_with(hass, entry, damage)
    assert entry.runtime_data._history_state["joined"] == "last-good"
    after = learned(entry.runtime_data)
    assert {k: v for k, v in after.items() if k != "rows"} == {
        k: v for k, v in before.items() if k != "rows"
    }


async def test_a_history_entry_for_a_device_no_longer_held_joins_nothing(
    hass: HomeAssistant,
):
    """The join adds to records the main file holds, never creates one."""
    loaded = {DATA_DEVICES: {"kept": {"daily_max": [1.0]}}}
    payload = {"generation": 1, "devices": {"gone": {"daily_max": [5.0]}, "kept": {"daily_max": [0.5]}}}
    counts = history_file.join(loaded, payload)
    assert loaded[DATA_DEVICES] == {"kept": {"daily_max": [0.5, 1.0]}}
    assert counts["dropped"] == 1


async def test_split_then_join_is_the_identity():
    """The pure pair, on a record with every series and rows."""
    data = {
        DATA_DEVICES: {"a": {f: series(f, 70) for f in SERIES_FIELDS}, "b": {f: series(f, 3) for f in SERIES_FIELDS}},
        DATA_HISTORY_LINE: NOW,
        DATA_SYSTEM_EVENTS: [{"when": NOW - 1}, {"when": NOW + 1}],
        DATA_SIGNAL_STRESS: [],
    }
    data[DATA_DEVICES]["a"][DEV_SIGNAL_ALT] = alt_block(70)
    original = copy.deepcopy(data)
    view, part = history_file.split(data)
    assert data == original
    joined = copy.deepcopy(view)
    history_file.join(joined, {"generation": 1, **part})
    assert joined == original
    assert history_file.digest(part) == history_file.digest(copy.deepcopy(part))


async def test_the_diagnostics_say_what_the_history_file_holds(
    hass: HomeAssistant, hass_storage
):
    entry, coord, _ids = await furnished(hass, n=40)
    await coord._save_now()
    await restart_with(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    held = diag["storage"]["history"]
    assert held["joined"] == "live"
    assert held["generation"] == held["pairs_with"]
    assert held["held"]["devices"] == 2
    assert held["held"]["entries"] == 2 * 10 * len(SERIES_FIELDS)


async def test_retention_settings_split_and_join_alike(hass: HomeAssistant, hass_storage):
    """Every retention offered keeps thirty in the main file and joins
    the rest back whole."""
    for retention in (30, 60, 90, 180, 360):
        hass_storage.clear()
        entry = await setup_entry(hass, {CONF_RETENTION_DAYS: retention})
        coord = entry.runtime_data
        device, _ = register_device(hass, f"ret{retention}", f"Retention {retention}")
        coord._rebuild_registry_view()
        furnish(coord.data[DATA_DEVICES][device.id], retention)
        await coord._save_now()
        main = main_file(hass_storage)[DATA_DEVICES][device.id]
        assert len(main["daily_max"]) == min(30, retention)
        before = learned(coord)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert learned(entry.runtime_data)[device.id] == before[device.id]
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
