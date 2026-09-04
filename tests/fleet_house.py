# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/fleet_house.py, Version: 0.20.1 (2026-09-04)

"""Build a live coordinator shaped like a real reference fleet.

Shared by the per-fleet integration outage files, which were one file
until its eight cases outgrew a single test run: each case pays the
full registry build for its fleet, so the split is by fleet rather
than by subject, and each file skips whole when its fleet is absent.

Every device gets one of the fleet's real records, so the statistics
under the judgment are real even though the wiring is reconstructed.
The shapes list the integrations each fleet runs that have no reader
watching them, taken from its own classification. Stand-in domain
names, because Home Assistant tries to load and unload a real one
around the test and leaves the loop holding work at teardown.
"""

from __future__ import annotations

import glob
import json

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_RUNNING,
    DATA_DEVICES,
)

from tests.conftest import fleet_path
from tests.helpers import setup_coordinator
from tests.test_upstream_events_fleet import _stub

JAMES = fleet_path("james", "device_sentinel.storage")
TIM = fleet_path("tim", "device_sentinel_storage.json")

JAMES_SHAPE = {
    "blinds_hub": 6,
    "camera_hub": 4,
    "presence_hub": 3,
    "node_hub": 3,
    "coordinator_hub": 2,
    "printer_hub": 1,
    "relay_hub": 1,
}
TIM_SHAPE = {
    "router_hub": 41,
    "node_hub": 34,
    "controller_hub": 17,
    "button_hub": 14,
    "server_hub": 12,
    "storage_hub": 4,
    "sensor_hub": 4,
}


def _records(path):
    """Return a fleet's real device records."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    data = loaded.get("data", loaded)
    return data.get("devices") or {}


def _names(path):
    """Return the device names from the diagnostics beside the fleet."""
    found = glob.glob(str(path.parent / "config_entry*.json"))
    if not found:
        return {}
    with open(found[0], encoding="utf-8") as handle:
        dump = json.load(handle)
    return {
        device_id: (record or {}).get("name") or device_id
        for device_id, record in (
            (dump.get("data") or {}).get("devices") or {}
        ).items()
    }


def _house(hass, path, shape):
    """Build a house shaped like the fleet, and carry its records."""
    records = list(_records(path).items())
    names = _names(path)
    entries: dict[str, MockConfigEntry] = {}
    behind: dict[str, list] = {}
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    index = 0

    for domain, count in shape.items():
        source = MockConfigEntry(domain=domain, title=f"{domain} hub")
        source.add_to_hass(hass)
        entries[domain] = source
        behind[domain] = []
        for _ in range(count):
            if index >= len(records):
                break
            device_id, _record = records[index]
            device = registry.async_get_or_create(
                config_entry_id=source.entry_id,
                identifiers={(domain, f"d{index}")},
                name=names.get(device_id) or device_id,
            )
            entities.async_get_or_create(
                "sensor", domain, f"d{index}",
                device_id=device.id, config_entry=source,
            )
            behind[domain].append((device, device_id))
            index += 1

    # The rest on Zigbee, with a bridge, which is the shape both
    # fleets really have.
    zigbee = MockConfigEntry(domain="mqtt", title="Zigbee")
    zigbee.add_to_hass(hass)
    entries["mqtt"] = zigbee
    bridge = registry.async_get_or_create(
        config_entry_id=zigbee.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    entities.async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0",
        device_id=bridge.id, config_entry=zigbee,
    )
    behind["mqtt"] = []
    while index < len(records):
        device_id, _record = records[index]
        uid = f"zigbee2mqtt_0x{index:016x}"
        device = registry.async_get_or_create(
            config_entry_id=zigbee.entry_id,
            identifiers={("mqtt", uid)},
            name=names.get(device_id) or device_id,
        )
        entities.async_get_or_create(
            "sensor", "mqtt", uid,
            device_id=device.id, config_entry=zigbee,
        )
        behind["mqtt"].append((device, device_id))
        index += 1
    return entries, behind


async def _fleet(hass, path, shape):
    """Load a fleet into a coordinator past its grace, entries up."""
    entries, behind = _house(hass, path, shape)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    records = _records(path)
    for _domain, members in behind.items():
        for device, device_id in members:
            record = records.get(device_id)
            if isinstance(record, dict):
                coord.data[DATA_DEVICES][device.id] = dict(record)

    now = dt_util.utcnow().timestamp()
    for source in entries.values():
        source.mock_state(hass, ConfigEntryState.LOADED)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    # Seen up, which is what a real house does before anything falls.
    coord._sample_integrations(now)
    return coord, entries, behind, now
