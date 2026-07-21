# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v065_persistence.py, Version: 0.6.5 (2026-07-21)

"""0.6.5 tests: two-tier persistence (analysis finding E1).

Routine activity-clock churn coalesces into one delayed write on the
STORAGE_COALESCE_SECONDS window; anything a reboot must not lose (a
verdict, a battery flip, a problem-list change, an acknowledgment)
still saves immediately. These tests spy on the store to prove which
tier each path takes.
"""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
    STORAGE_COALESCE_SECONDS,
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


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


class _StoreSpy:
    """Counts immediate saves and delayed schedules on a real store."""

    def __init__(self, store):
        self.saves = 0
        self.delays = 0
        self._real_save = store.async_save
        self._real_delay = store.async_delay_save
        store.async_save = self._save
        store.async_delay_save = self._delay

    async def _save(self, data):
        self.saves += 1
        await self._real_save(data)

    def _delay(self, data_func, delay):
        self.delays += 1
        assert delay == STORAGE_COALESCE_SECONDS
        self._real_delay(data_func, delay)


async def test_routine_churn_coalesces(hass: HomeAssistant, freezer):
    """Activity alone schedules a delayed write; nothing saves
    immediately on the tick."""
    device, entity_id = _register(hass, "r1", "Routine Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.saves == 0
    assert spy.delays >= 1


async def test_verdict_flip_saves_immediately(
    hass: HomeAssistant, freezer
):
    """A freeze verdict on the tick takes the immediate tier, the
    exact pre-0.6.5 behavior for anything that matters."""
    device, entity_id = _register(hass, "v1", "Verdict Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)

    spy = _StoreSpy(coord._store)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    saves_before = spy.saves

    freezer.tick(timedelta(hours=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.saves > saves_before  # the flip forced a real write
    assert coord._critical is False


async def test_acknowledgment_saves_immediately(hass: HomeAssistant):
    """The checkbox writes through at once, never waiting for a tick
    or a window."""
    device, entity_id = _register(hass, "a1", "Acked Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 8 * 3600
    coord._judge_all_devices()
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]

    spy = _StoreSpy(coord._store)
    await coord.async_todo_update(uid=uid, status="completed")
    assert spy.saves == 1


async def test_delayed_save_serializes_live_data(hass: HomeAssistant):
    """The delayed write reads the state at write time, not at
    schedule time."""
    entry = await _setup(hass)
    coord = entry.runtime_data
    assert coord._data_to_save() is coord.data


async def test_shutdown_flushes_pending(hass: HomeAssistant):
    """A clean unload writes through whatever tier was pending."""
    device, entity_id = _register(hass, "s1", "Flush Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    coord._dirty = True  # simulate pending routine churn

    with patch.object(
        coord._store, "async_save", wraps=coord._store.async_save
    ) as saved:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert saved.call_count >= 1
    assert coord._dirty is False
