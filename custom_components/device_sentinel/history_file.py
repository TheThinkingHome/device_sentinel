# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: history_file.py, Version: 0.26.2 (2026-10-13)

"""The history file: the older part of the learned history, kept apart.

Why (rulings #620, #633, #655, #660). The main file is rewritten about
a hundred times a day, and each write carried every day of history kept
to add one row. The part older than the newest thirty entries of each
daily series, and the long-kept rows older than the line, never change
between folds, so they live in a file of their own and the main file is
written as a view without them. Memory keeps one whole record: every
reader sees the joined record, as before.

The rules this module serves:

- The main file keeps the newest HISTORY_KEEP_ENTRIES entries of each
  daily series. The rest go to the history file, the date blocks stay
  on the record whole.
- System events and signal stress rows are cut at the line, local
  midnight less thirty days, set at each fold. Only the leading rows
  older than the line move, so the join puts them back in their order.
- The history file is written only when its part changes, which a
  digest of that part decides at each save (#655). The write runs four
  steps (#660): rename the history file to last-good, write the new one,
  write the main file, copy the new one over last-good.
- At load, the history copy whose generation matches the main file is
  joined. A copy that does not match, or does not pass the shape check,
  is not joined; with no copy to join, the start uses the main file's
  thirty days and says so.

Nothing here mutates the live data: the split builds a view, and the
join is the one writer, at load, before the first reader.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import orjson

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import STORAGE_DIR, Store
from homeassistant.util import dt as dt_util

from .const import (
    BACKUP_LAST_GOOD_SUFFIX,
    DATA_DEVICES,
    DATA_HISTORY_GENERATION,
    DATA_HISTORY_LINE,
    DATA_SIGNAL_STRESS,
    DATA_SYSTEM_EVENTS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_DAILY_MAX,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    EP_AT,
    HISTORY_KEEP_ENTRIES,
    STORAGE_HISTORY_KEY,
    STORAGE_HISTORY_VERSION,
    SYS_WHEN,
)
from .normalise import damaged_rows, series_fault

# The daily signal series, on the record and in its second scale.
SIGNAL_SERIES_FIELDS = (
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
)
# Every daily series a record carries at its top level.
SERIES_FIELDS = (
    DEV_DAILY_MAX,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    *SIGNAL_SERIES_FIELDS,
)
# The long-kept row lists, each with the field that dates a row.
ROW_TABLES = (
    (DATA_SYSTEM_EVENTS, SYS_WHEN),
    (DATA_SIGNAL_STRESS, EP_AT),
)

# The history file's own keys.
H_GENERATION = "generation"
H_LINE = "line"
H_DEVICES = "devices"

LAST_GOOD = f"{STORAGE_HISTORY_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"


def fold_line(now: Any = None) -> float:
    """Return the line rows cross: local midnight less thirty days."""
    start = dt_util.start_of_local_day(
        dt_util.as_local(now) if now is not None else None
    )
    return (start - timedelta(days=HISTORY_KEEP_ENTRIES)).timestamp()


def _cut_series(values: Any) -> tuple[Any, list[Any] | None]:
    """Split one series into its kept newest part and its older part."""
    if not isinstance(values, list) or len(values) <= HISTORY_KEEP_ENTRIES:
        return values, None
    return values[-HISTORY_KEEP_ENTRIES:], values[:-HISTORY_KEEP_ENTRIES]


def _leading_older(rows: Any, field: str, line: Any) -> int:
    """Count the leading rows dated before the line.

    Only a leading run moves, so the join puts every row back in the
    order it was written. A row with no usable time stops the run.
    """
    if not isinstance(rows, list) or not isinstance(line, (int, float)):
        return 0
    if isinstance(line, bool):
        return 0
    count = 0
    for row in rows:
        when = row.get(field) if isinstance(row, dict) else None
        if (
            not isinstance(when, (int, float))
            or isinstance(when, bool)
            or when >= line
        ):
            break
        count += 1
    return count


def split(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the main file's view and the history file's part.

    Neither the data nor anything in it is changed: records with an
    older part are copied, every other value is shared with the input.
    The history part holds only what is older; an empty part is
    {devices: {}} with no rows.
    """
    view = dict(data)
    older_devices: dict[str, Any] = {}
    devices = data.get(DATA_DEVICES)
    if isinstance(devices, dict):
        view_devices: dict[str, Any] = {}
        for device_id, record in devices.items():
            if not isinstance(record, dict):
                view_devices[device_id] = record
                continue
            kept: dict[str, Any] = {}
            older: dict[str, Any] = {}
            for field in SERIES_FIELDS:
                newest, cut = _cut_series(record.get(field))
                if cut is not None:
                    kept[field] = newest
                    older[field] = cut
            alt = record.get(DEV_SIGNAL_ALT)
            if isinstance(alt, dict):
                alt_kept: dict[str, Any] = {}
                alt_older: dict[str, Any] = {}
                for field in SIGNAL_SERIES_FIELDS:
                    newest, cut = _cut_series(alt.get(field))
                    if cut is not None:
                        alt_kept[field] = newest
                        alt_older[field] = cut
                if alt_older:
                    kept[DEV_SIGNAL_ALT] = {**alt, **alt_kept}
                    older[DEV_SIGNAL_ALT] = alt_older
            if older:
                view_devices[device_id] = {**record, **kept}
                older_devices[device_id] = older
            else:
                view_devices[device_id] = record
        view[DATA_DEVICES] = view_devices
    part: dict[str, Any] = {H_DEVICES: older_devices}
    line = data.get(DATA_HISTORY_LINE)
    for table, field in ROW_TABLES:
        rows = data.get(table)
        count = _leading_older(rows, field, line)
        if count and isinstance(rows, list):
            part[table] = rows[:count]
            view[table] = rows[count:]
    return view, part


def is_empty(part: dict[str, Any]) -> bool:
    """Say whether a history part holds nothing at all."""
    return not part.get(H_DEVICES) and not any(
        part.get(table) for table, _field in ROW_TABLES
    )


def digest(part: dict[str, Any]) -> str:
    """Return a digest of a history part, the same for the same content.

    Home Assistant's own encoder, with sorted keys, so a part that has
    not changed digests the same whatever order its maps were built in.
    """
    encoded = orjson.dumps(
        part, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS
    )
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


def same_content(written: Any, part: dict[str, Any]) -> bool:
    """Say whether what was read back holds exactly the part written."""
    if not isinstance(written, dict):
        return False
    body = {key: value for key, value in written.items() if key not in (H_GENERATION, H_LINE)}
    return body == json.loads(orjson.dumps(part, option=orjson.OPT_NON_STR_KEYS))


def check_payload(payload: Any) -> str | None:
    """Return why a history copy cannot be joined, or None if it can.

    The same kinds the record and row checks use, applied to the older
    entries before they join a record the main file holds clean. One
    bad value refuses the copy whole: a copy with damage in one place
    may have it in others the check cannot see.
    """
    if not isinstance(payload, dict):
        return "not a history file"
    generation = payload.get(H_GENERATION)
    if not isinstance(generation, int) or isinstance(generation, bool):
        return "no generation"
    devices = payload.get(H_DEVICES)
    if not isinstance(devices, dict):
        return "no device map"
    for device_id, older in devices.items():
        if not isinstance(older, dict):
            return f"{device_id}: not a map"
        for field, values in older.items():
            if field == DEV_SIGNAL_ALT:
                if not isinstance(values, dict):
                    return f"{device_id}: {field} is not a map"
                for alt_field, alt_values in values.items():
                    if alt_field not in SIGNAL_SERIES_FIELDS:
                        return f"{device_id}: {field}.{alt_field} is not a daily series"
                    why = series_fault(alt_field, alt_values)
                    if why is not None:
                        return f"{device_id}: {field}.{alt_field} {why}"
                continue
            if field not in SERIES_FIELDS:
                return f"{device_id}: {field} is not a daily series"
            if not isinstance(values, list):
                return f"{device_id}: {field} is not a list"
            why = series_fault(field, values)
            if why is not None:
                return f"{device_id}: {field} {why}"
    for table, _field in ROW_TABLES:
        rows = payload.get(table)
        if rows is None:
            continue
        if not isinstance(rows, list):
            return f"{table} is not a list"
        if damaged_rows({table: rows}).get(table):
            return f"{table} holds a damaged row"
    return None


def join(loaded: dict[str, Any], payload: dict[str, Any]) -> dict[str, int]:
    """Put the older part back in front of the main file's part, in place.

    A device the main file no longer holds joins nothing, and neither
    does a series the main file does not hold as a list: the record
    the history was cut from has gone, and its older part with it.
    Returns counts for the log and the diagnostics.
    """
    counts = {"devices": 0, "entries": 0, "rows": 0, "dropped": 0}
    devices = loaded.get(DATA_DEVICES)
    for device_id, older in (payload.get(H_DEVICES) or {}).items():
        record = devices.get(device_id) if isinstance(devices, dict) else None
        if not isinstance(record, dict):
            counts["dropped"] += 1
            continue
        joined = False
        for field, values in older.items():
            if field == DEV_SIGNAL_ALT:
                alt = record.get(DEV_SIGNAL_ALT)
                if not isinstance(alt, dict):
                    continue
                for alt_field, alt_values in values.items():
                    if isinstance(alt.get(alt_field), list) and alt_values:
                        alt[alt_field] = list(alt_values) + alt[alt_field]
                        counts["entries"] += len(alt_values)
                        joined = True
                continue
            if isinstance(record.get(field), list) and values:
                record[field] = list(values) + record[field]
                counts["entries"] += len(values)
                joined = True
        if joined:
            counts["devices"] += 1
    for table, _field in ROW_TABLES:
        rows = payload.get(table)
        if not rows:
            continue
        current = loaded.get(table)
        loaded[table] = list(rows) + (current if isinstance(current, list) else [])
        counts["rows"] += len(rows)
    return counts


# ------------------------------------------------------------- the files


def _path(hass: HomeAssistant, key: str) -> Path:
    return Path(hass.config.path(STORAGE_DIR)) / key


def _store(hass: HomeAssistant, last_good: bool) -> Store[dict[str, Any]]:
    """A fresh Store for one of the two files, written with an fsync.

    Fresh every time, because a Store keeps its first read and its
    pending data: a read-back through the writing Store would read the
    writer's own memory, not the file.
    """
    return Store(
        hass,
        STORAGE_HISTORY_VERSION,
        LAST_GOOD if last_good else STORAGE_HISTORY_KEY,
        atomic_writes=True,
    )


async def read_copy(hass: HomeAssistant, last_good: bool) -> tuple[Any, str | None]:
    """Read the live history file or its last-good copy.

    Returns (payload, why): the file's data, or None with the reason
    it could not be used. Through Home Assistant's own Store, which
    sets an unreadable file aside under its own repair and reads as
    missing.
    """
    try:
        data = await _store(hass, last_good).async_load()
    except (HomeAssistantError, ValueError, OSError) as err:
        return None, f"unreadable ({err.__class__.__name__})"
    if data is None:
        return None, "missing"
    if not isinstance(data, dict):
        return None, "not a history file"
    return data, None


def rename_to_last_good(hass: HomeAssistant) -> bool:
    """Step 1: the live history file becomes last-good, by a rename."""
    live = _path(hass, STORAGE_HISTORY_KEY)
    if not live.exists():
        return False
    os.replace(live, _path(hass, LAST_GOOD))
    return True


async def write_copy(hass: HomeAssistant, body: dict[str, Any], last_good: bool) -> None:
    """Write the history file (step 2) or its last-good copy (step 4).

    Step 4 writes the same body the live file holds rather than copying
    the file, through the same swap-in write, so a stop part way leaves
    the old last-good or the new one, never half a file.
    """
    await _store(hass, last_good).async_save(body)


async def delete_both(hass: HomeAssistant) -> int:
    """Remove the history file and its copy, when nothing is held there."""
    removed = 0
    for last_good in (False, True):
        key = LAST_GOOD if last_good else STORAGE_HISTORY_KEY
        path = _path(hass, key)
        existed = await hass.async_add_executor_job(path.exists)
        # Through the Store, so Home Assistant's file cache forgets the
        # key, and off the disk directly, whatever the Store did.
        await _store(hass, last_good).async_remove()
        await hass.async_add_executor_job(_unlink, path)
        removed += int(existed)
    return removed


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def history_paths(hass: HomeAssistant) -> list[tuple[Path, str]]:
    """The two history files, with the words an evidence notice uses."""
    return [
        (_path(hass, STORAGE_HISTORY_KEY), "the history file"),
        (_path(hass, LAST_GOOD), "the history backup"),
    ]


def file_size(hass: HomeAssistant) -> int | None:
    """The live history file's size in bytes, or None when absent."""
    path = _path(hass, STORAGE_HISTORY_KEY)
    try:
        return path.stat().st_size
    except OSError:
        return None


def describe(payload: Any) -> dict[str, Any]:
    """What a history copy holds, for the diagnostics."""
    if not isinstance(payload, dict):
        return {}
    devices = payload.get(H_DEVICES) or {}
    entries = 0
    if isinstance(devices, dict):
        for older in devices.values():
            if not isinstance(older, dict):
                continue
            for field, values in older.items():
                if field == DEV_SIGNAL_ALT and isinstance(values, dict):
                    entries += sum(len(v) for v in values.values() if isinstance(v, list))
                elif isinstance(values, list):
                    entries += len(values)
    return {
        "generation": payload.get(H_GENERATION),
        "line": payload.get(H_LINE),
        "devices": len(devices) if isinstance(devices, dict) else 0,
        "entries": entries,
        "rows": {
            table: len(payload.get(table) or [])
            for table, _field in ROW_TABLES
        },
    }


def main_generation(data: Any) -> int | None:
    """The generation a main file pairs with, or None."""
    value = data.get(DATA_HISTORY_GENERATION) if isinstance(data, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
