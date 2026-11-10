# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_problem_start_dates.py, Version: 0.28.10 (2026-11-10)

"""One start date for each problem, on every surface (rules LIST-10,
DASH-02).

Built from the reference rig's Soil Irrigation (Monstera): unavailable
for seven weeks, its battery at 0% for over fifteen. The incident log
reopened the unavailable problem at a restart and at a bridge outage,
so the last opening it holds is a week ago, and it keeps 14 days, so it
holds no battery opening at all. The Problem List item held both
problems without a break and has their true starts.

- The Problem List row, "unavailable, battery 0%", is dated from the
  problem it names first, the unavailable one, not the older battery.
- An earlier day of the Daily Brief tab dates the unavailable problem
  from when the device went and still lists the battery problem.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_UNAVAILABLE,
)
from tests.helpers import register_device, setup_coordinator

NAME = "Soil Irrigation (Monstera)"


def _noon(days_ago: int) -> float:
    day = dt_util.now().date() - timedelta(days=days_ago)
    return dt_util.as_utc(dt_util.start_of_local_day(day) + timedelta(hours=12)).timestamp()


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def _house(hass: HomeAssistant):
    soil, _ = register_device(hass, "soil", name=NAME)
    coord = await setup_coordinator(hass)
    went, battery = _noon(50), _noon(110)
    # The incident log as it stood: an unavailable opening, closed when
    # the bridge went down, and opened again when it came back.
    coord.data[DATA_INCIDENTS] = [
        {INC_DEVICE_ID: soil.id, INC_NAME: NAME, INC_KIND: TODO_KIND_UNAVAILABLE,
         INC_EVENT: INCIDENT_OPENED, INC_WHEN: _noon(12)},
        {INC_DEVICE_ID: soil.id, INC_NAME: NAME, INC_KIND: TODO_KIND_UNAVAILABLE,
         INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: _noon(7) - 14400, "duration": 400000.0},
        {INC_DEVICE_ID: soil.id, INC_NAME: NAME, INC_KIND: TODO_KIND_UNAVAILABLE,
         INC_EVENT: INCIDENT_OPENED, INC_WHEN: _noon(7)},
    ]
    coord.data[DATA_TODO_ITEMS] = [{
        "uid": "u1", "device_id": soil.id,
        "summary": f"{NAME}: unavailable, battery 0%", "description": "",
        "status": "completed", "acked_at": None, "sort_name": NAME,
        "kinds": {TODO_KIND_UNAVAILABLE: went, TODO_KIND_LOW_BATTERY: battery},
    }]
    return coord, went, battery


async def test_a_row_is_dated_from_the_problem_it_names_first(hass: HomeAssistant, hass_ws_client):
    _coord, went, _battery = await _house(hass)
    client = await hass_ws_client(hass)
    rows = (await _call(client, type="device_sentinel/problem_list"))["result"]["rows"]
    assert rows[0]["problem"] == "unavailable, battery 0%"
    assert rows[0]["since"] == dt_util.utc_from_timestamp(went).isoformat()


async def test_an_earlier_day_keeps_each_problems_own_start(hass: HomeAssistant, hass_ws_client):
    _coord, went, battery = await _house(hass)
    client = await hass_ws_client(hass)
    day = (dt_util.now().date() - timedelta(days=2)).isoformat()
    page = (await _call(client, type="device_sentinel/brief", day=day))["result"]
    starts = {row["problem"].split()[0]: row["since"] for row in page["now"] if row["name"] == NAME}
    # The unavailable problem from when the device went, not its last
    # reopening; the battery problem listed, though its opening has
    # left the incident log.
    assert dt_util.utc_from_timestamp(went).isoformat() in starts.values(), page["now"]
    assert dt_util.utc_from_timestamp(battery).isoformat() in starts.values(), page["now"]
    assert len([row for row in page["now"] if row["name"] == NAME]) == 2


async def test_a_problem_the_list_no_longer_holds_keeps_the_logs_date(hass: HomeAssistant, hass_ws_client):
    """A problem that has since ended has no item to read from, and its
    earlier day reads as the incident log has it."""
    coord, _went, _battery = await _house(hass)
    coord.data[DATA_TODO_ITEMS] = []
    client = await hass_ws_client(hass)
    day = (dt_util.now().date() - timedelta(days=2)).isoformat()
    page = (await _call(client, type="device_sentinel/brief", day=day))["result"]
    rows = [row for row in page["now"] if row["name"] == NAME]
    assert len(rows) == 1
    assert rows[0]["since"] == dt_util.utc_from_timestamp(_noon(7)).isoformat()


async def test_an_outages_row_is_not_an_earlier_days_device(hass: HomeAssistant, hass_ws_client):
    coord, _went, _battery = await _house(hass)
    coord.data[DATA_TODO_ITEMS].append({
        "uid": "u2", "device_id": "upstream:z2m", "summary": "Zigbee2MQTT down", "description": "",
        "status": "needs_action", "acked_at": None, "sort_name": "Zigbee2MQTT",
        "kinds": {"upstream": _noon(20)},
    })
    client = await hass_ws_client(hass)
    day = (dt_util.now().date() - timedelta(days=2)).isoformat()
    page = (await _call(client, type="device_sentinel/brief", day=day))["result"]
    assert all(not str(row.get("device_id") or "").startswith("upstream:") for row in page["now"])
