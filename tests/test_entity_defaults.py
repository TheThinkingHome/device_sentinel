# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_entity_defaults.py, Version: 0.12.12 (2026-08-07)

"""Which entities a first install presents, and what deletion leaves.

The defaults follow one test (ruling #239): enabled means a person reads
it daily or acts on it in their first week. The table below is the
ruling written as an assertion, so flipping a default is a decision
that edits this file rather than a side effect nobody notices. The
broker sensor is the one conditional: enabled where a bridge stack
was detected, off where the house has no MQTT to watch.

Deletion is the other end of the same courtesy (ruling #240): removing
the integration removes both storage files, every backup beside
them, and both report folders, so an uninstall leaves nothing for a
person to find later and wonder about.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from custom_components.device_sentinel.const import (
    REPORT_DIR,
    REPORT_WWW_DIR,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from tests.helpers import setup_entry

# The ruling as data: entity object id -> enabled by default. Every
# sensor and button the integration creates on a bridge-less test
# house appears here exactly once.
EXPECTED_DEFAULTS = {
    # Read daily or acted on in the first week: on.
    "sensor.device_sentinel_status": True,
    "sensor.device_sentinel_devices_watched": True,
    "sensor.device_sentinel_devices_learned": True,
    "sensor.device_sentinel_maintenance_ends": True,
    "todo.device_sentinel_problem_list": True,
    "button.device_sentinel_enable_signals": True,
    "button.device_sentinel_enable_last_seen": True,
    "button.device_sentinel_enable_battery": True,
    "button.device_sentinel_regenerate_reports": True,
    "button.device_sentinel_maintenance_mode": True,
    # Dashboard-builder detail: off, the problem list carries what is
    # wrong and the brief carries the day.
    "sensor.device_sentinel_signal_tracked": False,
    "sensor.device_sentinel_battery_tracked": False,
    "sensor.device_sentinel_device_tracked": False,
    "sensor.device_sentinel_signal_rails": False,
    "sensor.device_sentinel_signal_weak": False,
    "sensor.device_sentinel_battery_low": False,
    "sensor.device_sentinel_battery_falling": False,
    "sensor.device_sentinel_device_frozen": False,
    "sensor.device_sentinel_service_devices_ignored": False,
    # The conditional: this test house has no bridge stack, so the
    # broker sensor ships off. The other branch has its own test.
    "sensor.device_sentinel_broker_mqtt": False,
}


async def test_every_entity_default_matches_the_ruling(
    hass: HomeAssistant, entity_registry
):
    """The whole table (ruling #239), so a flip is always a decision."""
    await setup_entry(hass)
    ours = {
        entry.entity_id: entry.disabled_by is None
        for entry in entity_registry.entities.values()
        if entry.platform == "device_sentinel"
    }
    assert ours == EXPECTED_DEFAULTS


async def test_removal_deletes_everything_written(hass: HomeAssistant):
    """Deletion leaves nothing (ruling #240): storage, backups, reports,
    and the www folder all go, and files belonging to anything else
    are untouched."""
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
    for folder in (report_dir, www_dir):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sample.md").write_text("sample")
    bystander = storage / "other_integration.storage"
    bystander.write_text("{}")

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    for path in mine:
        assert not path.exists(), path
    assert not report_dir.exists()
    assert not www_dir.exists()
    assert bystander.exists()


async def test_the_broker_sensor_ships_enabled_where_a_bridge_lives(
    hass: HomeAssistant, entity_registry
):
    """The conditional's other branch (ruling #239): a house whose
    registry shows a Zigbee2MQTT bridge gets the broker sensor on,
    and the bridge sensor arrives enabled with it."""
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
