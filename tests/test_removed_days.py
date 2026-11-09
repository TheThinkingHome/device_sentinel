# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_removed_days.py, Version: 0.28.6 (2026-11-08)

"""A day removed by hand from a device's learned rhythm (rule FRZ-25).

A person who knows why a day's gap was long, a dead battery, a power cut,
an integration that stopped updating, presses its bar on the device page.
The day keeps its figure and its place and neither rule counts it: the
Trimmed Maximum keeps its 14 days and counts 12 with one removed, the
Log-Normal Percentile leaves it out, the days needed before either is
used are counted days, and the wait changes at once. Pressed again, it
counts again.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_LOGNORMAL_DAYS,
    DEV_REMOVED_DAYS,
    RULE_LOGNORMAL,
    RULE_TRIMMED,
)
from custom_components.device_sentinel.daily_dates import FAMILY_GAP, set_dates
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.records import _new_device_record
from custom_components.device_sentinel.removed_days import (
    REMOVED,
    counted_gaps,
    gap_dates,
    prune_removed,
    set_removed,
)
from tests.helpers import register_device, setup_coordinator

HOUR = 3600.0


def _steady(days: int, hours: float = 1.0) -> list[float]:
    """A steady device: its longest gap wobbles a little around `hours`."""
    return [hours * HOUR * (0.9 + 0.2 * ((i * 7) % 10) / 10) for i in range(days)]


def _record(daily: list[float]) -> dict:
    record = _new_device_record("2026-08-01T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = list(daily)
    record[DEV_LOGNORMAL_DAYS] = None
    return record


def _remove(record: dict, *indices: int) -> None:
    dates = gap_dates(record)
    for index in indices:
        assert set_removed(record, dates[index], True)


# ------------------------------------------------------------- the 14 days


async def test_the_14_days_keep_their_places_and_count_12_with_one_removed(hass: HomeAssistant):
    """The removed day keeps its place, no older day takes
    it, and the longest of the rest is still set aside."""
    coord = await setup_coordinator(hass)
    # Fifteen days: the oldest is long and outside the 14.
    daily = [20 * HOUR] + [1.0 * HOUR] * 10 + [5.9 * HOUR, 1.0 * HOUR, 10.9 * HOUR, 1.0 * HOUR]
    record = _record(daily)
    assert coord._freeze_rhythm(record)["trimmed"] == 5.9 * HOUR
    # Remove the 5.9h day: 10.9h stays the one set aside, the oldest 20h
    # day does not come back in, and the wait drops to an ordinary day.
    _remove(record, 11)
    window = counted_gaps(record)[-14:]
    rhythm, aside = coord._trimmed_maximum(window)
    assert rhythm == 1.0 * HOUR
    assert window[10] is REMOVED and aside == {12}
    counted = [g for g in window if g is not REMOVED]
    assert len(window) == 14 and len(counted) - len(aside) == 12


async def test_removing_the_hatched_day_sets_aside_the_next_longest(hass: HomeAssistant):
    """Two bad days in 14: removing the one set aside lets the trim take the
    other, so a second bad day heals as well."""
    coord = await setup_coordinator(hass)
    record = _record([1.0 * HOUR] * 10 + [5.9 * HOUR, 1.0 * HOUR, 10.9 * HOUR, 1.0 * HOUR])
    assert coord._freeze_rhythm(record)["trimmed"] == 5.9 * HOUR
    _remove(record, 12)
    rhythm, aside = coord._trimmed_maximum(counted_gaps(record)[-14:])
    assert aside == {10} and rhythm == 1.0 * HOUR


# ------------------------------------------------------- the wait, at once


async def test_the_wait_changes_at_once_and_comes_back_when_counted_again(hass: HomeAssistant, caplog):
    device, _entities = register_device(hass, "rd0", "Smoke Detector")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [1.0 * HOUR] * 10 + [5.9 * HOUR, 1.0 * HOUR, 10.9 * HOUR, 1.0 * HOUR]
    record[DEV_LOGNORMAL_DAYS] = None
    before = coord._freeze_rhythm(record)["window"]
    day = gap_dates(record)[10].isoformat()
    with caplog.at_level(logging.INFO, logger="custom_components.device_sentinel"):
        assert coord.set_day_removed(device.id, day, True) == {"removed": True}
    after = coord._freeze_rhythm(record)["window"]
    assert after < before
    assert record[DEV_REMOVED_DAYS] == [day]
    assert any(f"the day {day} removed from its learned rhythm by hand" in m for m in caplog.messages)
    # The figure itself is untouched.
    assert record[DEV_DAILY_MAX][10] == 5.9 * HOUR
    coord.set_day_removed(device.id, day, False)
    assert coord._freeze_rhythm(record)["window"] == before
    assert record[DEV_REMOVED_DAYS] is None


async def test_a_device_listed_frozen_by_the_new_wait(hass: HomeAssistant):
    """Removing a long day shortens the wait, so a device quiet now can be
    listed sooner: the minute check reads the new window at once."""
    device, _entities = register_device(hass, "rd1", "Door Sensor")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [1.0 * HOUR] * 12 + [6.0 * HOUR, 7.0 * HOUR]
    window = coord._freeze_window(record)
    coord.set_day_removed(device.id, gap_dates(record)[12].isoformat(), True)
    assert coord._freeze_window(record) < window


# ------------------------------------------------------- counted days


async def test_the_seven_days_before_judging_are_counted_days(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(_steady(7))
    assert coord._freeze_rhythm(record) is not None
    _remove(record, 3)
    assert coord._freeze_rhythm(record) is None


async def test_the_log_normal_percentile_needs_28_counted_days_and_leaves_removed_ones_out(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(_steady(28))
    assert coord._freeze_rhythm(record)["lognormal"] is not None
    _remove(record, 5)
    assert coord._freeze_rhythm(record)["lognormal"] is None
    # With enough days, a removed day changes the fit as if it were not there.
    long = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    record = _record(long)
    found = coord._freeze_rhythm(record)
    assert found["rule"] == RULE_LOGNORMAL
    _remove(record, 38, 39)
    again = coord._freeze_rhythm(record)
    # Both long days gone: the Trimmed Maximum falls to an ordinary day and
    # takes the wait back.
    assert again["trimmed"] < 2 * HOUR and again["rule"] == RULE_TRIMMED
    assert again["lognormal_days"] == found["lognormal_days"]


async def test_damage_in_a_history_is_still_not_judged(hass: HomeAssistant):
    """A removed day is not a blank: a None stored in the history stays
    damage, and the device waits as a young one does."""
    coord = await setup_coordinator(hass)
    record = _record(_steady(30))
    _remove(record, 4)
    record[DEV_DAILY_MAX][10] = None
    assert coord._freeze_rhythm(record) is None
    assert coord._trimmed_maximum([3600.0, None, 3600.0]) == (None, set())


# ------------------------------------------------------- the dashboard


async def test_the_command_removes_and_counts_again(hass: HomeAssistant, hass_ws_client):
    device, _entities = register_device(hass, "rd2", "Motion Hall")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(14)
    day = gap_dates(record)[6].isoformat()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/device_day", "device_id": device.id, "day": day, "removed": True})
    reply = await client.receive_json()
    assert reply["success"] and reply["result"] == {"removed": True}, reply
    assert record[DEV_REMOVED_DAYS] == [day]
    await client.send_json({"id": 2, "type": "device_sentinel/device_day", "device_id": device.id, "day": day, "removed": False})
    assert (await client.receive_json())["success"]
    assert record[DEV_REMOVED_DAYS] is None
    # Today, a day the history does not hold, and nonsense are refused.
    for message_id, bad in ((3, date.today().isoformat()), (4, "2020-01-01"), (5, "not a day")):
        await client.send_json({"id": message_id, "type": "device_sentinel/device_day", "device_id": device.id, "day": bad, "removed": True})
        reply = await client.receive_json()
        assert reply["error"]["code"] == "refused", reply
    await client.send_json({"id": 6, "type": "device_sentinel/device_day", "device_id": "no-such", "day": day, "removed": True})
    assert (await client.receive_json())["error"]["code"] == "not_found"
    assert record[DEV_REMOVED_DAYS] is None


async def test_a_non_admin_cannot_remove_a_day(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    device, _entities = register_device(hass, "rd3", "Guarded Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(14)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "device_sentinel/device_day", "device_id": device.id,
                            "day": gap_dates(record)[3].isoformat(), "removed": True})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    assert record[DEV_REMOVED_DAYS] is None


async def test_the_page_carries_each_bar_s_day_and_the_removed_ones(hass: HomeAssistant):
    device, _entities = register_device(hass, "rd4", "Up Stairs Smoke Detector")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    record[DEV_LOGNORMAL_DAYS] = None
    dates = gap_dates(record)
    coord.set_day_removed(device.id, dates[-1].isoformat(), True)
    rhythm = coord.dashboard_device(device.id)["rhythm"]
    assert rhythm["gap_days"] == [d.isoformat() for d in dates[-14:]]
    assert rhythm["gaps_removed"] == [13]
    # The figure is still drawn; the hatched day is one still counted.
    assert rhythm["gaps"][13] == 5.5 * HOUR
    assert 13 not in rhythm["set_aside"] and rhythm["set_aside"] == [12]
    rules = rhythm["rules"]
    assert rules["lognormal_dates"][-1] == dates[-1].isoformat()
    assert rules["lognormal_removed"] == [len(rules["lognormal_gaps"]) - 1]
    assert len(rules["lognormal_removed"]) == 1 and (len(rules["lognormal_gaps"]) - 1) not in rules["lognormal_set_aside"]


async def test_the_rhythm_chart_draws_each_day_as_the_rules_read_it_now(hass: HomeAssistant):
    device, _entities = register_device(hass, "rd5", "Charted Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [1.0 * HOUR] * 10 + [6.0 * HOUR, 7.0 * HOUR, 1.0 * HOUR, 1.0 * HOUR]
    before = coord._rhythm_history(record)["trimmed"][-1]
    coord.set_day_removed(device.id, gap_dates(record)[10].isoformat(), True)
    history = coord._rhythm_history(record)
    assert history["trimmed"][-1] < before
    assert all(d is None or d != 10 for d in history["deciding"])


# --------------------------------------------------------- the record


def test_the_record_holds_the_days_and_the_check_reads_them():
    record = _record(_steady(14))
    _remove(record, 2, 5)
    assert check_records({"d": record}) == []
    record[DEV_REMOVED_DAYS] = ["2026-13-40"]
    assert [f[1] for f in check_records({"d": record})] == [DEV_REMOVED_DAYS]
    record[DEV_REMOVED_DAYS] = ["2026-10-01", "2026-10-01"]
    assert [f[1] for f in check_records({"d": record})] == [DEV_REMOVED_DAYS]
    record[DEV_REMOVED_DAYS] = "2026-10-01"
    assert [f[1] for f in check_records({"d": record})] == [DEV_REMOVED_DAYS]


def test_a_removed_day_leaves_the_list_when_its_day_leaves_the_history():
    record = _record(_steady(20))
    end = date(2026, 11, 6)
    set_dates(record, FAMILY_GAP, [end - timedelta(days=19 - i) for i in range(20)])
    first, later = gap_dates(record)[0], gap_dates(record)[10]
    assert set_removed(record, first, True) and set_removed(record, later, True)
    # The fold trims the history and its dates; the oldest day goes.
    del record[DEV_DAILY_MAX][:1]
    set_dates(record, FAMILY_GAP, gap_dates(record, 20)[1:])
    assert prune_removed(record) == 1
    assert record[DEV_REMOVED_DAYS] == [later.isoformat()]


async def test_the_fold_drops_a_removed_day_that_ages_out(hass: HomeAssistant):
    device, _entities = register_device(hass, "rd6", "Old Day Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    keep = coord.retention_days
    record[DEV_DAILY_MAX] = _steady(keep)
    oldest = gap_dates(record)[0]
    coord.set_day_removed(device.id, oldest.isoformat(), True)
    record["today_max"] = 1.0 * HOUR
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == keep
    assert record[DEV_REMOVED_DAYS] is None


async def test_telemetry_marks_a_removed_day(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record([1.0 * HOUR] * 12 + [6.0 * HOUR, 1.0 * HOUR])
    _remove(record, 12)
    cell = coord._format_maxima_cell(counted_gaps(record), record[DEV_DAILY_MAX])
    assert "6.0h (removed by hand)" in cell or "6h (removed by hand)" in cell, cell
    assert "~~" not in cell.split("(removed by hand)")[0][-12:]


@pytest.mark.parametrize("removed", [True, False])
def test_marking_the_same_state_twice_changes_nothing(removed):
    record = _record(_steady(10))
    day = gap_dates(record)[4]
    if not removed:
        set_removed(record, day, True)
    first = set_removed(record, day, removed)
    assert first is True
    assert set_removed(record, day, removed) is False


async def test_a_removed_day_does_not_set_the_rhythm_chart_s_scale(hass: HomeAssistant):
    """A 28-hour power-cut day removed by hand, while the Log-Normal
    Percentile is in use, no longer squashes every bar flat (rule FRZ-25)."""
    coord = await setup_coordinator(hass)
    record = _record(_steady(40))
    record[DEV_DAILY_MAX][-20] = 28 * HOUR
    _remove(record, 20)
    assert coord._both_rules(record)["lognormal_gaps"], "the Log-Normal days are read"
    assert coord._rhythm_scale(record) < 10 * HOUR


async def test_the_countdown_to_the_log_normal_rule_leaves_removed_days_out(hass: HomeAssistant):
    """Three days removed since the count began: six to go, not three, and
    still shown once 28 days have passed with fewer counted (rule FRZ-25)."""
    coord = await setup_coordinator(hass)
    record = _record(_steady(40))
    record[DEV_LOGNORMAL_DAYS] = 25
    _remove(record, 30, 31, 32)
    assert coord._both_rules(record)["counting_again"]["to_go"] == 6
    record[DEV_LOGNORMAL_DAYS] = 29
    assert coord._both_rules(record)["counting_again"]["to_go"] == 2
