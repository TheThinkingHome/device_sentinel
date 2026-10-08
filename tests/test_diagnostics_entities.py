# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_entities.py, Version: 0.25.0 (2026-10-08)

"""Every entity of a device in the diagnostics download (0.25.0).

The device type (Project__Device_Type.md) is read from a device's own
entities: a camera entity, a cover, a moisture sensor. Until 0.25.0 the
download carried only the battery, signal and Last seen entities, so
the type rules could not be tested on a real house. Each device now
carries every entity the registry holds for it, with what those rules
read and nothing they do not: no state.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_entry


async def test_every_entity_of_a_device_is_listed_with_what_type_rules_read(hass: HomeAssistant):
    device, (sensor_id,) = register_device(hass, "ty1", "Leak Kitchen Sink")
    ent_reg = er.async_get(hass)
    source = ent_reg.async_get(sensor_id).config_entry_id
    leak = ent_reg.async_get_or_create(
        "binary_sensor", "test", "ty1-leak", config_entry=hass.config_entries.async_get_entry(source),
        device_id=device.id, original_device_class="moisture",
    )
    off = ent_reg.async_get_or_create(
        "sensor", "test", "ty1-temp", config_entry=hass.config_entries.async_get_entry(source),
        device_id=device.id, original_device_class="temperature", unit_of_measurement="°C",
        entity_category=EntityCategory.DIAGNOSTIC, disabled_by=er.RegistryEntryDisabler.USER,
    )
    ent_reg.async_update_entity(leak.entity_id, device_class="moisture")
    entry = await setup_entry(hass)
    payload = await async_get_config_entry_diagnostics(hass, entry)
    rows = {row["entity_id"]: row for row in payload["devices"][device.id]["all_entities"]}
    assert set(rows) == {sensor_id, leak.entity_id, off.entity_id}
    assert rows[leak.entity_id]["domain"] == "binary_sensor"
    assert rows[leak.entity_id]["device_class"] == "moisture"
    assert rows[leak.entity_id]["platform"] == "test"
    assert rows[off.entity_id] == {
        "entity_id": off.entity_id, "domain": "sensor", "platform": "test",
        "device_class": "temperature", "unit": "°C", "category": "diagnostic",
        "disabled_by": "user",
    }
    assert all("state" not in row for row in rows.values()), "a state reached the type list"

