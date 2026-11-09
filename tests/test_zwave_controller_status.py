# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_zwave_controller_status.py, Version: 0.28.6 (2026-11-08)

"""A Z-Wave controller's own Status, recorded and shown (rule STACK-15).

Z-Wave JS gives the controller a Status sensor reading ready, unresponsive
or jammed. Device Sentinel records each change with its time, keeps the
newest twenty, shows the newest on the controller's page and in Device
Telemetry, and judges nothing from it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_zwave
from custom_components.device_sentinel.const import (
    CONTROLLER_STATUS_KEPT,
    DATA_DEVICES,
    DEV_CONTROLLER_STATUS,
    DEV_FROZEN_CATEGORY,
)
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.status_readings import record_controller_status

from .helpers import setup_coordinator
from .outage_helpers import PIN

NOW = 1_794_000_000.0


class _Ent:
    def __init__(self, entity_id, unique_id, platform="zwave_js"):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.platform = platform


def test_the_status_sensor_is_found_by_its_unique_id():
    assert stack_zwave.is_controller_status(_Ent("sensor.my_stick", "4191921521.1.controller_status"))
    assert not stack_zwave.is_controller_status(_Ent("sensor.my_stick", "4191921521.1.node_status"))
    assert not stack_zwave.is_controller_status(_Ent("sensor.x", "1.1.controller_status", platform="zha"))
    assert not stack_zwave.is_controller_status(_Ent("button.x", "1.1.controller_status"))


def test_only_a_real_status_is_a_reading():
    assert stack_zwave.controller_status("jammed") == "jammed"
    for nothing in ("unknown", "unavailable", "", None, "alive"):
        assert stack_zwave.controller_status(nothing) is None


def test_a_change_is_recorded_and_a_repeat_is_not():
    record: dict = {}
    assert record_controller_status(record, "ready", NOW)
    assert not record_controller_status(record, "ready", NOW + 60)
    assert record_controller_status(record, "jammed", NOW + 120)
    assert not record_controller_status(record, None, NOW + 180)
    assert record[DEV_CONTROLLER_STATUS] == [["ready", NOW], ["jammed", NOW + 120]]


def test_the_newest_twenty_are_kept():
    record: dict = {}
    for i in range(CONTROLLER_STATUS_KEPT + 5):
        record_controller_status(record, "ready" if i % 2 else "jammed", NOW + i)
    pairs = record[DEV_CONTROLLER_STATUS]
    assert len(pairs) == CONTROLLER_STATUS_KEPT
    assert pairs[-1][1] == NOW + CONTROLLER_STATUS_KEPT + 4


def test_a_moment_outside_the_record_range_is_not_kept():
    record: dict = {}
    assert not record_controller_status(record, "ready", 10.0)
    assert record.get(DEV_CONTROLLER_STATUS) in (None, [])


def _stick(hass):
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", "4191921521-1")},
        name="Z-Stick Gen5+",
    )
    reg = er.async_get(hass)
    signal = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.1.statistics_rssi",
        device_id=device.id, config_entry=source,
    ).entity_id
    status = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.1.controller_status",
        device_id=device.id, config_entry=source, suggested_object_id="usb_controller_status",
    ).entity_id
    return device, signal, status


async def test_the_controller_page_shows_each_change(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, signal, status = _stick(hass)
    hass.states.async_set(signal, "-40")
    hass.states.async_set(status, "ready")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    # Read at the walk, whatever was there before Device Sentinel started:
    # dated when first read, and said so, since when it began is not known.
    assert [pair[0] for pair in record[DEV_CONTROLLER_STATUS]] == ["ready"]
    assert coord.dashboard_device(device.id)["identity"]["controller_status"]["first"] is True

    freezer.tick(300)
    hass.states.async_set(status, "jammed")
    await hass.async_block_till_done()
    # The sensor not answering is not a status.
    hass.states.async_set(status, "unavailable")
    await hass.async_block_till_done()
    assert [pair[0] for pair in record[DEV_CONTROLLER_STATUS]] == ["ready", "jammed"]

    page = coord.dashboard_device(device.id)
    assert page["identity"]["controller_status"]["value"] == "jammed"
    # A change seen happening is dated when it began.
    assert page["identity"]["controller_status"]["first"] is False
    assert page["identity"]["controller_status"]["since"].startswith("20")
    # Recorded and shown, never judged.
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not check_records({device.id: record})


async def test_telemetry_lists_the_controller(hass: HomeAssistant, freezer, tmp_path):
    freezer.move_to(PIN)
    device, signal, status = _stick(hass)
    hass.states.async_set(signal, "-40")
    hass.states.async_set(status, "unresponsive")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    lines = coord._status_reading_lines()
    assert "## Controller Status and Restarts" in lines
    row = next(line for line in lines if line.startswith("| Z-Stick Gen5+"))
    assert "| Controller status |" in row and "unresponsive" in row
