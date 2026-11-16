# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_day_ranges.py, Version: 0.29.3 (2026-11-15)

"""Each day's battery low and high, level and voltage, kept as history
(rules BAT-06, BAT-16, STOR-15, STOR-19).

At each midnight a battery device heard that day keeps one dated row:
the day's lowest and highest level, as the replacement rule reads them,
and its lowest and highest voltage. The rows are kept for How Much
History to Keep, the older ones in the history file. The day's levels
and voltages live with the clocks, so a power cut does not lose the
morning. The three-day lists an older release kept become dated rows
at load.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DEV_BATTERY_DAY_COUNTS,
    DEV_BATTERY_DAY_LEVELS,
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_RANGE_HIGHS,
    DEV_BATTERY_RANGE_LOWS,
    DEV_BATTERY_VALUE,
    DEV_BATTERY_VOLTS_TODAY_HIGH,
    DEV_BATTERY_VOLTS_TODAY_LOW,
    DEV_LAST_ACTIVITY,
    EPOCH_KEPT,
    RETIRED_DEVICE_FIELDS,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from custom_components.device_sentinel.detect_battery import (
    _ranges,
    close_battery_day,
    mark_raw_battery,
    note_battery_sample,
    note_battery_volts,
    old_cell_high,
    ranges_from_old_lists,
)
from custom_components.device_sentinel.history_file import SERIES_FIELDS
from custom_components.device_sentinel.normalise import check_records, day_range_row_ok
from custom_components.device_sentinel.records import _new_device_record

from tests.helpers import registry_settled, setup_coordinator, setup_entry

DAY = date(2026, 11, 14)


def _record(level: float = 60.0, heard: float | None = None) -> dict:
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_BATTERY_VALUE] = level
    record[DEV_LAST_ACTIVITY] = heard
    return record


def _noon(day: date) -> float:
    return dt_util.start_of_local_day(day).timestamp() + 12 * 3600


async def _battery_device(hass: HomeAssistant, uid: str, millivolts: str | None):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=uid,
    )
    ids = {}
    for key, device_class, value, unit in (
        ("battery", "battery", "60", "%"), ("voltage", "voltage", millivolts, "mV"),
    ):
        if value is None:
            continue
        entry = er.async_get(hass).async_get_or_create(
            "sensor", "test", f"{uid}_{key}", device_id=device.id, config_entry=source,
            original_device_class=device_class, suggested_object_id=f"{uid}_{key}",
        )
        hass.states.async_set(entry.entity_id, value, {"device_class": device_class, "unit_of_measurement": unit})
        ids[key] = entry.entity_id
    return device, ids


# ------------------------------------------------------------- one day


def test_a_heard_day_keeps_its_levels_and_voltages():
    record = _record(heard=_noon(DAY))
    for level in (60.0, 60.0, 59.0, 59.0, 58.0):
        note_battery_sample(record, level)
    for volts in (2.95, 2.91, 2.93):
        note_battery_volts(record, volts)
    record[DEV_BATTERY_VALUE] = 58.0
    close_battery_day(record, DAY, 90)
    # 58 was heard at one moment only, so the day's low is 59 (rule BAT-06).
    assert record[DEV_BATTERY_DAY_RANGES] == [["2026-11-14", 59.0, 60.0, 2.91, 2.95]]
    # A new day starts with the level held, and no voltage yet.
    assert record[DEV_BATTERY_DAY_LEVELS] == [58.0]
    assert record[DEV_BATTERY_DAY_COUNTS] == [1]
    assert record[DEV_BATTERY_VOLTS_TODAY_LOW] is None
    assert record[DEV_BATTERY_VOLTS_TODAY_HIGH] is None
    assert check_records({"d": record}) == []


def test_a_day_not_heard_writes_no_row():
    """It holds only the level carried in at midnight, so it measured
    nothing, as it writes no daily level (rule BAT-05)."""
    record = _record(heard=_noon(DAY) - 3 * 86400)
    note_battery_sample(record, 60.0)
    close_battery_day(record, DAY, 90)
    assert record[DEV_BATTERY_DAY_RANGES] == []


def test_a_device_with_a_voltage_and_no_level_keeps_the_voltage():
    record = _record(heard=_noon(DAY))
    record[DEV_BATTERY_VALUE] = None
    note_battery_volts(record, 3.01)
    close_battery_day(record, DAY, 90)
    assert record[DEV_BATTERY_DAY_RANGES] == [["2026-11-14", None, None, 3.01, 3.01]]
    # The replacement rule reads only rows with a level.
    assert _ranges(record) == ([], [])


def test_the_rows_are_kept_for_the_history_setting():
    record = _record()
    for back in range(40, 0, -1):
        day = DAY - timedelta(days=back)
        record[DEV_LAST_ACTIVITY] = _noon(day)
        note_battery_sample(record, 50.0)
        close_battery_day(record, day, 30)
    rows = record[DEV_BATTERY_DAY_RANGES]
    assert len(rows) == 30
    assert rows[-1][0] == (DAY - timedelta(days=1)).isoformat()
    assert rows[0][0] == (DAY - timedelta(days=30)).isoformat()


def test_the_replacement_rule_reads_the_newest_rows():
    record = _record()
    record[DEV_BATTERY_DAY_RANGES] = [
        ["2026-11-10", 20.0, 40.0, None, None],
        ["2026-11-11", 21.0, 30.0, 3.0, 3.1],
        ["2026-11-12", None, None, 3.0, 3.0],
        ["2026-11-13", 22.0, 25.0, None, None],
        ["2026-11-14", 23.0, 24.0, None, None],
    ]
    lows, highs = _ranges(record)
    assert highs == [30.0, 25.0, 24.0]
    # A rise to full reads the day before; one below full the two days before.
    assert old_cell_high(record, 100.0) == 24.0
    assert old_cell_high(record, 80.0) == 25.0


def test_a_voltage_that_is_not_one_is_not_noted():
    record = _record()
    for bad in (None, "3.0", float("nan"), float("inf"), True):
        note_battery_volts(record, bad)
    assert record[DEV_BATTERY_VOLTS_TODAY_LOW] is None
    # A hand-edited pair out of step starts the day again.
    record[DEV_BATTERY_VOLTS_TODAY_LOW] = 3.2
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = 3.0
    note_battery_volts(record, 2.9)
    assert (record[DEV_BATTERY_VOLTS_TODAY_LOW], record[DEV_BATTERY_VOLTS_TODAY_HIGH]) == (2.9, 2.9)


def test_the_raw_scale_halves_the_levels_not_the_voltages():
    record = _record()
    record[DEV_BATTERY_DAY_RANGES] = [["2026-11-14", 120.0, 160.0, 2.9, 3.0]]
    assert mark_raw_battery(record)
    assert record[DEV_BATTERY_DAY_RANGES] == [["2026-11-14", 60.0, 80.0, 2.9, 3.0]]


def test_damaged_rows_are_found():
    good = ["2026-11-14", 50.0, 60.0, 2.9, 3.0]
    assert day_range_row_ok(good)
    for bad in (
        good[:4], ["14 Nov", 50.0, 60.0, 2.9, 3.0], ["2026-11-14", 60.0, 50.0, 2.9, 3.0],
        ["2026-11-14", 50.0, None, 2.9, 3.0], ["2026-11-14", 50.0, 160.0, None, None],
        ["2026-11-14", 50.0, 60.0, 3.0, 99.0], ["2026-11-14", "50", 60.0, None, None],
        ["2026-11-14", True, 60.0, None, None],
    ):
        assert not day_range_row_ok(bad), bad
        faults = check_records({"d": {DEV_BATTERY_DAY_RANGES: [good, bad]}})
        assert any(field == DEV_BATTERY_DAY_RANGES for _, field, _ in faults), bad


def test_the_older_rows_go_to_the_history_file_under_a_key_of_their_own():
    """Not in the device map, where an older release would refuse the whole file for
    a field it does not know and lose every device's older history."""
    from custom_components.device_sentinel import history_file

    record = _record()
    record[DEV_BATTERY_DAY_RANGES] = [
        [(DAY - timedelta(days=back)).isoformat(), 50.0, 51.0, 2.9, 3.0] for back in range(44, -1, -1)
    ]
    view, part = history_file.split({DATA_DEVICES: {"dev": record}})
    assert len(view[DATA_DEVICES]["dev"][DEV_BATTERY_DAY_RANGES]) == 30
    assert len(part[history_file.H_DAY_RANGES]["dev"]) == 15
    assert DEV_BATTERY_DAY_RANGES not in part[history_file.H_DEVICES].get("dev", {})
    assert DEV_BATTERY_DAY_RANGES not in SERIES_FIELDS
    assert not history_file.is_empty(part)
    payload = {history_file.H_GENERATION: 1, **part}
    assert history_file.check_payload(payload) is None
    loaded = {DATA_DEVICES: {"dev": dict(view[DATA_DEVICES]["dev"])}}
    loaded[DATA_DEVICES]["dev"][DEV_BATTERY_DAY_RANGES] = list(loaded[DATA_DEVICES]["dev"][DEV_BATTERY_DAY_RANGES])
    history_file.join(loaded, payload)
    assert loaded[DATA_DEVICES]["dev"][DEV_BATTERY_DAY_RANGES] == record[DEV_BATTERY_DAY_RANGES]
    assert history_file.describe(payload)["entries"] == 15
    # A damaged older row refuses the copy, as damage anywhere does.
    payload[history_file.H_DAY_RANGES]["dev"][0][1] = "x"
    assert history_file.check_payload(payload) is not None


def test_a_series_a_newer_release_added_does_not_refuse_the_history_file():
    """A return from a later release keeps every history this one knows."""
    from custom_components.device_sentinel import history_file
    from custom_components.device_sentinel.const import DEV_BATTERY_DAILY

    payload = {history_file.H_GENERATION: 1, history_file.H_DEVICES: {
        "dev": {DEV_BATTERY_DAILY: [50.0, 49.0], "a_series_from_later": [1, 2, 3]},
    }}
    assert history_file.check_payload(payload) is None
    record = _record()
    record[DEV_BATTERY_DAILY] = [48.0]
    loaded = {DATA_DEVICES: {"dev": record}}
    history_file.join(loaded, payload)
    assert record[DEV_BATTERY_DAILY] == [50.0, 49.0, 48.0]
    assert "a_series_from_later" not in record


def test_the_rows_survive_a_new_epoch():
    assert DEV_BATTERY_DAY_RANGES in EPOCH_KEPT
    assert {DEV_BATTERY_VOLTS_TODAY_LOW, DEV_BATTERY_VOLTS_TODAY_HIGH} <= set(EPOCH_KEPT)


# ------------------------------------------------------- the clocks file


def test_the_days_samples_live_with_the_clocks():
    for field in (
        DEV_BATTERY_DAY_LEVELS, DEV_BATTERY_DAY_COUNTS,
        DEV_BATTERY_VOLTS_TODAY_LOW, DEV_BATTERY_VOLTS_TODAY_HIGH,
    ):
        assert field in CLOCK_FIELDS
    # The history is not a clock.
    assert DEV_BATTERY_DAY_RANGES not in CLOCK_FIELDS


async def test_a_power_cut_keeps_the_mornings_samples(hass: HomeAssistant, hass_storage):
    """The main file is written rarely; the clocks file is the one that
    carries the day's levels and voltages to the next start."""
    device, _ids = await _battery_device(hass, "door", "2950")
    record = _new_device_record("2026-07-11T00:00:00+00:00", time.time() - 600)
    record[DEV_BATTERY_DAY_LEVELS] = [99.0]
    record[DEV_BATTERY_DAY_COUNTS] = [1]
    saved = time.time() - 300
    hass_storage[STORAGE_KEY] = {"version": 1, "data": {
        DATA_DEVICES: {device.id: record}, DATA_SAVED_AT: saved - 100,
        DATA_STATS_EPOCH: STATS_EPOCH, DATA_CLEAN_STOP: True,
    }}
    hass_storage[STORAGE_CLOCKS_KEY] = {"version": 1, "data": {DATA_SAVED_AT: saved, "clocks": {device.id: {
        DEV_LAST_ACTIVITY: time.time() - 600,
        DEV_BATTERY_DAY_LEVELS: [60.0, 59.0], DEV_BATTERY_DAY_COUNTS: [5, 2],
        DEV_BATTERY_VOLTS_TODAY_LOW: 2.91, DEV_BATTERY_VOLTS_TODAY_HIGH: 2.95,
    }}}}
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    loaded = coord.data[DATA_DEVICES][device.id]
    assert loaded[DEV_BATTERY_DAY_LEVELS][:2] == [60.0, 59.0]
    # The start's own reading of the level held adds a moment to 60.
    assert loaded[DEV_BATTERY_DAY_COUNTS][0] >= 5 and loaded[DEV_BATTERY_DAY_COUNTS][1] == 2
    assert loaded[DEV_BATTERY_VOLTS_TODAY_LOW] == 2.91
    # Written to the clocks file, and never to the main one.
    clocks = coord._clocks_to_save()["clocks"][device.id]
    assert clocks[DEV_BATTERY_DAY_LEVELS][:2] == [60.0, 59.0]
    main = coord._data_to_save()
    assert DEV_BATTERY_DAY_LEVELS not in main[DATA_DEVICES][device.id]
    assert DEV_BATTERY_VOLTS_TODAY_LOW not in main[DATA_DEVICES][device.id]


async def test_an_older_clocks_file_without_the_samples_keeps_the_main_files(
    hass: HomeAssistant, hass_storage
):
    """The upgrade: the day's levels are still in the main file, and the
    clocks file has never carried them. The main file's are kept, nothing
    is set aside, and the three-day lists become dated rows."""
    device, _ids = await _battery_device(hass, "lock", None)
    record = _new_device_record("2026-07-11T00:00:00+00:00", time.time() - 600)
    record[DEV_BATTERY_DAY_LEVELS] = [71.0]
    record[DEV_BATTERY_DAY_COUNTS] = [3]
    del record[DEV_BATTERY_DAY_RANGES]
    del record[DEV_BATTERY_VOLTS_TODAY_LOW]
    del record[DEV_BATTERY_VOLTS_TODAY_HIGH]
    record[DEV_BATTERY_RANGE_LOWS] = [70.0, 71.0, 70.0]
    record[DEV_BATTERY_RANGE_HIGHS] = [72.0, 72.0, 71.0]
    saved = time.time() - 300
    saved_day = dt_util.as_local(dt_util.utc_from_timestamp(saved)).date()
    clocks = {k: v for k, v in record.items() if k in CLOCK_FIELDS and k not in (
        DEV_BATTERY_DAY_LEVELS, DEV_BATTERY_DAY_COUNTS,
        DEV_BATTERY_VOLTS_TODAY_LOW, DEV_BATTERY_VOLTS_TODAY_HIGH,
    )}
    main = {k: v for k, v in record.items() if k not in clocks}
    hass_storage[STORAGE_KEY] = {"version": 1, "data": {
        DATA_DEVICES: {device.id: main}, DATA_SAVED_AT: saved - 100,
        DATA_STATS_EPOCH: STATS_EPOCH, DATA_CLEAN_STOP: True,
    }}
    hass_storage[STORAGE_CLOCKS_KEY] = {"version": 1, "data": {DATA_SAVED_AT: saved, "clocks": {device.id: clocks}}}
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    loaded = coord.data[DATA_DEVICES][device.id]
    assert loaded[DEV_BATTERY_DAY_LEVELS][0] == 71.0
    assert loaded[DEV_BATTERY_DAY_COUNTS][0] >= 3
    last = saved_day - timedelta(days=1)
    assert loaded[DEV_BATTERY_DAY_RANGES] == [
        [(last - timedelta(days=2)).isoformat(), 70.0, 72.0, None, None],
        [(last - timedelta(days=1)).isoformat(), 71.0, 72.0, None, None],
        [last.isoformat(), 70.0, 71.0, None, None],
    ]
    assert DEV_BATTERY_RANGE_LOWS not in loaded and DEV_BATTERY_RANGE_HIGHS not in loaded
    assert check_records({device.id: loaded}) == []
    assert not coord._clocks_discarded


def test_the_old_lists_are_retired():
    assert {DEV_BATTERY_RANGE_LOWS, DEV_BATTERY_RANGE_HIGHS} <= RETIRED_DEVICE_FIELDS


def test_a_return_from_an_older_release_keeps_the_rows_it_has():
    """Back to the older release and forward again: a day already in the
    rows keeps its row, with its voltage."""
    record = _record()
    record[DEV_BATTERY_DAY_RANGES] = [["2026-11-12", 70.0, 72.0, 2.9, 3.0]]
    record[DEV_BATTERY_RANGE_LOWS] = [69.0, 68.0, 67.0]
    record[DEV_BATTERY_RANGE_HIGHS] = [70.0, 69.0, 68.0]
    assert ranges_from_old_lists(record, DAY)
    assert record[DEV_BATTERY_DAY_RANGES] == [
        ["2026-11-12", 70.0, 72.0, 2.9, 3.0],
        ["2026-11-13", 68.0, 69.0, None, None],
        ["2026-11-14", 67.0, 68.0, None, None],
    ]
    # Lists out of step make nothing, and are still removed.
    record[DEV_BATTERY_RANGE_LOWS] = [1.0, 2.0]
    record[DEV_BATTERY_RANGE_HIGHS] = [3.0]
    assert not ranges_from_old_lists(record, DAY)
    assert DEV_BATTERY_RANGE_LOWS not in record


# ------------------------------------------- through Home Assistant


async def test_the_voltage_is_read_each_moment_the_device_speaks(hass: HomeAssistant):
    device, ids = await _battery_device(hass, "coin", "2950")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    for millivolts in ("2950", "2890", "2920"):
        hass.states.async_set(ids["voltage"], millivolts, {"device_class": "voltage", "unit_of_measurement": "mV"})
        coord._battery_sampled_at.pop(device.id, None)
        coord._sample_battery_held(device.id)
    assert (record[DEV_BATTERY_VOLTS_TODAY_LOW], record[DEV_BATTERY_VOLTS_TODAY_HIGH]) == (2.89, 2.95)
    # The midnight fold keeps the day as a row.
    await hass.async_block_till_done()
    today = dt_util.now().date()
    record[DEV_LAST_ACTIVITY] = time.time()
    coord._fold_day_override = today
    await coord._on_midnight(None)
    rows = record[DEV_BATTERY_DAY_RANGES]
    assert rows[-1][0] == today.isoformat()
    assert rows[-1][3:] == [2.89, 2.95]
    assert record[DEV_BATTERY_VOLTS_TODAY_LOW] is None


def test_one_day_folded_twice_is_one_row():
    """A restart across midnight can fold one day twice: one row holds
    both parts, so the replacement rule never reads a day twice."""
    record = _record(heard=_noon(DAY))
    for level in (60.0, 60.0):
        note_battery_sample(record, level)
    note_battery_volts(record, 3.0)
    close_battery_day(record, DAY, 90)
    for level in (57.0, 57.0):
        note_battery_sample(record, level)
    note_battery_volts(record, 2.9)
    close_battery_day(record, DAY, 90)
    assert record[DEV_BATTERY_DAY_RANGES] == [["2026-11-14", 57.0, 60.0, 2.9, 3.0]]


async def test_the_voltage_is_read_inside_the_levels_minute(hass: HomeAssistant):
    """A battery report and its voltage in one message: the voltage is
    read once the message is written, even inside the minute that holds
    the level's next moment back."""
    device, ids = await _battery_device(hass, "lock", "3000")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    coord._battery_sampled_at[device.id] = time.time()
    hass.states.async_set(ids["voltage"], "2870", {"device_class": "voltage", "unit_of_measurement": "mV"})
    coord._sample_battery_held(device.id)
    assert record[DEV_BATTERY_VOLTS_TODAY_LOW] == 2.87
