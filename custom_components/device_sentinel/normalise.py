# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: normalise.py, Version: 0.16.2 (2026-08-19)

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
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_INCIDENTS,
    DATA_LAST_VERSION,
    DATA_SAVED_AT,
    DATA_SETUP_COUNT,
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
    "when": NUMBER,
    "cause": STRING,
    "duration": NUMBER,
}

EPISODE_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "since": NUMBER,
    "basis": NUMBER,
    "window": NUMBER,
    "at": NUMBER,
    "ended": TEXT,
    "lag": NUMBER,
    "learned": STRING,
    "taint_seconds": NUMBER,
    "signal": NULLABLE_MAPPING,
}

STRESS_SHAPE: dict[str, str] = {
    "device_id": TEXT,
    "name": TEXT,
    "since": NUMBER,
    "at": NUMBER,
    "ended": TEXT,
    "signal": NULLABLE_MAPPING,
}

SYSTEM_EVENT_SHAPE: dict[str, str] = {
    "kind": TEXT,
    "when": NUMBER,
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
    "at": NUMBER,
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
    "median_devices": NUMBER,
    "median_duration": NUMBER,
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
