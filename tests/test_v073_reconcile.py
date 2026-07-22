# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v073_reconcile.py, Version: 0.7.3 (2026-07-22)

"""0.7.3 tests: restating what is already true.

The composer speaks on transitions, which leaves a device that was
already broken before the engine started undescribed forever. The
reconcile pass says what is true rather than what just changed, and
it must be idempotent, skip acknowledged devices, and mark its
messages so a later engine can tell a restatement from news.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    DATA_OUTBOX,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    OUTBOX_REASON_EVENT,
    OUTBOX_REASON_RECONCILE,
    OUTBOX_SHAPE_DEVICE,
    OUT_REASON,
    OUT_SHAPE,
    OUT_TEXT,
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


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _freeze(coord, device_id, hours=4.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = (
        dt_util.utcnow().timestamp() - hours * 3600.0
    )


def _lines(coord, reason=None):
    return [
        row
        for row in coord.data[DATA_OUTBOX]
        if row[OUT_SHAPE] == OUTBOX_SHAPE_DEVICE
        and (reason is None or row[OUT_REASON] == reason)
    ]


async def test_standing_problem_is_restated(hass: HomeAssistant):
    """The field gap: a device already broken when the engine starts
    never transitions, so only a reconcile can describe it."""
    device, entity_id = _register(hass, "r1", "Standing Problem")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    coord.data[DATA_OUTBOX].clear()  # forget the transition

    assert coord.reconcile_device_lines() == 1
    restated = _lines(coord, OUTBOX_REASON_RECONCILE)
    assert len(restated) == 1
    assert "Standing Problem" in restated[0][OUT_TEXT]


async def test_reconcile_is_idempotent_in_content(
    hass: HomeAssistant,
):
    """Running it twice says the same thing twice, never something
    different: it states what is true, not what changed."""
    device, entity_id = _register(hass, "r2", "Twice Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    coord.data[DATA_OUTBOX].clear()

    coord.reconcile_device_lines()
    first = _lines(coord, OUTBOX_REASON_RECONCILE)[-1][OUT_TEXT]
    coord.reconcile_device_lines()
    second = _lines(coord, OUTBOX_REASON_RECONCILE)[-1][OUT_TEXT]
    assert first == second


async def test_acknowledged_devices_are_not_restated(
    hass: HomeAssistant,
):
    """The phone carries what is wrong and unacknowledged (#109)."""
    device, entity_id = _register(hass, "r3", "Acked Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    coord.data[DATA_OUTBOX].clear()

    assert coord.reconcile_device_lines() == 0


async def test_excluded_devices_are_never_restated(
    hass: HomeAssistant,
):
    device, entity_id = _register(hass, "r4", "Excluded Sensor")
    coord = await _coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    coord.data[DATA_OUTBOX].clear()
    assert coord.reconcile_device_lines() == 0


async def test_transitions_are_marked_as_events(hass: HomeAssistant):
    """A restatement and a piece of news must be distinguishable, so
    a later engine can replace a line without announcing it."""
    device, entity_id = _register(hass, "r5", "Marked Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    assert _lines(coord, OUTBOX_REASON_EVENT)


async def test_startup_reconcile_runs_when_grace_closes(
    hass: HomeAssistant,
):
    """The hook: once the clocks have settled, everything standing is
    restated without anything having happened."""
    device, entity_id = _register(hass, "r6", "Boot Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    coord.data[DATA_OUTBOX].clear()

    coord._on_grace_closed(None)
    assert len(_lines(coord, OUTBOX_REASON_RECONCILE)) == 1
