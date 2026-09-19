# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_repairs_named.py, Version: 0.22.0 (2026-09-18)

"""The disabled-entities repair names the devices it would change.

Issue #13 asked for it: a count says something is off, a name says
where. A fresh install of the second fleet would put 157 devices
under signal alone, so each kind names ten, alphabetically, and
counts the rest (ruling #456).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.device_sentinel.const import (
    DOMAIN,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_MOMENT_GRACE,
)

from tests.helpers import register_device, setup_entry


def _disable_battery(hass: HomeAssistant, uid: str, name: str, entities: int = 1):
    _, entity_ids = register_device(hass, uid, name=name, entity_count=entities)
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(
            entity_id,
            device_class="battery",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )
        registry.async_update_entity(entity_id, unit_of_measurement="%")


async def _detail(hass: HomeAssistant) -> str:
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    return issue.translation_placeholders["detail"]


async def test_the_devices_are_named_alphabetically(hass: HomeAssistant):
    _disable_battery(hass, "b", "Kitchen Door")
    _disable_battery(hass, "a", "attic Window")
    _disable_battery(hass, "c", "Bath Leak")
    detail = await _detail(hass)
    assert detail == "3 battery on attic Window, Bath Leak and Kitchen Door"


async def test_ten_are_named_and_the_rest_counted(hass: HomeAssistant):
    for n in range(12):
        _disable_battery(hass, f"d{n:02d}", f"Sensor {n:02d}")
    detail = await _detail(hass)
    named = ", ".join(f"Sensor {n:02d}" for n in range(10))
    assert detail == f"12 battery on {named}, and 2 others"


async def test_a_device_is_named_once_per_kind(hass: HomeAssistant):
    _disable_battery(hass, "twin", "Twin Probe", entities=2)
    detail = await _detail(hass)
    assert detail == "2 battery on Twin Probe"


async def test_kinds_are_parted_by_semicolons(hass: HomeAssistant):
    """Each kind's names carry commas, so the kinds part on semicolons."""
    _disable_battery(hass, "a", "Alpha")
    _, (entity_id,) = register_device(hass, "s", name="Sig Plug")
    er.async_get(hass).async_update_entity(
        entity_id,
        original_device_class="signal_strength",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    detail = await _detail(hass)
    assert "; " in detail
    assert detail.endswith("1 battery on Alpha")
