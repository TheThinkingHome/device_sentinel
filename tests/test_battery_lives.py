# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_lives.py, Version: 0.27.1 (2026-10-23)

"""Each battery replaced leaves a row for the battery that ended (#739).

These are the finished lives a survival model learns from: no battery on
either house had been watched from new to replaced when 0.27.1 was built.
A battery's start is the replacement on record, or else the day the
device was first seen, never the first day its trimmed history keeps:
the History setting keeps 90 days by default and a coin cell lasts
years (James, 23 October 2026).
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_BATTERY_LIVES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_FIRST_OBSERVED,
)
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
from custom_components.device_sentinel.normalise import check_storage

from .test_battery_last_replaced import _detected, _fold, _house, _rise_day, _start

# Row fields.
START, SEEN, END, FIRST_DAY, FIRST_LEVEL, LAST_LEVEL, LAST_HEARD = 5, 6, 7, 8, 9, 10, 11


def _lives(coord):
    return coord.data.get(DATA_BATTERY_LIVES) or []


def _first_seen(record, days_ago: int) -> str:
    """Set when Device Sentinel first saw the device; returns the day."""
    moment = dt_util.now() - timedelta(days=days_ago)
    record[DEV_FIRST_OBSERVED] = moment.isoformat()
    return moment.date().isoformat()


async def test_a_replacement_writes_the_battery_that_ended(hass: HomeAssistant):
    _entry, coord, device, _record = await _detected(hass)
    coord.page_set_power(device.id, "CR2032", 1)
    lives = _lives(coord)
    assert len(lives) == 1
    row = lives[0]
    assert row[0] == device.id and row[START] == _start().isoformat() and row[END] == _rise_day()
    assert row[SEEN] is False, "the first battery went in before Device Sentinel was watching"
    assert row[FIRST_DAY] == _start().isoformat()
    assert (row[FIRST_LEVEL], row[LAST_LEVEL]) == (40.0, 37.0)
    assert row[LAST_HEARD] == (_start() + timedelta(days=3)).isoformat()
    view = coord.battery_lives_view()[0]
    assert view["days"] == 4 and view["silent_days"] == 1 and view["still_here"] is True
    assert not [fault for fault in check_storage(coord.data) if DATA_BATTERY_LIVES in str(fault)]


async def test_a_first_battery_starts_when_the_device_was_first_seen(hass: HomeAssistant):
    """A first battery outlasting the History setting: its kept history
    begins 90 days before it ran out, but Device Sentinel saw the device
    200 days ago, so its life was at least 200 days, start not seen."""
    _entry, coord, device, record = await _house(hass)
    seen = _first_seen(record, 200)
    _fold(coord, record, device.id, [40, 39, 38, 37, 100, 100], _start())
    row = _lives(coord)[0]
    assert row[START] == seen and row[SEEN] is False
    assert row[FIRST_DAY] == _start().isoformat(), "the first kept day is kept beside it"
    assert coord.battery_lives_view()[0]["days"] > 190


async def test_a_second_battery_starts_on_its_replacement_whatever_was_trimmed(hass: HomeAssistant):
    """The second battery's start is the first replacement's day, seen,
    even when the history from then has been trimmed away."""
    _entry, coord, device, record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    _fold(coord, record, device.id, [99, 98], _start() + timedelta(days=6))
    # Retention trims the new battery's first days.
    del record[DEV_BATTERY_DAILY][:2]
    _fold(coord, record, device.id, [40, 100, 100], _start() + timedelta(days=8))
    lives = _lives(coord)
    assert len(lives) == 2
    assert lives[1][START] == _rise_day() and lives[1][SEEN] is True
    assert lives[1][FIRST_DAY] > lives[1][START]


async def test_cancel_takes_the_row_back(hass: HomeAssistant):
    _entry, coord, device, _record = await _detected(hass)
    assert len(_lives(coord)) == 1
    coord.battery_answer(device.id, "cancel")
    assert _lives(coord) == []


async def test_a_day_given_over_a_waiting_detection_corrects_its_row(hass: HomeAssistant):
    _entry, coord, device, _record = await _detected(hass)
    given = (_start() + timedelta(days=2)).isoformat()
    coord.battery_answer(device.id, "date", given)
    lives = _lives(coord)
    assert len(lives) == 1 and lives[0][END] == given and lives[0][START] == _start().isoformat()
    assert (lives[0][FIRST_LEVEL], lives[0][LAST_LEVEL]) == (40.0, 39.0)


async def test_a_day_given_with_nothing_detected_adds_a_row_from_first_seen(hass: HomeAssistant):
    """The person names a replacement nothing detected: the battery that
    ended started when the device was first seen."""
    _entry, coord, device, record = await _house(hass)
    seen = _first_seen(record, 120)
    _fold(coord, record, device.id, [40, 39, 38], _start())
    given = (_start() + timedelta(days=2)).isoformat()
    coord.battery_answer(device.id, "date", given)
    lives = _lives(coord)
    assert len(lives) == 1 and lives[0][START] == seen and lives[0][SEEN] is False and lives[0][END] == given


async def test_a_day_given_before_the_rise_is_one_battery(hass: HomeAssistant):
    """The person gives the day the evening they swap the cell; the rise
    confirmed nights later is that same replacement (#701), so the battery
    that ended keeps one row, ending on the person's day, and runs to the
    old cell's last heard level."""
    _entry, coord, device, record = await _house(hass)
    _fold(coord, record, device.id, [40, 39, 38], _start())
    given = (_start() + timedelta(days=3)).isoformat()
    coord.battery_answer(device.id, "date", given)
    assert len(_lives(coord)) == 1
    _fold(coord, record, device.id, [37, 100, 100], _start() + timedelta(days=3))
    lives = _lives(coord)
    assert len(lives) == 1, lives
    assert lives[0][START] == _start().isoformat() and lives[0][END] == given
    assert lives[0][LAST_LEVEL] == 37.0 and lives[0][SEEN] is False


async def test_the_row_says_when_the_device_was_first_seen(hass: HomeAssistant):
    """With no replacement on record the Battery Last Replaced row carries
    the day the device was first seen; with one, it does not."""
    _entry, coord, device, record = await _house(hass)
    seen = _first_seen(record, 72)
    view = coord.battery_replacement_view(device.id)
    assert view["day"] is None and view["first_seen"] == seen
    _fold(coord, record, device.id, [40, 39, 38, 37, 100, 100], _start())
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == _rise_day() and view["first_seen"] is None


async def test_the_diagnostics_carry_the_lives(hass: HomeAssistant):
    entry, coord, device, _record = await _detected(hass)
    found = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(found)
    assert "battery_lives" in text and _rise_day() in text


def test_a_damaged_life_is_found():
    good = ["dev", "Aqara", "MCCGQ11LM", "CR1632", 1, "2026-01-01", False, "2026-10-01", "2026-07-03",
            100.0, 12.0, "2026-09-28", None]
    for bad in (good[:12], [None, *good[1:]], [*good[:5], "Jan 1", *good[6:]], [*good[:6], "no", *good[7:]],
                [*good[:8], "July", *good[9:]], [*good[:9], 140.0, *good[10:]], [*good[:4], 0, *good[5:]]):
        faults = check_storage({DATA_BATTERY_LIVES: [good, bad]})
        assert any(table == DATA_BATTERY_LIVES or DATA_BATTERY_LIVES in str(field) for table, field, _ in faults), bad
    assert not [f for f in check_storage({DATA_BATTERY_LIVES: [good]}) if DATA_BATTERY_LIVES in str(f)]


async def test_a_row_the_load_check_would_refuse_is_never_written(hass: HomeAssistant):
    """One refused row drops the whole log at the next load, so the
    writer checks each row the same way first."""
    _entry, coord, device, record = await _detected(hass)
    assert len(_lives(coord)) == 1
    record[DEV_BATTERY_DAILY_PREVIOUS] = [140.0, 50.0]
    coord.battery_life_ended(device.id, record, None, None)
    assert len(_lives(coord)) == 1
    assert not [fault for fault in check_storage(coord.data) if DATA_BATTERY_LIVES in str(fault)]
