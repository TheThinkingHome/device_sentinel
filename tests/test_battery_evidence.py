# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_evidence.py, Version: 0.27.1 (2026-10-23)

"""Each battery device's day kept for a better forecast later (#737).

James, 23 October 2026: "anything we can do so that in the future, we
can build it more accurate." The voltage moves while a lithium cell's
percentage holds at 100; the device's own temperature and its count of
messages are kept beside it. Nothing reads them yet.
"""

from __future__ import annotations

import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_BATTERY_EVIDENCE,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
)
from custom_components.device_sentinel.history_file import SERIES_FIELDS
from custom_components.device_sentinel.normalise import check_records

from .helpers import registry_settled, setup_coordinator


def _sensor(hass, source, device, key: str, device_class: str, value: str, unit: str, attrs=None) -> str:
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", key, device_id=device.id, config_entry=source,
        original_device_class=device_class, suggested_object_id=key,
    )
    hass.states.async_set(entry.entity_id, value, {"device_class": device_class, "unit_of_measurement": unit, **(attrs or {})})
    return entry.entity_id


async def _device(hass: HomeAssistant, uid: str, readings: dict):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=uid,
    )
    _sensor(hass, source, device, f"{uid}_battery", "battery", "80", "%", readings.get("battery_attrs"))
    for key, reading in readings.items():
        if key != "battery_attrs":
            _sensor(hass, source, device, f"{uid}_{key}", *reading)
    return device


async def test_a_day_keeps_volts_degrees_and_events(hass: HomeAssistant):
    coin = await _device(hass, "coin", {"voltage": ("voltage", "2950", "mV"), "temperature": ("temperature", "70.7", "°F")})
    zha = await _device(hass, "zha", {"battery_attrs": {"battery_voltage": 2.8}})
    plug = await _device(hass, "plug", {"voltage": ("voltage", "231.5", "V")})
    quiet = await _device(hass, "quiet", {"voltage": ("voltage", "3.0", "V")})
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    now = time.time()
    for device, heard in ((coin, now), (zha, now), (plug, now), (quiet, now - 3 * 86400)):
        record = coord.data["devices"][device.id]
        record[DEV_LAST_ACTIVITY] = heard
        record[DEV_EVENT_COUNT] = 400
    today = dt_util.now().date()
    coord.battery_evidence_fold(today)
    coord.battery_evidence_fold(today)
    rows = {d.name: coord.data["devices"][d.id].get(DEV_BATTERY_EVIDENCE) for d in (coin, zha, plug, quiet)}
    assert rows["coin"] == [[today.isoformat(), 2.95, 21.5, 400]]
    # ZHA's battery_voltage on the battery sensor.
    assert rows["zha"] == [[today.isoformat(), 2.8, None, 400]]
    # A mains reading is not a battery's.
    assert rows["plug"] == [[today.isoformat(), None, None, 400]]
    # A device not heard that day measured nothing.
    assert rows["quiet"] == []
    for device in (coin, zha, plug):
        assert check_records({device.id: coord.data["devices"][device.id]}) == []


def test_the_view_gives_the_days_messages():
    from custom_components.device_sentinel.battery_evidence import BatteryEvidenceMixin

    view = BatteryEvidenceMixin.battery_evidence_view
    record = {DEV_BATTERY_EVIDENCE: [["2026-10-21", 2.95, 21.0, 300], ["2026-10-22", 2.94, 20.5, 482]]}
    assert view(None, record) == {"day": "2026-10-22", "volts": 2.94, "temperature": 20.5, "messages": 182, "days": 2}
    # A day missed between: no count is made up.
    record[DEV_BATTERY_EVIDENCE][0][0] = "2026-10-19"
    assert view(None, record)["messages"] is None
    assert view(None, {DEV_BATTERY_EVIDENCE: []}) is None


def test_the_rows_split_with_the_series_and_damage_is_found():
    assert DEV_BATTERY_EVIDENCE in SERIES_FIELDS
    good = ["2026-10-22", 2.95, 21.0, 400]
    for bad in (good[:3], ["22 Oct", 2.95, 21.0, 400], ["2026-10-22", "2.95", 21.0, 400],
                ["2026-10-22", 2.95, 400.0, 400], ["2026-10-22", 2.95, 21.0, -1], ["2026-10-22", 2.95, 21.0, True]):
        faults = check_records({"d": {DEV_BATTERY_EVIDENCE: [good, bad]}})
        assert any(field == DEV_BATTERY_EVIDENCE for _, field, _ in faults), bad
