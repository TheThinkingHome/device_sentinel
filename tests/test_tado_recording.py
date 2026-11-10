# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_tado_recording.py, Version: 0.28.10 (2026-11-10)

"""The Tado recording and the problem sensors' attributes, under
Extended Diagnostics (rules STACK-11, STACK-14).

Tado is read from the data Home Assistant's own coordinator holds,
never from tado's cloud. A line at each change of a device's Connection
State, battery or firmware; one at each refresh with its interval,
result and quota; one a day for each device with how often its
connection timestamp moved, which tells whether that timestamp is a
clock each device could be judged by. A problem sensor's attributes are
recorded with its state, so Alarm.com's Trouble says which condition
turned it on.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import _studiable
from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    PROBE_DETAIL,
    PROBE_NOW,
    PROBE_WAS,
    STUDIABLE,
    TADO_KEY,
    WATCH_KEY,
)

from .helpers import probe_lines, register_fleet, setup_coordinator

NOW = 1_800_000_000.0
SERIAL = "VA2150303744"


def _tado(hass: HomeAssistant, connected=True, stamp="2026-11-10T10:00:00Z", left=19000, ok=True):
    entry = MockConfigEntry(domain="tado", title="Home")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("tado", SERIAL)}, name="Radiator Valve",
    )
    entry.runtime_data = SimpleNamespace(
        last_update_success=ok,
        update_interval=timedelta(minutes=5),
        data={
            "device": {SERIAL: {
                "deviceType": "VA02", "batteryState": "NORMAL", "currentFwVersion": "113.1",
                "connectionState": {"value": connected, "timestamp": stamp},
            }},
            "rate_limit": {"granted": 20000, "remaining": left},
        },
    )
    return entry


def _device(entry, **change):
    record = entry.runtime_data.data["device"][SERIAL]
    if "stamp" in change:
        record["connectionState"]["timestamp"] = change["stamp"]
    if "connected" in change:
        record["connectionState"]["value"] = change["connected"]


async def test_tado_is_offered_where_tado_is_installed(hass: HomeAssistant):
    assert STUDIABLE[TADO_KEY] not in _studiable(hass)
    _tado(hass)
    assert STUDIABLE[TADO_KEY] in _studiable(hass)


async def test_a_line_at_each_change_and_a_day_line_for_the_timestamp(hass: HomeAssistant):
    entry = _tado(hass)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[TADO_KEY]]})
    coord._tado_tick(NOW)
    first = probe_lines(coord, node=SERIAL)
    assert len(first) == 1 and first[0][PROBE_NOW].startswith("connected True, battery NORMAL")
    refresh = probe_lines(coord, node="refresh")
    assert refresh and "next every 300 s" in refresh[0][PROBE_NOW] and "19000 of 20000" in refresh[0][PROBE_NOW]
    # The timestamp moves while nothing else does: no new device line.
    _device(entry, stamp="2026-11-10T10:05:00Z")
    coord._tado_tick(NOW + 300)
    _device(entry, stamp="2026-11-10T10:10:00Z")
    coord._tado_tick(NOW + 600)
    assert len(probe_lines(coord, node=SERIAL)) == 1
    # Connection lost: a line.
    _device(entry, connected=False)
    coord._tado_tick(NOW + 900)
    lines = probe_lines(coord, node=SERIAL)
    assert len(lines) == 2 and lines[1][PROBE_NOW].startswith("connected False")
    assert lines[1][PROBE_WAS].startswith("connected True")
    coord._tado_fold(NOW + 1000)
    day = probe_lines(coord, node="day")
    assert day and day[0][PROBE_NOW] == "timestamp moved 2 times"
    download = coord.tado_diagnostics()
    assert download["entries"][0]["devices"][SERIAL]["connected"] is False


async def test_an_entry_with_no_coordinator_is_recorded_and_breaks_nothing(hass: HomeAssistant):
    entry = _tado(hass)
    entry.runtime_data = object()
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[TADO_KEY]]})
    coord._tado_tick(NOW)
    assert probe_lines(coord, node="refresh")[0][PROBE_NOW] == "unreadable"
    assert coord.tado_diagnostics()["entries"][0]["coordinator"] is False


async def test_a_trouble_sensor_records_which_condition_turned_it_on(hass: HomeAssistant):
    source = MockConfigEntry(domain="alarmdotcom", title="Alarm.com")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    fleet = register_fleet(hass, source, 1, prefix="sensor")
    device = fleet[0][0]
    trouble = er.async_get(hass).async_get_or_create(
        "binary_sensor", "alarmdotcom", f"{device.id}-trouble", device_id=device.id,
        config_entry=source, original_device_class="problem", suggested_object_id="porch door trouble",
    ).entity_id
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[WATCH_KEY]]})
    hass.states.async_set(trouble, "off", {"active_count": 0, "trouble_types": [], "friendly_name": "Porch Door Trouble"})
    coord._watch_tick(NOW)
    hass.states.async_set(trouble, "on", {"active_count": 1, "trouble_types": ["SensorNotResponding"], "friendly_name": "Porch Door Trouble"})
    coord._watch_tick(NOW + 60)
    line = [row for row in probe_lines(coord) if trouble in row[PROBE_DETAIL]][-1]
    assert line[PROBE_NOW] == "on" and line[PROBE_WAS] == "off"
    assert "trouble_types=" in line[PROBE_DETAIL] and "SensorNotResponding" in line[PROBE_DETAIL]
    assert "friendly_name" not in line[PROBE_DETAIL]
    # A change of reason while it stays on is a line too.
    hass.states.async_set(trouble, "on", {"active_count": 1, "trouble_types": ["SensorLowBattery"], "friendly_name": "Porch Door Trouble"})
    coord._watch_tick(NOW + 120)
    assert "SensorLowBattery" in [row for row in probe_lines(coord) if trouble in row[PROBE_DETAIL]][-1][PROBE_DETAIL]
    sensors = coord.watch_diagnostics(NOW + 120)["problem_sensors"]
    assert "SensorLowBattery" in next(row for row in sensors if row["entity_id"] == trouble)["attributes"]
