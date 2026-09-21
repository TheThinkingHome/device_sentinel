# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_child_devices.py, Version: 0.22.18 (2026-09-21)

"""Child devices are watched like any other device.

Home Assistant 2026.9 added child devices: a device filed under
another, such as a boiler's pump beneath the boiler. The registry keeps
them apart from ordinary devices, and the lookup by config entry that
the registry walk used returns ordinary devices only, so a child was
never watched. An integration can also convert an existing device into
a child after a restart, keeping its id, and a watched device converted
that way dropped out of watch with its history left unused.

A child carries a name, an area, labels, a config entry and a disabled
flag, and none of the fields an ordinary device adds (manufacturer,
model, connections and the rest). Home Assistant answers a custom
integration that reads one of those from a child with an empty value
and a deprecation line, and the read breaks in 2027.9. The autouse
guard in conftest fails any test here that logs one, so rendering
every surface with a child present proves no such read was missed.

Every test skips on a Home Assistant without child devices, which is
the 2026.5.0 floor harness.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_MUTED_DEVICES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
)

from .helpers import flat_schema, setup_entry

pytestmark = pytest.mark.skipif(
    not hasattr(dr.DeviceRegistry, "async_get_or_create_child"),
    reason="child devices arrived in Home Assistant 2026.9",
)

SOURCE = "guntamatic"


def _boiler(hass: HomeAssistant):
    """A boiler with one entity of its own, the parent of what follows."""
    source = MockConfigEntry(domain=SOURCE, title="Boiler")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    parent = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(SOURCE, "boiler")},
        name="Boiler",
        manufacturer="Guntamatic",
        model="Biostar",
    )
    entities.async_get_or_create(
        "sensor", SOURCE, "boiler_temperature",
        device_id=parent.id, config_entry=source,
    )
    return source, registry, entities, parent


def _child(hass, source, registry, entities, parent, uid="pump", name="Pump"):
    """A child device with a plain entity and a battery entity."""
    child = registry.async_get_or_create_child(
        config_entry_id=source.entry_id,
        identifiers={(SOURCE, uid)},
        name=name,
        parent_device_id=parent.id,
    )
    plain = entities.async_get_or_create(
        "sensor", SOURCE, f"{uid}_temperature",
        device_id=child.id, config_entry=source,
    )
    battery = entities.async_get_or_create(
        "sensor", SOURCE, f"{uid}_battery",
        device_id=child.id, config_entry=source,
        original_device_class="battery",
    )
    return child, plain.entity_id, battery.entity_id


async def test_a_child_device_is_watched(hass: HomeAssistant, hass_storage):
    source, registry, entities, parent = _boiler(hass)
    child, _, _ = _child(hass, source, registry, entities, parent)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert coordinator._watched.get(child.id) == SOURCE
    assert child.id in coordinator.data["devices"]
    assert coordinator._device_names[child.id] == "Pump"


async def test_a_child_device_is_heard(hass: HomeAssistant, hass_storage):
    """Its own entity's report reaches its own clock."""
    source, registry, entities, parent = _boiler(hass)
    child, plain, _ = _child(hass, source, registry, entities, parent)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert coordinator._entity_map[plain][0] == child.id
    hass.states.async_set(plain, "41.0")
    await hass.async_block_till_done()
    hass.states.async_set(plain, "42.0")
    await hass.async_block_till_done()
    assert coordinator.data["devices"][child.id]["event_count"] >= 1


async def test_a_watched_device_converted_to_a_child_stays_watched(
    hass: HomeAssistant, hass_storage
):
    """The conversion keeps the id, so the device keeps its record."""
    source, registry, entities, parent = _boiler(hass)
    pump = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(SOURCE, "pump")},
        name="Pump",
    )
    entities.async_get_or_create(
        "sensor", SOURCE, "pump_temperature",
        device_id=pump.id, config_entry=source,
    )
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert pump.id in coordinator._watched
    record = coordinator.data["devices"][pump.id]
    record[DEV_DAILY_MAX] = [1800.0] * (FREEZE_ARMING_DAYS + 3)

    # As after a restart: the device came from the stored registry, so
    # the integration registering it as a child converts it in place.
    registry._live_device_ids.clear()
    child = registry.async_get_or_create_child(
        config_entry_id=source.entry_id,
        identifiers={(SOURCE, "pump")},
        name="Pump",
        parent_device_id=parent.id,
    )
    assert child.id == pump.id
    await hass.async_block_till_done()
    coordinator._rebuild_registry_view()

    assert coordinator._watched.get(pump.id) == SOURCE
    kept = coordinator.data["devices"][pump.id]
    assert kept[DEV_DAILY_MAX] == [1800.0] * (FREEZE_ARMING_DAYS + 3)


async def test_a_child_device_follows_exclusion_and_muting(
    hass: HomeAssistant, hass_storage
):
    source, registry, entities, parent = _boiler(hass)
    child, _, _ = _child(hass, source, registry, entities, parent)
    entry = await setup_entry(
        hass,
        {CONF_EXCLUDED_INTEGRATIONS: [], CONF_MUTED_DEVICES: [child.id]},
    )
    coordinator = entry.runtime_data
    assert coordinator._muted_devices.get(child.id) == "device"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_remove(entry.entry_id)
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: [SOURCE]})
    coordinator = entry.runtime_data
    assert child.id not in coordinator._watched
    assert coordinator._set_aside[child.id][1] == SOURCE


async def test_a_disabled_child_device_is_set_aside(
    hass: HomeAssistant, hass_storage
):
    source, registry, entities, parent = _boiler(hass)
    child = registry.async_get_or_create_child(
        config_entry_id=source.entry_id,
        identifiers={(SOURCE, "pump")},
        name="Pump",
        parent_device_id=parent.id,
        disabled_by=dr.DeviceEntryDisabler.USER,
    )
    entities.async_get_or_create(
        "sensor", SOURCE, "pump_temperature",
        device_id=child.id, config_entry=source,
    )
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert child.id not in coordinator._watched
    assert child.id in coordinator._set_aside


async def test_the_muting_picker_offers_a_child_device(
    hass: HomeAssistant, hass_storage
):
    source, registry, entities, parent = _boiler(hass)
    _child(hass, source, registry, entities, parent)
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    labels = []
    schema = flat_schema(result["data_schema"].schema)
    for key in schema:
        config = getattr(schema[key], "config", {})
        for option in config.get("options", []):
            if isinstance(option, dict):
                labels.append(option["label"])
    assert any(label.startswith("Pump") for label in labels), labels


async def test_every_surface_renders_a_child_without_a_deprecated_read(
    hass: HomeAssistant, hass_storage, hass_ws_client
):
    """A named child, a nameless child and an area, through every
    surface a person or a tester reads: the reports, the diagnostics,
    each dashboard reply and each settings screen. The autouse guard
    fails this test on any read of a field a child does not carry."""
    source, registry, entities, parent = _boiler(hass)
    child, plain, battery = _child(hass, source, registry, entities, parent)
    nameless, _, _ = _child(
        hass, source, registry, entities, parent, uid="valve", name=None
    )
    area = ar.async_get(hass).async_create("Basement")
    registry.async_update_child_device(child.id, area_id=area.id)
    hass.states.async_set(plain, "41.0")
    hass.states.async_set(battery, "9", {"device_class": "battery", "unit_of_measurement": "%"})

    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})
    coordinator = entry.runtime_data
    assert nameless.id in coordinator._watched
    record = coordinator.data["devices"][child.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 4 * 3600
    coordinator._sync_problem_list()

    await coordinator.async_regenerate_reports()
    await hass.async_block_till_done()
    assert "Pump" in coordinator._last_brief_text

    dump = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert child.id in dump["devices"]
    assert dump["devices"][child.id]["manufacturer"] is None

    client = await hass_ws_client(hass)
    for kind in (
        "status", "classification", "problem_list", "recommendations",
        "integrations", "devices", "brief", "battery_trends",
        "signal_trends",
    ):
        await client.send_json_auto_id({"type": f"device_sentinel/{kind}"})
        reply = await client.receive_json()
        assert reply["success"], (kind, reply)
    for device_id in (child.id, nameless.id):
        await client.send_json_auto_id(
            {"type": "device_sentinel/device", "device_id": device_id}
        )
        reply = await client.receive_json()
        assert reply["success"], reply
    await client.send_json_auto_id(
        {"type": "device_sentinel/integration", "domain": SOURCE}
    )
    reply = await client.receive_json()
    assert reply["success"], reply

    for step in ("notifications", "exclusions", "battery", "signal", "freeze"):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        assert result["step_id"] == step
        hass.config_entries.options.async_abort(result["flow_id"])
