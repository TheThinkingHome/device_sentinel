# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_house_tables_trim.py, Version: 0.27.8 (2026-10-27)

"""The house events and signal stress rows are held to the history length
at the midnight run only (rule STOR-14): a lower setting saved by mistake
cuts nothing until then, so it can be taken back."""

from __future__ import annotations

import copy

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_RETENTION_DAYS,
    DATA_SIGNAL_STRESS,
    DATA_SYSTEM_EVENTS,
    SYS_WHEN,
)

from .helpers import setup_entry

DAY = 86400.0


def _details(coord) -> list:
    return [r.get("detail") for r in coord.data[DATA_SYSTEM_EVENTS] if isinstance(r, dict)]


def _stress(name: str, since: float) -> dict:
    return {"device_id": "d", "name": name, "since": since, "at": since + 600,
            "ended": "recovered", "signal": None}


async def _house_with_old_rows(hass):
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 90})
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    coord._record_system_event("storage_repair", detail="today")
    old = copy.deepcopy(coord.data[DATA_SYSTEM_EVENTS][-1])
    old[SYS_WHEN] = now - 60 * DAY
    old["detail"] = "sixty days old"
    coord.data[DATA_SYSTEM_EVENTS].insert(0, old)
    coord.data[DATA_SIGNAL_STRESS] = [
        _stress("old stress", now - 60 * DAY),
        _stress("new stress", now - DAY),
    ]
    return entry, coord, now


async def test_a_lower_setting_cuts_nothing_before_midnight(hass: HomeAssistant):
    entry, coord, _now = await _house_with_old_rows(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_RETENTION_DAYS: 30})
    await hass.async_block_till_done()
    await coord.async_options_updated()
    coord._record_system_event("storage_repair", detail="another")
    assert "sixty days old" in _details(coord)
    assert len(coord.data[DATA_SIGNAL_STRESS]) == 2


async def test_taken_back_before_midnight_nothing_is_lost(hass: HomeAssistant):
    entry, coord, now = await _house_with_old_rows(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_RETENTION_DAYS: 30})
    await hass.async_block_till_done()
    await coord.async_options_updated()
    hass.config_entries.async_update_entry(entry, options={CONF_RETENTION_DAYS: 90})
    await hass.async_block_till_done()
    await coord.async_options_updated()
    coord._trim_house_tables(now)
    assert "sixty days old" in _details(coord)
    assert len(coord.data[DATA_SIGNAL_STRESS]) == 2


async def test_the_midnight_run_cuts_to_the_setting(hass: HomeAssistant):
    entry, coord, now = await _house_with_old_rows(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_RETENTION_DAYS: 30})
    await hass.async_block_till_done()
    await coord.async_options_updated()
    await coord._on_midnight(dt_util.utcnow())
    await hass.async_block_till_done()
    details = _details(coord)
    assert "sixty days old" not in details
    assert "today" in details
    assert [r["name"] for r in coord.data[DATA_SIGNAL_STRESS]] == ["new stress"]


async def test_a_damaged_row_is_left_for_the_repair(hass: HomeAssistant):
    _entry, coord, now = await _house_with_old_rows(hass)
    coord.data[DATA_SYSTEM_EVENTS].insert(0, {SYS_WHEN: "junk", "detail": "damaged"})
    coord.data[DATA_SIGNAL_STRESS].insert(0, "junk")
    coord._trim_house_tables(now + 61 * DAY)
    assert "damaged" in _details(coord)
    assert "junk" in coord.data[DATA_SIGNAL_STRESS]


async def test_nothing_to_cut_marks_nothing(hass: HomeAssistant):
    _entry, coord, now = await _house_with_old_rows(hass)
    coord._trim_house_tables(now)          # the 90 days keep all
    coord._cold_dirty = False
    coord._trim_house_tables(now)
    assert coord._cold_dirty is False
