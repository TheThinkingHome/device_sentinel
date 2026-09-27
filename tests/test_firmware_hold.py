# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_firmware_hold.py, Version: 0.23.10 (2026-09-26)

"""A firmware version is recorded only once it has held.

At the 5:19 PM restart of 25 September four buttons on the reference
rig each recorded an older firmware and their current one again within
the same second. 0.23.9 tied the record to the midnight fold with an
hour's hold. A restart forgets what is held, so a house restarting in
the hour before midnight, or rebooting across it (#406), never
recorded an update; the owner ruled on 26 September that a version is
recorded on the minute tick once it has held ten minutes, after the
startup grace (0.23.10). The histories pinned below are the four
buttons' real ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FIRMWARE_HISTORY,
    FIRMWARE_HOLD_SECONDS,
    STARTUP_GRACE_SECONDS,
)
from custom_components.device_sentinel.model_groups import unflicker_firmware

from .helpers import setup_entry

# Button Doorbell, Button Terrace Dining, Button Master Shower and
# Button James Night Table, exactly as the reference rig's storage
# recorded them on 25 September.
FLICKERED = {
    "Button Doorbell": [["v1.00.47", 1790350744.679463], ["v1.00.28", 1790374750.066726], ["v1.00.47", 1790374750.851958]],
    "Button Terrace Dining": [["v1.00.47", 1790350744.679463], ["v1.00.35", 1790374750.094984], ["v1.00.47", 1790374750.866176]],
    "Button Master Shower": [["v1.00.47", 1790350744.679463], ["v1.00.35", 1790374750.122661], ["v1.00.47", 1790374750.147609]],
    "Button James Night Table": [["24.4.5", 1790350744.679463], ["2.3.014", 1790374750.330115], ["24.4.5", 1790374750.391814]],
}


def test_the_four_buttons_go_back_to_one_version_each():
    for name, history in FLICKERED.items():
        record = {DEV_FIRMWARE_HISTORY: [list(pair) for pair in history]}
        assert unflicker_firmware(record), name
        assert record[DEV_FIRMWARE_HISTORY] == [history[0]], name


def test_a_real_update_and_a_real_rollback_are_kept():
    """Guard: only a version replaced within ten minutes by the one
    before it is a flicker."""
    day = 86400.0
    record = {DEV_FIRMWARE_HISTORY: [["1.0", 0.0], ["1.1", day], ["1.0", 5 * day]]}
    assert not unflicker_firmware(record)
    record = {DEV_FIRMWARE_HISTORY: [["1.0", 0.0], ["1.1", day]]}
    assert not unflicker_firmware(record)


def _source(hass):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    return source


def _panel(hass, source, version):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "panel")},
        name="Panel", manufacturer="Sonoff", model="NSPanel Pro", sw_version=version,
    )
    er.async_get(hass).async_get_or_create("sensor", "test", "panel-t", device_id=device.id, config_entry=source)
    return device


def _history(entry, device):
    return entry.runtime_data.data[DATA_DEVICES][device.id][DEV_FIRMWARE_HISTORY]


async def test_a_flicker_never_reaches_the_history(hass: HomeAssistant):
    source = _source(hass)
    panel = _panel(hass, source, "2.3.0")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    coord._confirm_firmware(now + 3601)
    registry = dr.async_get(hass)
    registry.async_update_device(panel.id, sw_version="1.9.0")
    await hass.async_block_till_done()
    registry.async_update_device(panel.id, sw_version="2.3.0")
    await hass.async_block_till_done()
    coord._confirm_firmware(now + 2 * 86400)
    assert [v for v, _ in _history(entry, panel)] == ["2.3.0"]


async def test_a_version_under_ten_minutes_old_waits(hass: HomeAssistant):
    source = _source(hass)
    panel = _panel(hass, source, "2.3.0")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    first = coord._firmware_candidates[panel.id][1]
    coord._confirm_firmware(first + FIRMWARE_HOLD_SECONDS - 1)
    assert _history(entry, panel) == []
    coord._confirm_firmware(first + FIRMWARE_HOLD_SECONDS)
    history = _history(entry, panel)
    assert history == [["2.3.0", first]], "written with the time it first appeared"


async def test_the_tick_records_it_once_the_grace_has_closed(hass: HomeAssistant, freezer):
    """The record is taken on the minute tick, never inside the grace,
    when the registry may still hold a restart's stale value."""
    source = _source(hass)
    panel = _panel(hass, source, "2.3.0")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    start = dt_util.utcnow()
    grace_left = coord._grace_until - start.timestamp()
    freezer.move_to(start + timedelta(seconds=max(0.0, grace_left - 1)))
    coord._firmware_candidates[panel.id] = ("2.3.0", start.timestamp() - FIRMWARE_HOLD_SECONDS)
    await coord._on_render_tick(None)
    assert _history(entry, panel) == [], "recorded inside the startup grace"
    freezer.move_to(start + timedelta(seconds=grace_left + 1))
    await coord._on_render_tick(None)
    assert [v for v, _ in _history(entry, panel)] == ["2.3.0"]


async def test_a_restart_forgets_every_candidate(hass: HomeAssistant):
    source = _source(hass)
    panel = _panel(hass, source, "2.3.0")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert panel.id in coord._firmware_candidates
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fresh = entry.runtime_data
    assert fresh is not coord
    assert fresh._firmware_candidates[panel.id][1] >= coord._firmware_candidates[panel.id][1]


async def test_a_downgrade_that_holds_is_recorded(hass: HomeAssistant):
    source = _source(hass)
    panel = _panel(hass, source, "3.4.0")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    coord._confirm_firmware(now + 3601)
    dr.async_get(hass).async_update_device(panel.id, sw_version="3.1.0")
    await hass.async_block_till_done()
    coord._confirm_firmware(now + 2 * 86400)
    assert [v for v, _ in _history(entry, panel)] == ["3.4.0", "3.1.0"]


# ---------------------------------------------- restart schedules, 0.23.10

_BASE = datetime(2026, 10, 1)


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    zone = dt_util.get_default_time_zone()
    return dt_util.as_utc(_BASE.replace(tzinfo=zone) + timedelta(days=day, hours=hour, minutes=minute))


async def _a_day_later_update(hass, freezer):
    """A panel recorded at 1.0, updated to 1.1 at 2 PM on day 2."""
    freezer.move_to(_local(1, 12))
    source = _source(hass)
    panel = _panel(hass, source, "1.0")
    entry = await setup_entry(hass)
    freezer.move_to(_local(1, 12) + timedelta(seconds=STARTUP_GRACE_SECONDS + FIRMWARE_HOLD_SECONDS + 5))
    await entry.runtime_data._on_render_tick(None)
    assert [v for v, _ in _history(entry, panel)] == ["1.0"]
    freezer.move_to(_local(2, 14))
    dr.async_get(hass).async_update_device(panel.id, sw_version="1.1")
    await hass.async_block_till_done()
    return entry, panel


async def _ticks(hass, entry, freezer, until: datetime) -> None:
    """The minute ticks from now until a moment, every five minutes."""
    now = dt_util.utcnow()
    while now < until:
        now = min(until, now + timedelta(minutes=5))
        freezer.move_to(now)
        await entry.runtime_data._on_render_tick(None)


async def test_a_house_that_restarts_every_night_at_23_30(hass: HomeAssistant, freezer):
    """0.23.9 held a week of folds and never recorded the update."""
    entry, panel = await _a_day_later_update(hass, freezer)
    await _ticks(hass, entry, freezer, _local(2, 14, 30))
    for day in range(2, 5):
        freezer.move_to(_local(day, 23, 30))
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await _ticks(hass, entry, freezer, _local(day + 1, 0, 30))
    assert [v for v, _ in _history(entry, panel)] == ["1.0", "1.1"]


async def test_a_house_that_reboots_across_midnight(hass: HomeAssistant, freezer):
    """Down at 23:58, back at 00:03, so the fold runs at start (#406).
    0.23.9 held a week of folds and never recorded the update; the
    update is recorded the afternoon it lands."""
    entry, panel = await _a_day_later_update(hass, freezer)
    for day in range(2, 5):
        await _ticks(hass, entry, freezer, _local(day, 23, 55))
        freezer.move_to(_local(day, 23, 58))
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        freezer.move_to(_local(day + 1, 0, 3))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    history = _history(entry, panel)
    assert [v for v, _ in history] == ["1.0", "1.1"]
    assert history[-1][1] == _local(2, 14).timestamp()
