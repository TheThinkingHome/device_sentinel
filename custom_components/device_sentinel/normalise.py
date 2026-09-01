# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: normalise.py, Version: 0.19.10 (2026-08-31)

"""Check every stored record against its expected shape. Report, and
touch nothing.

Why this exists (ruling #278). An adversarial pass on 0.15.1 planted a
storage file whose devices key was a string, and setup raised rather
than starting: the whole integration was offline until somebody edited
.storage by hand. It then planted one record whose daily_max was None,
and the midnight fold raised on that record and skipped every device
after it, silently, so one bad field cost the fleet a night of
statistics. Both are the same fault: the code trusts the shape of what
it loads from disk one level deeper than it should.

Why it only reports. The obvious fix is to repair on load, and that
was rejected for the first release. If a check is wrong, a repairing
normaliser silently damages a good record and leaves a warning nobody
reads for days. A reporting one costs nothing when it is wrong: the
worst outcome of a false positive is that the last-good backup is not
written that boot. So this release watches, on the reference fleet and
on a volunteer's, and only when a week of loads and folds has reported
nothing on good data does the next release give the checks the power
to change anything. The order is deliberate: observe first, act on
what was observed.

Why the checks are types and nothing else. Every check here is a type
test or a NaN test, and none depends on what a field means. A record
holding a plausible but wrong number passes, on purpose. The one
thing this must never do is fire on good data, and a value judgment is
the kind of check that does.

Why the shapes come from the file and not only the template. The
template in records.py says signal_p5_state is None, and on every
device that has learned a floor it is a list, because the P-square
estimator stores its markers there. Its daily count and rail series
hold integers where every sibling holds floats. A checker written from
the template alone would have fired on every device on the first boot.
The shapes below were read off a live file of 118 records before a
line was written.

And why a file is not enough either. That file was a snapshot, and a
snapshot cannot show a field whose type depends on what the fleet was
doing at the time. Every one of its 118 records held tainted as False,
because nothing was tainted that minute, so the field was recorded as
a boolean when #164 had already made it False or one of four reason
strings. It fired on the first live taint, on 17 August, and cost that
boot its last-good copy. A field is checked against what the code can
write into it, not against what one file happened to hold; the test
beside this walks the TAINT_REASONS tuple for exactly that reason.
"""

from __future__ import annotations

import math
from typing import Any

from .records import _new_device_record
from .const import (
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    TAINT_REASONS,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_SCALE,
    SIGNAL_ALT_FIELDS,
    CLOCK_FIELDS,
    DATA_BRIDGE_SEEN,
    DATA_BROKER_SEEN,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_INCIDENTS,
    DATA_LAST_VERSION,
    DATA_SAVED_AT,
    DATA_CLEAN_STOP,
    DATA_SETUP_COUNT,
    DATA_SIGNAL_DAY_REPAIR,
    DATA_SIGNAL_WEIGHTING,
    BACKUP_TAKEN_KEY,
    DATA_SIGNAL_STRESS,
    DATA_STATS_EPOCH,
    DATA_STORM_DAYS,
    DATA_STORMS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
)

# The kinds a field may hold. Each is a plain predicate over one value.
NUMBER = "number or None"
INTEGER = "integer"
STRING = "string or None"
BOOLEAN = "boolean"
FLOAT_SERIES = "list of numbers"
# A daily statistic that a rail-only day legitimately cannot supply:
# the row is written to keep the eight series aligned, and the value
# is null because no reading existed to compute one (ruling #305).
# Three of these (P5, P50, line) could already be written null by the
# estimators before rail days existed, so the stricter kind was a
# latent copy of the fold fault, waiting for a fleet whose estimator
# state was empty at a fold (#279: a field is checked against what
# the code can write, not what it usually writes).
NULLABLE_FLOAT_SERIES = "list of numbers or None"
INT_SERIES = "list of integers"
STATE = "None or list of numbers"
TAINT = "False or a taint reason"
ALT = "None or a second-scale block"
# The tables under the device records need three shapes the records
# never use: a string that must be present, a plain mapping whose
# inside is nobody's business here, and a field that may be absent
# altogether rather than present and null (ruling #332).
TEXT = "string"
# A number the row cannot mean anything without. NUMBER admits None,
# which is right for a duration that has not finished and wrong for
# the stamp that says when a row happened: a null there sorts
# nowhere, formats as nothing, and reads as a row that never
# occurred (ruling #333).
REAL_NUMBER = "number, not None"
TEXT_LIST = "list of strings"
MAPPING = "mapping"
NULLABLE_MAPPING = "None or a mapping"

# Every field a record is expected to hold, and what shape it takes.
# A key absent from this table is reported as unknown; a key in this
# table absent from a record is reported as missing.
EXPECTED: dict[str, str] = {
    DEV_LAST_ACTIVITY: NUMBER,
    DEV_DAILY_MAX: FLOAT_SERIES,
    DEV_TODAY_MAX: NUMBER,
    DEV_FIRST_OBSERVED: STRING,
    DEV_EVENT_COUNT: INTEGER,
    DEV_TAINTED: TAINT,
    DEV_SIGNAL_SCALE: STRING,
    DEV_SIGNAL_ALT: ALT,
    DEV_SET_ASIDE_SINCE: NUMBER,
    DEV_SIGNAL_VALUE: NUMBER,
    DEV_SIGNAL_TODAY_MIN: NUMBER,
    DEV_SIGNAL_COUNT: INTEGER,
    DEV_SIGNAL_READS: INTEGER,
    DEV_SIGNAL_MEAN_RUN: NUMBER,
    DEV_SIGNAL_M2: NUMBER,
    DEV_SIGNAL_P5_STATE: STATE,
    DEV_SIGNAL_P50_STATE: STATE,
    DEV_SIGNAL_PSQ_VALUE: NUMBER,
    DEV_SIGNAL_PSQ_TS: NUMBER,
    DEV_SIGNAL_DAILY_P5: NULLABLE_FLOAT_SERIES,
    DEV_SIGNAL_DAILY_P50: NULLABLE_FLOAT_SERIES,
    DEV_SIGNAL_TODAY_MAX: NUMBER,
    DEV_SIGNAL_DAILY_MEAN: NULLABLE_FLOAT_SERIES,
    DEV_SIGNAL_DAILY_SD: NULLABLE_FLOAT_SERIES,
    DEV_SIGNAL_DAILY_MAX: NULLABLE_FLOAT_SERIES,
    DEV_SIGNAL_DAILY_COUNT: INT_SERIES,
    DEV_SIGNAL_DAILY_RAIL: INT_SERIES,
    DEV_SIGNAL_RAIL_COUNT: INTEGER,
    DEV_SIGNAL_LAST_CHANGE: NUMBER,
    DEV_BATTERY_LOW: BOOLEAN,
    DEV_BATTERY_SINCE: STRING,
    DEV_BATTERY_VALUE: NUMBER,
    DEV_BATTERY_DAILY: FLOAT_SERIES,
    DEV_FROZEN_CATEGORY: STRING,
    DEV_FROZEN_SINCE: NUMBER,
}


def _is_number(value: Any) -> bool:
    """A finite int or float. A bool is not a number here: True is an
    int to Python and a mistake to a series."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _describe(value: Any) -> str:
    """Say what a value is, briefly, for a log line."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return f"bool {value}"
    if isinstance(value, float) and not math.isfinite(value):
        return f"float {value}"
    if isinstance(value, (int, float)):
        return f"{type(value).__name__} {value}"
    if isinstance(value, str):
        return f"str {value[:24]!r}"
    if isinstance(value, list):
        kinds = sorted({type(x).__name__ for x in value}) or ["empty"]
        return f"list[{'|'.join(kinds)}] len {len(value)}"
    return type(value).__name__


def _fault(kind: str, value: Any) -> str | None:
    """Return why a value does not fit its kind, or None if it does."""
    if kind == NUMBER:
        return None if value is None or _is_number(value) else _describe(value)
    if kind == INTEGER:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return None if ok else _describe(value)
    if kind == STRING:
        return None if value is None or isinstance(value, str) else _describe(value)
    if kind == BOOLEAN:
        return None if isinstance(value, bool) else _describe(value)
    if kind == FLOAT_SERIES:
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if not _is_number(x)]
        return None if not bad else f"{len(bad)} bad element(s), first {_describe(bad[0])}"
    if kind == NULLABLE_FLOAT_SERIES:
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if x is not None and not _is_number(x)]
        return None if not bad else f"{len(bad)} bad element(s), first {_describe(bad[0])}"
    if kind == INT_SERIES:
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if not (isinstance(x, int) and not isinstance(x, bool))]
        return None if not bad else f"{len(bad)} bad element(s), first {_describe(bad[0])}"
    if kind == ALT:
        # None, or a block holding exactly the recording fields under
        # the record's own names, each checked by the same table that
        # checks the primary (ruling #286). A whole key rather than a
        # scattering of optional fields, so every record still holds
        # the same field count and the check above stays as strict as
        # it was: nothing here is allowed to be absent-or-present.
        if value is None:
            return None
        if not isinstance(value, dict):
            return _describe(value)
        extra = sorted(set(value) - set(SIGNAL_ALT_FIELDS))
        if extra:
            return f"unknown field(s) in the block: {', '.join(extra)}"
        missing = sorted(set(SIGNAL_ALT_FIELDS) - set(value))
        if missing:
            return f"missing from the block: {', '.join(missing)}"
        for field in SIGNAL_ALT_FIELDS:
            inner = EXPECTED.get(field)
            if inner is None or inner == ALT:
                continue
            fault = _fault(inner, value[field])
            if fault is not None:
                return f"{field}: {fault}"
        return None
    if kind == TAINT:
        # False or one of the four reasons, tested by identity for the
        # False so that 0 and 1 are both faults: the field was a flag
        # before #164 and an integer in it is a record written by
        # something that still thinks it is one.
        if value is False or value in TAINT_REASONS:
            return None
        return _describe(value)
    if kind == TEXT:
        return None if isinstance(value, str) else _describe(value)
    if kind == REAL_NUMBER:
        return None if _is_number(value) else _describe(value)
    if kind == TEXT_LIST:
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if not isinstance(x, str)]
        if bad:
            return f"{len(bad)} bad element(s), first {_describe(bad[0])}"
        return None
    if kind == MAPPING:
        return None if isinstance(value, dict) else _describe(value)
    if kind == NULLABLE_MAPPING:
        if value is None or isinstance(value, dict):
            return None
        return _describe(value)
    if kind == STATE:
        if value is None:
            return None
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if not _is_number(x)]
        return None if not bad else f"{len(bad)} bad element(s), first {_describe(bad[0])}"
    return f"unknown kind {kind}"


def check_records(devices: Any) -> list[tuple[str, str, str]]:
    """Return every shape fault as (device_id, field, description).

    An empty list means every record holds every expected field in its
    expected shape and nothing it should not. Nothing is changed. The
    caller decides what a non-empty list means; this release logs it
    and withholds the last-good backup, and nothing more.
    """
    faults: list[tuple[str, str, str]] = []
    if not isinstance(devices, dict):
        return [("*", "devices", f"expected dict, found {_describe(devices)}")]
    for device_id, record in devices.items():
        if not isinstance(record, dict):
            faults.append((device_id, "*", f"expected dict, found {_describe(record)}"))
            continue
        for field, kind in EXPECTED.items():
            if field not in record:
                faults.append((device_id, field, "missing"))
                continue
            why = _fault(kind, record[field])
            if why is not None:
                faults.append((device_id, field, f"expected {kind}, found {why}"))
        for field in record:
            if field not in EXPECTED:
                faults.append((device_id, field, "unknown field"))
    return faults


# ------------------------------------------------- beyond the records

# Everything in the storage file that is not a device record, which is
# half the file by size and was never checked (ruling #332). The
# device records are 171 KB of the reference fleet's 355 KB; the
# tables below are the other 184 KB, and a fault in any of them used
# to pass the check, report clean, and let the last-good copy refresh
# over the damage.
#
# Optional keys are named rather than assumed. A row may omit a key
# only where it appears here, because the record check's strictness
# is what makes it worth running and the tables should not be softer
# than they must be.
#
# Unknown keys are not reported, which is the one place this check is
# deliberately looser than the record check. Every reader of these
# rows reaches for a key by name, so a key nobody reads is inert, and
# a fleet upgrading from an older version carries retired keys here
# for exactly one save. Reporting them would turn the first load
# after an upgrade into hundreds of faults and withhold the backup on
# the night it is most wanted.

INCIDENT_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "kind": TEXT,
    "event": TEXT,
    "when": REAL_NUMBER,
    "cause": STRING,
    "duration": NUMBER,
}

EPISODE_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "since": REAL_NUMBER,
    "basis": REAL_NUMBER,
    "window": REAL_NUMBER,
    # An episode is written the moment a silence passes its basis and
    # stays open until the device speaks or something intervenes, so
    # a row that is still running carries None in both of these by
    # design. Requiring them called healthy in-flight data damage:
    # any device silent across a load or a fold raised two faults and
    # a repair card that named nothing wrong (ruling #364). They are
    # checked as types the moment they hold a value, and a closed row
    # is still fully checked, because the closer writes both.
    "at": NUMBER,
    "ended": STRING,
    "lag": NUMBER,
    "learned": STRING,
    "taint_seconds": NUMBER,
    "signal": NULLABLE_MAPPING,
}

STRESS_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "since": REAL_NUMBER,
    "at": REAL_NUMBER,
    "ended": TEXT,
    "signal": NULLABLE_MAPPING,
}

SYSTEM_EVENT_SHAPE: dict[str, str] = {
    "kind": TEXT,
    "when": REAL_NUMBER,
    "scope": STRING,
    "detail": STRING,
    "duration": NUMBER,
    "devices": INTEGER,
}

TODO_ITEM_SHAPE: dict[str, str] = {
    "uid": TEXT,
    "device_id": TEXT,
    "summary": TEXT,
    "description": STRING,
    "status": TEXT,
    "acked_at": STRING,
    "sort_name": TEXT,
    "kinds": MAPPING,
}

JOURNAL_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "kind": TEXT,
    "when": TEXT,
}

STORM_SHAPE: dict[str, str] = {
    "at": REAL_NUMBER,
    "entry_id": TEXT,
    "domain": TEXT,
    "devices": INTEGER,
    "duration": NUMBER,
}

STORM_DAY_SHAPE: dict[str, str] = {
    "day": TEXT,
    "domain": TEXT,
    "count": INTEGER,
    "median_interval": NUMBER,
    "median_devices": REAL_NUMBER,
    "median_duration": REAL_NUMBER,
}

# table key -> (row shape, keys a row may leave out)
TABLES: dict[str, tuple[dict[str, str], frozenset[str]]] = {
    DATA_INCIDENTS: (INCIDENT_SHAPE, frozenset()),
    DATA_EPISODES: (EPISODE_SHAPE, frozenset()),
    DATA_SIGNAL_STRESS: (STRESS_SHAPE, frozenset()),
    # A row carries a device count only where the event has one to
    # carry, so this key is absent far more often than present.
    DATA_SYSTEM_EVENTS: (SYSTEM_EVENT_SHAPE, frozenset({"devices"})),
    DATA_TODO_ITEMS: (TODO_ITEM_SHAPE, frozenset()),
    DATA_TODO_JOURNAL: (JOURNAL_SHAPE, frozenset()),
    DATA_STORMS: (STORM_SHAPE, frozenset()),
    DATA_STORM_DAYS: (STORM_DAY_SHAPE, frozenset()),
}

# The keys that are one value rather than a table.
SCALARS: dict[str, str] = {
    DATA_FIRST_INSTALLED: TEXT,
    DATA_LAST_VERSION: TEXT,
    DATA_STATS_EPOCH: TEXT,
    DATA_SAVED_AT: NUMBER,
    DATA_SETUP_COUNT: INTEGER,
    DATA_BRIDGE_SEEN: MAPPING,
    DATA_BROKER_SEEN: MAPPING,
    # The migration markers (ruling #334). Both hold a version-like
    # string that the load compares against an expected mark, and a
    # marker that does not match runs a one-time conversion over data
    # that has already been converted. A marker corrupted to a number
    # or a list fails that comparison, so the conversion re-runs and
    # the check that exists to catch this said the file was clean.
    DATA_SIGNAL_DAY_REPAIR: TEXT,
    DATA_SIGNAL_WEIGHTING: TEXT,
    # Written at every clean stop and read once at the next load, and
    # the value decides whether the restart was clean. A non-boolean
    # here reads as false and every device's clock resets.
    DATA_CLEAN_STOP: BOOLEAN,
    # The suffixes of the one-time backups already taken (#204). A
    # damaged list means a backup is taken twice or not at all.
    BACKUP_TAKEN_KEY: TEXT_LIST,
}

# How many rows of one table are reported before the rest are counted.
# A table that has gone wrong has usually gone wrong throughout, and a
# thousand lines about one list buries every other fault in the file.
TABLE_FAULT_CAP = 5


def check_storage(data: Any) -> list[tuple[str, str, str]]:
    """Return every shape fault outside the device records.

    Same three-part tuples as the record check, with the table name
    and row number where a device id would be, because a bad incident
    row has no device to name (ruling #332). Reports and changes
    nothing.

    A key this table does not know is skipped rather than reported.
    The file gains keys between releases, and one that no reader
    knows about is inert; this check exists to protect the readers
    that do exist.
    """
    faults: list[tuple[str, str, str]] = []
    if not isinstance(data, dict):
        return [("*", "storage", f"expected dict, found {_describe(data)}")]

    for key, kind in SCALARS.items():
        if key not in data:
            continue
        why = _fault(kind, data[key])
        if why is not None:
            faults.append((key, key, f"expected {kind}, found {why}"))

    for key, (shape, optional) in TABLES.items():
        rows = data.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list):
            faults.append((key, key, f"expected list, found {_describe(rows)}"))
            continue
        seen = 0
        for index, row in enumerate(rows):
            if seen >= TABLE_FAULT_CAP:
                faults.append(
                    (key, key, f"{len(rows) - index} further row(s) not checked")
                )
                break
            if not isinstance(row, dict):
                faults.append(
                    (f"{key}[{index}]", "*", f"expected dict, found {_describe(row)}")
                )
                seen += 1
                continue
            before = len(faults)
            for field, kind in shape.items():
                if field not in row:
                    if field not in optional:
                        faults.append((f"{key}[{index}]", field, "missing"))
                    continue
                why = _fault(kind, row[field])
                if why is not None:
                    faults.append(
                        (
                            f"{key}[{index}]",
                            field,
                            f"expected {kind}, found {why}",
                        )
                    )
            if len(faults) > before:
                seen += 1
    return faults


def check_clocks(clocks: Any) -> list[tuple[str, str, str]]:
    """Return every shape fault in the activity clocks file.

    The companion file was never checked (ruling #332), and the merge
    takes it whatever its age, so a damaged one reached every record
    on the load path with nothing to stop it.

    A field the current schema does not know is skipped. A fleet
    upgrading across a release that retired a clock field carries it
    here until the next save rewrites the file, and reporting it
    would mean a fault for every device on the one load where the
    person can do least about it.
    """
    faults: list[tuple[str, str, str]] = []
    if clocks is None:
        return faults
    if not isinstance(clocks, dict):
        return [("*", "clocks", f"expected dict, found {_describe(clocks)}")]
    for device_id, record in clocks.items():
        if not isinstance(record, dict):
            faults.append(
                (device_id, "*", f"expected dict, found {_describe(record)}")
            )
            continue
        for field in CLOCK_FIELDS:
            kind = EXPECTED.get(field)
            if kind is None:
                continue
            if field not in record:
                faults.append((device_id, field, "missing"))
                continue
            why = _fault(kind, record[field])
            if why is not None:
                faults.append((device_id, field, f"expected {kind}, found {why}"))
    return faults


def fault_id(fault: tuple[str, str, str]) -> str:
    """Return the stable identity of one fault (ruling #338).

    `file:holder:field`, where the holder is a device id for a record
    fault, a table position like `incidents[3]` for a table fault,
    or the key itself for a scalar. The identity is what lets a later
    release act on one fault rather than on a list, and what lets a
    fix flow check that the fault it was opened for still exists by
    the time a person clicks.

    The file column is derived rather than stored: a clocks-record
    field belongs to the clocks file, everything else to the main
    file. That stays true because the main save strips every clock
    field (#101), so no field name lives in both.
    """
    holder, field, _why = fault
    file = "clocks" if field in CLOCK_FIELDS else "main"
    return f"{file}:{holder}:{field}"


# The kinds whose absence a reader cannot survive: a row without its
# device, its kind, its timestamp, or its text has no place in the
# table at all. A nullable field that is merely absent reads as None,
# which is the shape's own allowed value, and is left to the card
# rather than held (the same boundary #356 drew for clock fields).
_KEY_KINDS = frozenset({TEXT, REAL_NUMBER, INTEGER, MAPPING, FLOAT_SERIES,
                        INT_SERIES, TEXT_LIST})


def damaged_rows(data: Any) -> dict[str, list[int]]:
    """Return, per table, the index of every row a reader cannot use.

    The boundary rule (ruling #370): a row that is not a dict, a row
    with a field of the wrong type, or a row missing a field whose
    kind allows no None, is repaired out of the table at load and at
    save, so no reader ever meets it. Unlike check_storage
    this walks every row, because it decides what is repaired rather
    than what the card prints, and a cap would let the uncounted
    rows through to the readers.
    """
    found: dict[str, list[int]] = {}
    if not isinstance(data, dict):
        return found
    for key, (shape, optional) in TABLES.items():
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        bad: list[int] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                bad.append(index)
                continue
            for field, kind in shape.items():
                if field not in row:
                    if field not in optional and kind in _KEY_KINDS:
                        bad.append(index)
                        break
                    continue
                if _fault(kind, row[field]) is not None:
                    bad.append(index)
                    break
        if bad:
            found[key] = bad
    return found


def fill_missing_row_fields(data: Any) -> int:
    """Give every usable table row the nullable fields it lacks.

    The record reconciler has always filled a missing field on a
    device record so that no reader has to ask whether a key exists.
    Tables never had that, and a row written by an earlier version
    that lacks a field a later version reads by name would raise in
    the reader. A field whose kind allows None is filled with None,
    which is the shape's own allowed value and describes exactly what
    the row said before: nothing. A field whose kind allows no None
    is not filled, because inventing a device or a timestamp would
    be a lie; a row missing one of those is dropped instead
    (ruling #370). Returns how many fields were filled.
    """
    filled = 0
    if not isinstance(data, dict):
        return filled
    for key, (shape, _optional) in TABLES.items():
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field, kind in shape.items():
                if field not in row and kind not in _KEY_KINDS:
                    row[field] = None
                    filled += 1
    return filled


def row_damage(table: str, row: Any) -> str | None:
    """Say what is wrong with one row for one table, or None.

    The same rule damaged_rows applies to a file, applied to a single
    row at the moment a writer makes it (ruling #370), so a writer
    fault is caught when it happens rather than at the next save.
    """
    shape_and_optional = TABLES.get(table)
    if shape_and_optional is None:
        return None
    shape, optional = shape_and_optional
    if not isinstance(row, dict):
        return f"expected dict, found {_describe(row)}"
    for field, kind in shape.items():
        if field not in row:
            if field not in optional and kind in _KEY_KINDS:
                return f"{field} missing"
            continue
        why = _fault(kind, row[field])
        if why is not None:
            return f"{field}: expected {kind}, found {why}"
    return None


def repair_tables(data: Any) -> dict[str, int]:
    """Drop every damaged table row, in place, and say what went.

    The repair half of the boundary (ruling #370): a row a reader
    cannot use is removed from the table at the moment it is found,
    at load or at save, after the evidence copy has preserved the
    original. Nothing is invented: a dropped row is a row the shape
    check named, by the same rules `damaged_rows` applies, and every
    usable row keeps its position relative to its neighbours.

    Returns rows dropped per table, empty when nothing was damaged.
    """
    dropped: dict[str, int] = {}
    damaged = damaged_rows(data)
    for table, indexes in damaged.items():
        rows = data.get(table)
        if not isinstance(rows, list):
            continue
        bad = set(indexes)
        data[table] = [
            row for index, row in enumerate(rows) if index not in bad
        ]
        dropped[table] = len(bad)
    return dropped


# The container fields of a device record: those whose template
# default is a list. Derived from the template rather than listed, so
# a series added later is covered without an edit here (ruling #207's
# principle, applied to the containers).
RECORD_LIST_FIELDS: frozenset[str] = frozenset(
    field
    for field, value in _new_device_record(
        "1970-01-01T00:00:00+00:00", None
    ).items()
    if isinstance(value, list)
)


def check_containers(data: Any) -> list[tuple[str, str, str]]:
    """Name everything gate 1 can check before the clocks merge.

    Gate 1 (ruling #371). The load-time steps run before the full
    check, because one of them fills the seventeen clock fields the
    main file does not carry and a full check ahead of it would fault
    every record on a healthy fleet. Those steps walk the data raw,
    so a value of the wrong container kind stops setup: forty crashes
    were measured across five steps, every one of them an `.items()`
    on something that is not a map, an iteration over something that
    is not a list, or an assignment into something that is not a
    record.

    The seam is the clocks merge, not a list of shapes. Seventeen
    record fields arrive from the hot file, so the record check
    cannot run before the merge without faulting every record on a
    healthy fleet. Everything else can, and does: the containers and
    the top-level scalars.

    Containers alone were the first attempt and were too narrow. A
    scalar of the wrong kind crashes a step too, whenever a step
    compares it: `saved_at` holding a map stops `_merge_clocks` at
    `hot_at < cold_at`, found by the boundary campaign on the second
    reference fleet.

    The main document only. The clocks file is guarded by
    `check_clocks` before the merge reads it, which discards a
    damaged one whole (ruling #356) and was measured to catch all
    eight damage shapes, so nothing here would add. Measured silent
    on both reference fleets, live and last-good, all four files.

    Returns (holder, field, why) triples in the shape the full check
    uses, so one repair path serves both gates.
    """
    faults: list[tuple[str, str, str]] = []

    devices = data.get(DATA_DEVICES) if isinstance(data, dict) else None
    if DATA_DEVICES in (data if isinstance(data, dict) else {}):
        if not isinstance(devices, dict):
            faults.append(
                (DATA_DEVICES, "*", f"expected a map, found {_describe(devices)}")
            )
        else:
            for device_id, record in devices.items():
                if not isinstance(record, dict):
                    faults.append(
                        (device_id, "*", f"expected a record, found {_describe(record)}")
                    )
                    continue
                for field in sorted(RECORD_LIST_FIELDS):
                    if field in record and not isinstance(record[field], list):
                        faults.append(
                            (
                                device_id,
                                field,
                                f"expected a list, found {_describe(record[field])}",
                            )
                        )

    if isinstance(data, dict):
        for table in TABLES:
            if table in data and not isinstance(data[table], list):
                faults.append(
                    (table, "*", f"expected a list, found {_describe(data[table])}")
                )
        for key, kind in SCALARS.items():
            if key not in data:
                continue
            why = _fault(kind, data[key])
            if why is not None:
                faults.append((key, key, f"expected {kind}, found {why}"))

    return faults


def repair_containers(data: Any) -> dict[str, int]:
    """Make every container a container, in place (ruling #371).

    The repair half of gate 1, by the #370 rules: a map that is not a
    map is emptied, a record that is not a record is dropped, a
    series that is not a list is reset to its default, and a table
    that is not a list is emptied. A damaged scalar is dropped rather
    than reset: the load path calls `setdefault` for every one of
    them a few lines later, so dropping restores the real default and
    cannot invent a wrong one. The clocks file is not touched here;
    it has its own guard (ruling #356).

    Returns a count per kind, for the notice.
    """
    counts: dict[str, int] = {}

    def _count(kind: str, by: int = 1) -> None:
        if by:
            counts[kind] = counts.get(kind, 0) + by

    if not isinstance(data, dict):
        return counts

    devices = data.get(DATA_DEVICES)
    if DATA_DEVICES in data and not isinstance(devices, dict):
        data[DATA_DEVICES] = {}
        _count("devices emptied")
        devices = data[DATA_DEVICES]
    if isinstance(devices, dict):
        for device_id in [
            device_id
            for device_id, record in devices.items()
            if not isinstance(record, dict)
        ]:
            del devices[device_id]
            _count("records dropped")
        for record in devices.values():
            for field in RECORD_LIST_FIELDS:
                if field in record and not isinstance(record[field], list):
                    # A fresh list per record, never a shared default.
                    record[field] = []
                    _count("series reset")

    for table in TABLES:
        if table in data and not isinstance(data[table], list):
            data[table] = []
            _count("tables emptied")

    for key, kind in SCALARS.items():
        if key in data and _fault(kind, data[key]) is not None:
            del data[key]
            _count("keys dropped")

    return counts
