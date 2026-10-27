# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_frozen_sentence_times.py, Version: 0.27.10 (2026-10-27)

"""The frozen sentence's quiet and return times, across a longer wait,
midnight and the clock change (rules FRZ-07, UNAV-07).

Accepted rather than tested: a frozen device taken back counts from
when it was watched again, so its sentence's quiet time is that moment
(rule WATCH-08); and an unavailable device's paired sentence opens at
its debounced verdict while its span counts from when it went, so the
recovery reads a few minutes late (rule UNAV-07).
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    TODO_KIND_FROZEN,
)

from .helpers import setup_coordinator


async def test_a_freeze_cleared_by_a_longer_wait_is_not_told_as_a_report(
    hass: HomeAssistant, freezer
):
    from .test_recovery_one_way import _armed_device, _minutes_on

    coord, device, _eid = await _armed_device(hass, freezer, "quiet1")
    await _minutes_on(hass, freezer, 240)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    heard = record[DEV_LAST_ACTIVITY]

    record[DEV_DAILY_MAX] = [12 * 3600.0] * (FREEZE_ARMING_DAYS + 2)
    await _minutes_on(hass, freezer, 1)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_LAST_ACTIVITY] == heard, "precondition: it never reported"
    # Its line leaves a minute after it cleared (rule LIST-06).
    await _minutes_on(hass, freezer, 2)

    rows = [
        r for r in coord.data[DATA_INCIDENTS]
        if r.get(INC_DEVICE_ID) == device.id and r.get(INC_KIND) == TODO_KIND_FROZEN
    ]
    opened = next(r for r in rows if r[INC_EVENT] == INCIDENT_OPENED)
    resolved = next(r for r in rows if r[INC_EVENT] == INCIDENT_RESOLVED)
    sentence = coord._compose_episode(opened, resolved)
    assert "reported again" not in sentence, sentence


async def test_a_freeze_across_the_fall_back_hour_does_not_read_backwards(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CDT
        verdict = datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc).timestamp()  # 1:05 AM CST
        back = datetime(2026, 11, 1, 7, 10, tzinfo=timezone.utc).timestamp()  # 1:10 AM CST
        opened = {
            INC_DEVICE_ID: "d", INC_NAME: "Door Master", INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: INCIDENT_OPENED, INC_WHEN: verdict, INC_CAUSE: None, INC_DURATION: None,
        }
        resolved = dict(opened, **{
            INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: back, INC_DURATION: back - quiet,
        })
        sentence = coord._compose_episode(opened, resolved)
    finally:
        dt_util.set_default_time_zone(before)
    assert "stopped reporting at 1:30 AM and reported again at 1:10 AM" not in sentence, sentence


async def test_a_freeze_across_the_fall_back_hour_names_the_zones(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 6, 10, tzinfo=timezone.utc).timestamp()  # 1:10 AM CDT
        verdict = datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc).timestamp()  # 1:05 AM CST
        back = datetime(2026, 11, 1, 7, 20, tzinfo=timezone.utc).timestamp()  # 1:20 AM CST
        opened = {
            INC_DEVICE_ID: "d", INC_NAME: "Door Master", INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: INCIDENT_OPENED, INC_WHEN: verdict, INC_CAUSE: None, INC_DURATION: None,
        }
        resolved = dict(opened, **{
            INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: back, INC_DURATION: back - quiet,
        })
        sentence = coord._compose_episode(opened, resolved)
    finally:
        dt_util.set_default_time_zone(before)
    assert "at 1:10 AM and recovered at 1:20 AM" not in sentence, sentence
    assert "CDT" in sentence and "CST" in sentence, sentence


async def test_a_freeze_across_midnight_and_the_clock_change_names_the_zones(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc).timestamp()  # 11:00 PM CDT, Oct 31
        verdict = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CDT
        back = datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CST
        opened = {
            INC_DEVICE_ID: "d", INC_NAME: "Door Master", INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: INCIDENT_OPENED, INC_WHEN: verdict, INC_CAUSE: None, INC_DURATION: None,
        }
        resolved = dict(opened, **{
            INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: back, INC_DURATION: back - quiet,
        })
        sentence = coord._compose_episode(opened, resolved)
    finally:
        dt_util.set_default_time_zone(before)
    assert "CDT" in sentence and "CST" in sentence, sentence
