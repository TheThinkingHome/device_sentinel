# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v061_status_icon.py, Version: 0.6.2 (2026-07-21)

"""0.6.1's surviving tests: the journal in diagnostics.

The 0.6.1 STATUS icon lived one release and moved to the Reporting
Devices section at 0.6.2 (tested in test_v062_reporting_section.py),
so the icon assertions that named this file are gone. What remains is
0.6.1's other half, the additions journal surfaced in the diagnostics
download, plus the exclusion grammar that the revert left untouched.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


async def _entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _freeze(coord, device_id, since=1_000_000.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


async def test_excluded_device_keeps_its_grammar(hass: HomeAssistant):
    """An excluded device shows its exclude reason, verdictless."""
    device, entity_id = _register(hass, "e1", "Excluded Sensor")
    entry = await _entry(hass, options={"excluded_devices": [device.id]})
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    assert coord._device_status(device.id) == "Excluded (GLB)"


async def test_journal_is_in_diagnostics(hass: HomeAssistant):
    device, entity_id = _register(hass, "j1", "Journal Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "todo_journal" in diag
    assert any(
        e["device_id"] == device.id for e in diag["todo_journal"]
    )
    assert any(
        r["device_id"] == device.id for r in diag["todo_items"]
    )
