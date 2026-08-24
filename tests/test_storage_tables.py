# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_tables.py, Version: 0.17.5 (2026-08-24)

"""The half of the file the shape check never read (ruling #332).

The device records are 171 KB of the reference fleet's 355 KB. The
tables beneath them, the incident log, the system events, the to-do
list and its journal, the silence episodes, the storm rows and the
storm tally, are the other 184 KB, and the activity clocks file
beside them was never checked at all.

All three gaps feed one failure. A damaged table passes the check,
the check reports clean, and the last-good copy is refreshed over the
damage, so Heal and Restore read a copy of the fault. The ladder
those two sit on rests entirely on the last-good pair being
trustworthy.

This check reports and touches nothing, exactly as the record check
does (ruling #278).
"""

import pytest

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_STORMS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_JOURNAL,
)
from custom_components.device_sentinel.normalise import (
    TABLE_FAULT_CAP,
    check_clocks,
    check_storage,
)


def _incident(**over):
    row = {
        "device_id": "abc",
        "name": "Door Laundry",
        "kind": "unavailable",
        "event": "opened",
        "when": 1786000000.0,
        "cause": None,
        "duration": None,
    }
    row.update(over)
    return row


def _clock(**over):
    row = {
        "last_activity": 1786000000.0,
        "event_count": 12,
        "tainted": False,
        "today_max": None,
        "signal_value": 148.0,
        "signal_today_min": None,
        "signal_last_change": None,
        "signal_count": 3,
        "signal_mean_run": 0.0,
        "signal_m2": 0.0,
        "signal_p5_state": None,
        "signal_p50_state": None,
        "signal_psq_value": None,
        "signal_psq_ts": None,
        "signal_reads": 0,
        "signal_today_max": None,
        "signal_rail_count": 0,
    }
    row.update(over)
    return row


# ------------------------------------------------- a good file is quiet


def test_a_healthy_file_reports_nothing():
    data = {
        DATA_DEVICES: {},
        DATA_INCIDENTS: [_incident()],
        DATA_SYSTEM_EVENTS: [
            {
                "kind": "restart",
                "when": 1786000000.0,
                "scope": "",
                "detail": None,
                "duration": 29.4,
            }
        ],
        "first_installed": "2026-07-11T00:08:21+00:00",
        "last_version": "0.17.5",
        "stats_epoch": "0.2.3",
        "saved_at": 1786000000.0,
        "setup_count": 318,
        "bridge_seen": {"z2m": {"state": "running"}},
        "broker_seen": {"state": "running"},
    }
    assert check_storage(data) == []


def test_an_empty_table_is_not_a_fault():
    """A fleet with no storms and no episodes is an ordinary fleet,
    and one of the two real ones looks exactly like this."""
    assert check_storage({DATA_STORMS: [], "silence_episodes": []}) == []


def test_a_missing_table_is_not_a_fault():
    """A key the file has not grown yet is absent, not broken. A
    fresh install has none of these."""
    assert check_storage({DATA_DEVICES: {}}) == []


# --------------------------------------------------- what it must catch


def test_a_row_that_is_not_a_row():
    faults = check_storage({DATA_INCIDENTS: ["a string"]})
    assert faults
    scope, field, why = faults[0]
    assert scope == "incidents[0]"
    assert field == "*"
    assert "expected dict" in why


def test_a_table_that_is_not_a_list():
    faults = check_storage({DATA_INCIDENTS: {"nope": 1}})
    assert faults == [
        ("incidents", "incidents", "expected list, found dict")
    ]


def test_a_missing_field_in_a_row():
    row = _incident()
    del row["when"]
    faults = check_storage({DATA_INCIDENTS: [row]})
    assert ("incidents[0]", "when", "missing") in faults


def test_a_field_of_the_wrong_type():
    faults = check_storage({DATA_INCIDENTS: [_incident(when="yesterday")]})
    assert faults
    scope, field, why = faults[0]
    assert (scope, field) == ("incidents[0]", "when")
    assert "str" in why


def test_a_null_where_text_is_required():
    """`ended` and `kind` carry a word or the row means nothing. A
    None there is a fault, unlike `cause`, which is null on 452 of
    the reference fleet's 462 rows."""
    faults = check_storage({DATA_INCIDENTS: [_incident(kind=None)]})
    assert ("incidents[0]", "kind") == faults[0][:2]


def test_a_nullable_field_may_be_null():
    """An open incident has no duration yet, and ten storm rows on
    the reference fleet were open when the file was written."""
    assert check_storage({DATA_INCIDENTS: [_incident(duration=None)]}) == []


def test_a_scalar_of_the_wrong_type():
    faults = check_storage({"setup_count": "many"})
    assert faults == [
        ("setup_count", "setup_count", "expected integer, found str 'many'")
    ]


def test_a_boolean_is_not_an_integer():
    """The bool-as-int trap the record check already guards. True is
    an int in Python and is not a setup count."""
    faults = check_storage({"setup_count": True})
    assert faults and faults[0][1] == "setup_count"


# ------------------------------------------------ the deliberate looseness


def test_an_optional_key_may_be_absent():
    """A system event carries a device count only where it has one,
    which is most rows on both fleets."""
    row = {
        "kind": "restart",
        "when": 1786000000.0,
        "scope": "",
        "detail": None,
        "duration": None,
    }
    assert check_storage({DATA_SYSTEM_EVENTS: [row]}) == []


def test_an_unknown_key_is_not_reported():
    """Deliberately looser than the record check.

    Every reader of these rows reaches for a key by name, so a key
    nobody reads is inert. A fleet upgrading from an older release
    carries retired keys here for exactly one save, and reporting
    them would withhold the backup on the night it is most wanted.
    """
    assert check_storage(
        {DATA_TODO_JOURNAL: [
            {
                "device_id": "a",
                "name": "b",
                "kind": "c",
                "when": "d",
                "retired_thing": 1,
            }
        ]}
    ) == []


def test_one_broken_table_cannot_bury_the_file():
    """A table that has gone wrong has usually gone wrong
    throughout. Reporting every row of a 3,866-row incident log
    would bury every other fault in the file."""
    rows = [_incident(when="bad") for _ in range(50)]
    faults = check_storage({DATA_INCIDENTS: rows})
    assert len(faults) == TABLE_FAULT_CAP + 1
    assert "further row(s) not checked" in faults[-1][2]


def test_a_storage_that_is_not_a_dict():
    assert check_storage(["not", "storage"])[0][1] == "storage"


# ------------------------------------------------------- the clocks file


def test_a_healthy_clocks_file_reports_nothing():
    assert check_clocks({"abc": _clock()}) == []


def test_a_missing_clocks_file_is_not_a_fault():
    """The merge already survives one, and losing it costs an
    interval of live counters rather than the record."""
    assert check_clocks(None) == []


def test_a_broken_clock_field_is_caught():
    faults = check_clocks({"abc": _clock(event_count="lots")})
    assert faults and faults[0][:2] == ("abc", "event_count")


def test_a_missing_clock_field_is_caught():
    row = _clock()
    del row["tainted"]
    assert ("abc", "tainted", "missing") in check_clocks({"abc": row})


def test_a_retired_clock_field_is_tolerated():
    """The case that would have fired 228 times.

    The external fleet's clocks file predates the dwell erasure and
    carries two fields the current schema does not know. They leave
    on the next save; reporting them would mean a fault for every
    device on the one load where a person can do least about it.
    """
    row = _clock()
    row["signal_below_since"] = None
    row["signal_below_today_seconds"] = 0.0
    assert check_clocks({"abc": row}) == []


def test_a_clock_record_that_is_not_a_record():
    faults = check_clocks({"abc": "gone"})
    assert faults[0][:2] == ("abc", "*")


@pytest.mark.parametrize(
    "value", [False, 0, "", [], {}], ids=["false", "zero", "empty", "list", "dict"]
)
def test_a_falsy_clocks_payload_never_raises(value):
    """Called with whatever the file held, including the shapes a
    truthiness test would swallow."""
    check_clocks(value)
