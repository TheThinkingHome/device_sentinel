# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_daily_dates.py, Version: 0.24.6 (2026-10-05)

"""The dates of a daily history's entries (0.24.4, issue #18)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.device_sentinel.daily_dates import (
    DAILY_DATES,
    FAMILY_GAP,
    dates_for,
    day_appended,
    entry_removed,
    set_dates,
    trimmed_to,
)

D = date(2026, 10, 3)


def _days(*offsets):
    return [D - timedelta(days=o) for o in offsets]


def test_a_block_round_trips_with_its_skipped_days():
    holder = {}
    dates = _days(9, 8, 7, 3, 2, 0)
    set_dates(holder, FAMILY_GAP, dates)
    block = holder[DAILY_DATES][FAMILY_GAP]
    assert block == {"last": "2026-10-03", "count": 6, "skipped": [["2026-09-27", "2026-09-29"], ["2026-10-02", "2026-10-02"]]}
    assert dates_for(holder, FAMILY_GAP, 6, D) == dates


def test_a_history_without_a_block_reads_as_consecutive_days():
    assert dates_for({}, FAMILY_GAP, 3, D) == _days(2, 1, 0)


def test_entries_an_older_release_appended_follow_the_newest_day():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(4, 3, 2))
    assert dates_for(holder, FAMILY_GAP, 5, D) == _days(4, 3, 2, 1, 0)


def test_a_fold_appends_today_and_records_the_skip():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(5, 4))
    day_appended(holder, FAMILY_GAP, 2, 3, D, added=True)
    assert dates_for(holder, FAMILY_GAP, 3, D) == _days(5, 4, 0)
    assert holder[DAILY_DATES][FAMILY_GAP]["skipped"] == [["2026-09-30", "2026-10-02"]]


def test_the_first_dated_fold_dates_the_old_entries_consecutively():
    holder = {}
    day_appended(holder, FAMILY_GAP, 4, 5, D, added=True)
    assert dates_for(holder, FAMILY_GAP, 5, D) == _days(4, 3, 2, 1, 0)


def test_a_trim_drops_the_oldest_dates_and_skips_older_than_the_history():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(20, 19, 10, 2, 1, 0))
    trimmed_to(holder, FAMILY_GAP, 6, 3, D)
    assert dates_for(holder, FAMILY_GAP, 3, D) == _days(2, 1, 0)
    assert holder[DAILY_DATES][FAMILY_GAP]["skipped"] == []


def test_a_removed_entry_leaves_its_day_skipped():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(3, 2, 1, 0))
    entry_removed(holder, FAMILY_GAP, 4, 1, D)
    assert dates_for(holder, FAMILY_GAP, 3, D) == _days(3, 1, 0)


def test_an_emptied_history_drops_its_block():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(1, 0))
    trimmed_to(holder, FAMILY_GAP, 2, 0, D)
    assert holder[DAILY_DATES] is None, "the record's key went missing"


@pytest.mark.parametrize("block", [
    "nonsense", {"last": "not a date", "count": 3}, {"last": "2026-10-03", "count": "3"},
    {"last": "2026-10-03", "count": 3, "skipped": [["x", "y"], [1], None, ["2026-10-02", "2026-09-01"]]},
    {"last": "2026-10-03", "count": True},
])
def test_a_damaged_block_never_raises(block):
    holder = {DAILY_DATES: {FAMILY_GAP: block}}
    dates = dates_for(holder, FAMILY_GAP, 3, D)
    assert len(dates) == 3 and dates[-1] == D


def test_a_fold_at_the_limit_adds_today_and_drops_the_oldest():
    # One added and one trimmed leaves the length where it was (0.24.6).
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(3, 2, 1))
    day_appended(holder, FAMILY_GAP, 3, 3, D, added=True)
    assert dates_for(holder, FAMILY_GAP, 3, D) == _days(2, 1, 0)


def test_a_fold_that_adds_nothing_keeps_the_dates():
    holder = {}
    set_dates(holder, FAMILY_GAP, _days(3, 2, 1))
    day_appended(holder, FAMILY_GAP, 3, 3, D, added=False)
    assert dates_for(holder, FAMILY_GAP, 3, D) == _days(3, 2, 1)
