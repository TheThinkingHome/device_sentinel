# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_window.py, Version: 0.11.8 (2026-08-04)

"""Which window the brief covers, and what it is named.

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

def _briefs(hass):
    return sorted(
        glob.glob(hass.config.path("www", "device_sentinel", "daily_brief_2*.html"))
    )


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def test_scheduled_roll_opens_todays_in_progress_brief(
    hass: HomeAssistant, freezer
):
    """The 7 AM roll closes yesterday and opens today (#116, 0.9.9).

    Before this, the scheduled write completed the day that ended and
    left the day just beginning with no file until the next startup,
    so from the roll onward the file named for today was absent and
    the outside witness reported the brief missing. The roll now
    writes today's in-progress brief too, so both files exist."""
    from custom_components.device_sentinel.const import (
        BRIEF_TRIGGER,
        CONF_REMINDER_TIME,
    )

    # A moment just after the 7 AM brief hour, so the closing window is
    # yesterday and the newly opened window is today. Pin the zone so
    # the dates do not depend on the test default: 12:00:01Z is
    # 07:00:01 local at UTC-5, just past the 07:00 brief hour.
    await hass.config.async_set_time_zone("America/Guayaquil")  # UTC-5
    freezer.move_to("2026-07-26T12:00:01+00:00")  # 07:00:01 local
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})

    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)

    written = sorted(
        glob.glob(hass.config.path("www", "device_sentinel", "daily_brief_2*.html"))
    )
    names = [p.rsplit("/", 1)[-1] for p in written]
    assert "daily_brief_2026-07-25.html" in names, names  # closed day
    assert "daily_brief_2026-07-26.html" in names, names  # opened day

    with open(
        hass.config.path("www", "device_sentinel", "daily_brief_2026-07-25.html"),
        encoding="utf-8",
    ) as handle:
        completed = handle.read()
    with open(
        hass.config.path("www", "device_sentinel", "daily_brief_2026-07-26.html"),
        encoding="utf-8",
    ) as handle:
        today = handle.read()

    assert "Covering the 24 hours" in completed  # the closed brief
    assert "(in progress)" in today              # today's open brief


async def test_one_window_writes_one_file(hass: HomeAssistant):
    """Naming by the moment of writing renamed the in-progress brief
    at midnight, so a single window left two overlapping files."""
    coord = await setup_coordinator(hass)
    for _ in range(3):
        await hass.async_add_executor_job(coord._write_reports, "test")
    written = glob.glob(
        hass.config.path("www", "device_sentinel", "daily_brief_2*.html")
    )
    assert len(written) == 1


async def test_the_file_is_named_for_the_window_start(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    start = coord._brief_window_start(dt_util.utcnow().timestamp())
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    written = glob.glob(
        hass.config.path("www", "device_sentinel", "daily_brief_2*.html")
    )
    assert os.path.basename(written[0]) == expected


async def test_a_scheduled_write_completes_the_brief(
    hass: HomeAssistant,
):
    """The fault: nothing ever passed the closing trigger, so every
    brief said "in progress" forever."""
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    closed = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    text = _text(
        hass.config.path("www", "device_sentinel", closed)
    )
    assert "(in progress)" not in text
    assert "Covering the 24 hours since" in text


async def test_a_manual_write_stays_in_progress(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _text(_briefs(hass)[0])
    # One marker, not two: the line used to open "In progress" and
    # close "(incomplete)", saying the same thing twice (0.8.10).
    assert "(in progress)" in text
    assert "In progress" not in text


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


async def test_the_completed_brief_is_named_for_the_day_it_covers(
    hass: HomeAssistant,
):
    """A completed brief and the window that follows it must not
    collide, which is what produced two files for one window."""
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    assert os.path.basename(_briefs(hass)[0]) == expected

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert len(_briefs(hass)) == 2      # yesterday closed, today open


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

    The undated file is the dashboard's address, and its window ran
    from the brief hour to now. Read at 11 AM that was four hours,
    so the card said two events had happened while a full day of
    twelve sat in yesterday's dated file. The live copy now carries
    a rolling day.

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
    page = _text(
        hass.config.path("www", "device_sentinel", "daily_brief.html")
    )
    assert "Rolling Device" in page
    assert "(in progress)" in page


async def test_the_live_brief_never_lands_on_a_closed_record(
    hass: HomeAssistant,
):
    """The hazard the rolling window creates, closed by ruling #187.

    The dated file is named from the window start. Left alone, a
    rolling window starting yesterday would name the live copy for
    yesterday and overwrite the closed record with an unfinished
    document. The naming day is passed separately, so the live copy
    is still named for the brief day.
    """
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    now = dt_util.utcnow().timestamp()
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(coord._brief_window_start(now))
    ).strftime("daily_brief_%Y-%m-%d.html")
    directory = hass.config.path("www", "device_sentinel")
    assert os.path.isfile(os.path.join(directory, expected))
    # Yesterday's name belongs to yesterday's closed brief and must
    # not have been written by this live copy.
    yesterday = dt_util.as_local(
        dt_util.utc_from_timestamp(now - 86400.0)
    ).strftime("daily_brief_%Y-%m-%d.html")
    if yesterday != expected:
        assert not os.path.isfile(os.path.join(directory, yesterday))


async def test_the_closed_brief_still_runs_brief_to_brief(
    hass: HomeAssistant,
):
    """Ruling #116 is untouched: the record is the closed window.

    The rolling day is the live copy's job alone, so a closing write
    still says it covers the 24 hours since the brief hour and is
    named for the day that window opened.
    """
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    closed = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    text = _text(hass.config.path("www", "device_sentinel", closed))
    assert "Covering the 24 hours since" in text
    assert "(in progress)" not in text


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
