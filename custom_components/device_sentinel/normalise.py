# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: normalise.py, Version: 0.15.2 (2026-08-17)

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
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_LINE,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
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
)

# The kinds a field may hold. Each is a plain predicate over one value.
NUMBER = "number or None"
INTEGER = "integer"
STRING = "string or None"
BOOLEAN = "boolean"
FLOAT_SERIES = "list of numbers"
INT_SERIES = "list of integers"
STATE = "None or list of numbers"

# Every field a record is expected to hold, and what shape it takes.
# A key absent from this table is reported as unknown; a key in this
# table absent from a record is reported as missing.
EXPECTED: dict[str, str] = {
    DEV_LAST_ACTIVITY: NUMBER,
    DEV_DAILY_MAX: FLOAT_SERIES,
    DEV_TODAY_MAX: NUMBER,
    DEV_FIRST_OBSERVED: STRING,
    DEV_EVENT_COUNT: INTEGER,
    DEV_TAINTED: BOOLEAN,
    DEV_SET_ASIDE_SINCE: NUMBER,
    DEV_SIGNAL_VALUE: NUMBER,
    DEV_SIGNAL_TODAY_MIN: NUMBER,
    DEV_SIGNAL_DAILY_MIN: FLOAT_SERIES,
    DEV_SIGNAL_BELOW_SINCE: NUMBER,
    DEV_SIGNAL_BELOW_TODAY: NUMBER,
    DEV_SIGNAL_DWELL_DAILY: FLOAT_SERIES,
    DEV_SIGNAL_COUNT: INTEGER,
    DEV_SIGNAL_READS: INTEGER,
    DEV_SIGNAL_MEAN_RUN: NUMBER,
    DEV_SIGNAL_M2: NUMBER,
    DEV_SIGNAL_P5_STATE: STATE,
    DEV_SIGNAL_P50_STATE: STATE,
    DEV_SIGNAL_PSQ_VALUE: NUMBER,
    DEV_SIGNAL_PSQ_TS: NUMBER,
    DEV_SIGNAL_DAILY_P5: FLOAT_SERIES,
    DEV_SIGNAL_DAILY_P50: FLOAT_SERIES,
    DEV_SIGNAL_TODAY_MAX: NUMBER,
    DEV_SIGNAL_DAILY_MEAN: FLOAT_SERIES,
    DEV_SIGNAL_DAILY_SD: FLOAT_SERIES,
    DEV_SIGNAL_DAILY_MAX: FLOAT_SERIES,
    DEV_SIGNAL_DAILY_COUNT: INT_SERIES,
    DEV_SIGNAL_DAILY_LINE: FLOAT_SERIES,
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
    if kind == INT_SERIES:
        if not isinstance(value, list):
            return _describe(value)
        bad = [x for x in value if not (isinstance(x, int) and not isinstance(x, bool))]
        return None if not bad else f"{len(bad)} bad element(s), first {_describe(bad[0])}"
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
