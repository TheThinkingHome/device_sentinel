# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v061_status_icon.py, Version: 0.6.1 (2026-07-21)

"""0.6.1 tests: the todo icon in STATUS and the journal in diagnostics.

A Reported device with a fault carries its problem-list state in the
STATUS cell: (circle) listed and open, (check) acknowledged, (cross)
a fault present but no item, the window after a hand delete. A
healthy Reported device wears no icon. The diagnostics download gains
the additions journal beside the items, so a download reflects the
whole todo layer.
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

OPEN_ICON = "Reported (\u25cb)"
ACKED_ICON = "Reported (\u2713)"
ORPHAN_ICON = "Reported (\u2717)"


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


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options=options or {}
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


async def test_healthy_reported_device_has_no_icon(hass: HomeAssistant):
    device, entity_id = _register(hass, "h1", "Healthy Sensor")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "on")
    coord._sync_problem_list()
    assert coord._device_status(device.id) == "Reported"


async def test_open_problem_shows_circle(hass: HomeAssistant):
    device, entity_id = _register(hass, "o1", "Open Sensor")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    assert coord._device_status(device.id) == OPEN_ICON


async def test_acknowledged_problem_shows_check(hass: HomeAssistant):
    device, entity_id = _register(hass, "a1", "Acked Sensor")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    assert coord._device_status(device.id) == ACKED_ICON


async def test_fault_without_item_shows_cross(hass: HomeAssistant):
    """The hand-delete window: fault present, item gone, before the
    next sync re-adds it."""
    device, entity_id = _register(hass, "x1", "Orphan Sensor")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_delete([uid])
    # Fault still detected, item now gone: the orphan state.
    assert coord._device_status(device.id) == ORPHAN_ICON


async def test_excluded_device_keeps_its_grammar(hass: HomeAssistant):
    """An excluded device shows its exclude reason, never an icon,
    even with a stored verdict."""
    device, entity_id = _register(hass, "e1", "Excluded Sensor")
    entry = await _coordinator(
        hass, options={"excluded_devices": [device.id]}
    )
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    assert coord._device_status(device.id) == "Excluded (GLB)"


async def test_icon_reaches_the_written_report(hass: HomeAssistant):
    device, entity_id = _register(hass, "r1", "Reported In File")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "device_telemetry.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert OPEN_ICON in text


async def test_journal_is_in_diagnostics(hass: HomeAssistant):
    device, entity_id = _register(hass, "j1", "Journal Sensor")
    entry = await _coordinator(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "todo_journal" in diag
    assert any(
        e["device_id"] == device.id for e in diag["todo_journal"]
    )
    # The items are still there too.
    assert any(
        r["device_id"] == device.id for r in diag["todo_items"]
    )
