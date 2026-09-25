# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_window.py, Version: 0.23.5 (2026-09-25)

"""Which window the brief covers, and where it is written.

Since 0.23.5 the brief is one file, daily_brief.html in the reports
folder. The dated copies that held each closed day retired with the
www folder (#470): the closed day is the one returned to the sender
and emailed, and the file then carries the day just beginning.

One of the files split out of test_email_brief.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""


import glob
import os

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CONF_REMINDER_TIME,
    DATA_INCIDENTS,
    INCIDENT_OPENED,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    TODO_KIND_FROZEN,
)

from tests.helpers import register_device, setup_coordinator

DOMAIN = "device_sentinel"

def _brief_path(hass):
    return hass.config.path("device_sentinel", "daily_brief.html")


def _briefs(hass):
    return sorted(glob.glob(hass.config.path("device_sentinel", "daily_brief*")))


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def test_the_closed_window_is_the_one_that_just_ended(
    hass: HomeAssistant,
):
    """It finishes the day behind it rather than the one starting, so
    the completed brief covers brief hour to brief hour."""
    coord = await setup_coordinator(hass)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0
    hour, minute = coord._brief_hour_minute()
    for edge in (start, end):
        local = dt_util.as_local(dt_util.utc_from_timestamp(edge))
        assert (local.hour, local.minute) == (hour, minute)
    assert end <= dt_util.utcnow().timestamp()


async def test_the_schedule_follows_the_configured_time(
    hass: HomeAssistant,
):
    """The brief time is a live option, so changing it re-arms."""
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "06:30:00"})
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
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "not a time"})
    assert coord._brief_hour_minute() == (8, 0)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0


async def test_the_scheduled_write_survives_a_day_boundary(
    hass: HomeAssistant, freezer
):
    """Whatever the clock says when the callback lands, the window it
    closes is the one that ended at the configured hour."""
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})
    freezer.tick(timedelta(seconds=2))
    start, end = coord._brief_close_bounds()
    local_end = dt_util.as_local(dt_util.utc_from_timestamp(end))
    assert (local_end.hour, local_end.minute) == (7, 0)
    assert end - start == 86400.0


async def test_the_live_brief_covers_a_rolling_day(
    hass: HomeAssistant, freezer,
):
    """Ruling #187, found on the live fleet on 2026-08-03.

    The live file's window ran from the brief hour to now. Read at 11 AM that was four hours,
    so the card said two events had happened while a full day of
    twelve had passed. The live copy carries a rolling day.

    An incident from yesterday afternoon is the test: outside the
    brief-hour window, inside the rolling one.
    """
    # The clock is pinned. As first written this test placed the
    # incident an hour before the brief hour and asserted it was
    # inside a rolling day, which is only true while the brief hour
    # is recent: run late enough in the day the brief hour is nearly
    # twenty-four hours back and an hour before it is outside the
    # window. It passed at build time and failed hours later on
    # nothing but the wall clock (ruling #198).
    freezer.move_to("2026-08-04T12:00:00-05:00")
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "rw1", "Rolling Device")
    now = dt_util.utcnow().timestamp()
    brief_start = coord._brief_window_start(now)
    # Comfortably before the brief hour, comfortably inside a day.
    when = brief_start - 3600.0
    assert now - brief_start < 82800.0, "the pin must leave room"
    assert now - when < 86400.0
    coord.data[DATA_INCIDENTS] = [
        {
            INC_WHEN: when,
            INC_DEVICE_ID: device.id,
            INC_NAME: "Rolling Device",
            INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: INCIDENT_OPENED,
        }
    ]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _text(_brief_path(hass))
    assert "Rolling Device" in page
    assert "(in progress)" in page


async def test_the_span_is_counted_and_not_asserted(
    hass: HomeAssistant, freezer,
):
    """Ruling #206. The window is anchored to the wall clock so a
    seven o'clock brief covers seven to seven, which across a
    daylight saving change is 23 or 25 real hours rather than 24.

    Reproduced on a New York clock before the fix: the March window
    measures 23.0 hours and the November one 25.0, and the page said
    24 for both. Anchoring to the epoch instead would hold the number
    and move the brief hour, which is the thing a person notices.
    """
    await hass.config.async_update(time_zone="America/New_York")
    coord = await setup_coordinator(hass)

    for when, expected in (
        ("2026-07-15T12:00:00+00:00", 24),
        ("2026-03-08T12:00:00+00:00", 23),
        ("2026-11-01T13:00:00+00:00", 25),
    ):
        freezer.move_to(when)
        start, end = coord._brief_close_bounds()
        assert round((end - start) / 3600.0) == expected, when
        text = coord._write_brief(
            hass.config.path("www", "device_sentinel"),
            BRIEF_TRIGGER,
            start,
            end,
            complete=True,
        )
        assert f"Covering the {expected} hours since" in text


async def test_the_roll_emails_the_closed_day_and_opens_today(
    hass: HomeAssistant, freezer
):
    """The 7 AM roll closes yesterday and opens today (#116, 0.9.9).

    The closed day is what the writer returns, and what is emailed;
    the file then holds today's in-progress brief, so it is never
    left describing a window that has ended.
    """
    await hass.config.async_set_time_zone("America/Guayaquil")  # UTC-5
    freezer.move_to("2026-07-26T12:00:01+00:00")  # 07:00:01 local
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})

    closed = await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)

    assert closed is not None
    assert "Covering the 24 hours since" in closed
    assert "(in progress)" not in closed
    assert "(in progress)" in _text(_brief_path(hass))


async def test_every_write_lands_on_the_one_file(hass: HomeAssistant):
    """Manual writes and a closing write leave one file, never a
    dated copy beside it (0.23.5)."""
    coord = await setup_coordinator(hass)
    for trigger in ("test", BRIEF_TRIGGER, "manual"):
        await hass.async_add_executor_job(coord._write_reports, trigger)
    assert [os.path.basename(path) for path in _briefs(hass)] == ["daily_brief.html"]


async def test_a_manual_write_stays_in_progress(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    returned = await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _text(_brief_path(hass))
    # One marker, not two: the line used to open "In progress" and
    # close "(incomplete)", saying the same thing twice (0.8.10).
    assert "(in progress)" in text
    assert "In progress" not in text
    # And an in-progress brief is never handed to the sender (#135).
    assert returned is None
