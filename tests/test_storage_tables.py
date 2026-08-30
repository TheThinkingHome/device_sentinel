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


# ------------------------------------ a stamp is not optional (#333)


def test_a_null_stamp_is_a_fault():
    """A duration may be null while a thing is still happening. The
    stamp that says when it happened may not: a null there sorts
    nowhere, formats as nothing, and reads as a row that never
    occurred. Found by adversarial simulation on 24 August."""
    faults = check_storage({DATA_INCIDENTS: [_incident(when=None)]})
    assert faults and faults[0][:2] == ("incidents[0]", "when")


def test_a_null_duration_is_still_fine():
    """The distinction the last test rests on."""
    assert check_storage({DATA_INCIDENTS: [_incident(duration=None)]}) == []


def test_every_row_defining_stamp_is_required():
    """The same rule across every table that carries one."""
    from custom_components.device_sentinel.normalise import (
        EPISODE_SHAPE,
        REAL_NUMBER,
        STORM_SHAPE,
        STRESS_SHAPE,
        SYSTEM_EVENT_SHAPE,
    )

    assert SYSTEM_EVENT_SHAPE["when"] == REAL_NUMBER
    assert STORM_SHAPE["at"] == REAL_NUMBER
    assert STRESS_SHAPE["at"] == REAL_NUMBER
    for field in ("since", "basis", "window"):
        assert EPISODE_SHAPE[field] == REAL_NUMBER
    # And the ones that legitimately stay nullable. An episode's `at`
    # was in the list above until 0.19.4 and did not belong there:
    # `since` is what defines an episode row, and `at` is when it
    # closed, which is unknown for as long as the silence runs
    # (ruling #364). A stress row's `at` is different and stays
    # required, because a stress row is folded only from an episode
    # that has already closed.
    assert EPISODE_SHAPE["at"] != REAL_NUMBER
    assert EPISODE_SHAPE["ended"] != REAL_NUMBER
    assert EPISODE_SHAPE["lag"] != REAL_NUMBER
    assert STORM_SHAPE["duration"] != REAL_NUMBER


def test_a_not_a_number_stamp_is_a_fault():
    """Infinity and NaN survive a JSON round trip through Python and
    are not moments in time."""
    for value in (float("inf"), float("nan")):
        faults = check_storage({DATA_INCIDENTS: [_incident(when=value)]})
        assert faults, value


# --------------------------- the keys nothing verified (#334)


def test_a_migration_marker_of_the_wrong_type_is_a_fault():
    """The second adversarial pass found these unshaped.

    Both markers hold a version-like string that the load compares
    against an expected mark. A marker that does not match runs a
    one-time conversion over data already converted, so a marker
    corrupted to a number fails the comparison, the conversion
    re-runs, and the check said the file was clean.
    """
    for key in ("signal_day_repair", "signal_weighting"):
        faults = check_storage({key: 12})
        assert faults and faults[0][:2] == (key, key), key
        assert check_storage({key: "0.12.21"}) == []


def test_a_clean_stop_that_is_not_a_boolean_is_a_fault():
    """Read once at the next load to decide whether the restart was
    clean. Anything that is not a boolean reads as false, and every
    device's clock resets."""
    assert check_storage({"clean_stop": True}) == []
    for wrong in (1, 0, "true", None, []):
        assert check_storage({"clean_stop": wrong}), wrong


def test_the_backup_list_must_hold_strings():
    """The suffixes of the one-time backups already taken. A damaged
    list means a backup is taken twice or not at all."""
    assert check_storage({"backup_taken": ["prephase-c", "0.2.3"]}) == []
    assert check_storage({"backup_taken": []}) == []
    for wrong in ("prephase-c", {"a": 1}, [1, 2], [None]):
        assert check_storage({"backup_taken": wrong}), wrong


def test_every_key_both_fleets_hold_has_a_shape():
    """The test that found #334, kept so the next key added to
    storage cannot arrive unverified.

    A key with no shape is skipped in silence, which is right for a
    field inside a row and wrong for a whole key: nothing else looks
    at it.
    """
    from custom_components.device_sentinel.normalise import SCALARS, TABLES

    known = set(TABLES) | set(SCALARS) | {"devices"}
    # Every top-level key both real fleets carried on 24 August 2026.
    seen = {
        "devices", "first_installed", "setup_count", "stats_epoch",
        "saved_at", "last_version", "bridge_seen", "broker_seen",
        "incidents", "silence_episodes", "signal_stress",
        "system_events", "todo_items", "todo_journal", "storms",
        "storm_days", "signal_day_repair", "signal_weighting",
    }
    assert seen <= known, sorted(seen - known)


# ------------------------- an open episode is not damage (#364)


def _open_episode(**over):
    """One silence episode as the journal writes it when it opens."""
    row = {
        "device_id": "abc",
        "name": "Door Laundry",
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
    row.update(over)
    return row


def test_an_open_episode_is_not_a_fault():
    """The false card Tim's fleet raised on 29 August 2026.

    An episode opens the moment a silence passes its basis and stays
    open until the device speaks, so a device silent across a load or
    a fold has a row with None in `at` and `ended`. The table
    required both, so four such devices produced eight faults and a
    repair card that named nothing wrong.
    """
    assert check_storage({"silence_episodes": [_open_episode()]}) == []


def test_four_open_episodes_no_longer_make_eight_faults():
    """His card, reproduced and then silenced."""
    rows = [_open_episode(device_id=f"d{index}") for index in range(4)]
    assert check_storage({"silence_episodes": rows}) == []


def test_a_closed_episode_is_still_fully_checked():
    """Nullable is not unchecked: once a value is there, its type is
    judged exactly as before."""
    faults = check_storage(
        {
            "silence_episodes": [
                _open_episode(at="yesterday", ended=["resumed"])
            ]
        }
    )
    fields = sorted(field for _holder, field, _why in faults)
    assert fields == ["at", "ended"]


def test_a_completed_episode_reports_nothing():
    faults = check_storage(
        {
            "silence_episodes": [
                _open_episode(
                    at=1786003600.0,
                    ended="resumed",
                    lag=None,
                    learned="yes",
                )
            ]
        }
    )
    assert faults == []


def test_a_signal_stress_row_still_requires_both():
    """Stress rows are folded only from closed episodes, so they are
    written with both fields and stay strict."""
    faults = check_storage(
        {
            "signal_stress": [
                {
                    "device_id": "abc",
                    "name": "Door Laundry",
                    "since": 1786000000.0,
                    "at": None,
                    "ended": None,
                    "signal": None,
                }
            ]
        }
    )
    fields = sorted(field for _holder, field, _why in faults)
    assert fields == ["at", "ended"]
