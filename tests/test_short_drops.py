# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_short_drops.py, Version: 0.28.0 (2026-11-03)

"""Each drop a device makes is recorded, and a drop is timed from when
the device went (rules SIG-16, UNAV-07).

A sensor can drop to unavailable nine times in two days, and an outlet
sixteen times in one evening. A rule that silences short drops needs
each drop on record first: when the device went, how long it was gone,
the window it was judged against, and its signal at the drop, at the
recovery and as usual. They are recorded and shown on the device page,
and nothing that is told or pushed changes.

Once a dropping-out item stands, a drop is still timed from when the
device went, not from when it was listed minutes later.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SHORT_DROPS,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_VALUE,
    INC_EVENT,
    INC_KIND,
    INCIDENT_RESOLVED,
    LEARNING_MIN_DAYS,
)
from custom_components.device_sentinel.normalise import check_storage
from custom_components.device_sentinel.short_drops import is_short, usual_signal

from tests.test_flapping import _drop, _minutes, _shed


def _drops(coord, device_id):
    return [r for r in coord.data.get(DATA_SHORT_DROPS) or [] if r["device_id"] == device_id]


async def test_a_drop_is_recorded_with_its_length_and_signal(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 2)
    record[DEV_SIGNAL_VALUE] = -71.0
    record[DEV_SIGNAL_DAILY_P50] = [-60.0, -62.0, -61.0]
    went = dt_util.utcnow().timestamp()
    await _drop(hass, coord, freezer, entity_id, down=5, back=1)
    (row,) = _drops(coord, device.id)
    assert abs(row["went"] - went) < 2
    assert abs(row["length"] - 300) < 2
    assert row["window"] is not None and is_short(row)
    assert row["signal_went"] == -71.0
    assert row["signal_usual"] == -61.0
    assert row["signal_back"] is None


async def test_the_first_reading_after_the_return_is_its_recovery_signal(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    await _drop(hass, coord, freezer, entity_id, down=5, back=0)
    coord._drop_signal_back(device.id, -55.0, dt_util.utcnow().timestamp() + 30)
    (row,) = _drops(coord, device.id)
    assert row["signal_back"] == -55.0
    # Only the first: a second reading changes nothing.
    coord._drop_signal_back(device.id, -90.0, dt_util.utcnow().timestamp() + 40)
    assert row["signal_back"] == -55.0


async def test_a_reading_long_after_the_return_is_not_its_recovery_signal(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    await _drop(hass, coord, freezer, entity_id, down=5, back=0)
    coord._drop_signal_back(device.id, -55.0, dt_util.utcnow().timestamp() + 900)
    (row,) = _drops(coord, device.id)
    assert row["signal_back"] is None


async def test_a_drop_its_upstream_took_down_is_not_its_own(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    coord._entry_down_at = {}
    claimed = dt_util.utcnow().timestamp()
    original = coord.upstream_down_since
    coord.upstream_down_since = lambda device_id: ("test", claimed)
    try:
        await _drop(hass, coord, freezer, entity_id, down=5, back=0)
    finally:
        coord.upstream_down_since = original
    assert _drops(coord, device.id) == []


async def test_a_drop_across_a_restart_is_not_recorded(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    coord._note_drop(device.id, record, coord._started_at - 60, dt_util.utcnow().timestamp())
    assert _drops(coord, device.id) == []


async def test_the_page_counts_short_drops_in_the_last_12_hours(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    rows = coord.data.setdefault(DATA_SHORT_DROPS, [])
    base = {"device_id": device.id, "signal_went": None, "signal_back": None, "signal_usual": None}
    rows.append({**base, "went": now - 13 * 3600, "length": 60.0, "window": 600.0})  # too old
    rows.append({**base, "went": now - 3600, "length": 1200.0, "window": 600.0})  # long
    rows.append({**base, "went": now - 1800, "length": 300.0, "window": 600.0})
    rows.append({**base, "went": now - 600, "length": 120.0, "window": 600.0})
    found = coord.short_drops_of(device.id, now)
    assert found["count"] == 2
    assert found["longest"] == 300.0
    assert abs(dt_util.parse_datetime(found["last"]).timestamp() - (now - 600)) < 1
    page = coord.dashboard_device(device.id)
    assert page["identity"]["short_drops"]["count"] == 2
    assert coord.short_drops_of("someone_else", now) is None


async def test_drops_are_held_to_the_history_length(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    rows = coord.data.setdefault(DATA_SHORT_DROPS, [])
    base = {"device_id": device.id, "length": 60.0, "window": 600.0,
            "signal_went": None, "signal_back": None, "signal_usual": None}
    rows.append({**base, "went": now - (coord.retention_days + 2) * 86400})
    rows.append({**base, "went": now - 86400})
    coord._trim_house_tables(now)
    assert len(coord.data[DATA_SHORT_DROPS]) == 1


def test_a_damaged_drop_row_is_found_by_the_shape_check():
    good = {"device_id": "a", "went": 1_790_000_000.0, "length": 60.0, "window": None,
            "signal_went": -70.0, "signal_back": None, "signal_usual": None}
    assert check_storage({"short_drops": [good]}) == []
    bad = dict(good, went="yesterday")
    assert check_storage({"short_drops": [bad]})


def test_the_usual_signal_is_the_middle_of_the_last_days():
    assert usual_signal({DEV_SIGNAL_DAILY_P50: [-50.0, -70.0, -60.0]}) == -60.0
    assert usual_signal({}) is None


async def test_a_drop_while_dropping_out_is_timed_from_when_the_device_went(hass: HomeAssistant, freezer):
    """Ten-minute drops read ten, not seven, once the item stands."""
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(5):
        await _drop(hass, coord, freezer, entity_id, down=10, back=20)
    assert coord.is_flapping(device.id)
    resolved = [
        r for r in coord.data[DATA_INCIDENTS]
        if r["device_id"] == device.id and r[INC_KIND] == "unavailable" and r[INC_EVENT] == INCIDENT_RESOLVED
    ]
    assert len(resolved) == 5
    for row in resolved:
        assert abs(row["duration"] - 600) <= 60, [round(r["duration"]) for r in resolved]


async def test_recording_drops_changes_nothing_told(hass: HomeAssistant, freezer):
    """A short drop pushes nothing new and opens nothing new (rule SIG-16):
    the dropping-out item and its one push are as before."""
    coord, device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    before = len(phone)
    for _ in range(4):
        await _drop(hass, coord, freezer, entity_id)
    assert len(phone) == before
    assert len(_drops(coord, device.id)) == 7
    await _minutes(hass, coord, freezer, 1)
