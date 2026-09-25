# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_model_groups.py, Version: 0.23.4 (2026-09-25)

"""Model groups, the backbone (0.23.4).

The owner ruled on 25 September that identical devices are read as
groups, recorded first and used later: a group is maker, model id or
model, and hardware version, with firmware shown inside; a device
that gives no hardware version joins its model's only given version;
firmware history is kept for the History setting's window; muted
devices count and excluded ones are recorded nowhere. Nothing that
judges reads any of it.

The tests that are not guards fail on 0.23.3, which has no firmware
history and no Model Groups section.
"""

from __future__ import annotations

import glob
import json

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_MUTED_DEVICES,
    CONF_RETENTION_DAYS,
    DATA_DEVICES,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_FIRMWARE_HISTORY,
    STATS_EPOCH,
    STORAGE_KEY,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.device_sentinel.model_groups import (
    build_model_groups,
    prune_firmware,
)
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.records import _new_device_record
from custom_components.device_sentinel.report_battery import BatteryReportMixin

from tests.conftest import fleet_param
from .helpers import setup_entry

DAY = 86400.0


def _never(_record) -> bool:
    return False


def _source(hass: HomeAssistant) -> MockConfigEntry:
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    return source


def _device(hass, source, uid: str, **identity):
    """A registry device with one entity of its own and the identity given."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=uid,
        **identity,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


def _history(entry, device) -> list:
    return entry.runtime_data.data[DATA_DEVICES][device.id][DEV_FIRMWARE_HISTORY]


# ------------------------------------------------------ firmware history


def test_a_new_record_starts_with_no_firmware():
    """Guard: the schema carries the field, empty."""
    assert _new_device_record("", None)[DEV_FIRMWARE_HISTORY] == []


async def test_the_firmware_a_device_gives_is_recorded_at_the_start(
    hass: HomeAssistant,
):
    source = _source(hass)
    panel = _device(hass, source, "panel", manufacturer="Sonoff", model="NSPanel Pro", sw_version="2.3.0")
    entry = await setup_entry(hass)
    history = _history(entry, panel)
    assert [version for version, _ in history] == ["2.3.0"]
    assert isinstance(history[0][1], float)


async def test_an_update_is_recorded_once_and_a_repeat_is_not(hass: HomeAssistant):
    source = _source(hass)
    panel = _device(hass, source, "panel", manufacturer="Sonoff", model="NSPanel Pro", sw_version="2.3.0")
    entry = await setup_entry(hass)
    registry = dr.async_get(hass)
    registry.async_update_device(panel.id, sw_version="3.4.0")
    await hass.async_block_till_done()
    registry.async_update_device(panel.id, name_by_user="James's panel")
    await hass.async_block_till_done()
    assert [version for version, _ in _history(entry, panel)] == ["2.3.0", "3.4.0"]


async def test_a_device_that_gives_no_firmware_records_none(hass: HomeAssistant):
    """Guard: an empty version is not a version."""
    source = _source(hass)
    door = _device(hass, source, "door", manufacturer="Aqara", model="Door and window sensor")
    entry = await setup_entry(hass)
    assert _history(entry, door) == []


def test_the_history_keeps_the_window_and_always_the_current_version():
    now = 1_790_000_000.0
    record = {
        DEV_FIRMWARE_HISTORY: [
            ["1.0", now - 200 * DAY],
            ["1.1", now - 120 * DAY],
            ["1.2", now - 10 * DAY],
        ]
    }
    # 1.0 was replaced 120 days ago, before a 90-day window opened;
    # 1.1 was current until 10 days ago, inside it.
    assert prune_firmware(record, now, 90)
    assert [v for v, _ in record[DEV_FIRMWARE_HISTORY]] == ["1.1", "1.2"]
    lone = {DEV_FIRMWARE_HISTORY: [["1.0", now - 400 * DAY]]}
    assert not prune_firmware(lone, now, 30)
    assert [v for v, _ in lone[DEV_FIRMWARE_HISTORY]] == ["1.0"]


async def test_the_fold_prunes_by_the_history_setting(hass: HomeAssistant):
    source = _source(hass)
    panel = _device(hass, source, "panel", manufacturer="Sonoff", model="NSPanel Pro", sw_version="3.4.0")
    entry = await setup_entry(hass, {CONF_RETENTION_DAYS: 30})
    now = dt_util.utcnow().timestamp()
    record = entry.runtime_data.data[DATA_DEVICES][panel.id]
    record[DEV_FIRMWARE_HISTORY] = [["2.3.0", now - 90 * DAY], ["3.4.0", now - 40 * DAY]]
    await entry.runtime_data._on_midnight(None)
    assert [v for v, _ in record[DEV_FIRMWARE_HISTORY]] == ["3.4.0"]


async def test_a_record_stored_before_the_field_is_filled_and_noted(
    hass: HomeAssistant, hass_storage
):
    """End to end through the real load: a record written by 0.23.3
    carries no firmware history, and the first start of 0.23.4 fills
    the field and records the version the registry gives."""
    source = _source(hass)
    panel = _device(hass, source, "panel", manufacturer="Sonoff", model="NSPanel Pro", sw_version="3.4.0")
    stored = _new_device_record("2026-07-01T00:00:00+00:00", 1000.0)
    del stored[DEV_FIRMWARE_HISTORY]
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {panel.id: stored},
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: 1000.0,
        },
    }
    entry = await setup_entry(hass)
    assert [v for v, _ in _history(entry, panel)] == ["3.4.0"]


def test_the_shape_check_refuses_a_damaged_history():
    """Guard: the field is checked like every other."""
    good = _new_device_record("", None)
    good[DEV_FIRMWARE_HISTORY] = [["1.0", 1000.0]]
    assert not [f for f in check_records({"a": good}) if f[1] == DEV_FIRMWARE_HISTORY]
    for damage in ("1.0", [["", 1.0]], [["1.0"]], [["1.0", "yesterday"]]):
        bad = _new_device_record("", None)
        bad[DEV_FIRMWARE_HISTORY] = damage
        assert [f for f in check_records({"a": bad}) if f[1] == DEV_FIRMWARE_HISTORY], damage


# ------------------------------------------------------ the section


def _identity(maker, model, hardware=None, firmware=None, model_id=None):
    return {
        "maker": maker,
        "model": model,
        "model_id": model_id,
        "hardware": hardware,
        "firmware": firmware,
    }


def _group(section, model):
    return next(group for group in section["groups"] if group["model"] == model)


def test_a_missing_hardware_version_joins_the_only_one_given():
    identities = {
        "a": _identity("Aqara", "Door", "2", "3000-0001"),
        "b": _identity("Aqara", "Door", "2", "3000-0001"),
        "c": _identity("Aqara", "Door", None, None),
    }
    section = build_model_groups({}, identities, {}, set(), BatteryReportMixin._battery_slope, _never)
    door = _group(section, "Door")
    assert door["size"] == 3
    assert door["hardware"] == "2"
    assert door["firmware"] == {"3000-0001": 2, "not given": 1}


def test_two_hardware_versions_are_two_groups():
    identities = {
        "a": _identity("athom", "sw01", "1.0"),
        "b": _identity("athom", "sw01", "1.0"),
        "c": _identity("athom", "sw01", "1.1"),
        "d": _identity("athom", "sw01", "1.1"),
        "e": _identity("athom", "sw01", None),
        "f": _identity("athom", "sw01", None),
    }
    section = build_model_groups({}, identities, {}, set(), BatteryReportMixin._battery_slope, _never)
    assert sorted(group["hardware"] for group in section["groups"]) == ["1.0", "1.1", "not given"]


def test_the_model_id_keys_the_group_ahead_of_the_display_name():
    identities = {
        "a": _identity("Aqara", "Door and window sensor", model_id="MCCGQ11LM"),
        "b": _identity("Aqara", "Door and window sensor", model_id="MCCGQ11LM"),
        "c": _identity("Aqara", "Door and window sensor", model_id="MCCGQ14LM"),
    }
    section = build_model_groups({}, identities, {}, set(), BatteryReportMixin._battery_slope, _never)
    assert [group["model"] for group in section["groups"]] == ["MCCGQ11LM"]
    assert section["groups"][0]["model_name"] == "Door and window sensor"
    assert section["alone"] == 1


def test_every_watched_device_is_accounted_for_once():
    identities = {
        "a": _identity("Sonoff", "NSPanel Pro", firmware="2.3.0"),
        "b": _identity("Sonoff", "NSPanel Pro", firmware="3.4.0"),
        "c": _identity("IKEA", "Remote"),
        "d": _identity(None, None),
    }
    section = build_model_groups({}, identities, {}, {"a"}, BatteryReportMixin._battery_slope, _never)
    assert (section["grouped"], section["alone"], section["unidentified"]) == (2, 1, 1)
    panel = _group(section, "NSPanel Pro")
    assert panel["firmware"] == {"2.3.0": 1, "3.4.0": 1}
    assert [device["muted"] for device in panel["devices"]] == [True, False]


def test_each_cell_is_read_against_its_group():
    flat = [100.0] * 30
    records = {
        "a": {DEV_BATTERY_VALUE: 90.0, DEV_BATTERY_DAILY: [90.0 + i * -0.1 for i in range(30)]},
        "b": {DEV_BATTERY_VALUE: 90.0, DEV_BATTERY_DAILY: [90.0 + i * -0.1 for i in range(30)]},
        "c": {DEV_BATTERY_VALUE: 70.0, DEV_BATTERY_DAILY: [90.0 + i * -0.5 for i in range(30)]},
        "d": {DEV_BATTERY_VALUE: 100.0, DEV_BATTERY_DAILY: flat},
    }
    identities = {key: _identity("Third Reality", "Door sensor", "1", "1.00.69") for key in records}
    section = build_model_groups(records, identities, {}, set(), BatteryReportMixin._battery_slope, _never)
    battery = _group(section, "Door sensor")["battery"]
    rows = {row["device_id"]: row for row in battery["devices"]}
    assert battery["median_rate"] == -0.1
    assert rows["c"]["from_median"] == -0.4
    assert rows["d"]["never_moved"] is True
    assert _group(section, "Door sensor")["quirks"]["battery_never_moved"] == 1


async def test_the_diagnostics_carry_the_section_and_each_model_id(hass: HomeAssistant):
    source = _source(hass)
    james = _device(hass, source, "james", manufacturer="Sonoff", model="NSPanel Pro", model_id="NSPanel-Pro", sw_version="2.3.0")
    randy = _device(hass, source, "randy", manufacturer="Sonoff", model="NSPanel Pro", model_id="NSPanel-Pro", sw_version="3.4.0")
    entry = await setup_entry(hass, {CONF_MUTED_DEVICES: [randy.id]})
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["devices"][james.id]["model_id"] == "NSPanel-Pro"
    section = diagnostics["model_groups"]
    panel = _group(section, "NSPanel-Pro")
    assert panel["firmware"] == {"2.3.0": 1, "3.4.0": 1}
    assert {device["device_id"]: device["muted"] for device in panel["devices"]} == {
        james.id: False,
        randy.id: True,
    }
    json.dumps(section)


# ------------------------------------------------------ the three houses


def _fleet_inputs(path):
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    records = loaded.get("data", loaded)["devices"]
    diagnostics = glob.glob(str(path.parent / "config_entry*.json"))[0]
    with open(diagnostics, encoding="utf-8") as handle:
        described = json.load(handle)["data"]["devices"]
    identities = {}
    names = {}
    for device_id, record in records.items():
        entry = described.get(device_id)
        if not isinstance(entry, dict) or record.get("set_aside_since") is not None:
            continue
        identities[device_id] = _identity(
            entry.get("manufacturer"),
            entry.get("model"),
            entry.get("hw_version"),
            entry.get("sw_version"),
            entry.get("model_id"),
        )
        names[device_id] = entry.get("name")
    return records, identities, names


@pytest.mark.parametrize(
    "path",
    [
        fleet_param("reference", "device_sentinel.storage", id="reference"),
        fleet_param("second", "device_sentinel_storage.json", id="second"),
        fleet_param("fourth", "device_sentinel_storage.json", id="fourth"),
    ],
)
def test_the_section_on_each_house(path):
    """Every watched device counted once, and the section a readable
    size on the largest house."""
    records, identities, names = _fleet_inputs(path)
    section = build_model_groups(records, identities, names, set(), BatteryReportMixin._battery_slope, _never)
    assert section["grouped"] + section["alone"] + section["unidentified"] == len(identities)
    seen = [device["device_id"] for group in section["groups"] for device in group["devices"]]
    assert len(seen) == len(set(seen))
    size = len(json.dumps(section))
    assert size < 150_000, size
    print(f"\n{path.parent.name}: {len(section['groups'])} groups, {section['grouped']} grouped, {size} bytes")
