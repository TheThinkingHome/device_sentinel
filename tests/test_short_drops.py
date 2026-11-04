# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_short_drops.py, Version: 0.28.2 (2026-11-04)

"""Each drop a device makes is recorded, and a drop is timed from when
the device went (rules SIG-16, UNAV-07).

A sensor can drop to unavailable nine times in two days, and an outlet
sixteen times in one evening. A rule that silences short drops needs
each drop on record first: when the device went, how long it was gone,
the window it was judged against, and its signal at the drop, at the
recovery and as usual. They are recorded and shown on the device page,
and nothing that is told or pushed changes.

A long drop while a device has short drop-outs is timed from when the
device went (`test_short_drop_outs.py`).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SHORT_DROP_DAYS,
    SHORT_DROP_DAY_LIMIT,
    DATA_SHORT_DROPS,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_VALUE,
    LEARNING_MIN_DAYS,
)
from custom_components.device_sentinel.normalise import check_storage
from custom_components.device_sentinel.short_drops import (
    drop_day,
    forget_restart_drops,
    is_short,
    usual_signal,
)

from tests.test_short_drop_outs import _drop, _shed


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


async def test_a_drop_inside_the_startup_grace_is_not_recorded(hass: HomeAssistant, freezer):
    """At a restart Zigbee2MQTT's devices read unavailable until the
    bridge publishes them, about 37 seconds on the reference rig: all
    69 of them, together. That is the start, not the devices (rule
    UP-04: nothing is recorded inside the startup grace)."""
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    now = dt_util.utcnow().timestamp()
    coord._started_at = now - 1
    coord._grace_until = now + 300
    coord._note_drop(device.id, record, now, now + 37)
    assert _drops(coord, device.id) == []
    # One that went after the grace is recorded as before.
    coord._note_drop(device.id, record, now + 301, now + 600)
    assert len(_drops(coord, device.id)) == 1


async def test_a_device_unavailable_at_the_start_is_not_a_drop(hass: HomeAssistant, freezer):
    """Through a real start: the device reads unavailable as Device
    Sentinel starts and comes back 37 seconds later (rule UP-04)."""
    from custom_components.device_sentinel.const import DEV_EVENT_COUNT, DEV_LAST_ACTIVITY

    from tests.helpers import register_device, setup_entry

    device, entities = register_device(hass, "z1", name="Door Entryway")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "unavailable")
    entry = await setup_entry(hass, {})
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 500
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60
    assert coord._grace_until > dt_util.utcnow().timestamp()
    freezer.tick(37)
    hass.states.async_set(entity_id, "closed")
    await hass.async_block_till_done()
    freezer.tick(60)
    await coord._on_render_tick(None) if callable(getattr(coord, "_on_render_tick", None)) else None
    await hass.async_block_till_done()
    assert _drops(coord, device.id) == []
    assert coord.short_drops_of(device.id) is None


async def test_the_page_counts_short_drops_in_the_last_12_hours(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    rows = coord.data.setdefault(DATA_SHORT_DROPS, [])
    base = {"device_id": device.id, "signal_went": None, "signal_back": None, "signal_usual": None}
    rows.append({**base, "went": now - 13 * 3600, "length": 60.0, "window": 600.0})  # too old
    rows.append({**base, "went": now - 3600, "length": 1200.0, "window": 600.0})  # long
    rows.append({**base, "went": now - 1800, "length": 300.0, "window": 600.0})
    rows.append({**base, "went": now - 600, "length": 200.0, "window": 600.0})
    found = coord.short_drops_of(device.id, now)
    assert found["count"] == 2
    assert found["longest"] == 300.0
    assert abs(dt_util.parse_datetime(found["last"]).timestamp() - (now - 600)) < 1
    page = coord.dashboard_device(device.id)
    assert page["identity"]["short_drops"]["count"] == 2
    assert coord.short_drops_of("someone_else", now) is None


def _row(device_id, went, length=60.0, window=600.0, went_sig=None, back_sig=None, usual=None):
    return {"device_id": device_id, "went": went, "length": length, "window": window,
            "signal_went": went_sig, "signal_back": back_sig, "signal_usual": usual}


async def test_a_drop_is_kept_seven_days_then_folded_into_its_day(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    old = now - 8 * 86400
    rows = coord.data.setdefault(DATA_SHORT_DROPS, [])
    rows.append(_row(device.id, old, 200.0, 600.0, -80.0, -70.0, -65.0))
    rows.append(_row(device.id, old + 60, 900.0, 600.0, -90.0, None, -65.0))
    rows.append(_row(device.id, now - 86400))
    coord._trim_house_tables(now)
    assert [r["went"] for r in _drops(coord, device.id)] == [now - 86400]
    (day,) = coord.data[DATA_SHORT_DROP_DAYS]
    assert day["day"] == drop_day(old)
    assert (day["drops"], day["short"], day["total"], day["longest"]) == (2, 1, 1100.0, 900.0)
    assert day["signal_went"] == -85.0 and day["signal_went_n"] == 2
    assert day["signal_back"] == -70.0 and day["signal_back_n"] == 1
    assert day["signal_usual"] == -65.0
    assert check_storage({"short_drop_days": [day]}) == []


async def test_day_rows_are_held_to_the_history_length(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    rows = coord.data.setdefault(DATA_SHORT_DROPS, [])
    rows.append(_row(device.id, now - (coord.retention_days + 2) * 86400))
    rows.append(_row(device.id, now - 10 * 86400))
    coord._trim_house_tables(now)
    assert _drops(coord, device.id) == []
    assert [d["day"] for d in coord.data[DATA_SHORT_DROP_DAYS]] == [drop_day(now - 10 * 86400)]


async def test_past_a_hundred_drops_in_a_day_a_drop_counts_in_the_day_only(hass: HomeAssistant, freezer):
    coord, device, _entity_id, _phone = await _shed(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 2)
    base = dt_util.start_of_local_day().timestamp() + 3600
    coord._started_at = base - 1
    for i in range(SHORT_DROP_DAY_LIMIT + 5):
        coord._note_drop(device.id, record, base + i * 300, base + i * 300 + 200)
    assert len(_drops(coord, device.id)) == SHORT_DROP_DAY_LIMIT
    (day,) = coord.data[DATA_SHORT_DROP_DAYS]
    assert day["day"] == drop_day(base) and day["drops"] == 5 and day["short"] == 5
    # At the fold, the kept drops join the same day's row.
    coord._trim_house_tables(base + 8 * 86400)
    (day,) = coord.data[DATA_SHORT_DROP_DAYS]
    assert day["drops"] == SHORT_DROP_DAY_LIMIT + 5 and day["total"] == 200.0 * (SHORT_DROP_DAY_LIMIT + 5)


def test_the_drops_0_28_0_kept_at_a_start_are_removed():
    """A restart at which 69 devices read unavailable for 37 seconds."""
    start = 1_793_746_472.0
    data = {
        "system_events": [{"kind": "restart", "when": start, "scope": "system", "detail": None}],
        "short_drops": [_row("a", start + 0.07, 37.3), _row("b", start + 0.37, 36.9),
                        _row("c", start + 400, 60.0), _row("d", start - 3600, 60.0)],
    }
    assert forget_restart_drops(data) == 2
    assert [r["device_id"] for r in data["short_drops"]] == ["c", "d"]
    assert forget_restart_drops(data) == 0


def test_a_damaged_drop_row_is_found_by_the_shape_check():
    good = {"device_id": "a", "went": 1_790_000_000.0, "length": 60.0, "window": None,
            "signal_went": -70.0, "signal_back": None, "signal_usual": None}
    assert check_storage({"short_drops": [good]}) == []
    bad = dict(good, went="yesterday")
    assert check_storage({"short_drops": [bad]})


def test_the_usual_signal_is_the_middle_of_the_last_days():
    assert usual_signal({DEV_SIGNAL_DAILY_P50: [-50.0, -70.0, -60.0]}) == -60.0
    assert usual_signal({}) is None


async def test_the_restart_drops_go_at_the_next_start(hass: HomeAssistant):
    """The rows a start left behind are gone at the next load."""
    from tests.helpers import setup_entry

    entry = await setup_entry(hass, {})
    coord = entry.runtime_data
    start = dt_util.utcnow().timestamp() - 3600
    coord.data["system_events"].append({"kind": "restart", "when": start, "scope": "system", "detail": None})
    coord.data.setdefault(DATA_SHORT_DROPS, []).extend(
        [_row("a", start + 0.07, 37.3), _row("b", start + 1200, 60.0)]
    )
    coord._mark_cold_dirty()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    kept = entry.runtime_data.data.get(DATA_SHORT_DROPS)
    assert [r["device_id"] for r in kept] == ["b"]


async def test_a_return_inside_the_three_minute_debounce_is_not_a_drop(hass: HomeAssistant, freezer):
    """The device never turned unavailable (rule UNAV-03), so two
    two-minute blips make no short drop-outs."""
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    now = dt_util.utcnow().timestamp()
    coord._started_at = now - 3600
    coord._note_drop(device.id, record, now - 600, now - 480)
    coord._note_drop(device.id, record, now - 300, now - 120.5)
    assert _drops(coord, device.id) == []
    coord._note_drop(device.id, record, now - 200, now)
    assert len(_drops(coord, device.id)) == 1
