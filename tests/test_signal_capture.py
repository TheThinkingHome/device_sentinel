# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_capture.py, Version: 0.24.0 (2026-10-02)

"""The signal when a device goes unavailable, and the evidence in the download.

Link failures surface as a device going unavailable, not as a freeze
silence, so before 0.24.0 the evidence ruling #172 waits on never
recorded a single one: on 2 October no fleet held a silence that ended
in a link failure. The opening row of an unavailable incident now
carries the device's signal at that moment, and the diagnostics
download carries the signal stress table, so testers' files bring the
evidence with them.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_SIGNAL_STRESS,
    DEV_SIGNAL_VALUE,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_SIGNAL,
    INCIDENT_OPENED,
)
from custom_components.device_sentinel.normalise import check_storage
from tests.helpers import register_device, setup_entry


async def _device(hass: HomeAssistant):
    device, _entities = register_device(hass, "sc0", "Shed Door")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_VALUE] = 61.0
    return entry, coord, device.id


async def test_an_unavailable_opening_carries_the_signal(hass: HomeAssistant):
    _entry, coord, device_id = await _device(hass)
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_UNAVAILABLE, INCIDENT_OPENED)
    row = coord.data[DATA_INCIDENTS][-1]
    assert row[INC_SIGNAL]["value"] == 61.0


async def test_only_unavailable_openings_carry_it(hass: HomeAssistant):
    _entry, coord, device_id = await _device(hass)
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_FROZEN, INCIDENT_OPENED)
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_UNAVAILABLE, "resolved", duration=60.0)
    for row in coord.data[DATA_INCIDENTS][-2:]:
        assert INC_SIGNAL not in row


async def test_a_device_with_no_signal_records_none(hass: HomeAssistant):
    _entry, coord, device_id = await _device(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_VALUE] = None
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_UNAVAILABLE, INCIDENT_OPENED)
    assert coord.data[DATA_INCIDENTS][-1][INC_SIGNAL] is None


async def test_old_and_new_incident_rows_both_pass_the_load_check(hass: HomeAssistant):
    """A new opening row with the signal, a new row without it, and a
    row shaped as every row before 0.24.0: none is a fault."""
    _entry, coord, device_id = await _device(hass)
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_UNAVAILABLE, INCIDENT_OPENED)
    coord._record_incident(device_id, "Shed Door", FREEZE_CATEGORY_FROZEN, INCIDENT_OPENED)
    coord.data[DATA_INCIDENTS].append({
        "device_id": device_id, "name": "Shed Door", "kind": "unavailable",
        "event": "opened", "when": 1_790_000_000.0, "cause": None, "duration": None,
    })
    faults = [f for f in check_storage(coord.data) if f[0].startswith(DATA_INCIDENTS + "[")]
    assert faults == [], faults


async def test_the_download_carries_the_stress_table(hass: HomeAssistant):
    entry, coord, _device_id = await _device(hass)
    coord.data[DATA_SIGNAL_STRESS] = [{
        "device_id": "d", "name": "Shed Door", "since": 1_790_000_000.0,
        "at": 1_790_003_600.0, "ended": "resumed",
        "signal": {"value": 61.0, "mean": 80.0, "sd": 4.0},
    }]
    found = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert found["signal_stress"][0]["signal"]["value"] == 61.0
