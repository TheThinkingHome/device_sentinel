# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v076_brief_close.py, Version: 0.7.6 (2026-07-23)

"""0.7.6 tests: finishing the day, and not overclaiming a recovery.

Ruling 116 specified a write at the brief hour that closes the
window. No caller ever made one, so every brief ever written said it
was in progress and no window was finished before its file was
replaced. And a recovery with no lever we happened to see was being
reported as a recovery with no lever at all, which a rebind by hand
disproved on the morning of 2026-07-23.
"""

import glob
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CONF_REMINDER_TIME,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    RECOVERY_CAUSE_UNOBSERVED,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _briefs(hass):
    return sorted(
        glob.glob(hass.config.path("device_sentinel", "daily_brief_*.md"))
    )


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ----------------------------------------------- closing the window

async def test_a_scheduled_write_completes_the_brief(
    hass: HomeAssistant,
):
    """The fault: nothing ever passed the closing trigger, so every
    brief said "in progress" forever."""
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    closed = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    text = _text(hass.config.path("device_sentinel", closed))
    assert "(incomplete)" not in text
    assert "In progress" not in text
    assert "Covering the 24 hours since" in text


async def test_a_manual_write_stays_in_progress(hass: HomeAssistant):
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _text(_briefs(hass)[0])
    assert "(incomplete)" in text


async def test_the_closed_window_is_the_one_that_just_ended(
    hass: HomeAssistant,
):
    """It finishes the day behind it rather than the one starting, so
    the completed brief covers brief hour to brief hour."""
    coord = await _coordinator(hass)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0
    hour, minute = coord._brief_hour_minute()
    for edge in (start, end):
        local = dt_util.as_local(dt_util.utc_from_timestamp(edge))
        assert (local.hour, local.minute) == (hour, minute)
    assert end <= dt_util.utcnow().timestamp()


async def test_the_completed_brief_is_named_for_the_day_it_covers(
    hass: HomeAssistant,
):
    """A completed brief and the window that follows it must not
    collide, which is what produced two files for one window."""
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    assert os.path.basename(_briefs(hass)[0]) == expected

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert len(_briefs(hass)) == 2      # yesterday closed, today open


async def test_the_schedule_follows_the_configured_time(
    hass: HomeAssistant,
):
    """The brief time is a live option, so changing it re-arms."""
    coord = await _coordinator(hass, {CONF_REMINDER_TIME: "06:30:00"})
    assert coord._brief_hour_minute() == (6, 30)
    assert coord._brief_unsub is not None

    first = coord._brief_unsub
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_REMINDER_TIME: "21:15:00"}
    )
    await coord.async_options_updated()
    assert coord._brief_hour_minute() == (21, 15)
    assert coord._brief_unsub is not first


async def test_a_nonsense_time_falls_back_rather_than_raising(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass, {CONF_REMINDER_TIME: "not a time"})
    assert coord._brief_hour_minute() == (8, 0)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0


# -------------------------------------------- not overclaiming

async def test_an_unobserved_recovery_says_so_plainly(
    hass: HomeAssistant,
):
    """A rebind by hand read as "on its own" in a live brief. We can
    say we saw no intervention; we cannot say there was none."""
    coord = await _coordinator(hass)
    row = {
        INC_DEVICE_ID: "d",
        INC_NAME: "Door Master",
        INC_KIND: "frozen",
        INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_CAUSE: RECOVERY_CAUSE_UNOBSERVED,
        INC_DURATION: 4.3 * 3600,
    }
    text = coord._compose_event(row)
    assert "no intervention recorded" in text
    assert "on its own" not in text
    assert "revived by" not in text


async def test_a_known_lever_is_still_credited(hass: HomeAssistant):
    coord = await _coordinator(hass)
    row = {
        INC_DEVICE_ID: "d",
        INC_NAME: "Door Master",
        INC_KIND: "frozen",
        INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_CAUSE: "bridge reconnect",
        INC_DURATION: 7200.0,
    }
    assert "revived by a bridge reconnect" in coord._compose_event(row)


async def test_the_scheduled_write_survives_a_day_boundary(
    hass: HomeAssistant, freezer
):
    """Whatever the clock says when the callback lands, the window it
    closes is the one that ended at the configured hour."""
    coord = await _coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})
    freezer.tick(timedelta(seconds=2))
    start, end = coord._brief_close_bounds()
    local_end = dt_util.as_local(dt_util.utc_from_timestamp(end))
    assert (local_end.hour, local_end.minute) == (7, 0)
    assert end - start == 86400.0
