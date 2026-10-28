# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_entity_defaults.py, Version: 0.27.10 (2026-10-27)

"""Which entities a first install presents, and what removal leaves
(rules CFG-08, CFG-09, STOR-24).

Enabled means a person reads it daily or acts on it in their first
week. The table below is that rule as an assertion, so flipping a
default edits this file rather than slipping by. The broker sensor is
the one conditional: enabled where a stack was detected, off where the
house has none (rule UP-02).

Removing the integration removes its four storage files, every backup
beside them, and every file it wrote in the reports folder and the old
www folder, so an uninstall leaves nothing for a person to find later.
Only its own: a file another tool keeps in the reports folder stays,
and so does the folder that holds it.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR

from custom_components.device_sentinel.const import (
    DOMAIN,
    REPORT_DIR,
    REPORT_WWW_DIR,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from tests.helpers import setup_entry

# The rule as data: entity object id -> enabled by default. Every
# sensor and button the integration creates on a bridge-less test
# house appears here exactly once (rule CFG-08).
EXPECTED_DEFAULTS = {
    # Read daily or acted on in the first week: on.
    "sensor.device_sentinel_status": True,
    "sensor.device_sentinel_devices_watched": True,
    "sensor.device_sentinel_devices_learned": True,
    "sensor.device_sentinel_maintenance_ends": True,
    # The Data sensors: on, because the question they answer (how much
    # history stands behind a verdict) is otherwise answerable only by
    # downloading diagnostics. Diagnostic category, so they sit under
    # the device page's own heading rather than on the dashboard.
    "todo.device_sentinel_problem_list": True,
    "button.device_sentinel_regenerate_reports": True,
    "button.device_sentinel_maintenance_mode": True,
    # Dashboard-builder detail: off, the problem list carries what is
    # wrong and the brief carries the day.
    "sensor.device_sentinel_signal_rails": False,
    "sensor.device_sentinel_signal_weak": False,
    "sensor.device_sentinel_battery_low": False,
    "sensor.device_sentinel_battery_falling": False,
    "sensor.device_sentinel_device_frozen": False,
    "sensor.device_sentinel_devices_set_aside": False,
    # The conditional: this test house has no stack, so the
    # broker sensor ships off. The other branch has its own test.
    "sensor.device_sentinel_broker_mqtt": False,
}


async def test_every_entity_default_matches_the_table(
    hass: HomeAssistant, entity_registry
):
    """The whole table, so a flip is always a decision (rule CFG-08)."""
    await setup_entry(hass)
    ours = {
        entry.entity_id: entry.disabled_by is None
        for entry in entity_registry.entities.values()
        if entry.platform == "device_sentinel"
    }
    assert ours == EXPECTED_DEFAULTS


async def test_removal_deletes_everything_written(hass: HomeAssistant):
    """Removal leaves nothing: storage, backups, reports, and a leftover
    www folder all go, and files belonging to anything else are
    untouched (rule STOR-24)."""
    entry = await setup_entry(hass)

    storage = Path(hass.config.path(STORAGE_DIR))
    storage.mkdir(parents=True, exist_ok=True)
    mine = [
        storage / STORAGE_KEY,
        storage / STORAGE_CLOCKS_KEY,
        storage / f"{STORAGE_KEY}.prephase-c",
        storage / f"{STORAGE_CLOCKS_KEY}.epoch-2",
    ]
    for path in mine:
        path.write_text("{}")
    report_dir = Path(hass.config.path(REPORT_DIR))
    www_dir = Path(hass.config.path(REPORT_WWW_DIR))
    _write_own_reports(hass, report_dir)
    www_dir.mkdir(parents=True, exist_ok=True)
    (www_dir / "sample.md").write_text("sample")
    bystander = storage / "other_integration.storage"
    bystander.write_text("{}")

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    for path in mine:
        assert not path.exists(), path
    assert not report_dir.exists()
    assert not www_dir.exists()
    assert bystander.exists()


def _write_own_reports(hass, report_dir):
    """Every file Device Sentinel writes in its reports folder."""
    from custom_components.device_sentinel.const import TRIM_BACKUP_DIR

    report_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "device_telemetry.md", "classification.md", "silence_episodes.md",
        "daily_brief.html", "stack_probe.md", "stack_probe.md.1",
        "stack_probe.md.3", "classification.md.tmp", "rhythm_shadow.md",
    ):
        (report_dir / name).write_text("mine")
    trims = Path(hass.config.path(TRIM_BACKUP_DIR))
    trims.mkdir(parents=True, exist_ok=True)
    (trims / "device_sentinel_2026-10-01.storage.json").write_text("{}")


async def test_removal_leaves_what_another_tool_keeps_there(hass: HomeAssistant):
    """A reports folder that holds another tool's files beside Device
    Sentinel's: removal takes Device Sentinel's and leaves the others,
    and the folder that holds them (rule STOR-24)."""
    entry = await setup_entry(hass)
    report_dir = Path(hass.config.path(REPORT_DIR))
    _write_own_reports(hass, report_dir)
    theirs = [report_dir / "mesh_probe_report.txt", report_dir / "mesh_probe_record" / "record-2026-10-21.jsonl"]
    for path in theirs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("theirs")

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert sorted(p.name for p in report_dir.iterdir()) == ["mesh_probe_record", "mesh_probe_report.txt"]
    for path in theirs:
        assert path.read_text() == "theirs"


async def test_the_broker_sensor_ships_enabled_where_a_bridge_lives(
    hass: HomeAssistant, entity_registry
):
    """The conditional's other branch: a house whose registry shows a
    Zigbee2MQTT bridge gets the broker sensor on, and the bridge sensor
    arrives enabled with it (rule CFG-08)."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "bridge1")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "bridge1_0",
        device_id=device.id, config_entry=source,
    )
    await setup_entry(hass)

    broker = entity_registry.async_get(
        "sensor.device_sentinel_broker_mqtt"
    )
    assert broker is not None
    assert broker.disabled_by is None
    bridge = entity_registry.async_get(
        "sensor.device_sentinel_bridge_zigbee2mqtt"
    )
    assert bridge is not None
    assert bridge.disabled_by is None


async def test_the_count_sensors_split_found_from_watched(
    hass: HomeAssistant,
):
    """Counts of what was found are primary, counts of what is watched
    are diagnostic (rule CFG-09).

    Frozen Devices, Low Batteries, Falling Batteries, Signal Weak and
    Signal Rails are findings about the house, like a stopped broker,
    and a person who enables one puts it on a dashboard, which leaves
    diagnostic entities out. Classification, the three tracked totals,
    Devices: Watched and Devices: Learned describe the integration's
    own bookkeeping and stay diagnostic, named in the Category: State
    pattern every other sensor follows (rule CFG-06).
    """
    from homeassistant.const import EntityCategory
    entry = await setup_entry(hass)
    reg = er.async_get(hass)
    found = ("frozen_devices", "low_batteries", "falling_batteries",
             "signal_weak", "signal_rails")
    watched = ("classification", "coverage", "learning_progress")
    for key in found:
        eid = reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        )
        assert reg.async_get(eid).entity_category is None, key
    for key in watched:
        eid = reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        )
        assert (
            reg.async_get(eid).entity_category == EntityCategory.DIAGNOSTIC
        ), key


# Bulky and fixed attributes stay live and leave the recorder (rule GEN-05).


def test_lists_and_setting_mirrors_are_kept_out_of_history():
    from custom_components.device_sentinel import sensor as s

    expected = {
        s.DeviceSentinelClassificationSensor: {"by_integration"},
        s.DeviceSentinelSignalRailsSensor: {"devices"},
        s.DeviceSentinelSignalWeakSensor: {"devices", "drop_lqi", "drop_rssi", "sensitivity"},
        s.DeviceSentinelLowBatteriesSensor: {"devices", "clear_margin", "low_threshold"},
        s.DeviceSentinelFallingBatteriesSensor: {"devices", "days_till_empty"},
        s.DeviceSentinelFrozenDevicesSensor: {"devices"},
    }
    for cls, keys in expected.items():
        assert cls._unrecorded_attributes == frozenset(keys), cls.__name__
    # The small counts keep their history.
    assert not getattr(s.DeviceSentinelCoverageSensor, "_unrecorded_attributes", frozenset())


async def test_an_unrecorded_list_is_still_live(hass):
    from .helpers import setup_entry

    # The listing sensors are off by default (rule CFG-08); a person who
    # enables one for an automation reads its list from the state.
    entry = await setup_entry(hass)
    reg = er.async_get(hass)
    frozen = next(
        e for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        if e.unique_id.endswith("frozen_devices")
    )
    reg.async_update_entity(frozen.entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "devices" in hass.states.get(frozen.entity_id).attributes


# Every entity's name lives in strings.json, as Home Assistant's entity
# translations expect; the ids do not change (rule CFG-06).


def test_every_translation_key_has_its_name():
    import json

    from custom_components.device_sentinel import sensor
    from custom_components.device_sentinel.const import BRIDGE_TRANSLATION_KEYS

    root = Path(sensor.__file__).parent
    strings = json.loads((root / "strings.json").read_text())["entity"]
    english = json.loads((root / "translations" / "en.json").read_text())["entity"]
    assert strings == english
    source = (root / "sensor.py").read_text() + (root / "todo.py").read_text()
    import re

    keys = set(re.findall(r'_attr_translation_key = "([a-z_]+)"', source))
    keys |= set(BRIDGE_TRANSLATION_KEYS.values())
    named = set(strings["sensor"]) | set(strings["todo"])
    assert keys <= named, keys - named
    assert set(re.findall(r'key="([a-z_]+)"', (root / "button.py").read_text())) == set(strings["button"])
    assert strings["sensor"]["bridge_zigbee2mqtt"]["name"] == "Bridge: Zigbee2MQTT"
    assert strings["sensor"]["bridge_zha"]["name"] == "Bridge: ZHA"
    # No entity is named in code.
    for platform in ("sensor.py", "button.py", "todo.py"):
        assert not re.search(r'_attr_name = "', (root / platform).read_text()), platform


async def test_a_bridge_sensor_takes_its_translated_name(hass):
    from custom_components.device_sentinel.const import STACK_Z2M, STACK_ZHA
    from custom_components.device_sentinel.sensor import DeviceSentinelBridgeSensor

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    for stack, key in ((STACK_Z2M, "bridge_zigbee2mqtt"), (STACK_ZHA, "bridge_zha")):
        sensor = DeviceSentinelBridgeSensor(coord, stack)
        assert sensor.translation_key == key
    other = DeviceSentinelBridgeSensor(coord, "zwave_js")
    assert other.translation_key is None and other.name == "zwave_js Bridge"
