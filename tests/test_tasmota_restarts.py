# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_tasmota_restarts.py, Version: 0.28.5 (2026-11-08)

"""Why and when a Tasmota device last restarted (rule DEV-17).

Tasmota sends its Restart Reason and Last Restart Time once, each time the
device connects. Device Sentinel records each restart with its reason, keeps
the newest ten, shows the newest in the device page's Reporting group with
the earlier ones folded under it, and lists them in Device Telemetry. It
explains a gap and never decides one.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_RESTARTS,
    RESTARTS_KEPT,
)
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.status_readings import (
    RESTART_REASON,
    RESTART_TIME,
    record_restart,
    restart_moment,
    restart_sensor,
)

from .helpers import setup_coordinator
from .outage_helpers import PIN

NOW = 1_794_000_000.0
MAC = "A4CF12345678"


class _Ent:
    def __init__(self, entity_id, unique_id, platform="tasmota"):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.platform = platform


def test_the_two_sensors_are_found_by_their_unique_ids():
    # Named anything at all: the unique id says which it is.
    assert restart_sensor(_Ent("sensor.mini_switch_restart_reason", f"{MAC}_sensor_status_sensor_status_restart_reason")) == RESTART_REASON
    assert restart_sensor(_Ent("sensor.tasmota_last_restart_time_3", f"{MAC}_sensor_status_sensor_last_restart_time")) == RESTART_TIME
    assert restart_sensor(_Ent("sensor.x", f"{MAC}_sensor_status_sensor_status_signal")) is None
    assert restart_sensor(_Ent("sensor.x", f"{MAC}_sensor_status_sensor_status_restart_reason", platform="esphome")) is None


def test_a_restart_time_is_read_from_the_sensor():
    assert restart_moment("2026-11-07T08:02:00+00:00") == 1_794_038_520.0
    for nothing in ("unknown", "unavailable", "", None, "not a time"):
        assert restart_moment(nothing) is None
    # A device whose clock was never set restarts in 1970: no reading.
    assert restart_moment("1970-01-01T00:00:12+00:00") is None


def test_one_restart_read_twice_is_recorded_once():
    record: dict = {}
    assert record_restart(record, "Power On", NOW)
    # Worked out from the uptime again, the time moves by a second or two;
    # the record follows it and stays one restart.
    record_restart(record, "Power On", NOW + 2)
    assert not record_restart(record, "Power On", NOW + 2)
    assert record_restart(record, "Software/System restart", NOW + 3600)
    assert record[DEV_RESTARTS] == [["Power On", NOW + 2], ["Software/System restart", NOW + 3600]]


def test_a_reason_arriving_after_its_time_corrects_that_restart():
    record: dict = {DEV_RESTARTS: [["Power On", NOW]]}
    assert record_restart(record, "Hardware Watchdog", NOW + 1)
    assert record[DEV_RESTARTS] == [["Hardware Watchdog", NOW + 1]]


def test_a_time_drifting_a_little_at_each_reading_stays_one_restart():
    record: dict = {}
    for drift in range(0, 600, 90):
        record_restart(record, "Power On", NOW + drift)
    assert record[DEV_RESTARTS] == [["Power On", NOW + 540]]


def test_nothing_is_recorded_without_both_readings():
    record: dict = {}
    assert not record_restart(record, None, NOW)
    assert not record_restart(record, "unavailable", NOW)
    assert not record_restart(record, "Power On", None)
    assert record.get(DEV_RESTARTS) in (None, [])


def test_the_newest_ten_are_kept():
    record: dict = {}
    for i in range(RESTARTS_KEPT + 3):
        record_restart(record, "Power On", NOW + i * 3600)
    assert len(record[DEV_RESTARTS]) == RESTARTS_KEPT
    assert record[DEV_RESTARTS][0][1] == NOW + 3 * 3600


def _tasmota(hass):
    source = MockConfigEntry(domain="tasmota")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "a4:cf:12:34:56:78")},
        name="w26 Porch light",
    )
    reg = er.async_get(hass)
    ids = {}
    ids["light"] = reg.async_get_or_create(
        "light", "tasmota", f"{MAC}_light_relay_0", device_id=device.id, config_entry=source,
    ).entity_id
    ids["reason"] = reg.async_get_or_create(
        "sensor", "tasmota", f"{MAC}_sensor_status_sensor_status_restart_reason",
        device_id=device.id, config_entry=source, suggested_object_id="mini_switch_restart_reason",
    ).entity_id
    ids["time"] = reg.async_get_or_create(
        "sensor", "tasmota", f"{MAC}_sensor_status_sensor_last_restart_time",
        device_id=device.id, config_entry=source, suggested_object_id="mini_switch_last_restart_time",
    ).entity_id
    return device, ids


async def test_each_restart_reaches_the_page_and_telemetry(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, ids = _tasmota(hass)
    hass.states.async_set(ids["light"], "on")
    hass.states.async_set(ids["reason"], "Power On")
    hass.states.async_set(ids["time"], "2026-11-07T08:02:00+00:00")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_RESTARTS] == [["Power On", 1_794_038_520.0]]

    # It restarts after a crash: the time changes first, then the reason.
    freezer.tick(3600)
    hass.states.async_set(ids["time"], "2026-11-08T09:00:01+00:00")
    await hass.async_block_till_done()
    hass.states.async_set(ids["reason"], "Exception")
    await hass.async_block_till_done()
    assert record[DEV_RESTARTS] == [
        ["Power On", 1_794_038_520.0],
        ["Exception", 1_794_128_401.0],
    ]

    page = coord.dashboard_device(device.id)
    restarts = page["identity"]["restarts"]
    assert [r["value"] for r in restarts] == ["Exception", "Power On"]
    assert restarts[0]["at"].startswith("2026-11-08T09:00:01")

    lines = coord._status_reading_lines()
    row = next(line for line in lines if line.startswith("| w26 Porch light"))
    assert "| Restart |" in row and row.index("Exception") < row.index("Power On")
    # Recorded and shown, never judged.
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not check_records({device.id: record})


async def test_a_restart_of_home_assistant_adds_nothing(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, ids = _tasmota(hass)
    hass.states.async_set(ids["light"], "on")
    hass.states.async_set(ids["reason"], "Power On")
    hass.states.async_set(ids["time"], "2026-11-07T08:02:00+00:00")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    # The same values handed back, and the time worked out a second later.
    hass.states.async_set(ids["time"], "2026-11-07T08:02:01+00:00")
    await hass.async_block_till_done()
    coord._note_status_reading(ids["reason"])
    assert record[DEV_RESTARTS] == [["Power On", 1_794_038_521.0]]
