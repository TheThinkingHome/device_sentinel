# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v066_coalesce_fires.py, Version: 0.6.6 (2026-07-21)

"""0.6.6 tests: the coalesced write actually fires.

The 0.6.5 flaw, caught by the storage watch in its first hour: the
delayed save was rescheduled on every dirty tick, so a fleet that is
always dirty pushed the deadline forward forever and the routine
write never happened. These tests prove the fix: many dirty ticks in
one window place exactly one schedule, the write fires when the
window elapses, and an immediate save mid-window clears the pending
flag so the next window schedules cleanly.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
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
    """Counts immediate saves and delayed schedules."""

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
        self._real_delay(data_func, delay)


async def test_dirty_ticks_schedule_once_and_the_write_fires(
    hass: HomeAssistant, freezer
):
    """Continuous churn: one schedule per window, and the delayed
    write really executes when the window elapses. This is the test
    0.6.5 shipped without."""
    device, entity_id = _register(hass, "c1", "Churn Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Ten dirty ticks inside one window: activity each minute.
    value = 0
    for _ in range(10):
        value += 1
        hass.states.async_set(entity_id, str(value))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.delays == 1          # scheduled once, never rescheduled
    assert spy.saves == 0           # nothing immediate for churn
    assert coord._delay_pending is True

    # The window elapses: the delayed write fires for real. The
    # store's delayed path writes internally rather than through
    # async_save, so the firing proof is the pending flag clearing,
    # which only _data_to_save does, and it runs exactly when the
    # store serializes the delayed write. spy.saves staying at zero
    # proves no immediate save could have cleared it instead.
    freezer.tick(
        timedelta(seconds=STORAGE_COALESCE_SECONDS + 30)
    )
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert spy.saves == 0
    assert coord._delay_pending is False

    # More churn after the fire: a fresh window schedules again.
    value += 1
    hass.states.async_set(entity_id, str(value))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spy.delays == 2


async def test_immediate_save_clears_the_pending_window(
    hass: HomeAssistant, freezer
):
    """A critical save mid-window resets the pending flag, so the
    next churn schedules a clean new window instead of assuming one
    is still coming."""
    device, entity_id = _register(hass, "c2", "Reset Sensor")
    entry = await _setup(hass)
    coord = entry.runtime_data
    spy = _StoreSpy(coord._store)

    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coord._delay_pending is True

    # An acknowledged-style direct save mid-window.
    await coord._save_now()
    assert coord._delay_pending is False
    saves_after_direct = spy.saves

    # New churn: a fresh window schedules.
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coord._delay_pending is True
    assert spy.delays == 2
    assert spy.saves == saves_after_direct  # churn stayed routine
