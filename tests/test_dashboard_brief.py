# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_brief.py, Version: 0.22.19 (2026-09-21)

"""The Daily Brief tab, and stepping back through the days.

The tab is the brief as a page, by calendar day: midnight to midnight
for a day that has finished, midnight to now for today. It reads the
same records the written brief reads and renders each line with the
brief's own phrasing, so the two cannot describe the same event in two
ways. A past day's standing problems are rebuilt from the incidents,
which are kept fourteen days, and that is how far back the tab goes.
"""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    SYS_KIND,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_WHEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_UNAVAILABLE,
)

from tests.helpers import register_device, setup_coordinator


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _noon(days_ago: int) -> float:
    """Local noon, so a test never lands on a day boundary."""
    day = dt_util.now().date() - timedelta(days=days_ago)
    return dt_util.as_utc(
        dt_util.start_of_local_day(day) + timedelta(hours=12)
    ).timestamp()


async def _house(hass: HomeAssistant):
    soil, _ = register_device(hass, "soil", name="Soil Irrigation (Monstera)")
    plug, _ = register_device(hass, "plug", name="Plug Living Room Router")
    coord = await setup_coordinator(hass)
    coord.data[DATA_INCIDENTS] = [
        # Opened five days ago and never closed: standing on every day since.
        {INC_DEVICE_ID: soil.id, INC_NAME: "Soil Irrigation (Monstera)",
         INC_KIND: TODO_KIND_LOW_BATTERY, INC_EVENT: INCIDENT_OPENED, INC_WHEN: _noon(5)},
        # Opened and closed three days ago.
        {INC_DEVICE_ID: plug.id, INC_NAME: "Plug Living Room Router",
         INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED, INC_WHEN: _noon(3) - 3600},
        {INC_DEVICE_ID: plug.id, INC_NAME: "Plug Living Room Router",
         INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_RESOLVED,
         INC_WHEN: _noon(3), INC_DURATION: 3600.0},
    ]
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_WHEN: _noon(3) + 60, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system", "duration": 31.0},
        {SYS_WHEN: _noon(20), SYS_KIND: SYS_RESTART, SYS_SCOPE: "system", "duration": 31.0},
    ]
    return coord, soil, plug


async def test_today_runs_from_midnight_to_now(hass: HomeAssistant, hass_ws_client):
    coord, soil, _ = await _house(hass)
    coord.data[DATA_TODO_ITEMS] = [{
        "uid": "u1", "device_id": soil.id,
        "summary": "Soil Irrigation (Monstera): battery 0%", "description": "",
        "status": "needs_action", "acked_at": None,
        "sort_name": "Soil Irrigation (Monstera)", "kinds": {TODO_KIND_LOW_BATTERY: _noon(5)},
    }]
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/brief")
    assert reply["success"], reply
    page = reply["result"]
    assert page["is_today"] is True
    assert page["day"] == dt_util.now().date().isoformat()
    assert page["forward"] is None, "no day after today"
    assert page["now"][0]["name"] == "Soil Irrigation (Monstera)"
    assert page["now"][0]["problem"] == "battery 0%"
    assert page["now"][0]["acknowledged"] is False
    assert page["events"] == [], "nothing happened today in this house"
    assert page["counts"] == {"events": 0, "opened": 0, "resolved": 0}


async def test_a_past_day_rebuilds_what_stood_that_night(hass: HomeAssistant, hass_ws_client):
    coord, soil, plug = await _house(hass)
    day = (dt_util.now().date() - timedelta(days=3)).isoformat()
    client = await hass_ws_client(hass)
    page = (await _call(client, type="device_sentinel/brief", day=day))["result"]
    assert page["is_today"] is False
    assert page["day"] == day
    assert page["forward"] == (dt_util.now().date() - timedelta(days=2)).isoformat()
    assert page["back"] == (dt_util.now().date() - timedelta(days=4)).isoformat()
    # The battery problem was standing that night; the plug had recovered.
    assert [row["name"] for row in page["now"]] == ["Soil Irrigation (Monstera)"]
    # Both of the plug's rows and the restart fall in that day.
    what = [f"{row['who']}: {row['what']}" for row in page["events"]]
    assert any("Plug Living Room Router" in line and "recovered after" in line for line in what)
    assert any(line.startswith("The system: system restarted") for line in what)
    assert page["counts"] == {"events": 3, "opened": 1, "resolved": 1}


async def test_the_walk_back_stops_where_the_records_do(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    page = (await _call(client, type="device_sentinel/brief"))["result"]
    earliest = (dt_util.now().date() - timedelta(days=13)).isoformat()
    assert page["earliest"] == earliest
    oldest = (await _call(client, type="device_sentinel/brief", day=earliest))["result"]
    assert oldest["back"] is None, "nothing older is kept"


async def test_repeat_offenders_only_where_seven_days_are_held(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    near = (await _call(client, type="device_sentinel/brief"))["result"]
    assert near["repeat"]["available"] is True
    far_day = (dt_util.now().date() - timedelta(days=10)).isoformat()
    far = (await _call(client, type="device_sentinel/brief", day=far_day))["result"]
    assert far["repeat"]["available"] is False
    assert "seven days" in far["repeat"]["words"]


async def test_a_day_that_is_not_kept_is_refused(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    long_ago = (dt_util.now().date() - timedelta(days=40)).isoformat()
    reply = await _call(client, type="device_sentinel/brief", day=long_ago)
    assert reply["error"]["code"] == "not_found"
    assert (await _call(client, type="device_sentinel/brief", day="not-a-day"))["error"]["code"] in (
        "not_found", "invalid_format"
    )


async def test_it_is_admin_only(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await _house(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _call(client, type="device_sentinel/brief"))["error"]["code"] == "unauthorized"


# ==================================================================
# A day ends at the next local midnight, not 24 hours after the last.
# ==================================================================

async def test_a_day_ends_at_the_next_midnight_across_a_clock_change(
    hass: HomeAssistant,
):
    """The tab ended a finished day at midnight plus 24 hours. On the
    25-hour day the clocks go back, 1 November in the second and fourth
    fleets' time zone, that lost the last hour; on the 23-hour day they
    go forward, 8 March, it repeated the next day's first hour."""
    await hass.config.async_set_time_zone("America/Chicago")
    coord = await setup_coordinator(hass)
    for day, hours in (
        (date(2026, 11, 1), 25),
        (date(2026, 3, 8), 23),
        (date(2026, 9, 20), 24),
    ):
        start, end, is_today = coord._brief_day_bounds(day)
        next_midnight = dt_util.as_utc(
            dt_util.start_of_local_day(day + timedelta(days=1))
        ).timestamp()
        assert is_today is False
        assert end == next_midnight, day
        assert end - start == hours * 3600, day


async def test_the_last_hour_of_a_long_day_is_shown_once(
    hass: HomeAssistant, freezer
):
    """An event at 11:30 PM on 1 November belongs to 1 November, and an
    event at the stroke of midnight belongs to the day it opens."""
    await hass.config.async_set_time_zone("America/Chicago")
    freezer.move_to("2026-11-03T18:00:00+00:00")
    plug, _ = register_device(hass, "plug", name="Plug Living Room Router")
    coord = await setup_coordinator(hass)
    # 24.5 hours of elapsed time after the day began, which on this
    # 25-hour day is 11:30 PM by the clock.
    late = (
        dt_util.as_utc(dt_util.start_of_local_day(date(2026, 11, 1)))
        + timedelta(hours=24, minutes=30)
    ).timestamp()
    assert dt_util.as_local(dt_util.utc_from_timestamp(late)).hour == 23
    midnight = dt_util.as_utc(
        dt_util.start_of_local_day(date(2026, 11, 2))
    ).timestamp()
    coord.data[DATA_INCIDENTS] = [
        {INC_DEVICE_ID: plug.id, INC_NAME: "Plug Living Room Router",
         INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED, INC_WHEN: late},
        {INC_DEVICE_ID: plug.id, INC_NAME: "Plug Living Room Router",
         INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_RESOLVED,
         INC_WHEN: midnight, INC_DURATION: midnight - late},
    ]
    first = coord.dashboard_brief(date(2026, 11, 1))
    second = coord.dashboard_brief(date(2026, 11, 2))
    assert first["counts"]["opened"] == 1
    assert first["counts"]["resolved"] == 0
    assert second["counts"]["opened"] == 0
    assert second["counts"]["resolved"] == 1
