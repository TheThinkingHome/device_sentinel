# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_problem_sensors_and_polling.py, Version: 0.28.3 (2026-11-04)

"""Problem sensors and polled integrations under Extended Diagnostics,
recorded and never judged (rule STACK-14).

From a tester's house: Alarm.com polls a cloud and
updates all its devices at once, its polls stopped twice for hours with
the integration loaded, and each device publishes its health as a
Malfunction sensor that nothing read.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import _studiable
from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    PROBE_DETAIL,
    PROBE_NOW,
    PROBE_SENTINEL,
    PROBE_STACK,
    PROBE_WAS,
    STUDIABLE,
    WATCH_KEY,
)
from custom_components.device_sentinel.study_watch import lockstep

from .helpers import probe_lines, register_fleet, setup_coordinator

CHOICE = STUDIABLE[WATCH_KEY]
NOW = 1_800_000_000.0


async def _alarm_house(hass, count=4, **options):
    source = MockConfigEntry(domain="alarmdotcom", title="Alarm.com")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    fleet = register_fleet(hass, source, count, prefix="sensor")
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [CHOICE], **options})
    return coord, source, fleet


def _malfunction(hass, source, device):
    return er.async_get(hass).async_get_or_create(
        "binary_sensor", "alarmdotcom", f"{device.id}-malfunction",
        device_id=device.id, config_entry=source,
        original_device_class="problem", suggested_object_id=f"{device.name} malfunction",
    ).entity_id


def _in_step(coord, fleet, gap=354.0, heard=NOW):
    records = coord.data[DATA_DEVICES]
    for device, _entity in fleet:
        records[device.id][DEV_DAILY_MAX] = [gap] * 7
        records[device.id][DEV_LAST_ACTIVITY] = heard
    coord._grace_until = 0.0


def test_the_choice_is_offered_on_every_house(hass: HomeAssistant):
    assert CHOICE in _studiable(hass)


def test_lockstep_finds_a_polled_integration_and_nothing_else():
    """Alarm.com's devices share each day's longest gap to the
    millisecond; devices that report on their own scatter."""
    records, watched = {}, {}
    for index in range(15):
        records[f"a{index}"] = {DEV_DAILY_MAX: [455.3, 353.55, 351.74, 581.84, 369.2]}
        watched[f"a{index}"] = "alarmdotcom"
    for index in range(10):
        records[f"s{index}"] = {DEV_DAILY_MAX: [3600.0 * (index + 1), 900.0 + index, 7200.0, 300.0 * index, 50.0]}
        watched[f"s{index}"] = "smartthings"
    records["t0"] = {DEV_DAILY_MAX: [60.0] * 2}
    watched["t0"] = "tuya"
    found = lockstep(records, watched)
    assert found["alarmdotcom"]["lockstep"] is True
    assert found["alarmdotcom"]["in_step"] == 15
    assert found["smartthings"]["lockstep"] is False
    # Too few devices with five days of maxima to measure.
    assert "tuya" not in found


async def test_a_problem_sensor_is_written_when_it_changes(hass: HomeAssistant):
    coord, source, fleet = await _alarm_house(hass, count=1)
    entity_id = _malfunction(hass, source, fleet[0][0])
    hass.states.async_set(entity_id, "off")
    coord.probe_tick(NOW)
    coord.probe_tick(NOW + 60)
    lines = probe_lines(coord, "problem")
    assert [(row[PROBE_STACK], row[PROBE_WAS], row[PROBE_NOW]) for row in lines] == [("alarmdotcom", "", "off")]
    assert lines[0][PROBE_DETAIL] == entity_id
    hass.states.async_set(entity_id, "on")
    coord.probe_tick(NOW + 120)
    assert [(row[PROBE_WAS], row[PROBE_NOW]) for row in probe_lines(coord, "problem")][-1] == ("off", "on")
    sensors = coord.watch_diagnostics(NOW + 120)["problem_sensors"]
    assert [(sensor["entity_id"], sensor["state"]) for sensor in sensors] == [(entity_id, "on")]


async def test_nothing_is_recorded_unless_chosen(hass: HomeAssistant):
    source = MockConfigEntry(domain="alarmdotcom", title="Alarm.com")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    fleet = register_fleet(hass, source, 1, prefix="sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(_malfunction(hass, source, fleet[0][0]), "on")
    coord.probe_tick(NOW)
    coord.probe_fold(NOW)
    assert probe_lines(coord, "problem") == [] and probe_lines(coord, "polling") == []
    assert "problem_sensors_and_polling" not in coord.study_diagnostics


async def test_a_stop_of_a_lockstep_integration_is_written_and_its_return(hass: HomeAssistant):
    """As on the tester's house: the polls stopped for about six hours, the
    integration loaded throughout."""
    coord, _source, fleet = await _alarm_house(hass)
    _in_step(coord, fleet)
    coord.probe_tick(NOW + 60)
    assert probe_lines(coord, "polling") == []
    # Twice the usual longest gap is 708 seconds; nothing heard for 709.
    coord.probe_tick(NOW + 709)
    stopped = probe_lines(coord, "polling")
    assert [(row[PROBE_WAS], row[PROBE_NOW]) for row in stopped] == [("updating", "stopped")]
    assert stopped[0][PROBE_SENTINEL] == "0 of 4 listed"
    assert stopped[0][PROBE_DETAIL].endswith("4 devices")
    coord.probe_tick(NOW + 3600)
    assert len(probe_lines(coord, "polling")) == 1
    for device, _entity in fleet:
        coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = NOW + 6 * 3600
    coord.probe_tick(NOW + 6 * 3600 + 30)
    back = probe_lines(coord, "polling")[-1]
    assert (back[PROBE_WAS], back[PROBE_NOW]) == ("stopped", "updating")
    assert back[PROBE_DETAIL].startswith("stopped 6.0h")
    ended = coord.watch_diagnostics(NOW + 6 * 3600 + 30)["stops_ended"]
    assert [(stop["integration"], stop["seconds"], stop["devices"]) for stop in ended] == [
        ("alarmdotcom", 6 * 3600, 4),
    ]


async def test_no_stop_is_opened_inside_the_startup_grace(hass: HomeAssistant):
    coord, _source, fleet = await _alarm_house(hass)
    _in_step(coord, fleet)
    coord._grace_until = NOW + 7200
    coord.probe_tick(NOW + 3600)
    assert probe_lines(coord, "polling") == []


async def test_the_fold_writes_the_measure_and_the_day_of_problem_sensors(hass: HomeAssistant):
    coord, source, fleet = await _alarm_house(hass)
    _in_step(coord, fleet)
    for index, (device, _entity) in enumerate(fleet):
        hass.states.async_set(_malfunction(hass, source, device), "on" if index == 0 else "off")
    coord.probe_fold(NOW)
    day = [row for row in probe_lines(coord, "problem") if row[PROBE_NOW] == "day"]
    assert [row[PROBE_DETAIL] for row in day] == ["off 3, on 1"]
    measure = probe_lines(coord, "polling")
    assert [(row[PROBE_STACK], row[PROBE_NOW]) for row in measure] == [("alarmdotcom", "lockstep")]
    assert measure[0][PROBE_DETAIL].startswith("4 of 4 devices in step over 5 days")


async def test_taking_the_choice_off_forgets_it(hass: HomeAssistant):
    coord, _source, fleet = await _alarm_house(hass)
    _in_step(coord, fleet)
    coord.probe_tick(NOW + 709)
    assert coord._watch_stops
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_STUDY_HARDWARE: []})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    written = len(probe_lines(coord, "polling"))
    coord.probe_tick(NOW + 800)
    coord.probe_fold(NOW + 900)
    assert not coord._watch_stops and coord._watch_lockstep is None
    assert len(probe_lines(coord, "polling")) == written


async def test_a_failure_here_leaves_the_stacks_their_lines(hass: HomeAssistant, monkeypatch):
    coord, _source, _fleet = await _alarm_house(hass)

    def broken(*_args, **_kwargs):
        raise RuntimeError("registry gone")

    monkeypatch.setattr(coord, "_problem_sensors", broken)
    coord.probe_tick(NOW)
    coord.probe_fold(NOW)
    assert any(key.startswith(WATCH_KEY) for key in coord._probe_failed)


async def test_a_failure_here_still_lets_the_download_arrive(hass: HomeAssistant, monkeypatch):
    from custom_components.device_sentinel import diagnostics

    coord, _source, _fleet = await _alarm_house(hass)

    def broken(*_args, **_kwargs):
        raise RuntimeError("registry gone")

    monkeypatch.setattr(coord, "watch_diagnostics", broken)
    report = await diagnostics.async_get_config_entry_diagnostics(hass, coord.entry)
    found = report["classification"]["study"]["problem_sensors_and_polling"]
    assert found == {"unreadable": "RuntimeError: registry gone"}

