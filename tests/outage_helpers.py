# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: outage_helpers.py, Version: 0.27.10 (2026-10-27)

"""Helpers for the outage and unwatched-time tests (rules UNAV-04,
WATCH-08): a device armed with a dated rhythm, minute walks, reloads
and restarts.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_TODAY_MAX,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
)

PIN = "2026-10-11 15:00:00+00:00"


class Info:
    def __init__(self, deep_sleep):
        self.has_deep_sleep = deep_sleep


class Runtime:
    def __init__(self, deep_sleep, available=True):
        self.device_info = Info(deep_sleep)
        self.available = available


def esp_source(hass, runtime):
    source = MockConfigEntry(domain="esphome")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    source.runtime_data = runtime
    return source


def esp_device(hass, source, uid, domains=("sensor", "binary_sensor")):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", uid)}, name=f"Device {uid}")
    eids = []
    for index, domain in enumerate(domains):
        entity = er.async_get(hass).async_get_or_create(
            domain, "esphome", f"{uid}_{index}", device_id=device.id, config_entry=source)
        eids.append(entity.entity_id)
    return device, eids


def entry_of(hass):
    return hass.config_entries.async_entries("device_sentinel")[0]


def arm(coord, device_id, rhythm=3600.0):
    record = coord.data[DATA_DEVICES][device_id]
    days = FREEZE_ARMING_DAYS + 2
    record[DEV_DAILY_MAX] = [rhythm] * days
    record[DEV_TODAY_MAX] = None
    from custom_components.device_sentinel.daily_dates import FAMILY_GAP, set_dates
    today = dt_util.as_local(dt_util.utcnow()).date()
    set_dates(record, FAMILY_GAP, [today - timedelta(days=days - i) for i in range(days)])
    from custom_components.device_sentinel.const import DATA_FIRST_INSTALLED, DEV_FIRST_OBSERVED
    earlier = (dt_util.utcnow() - timedelta(days=30)).isoformat()
    record[DEV_FIRST_OBSERVED] = earlier
    coord.data[DATA_FIRST_INSTALLED] = earlier
    coord._dirty = True
    coord._critical = True
    return record


async def tick(hass, freezer, step=61, n=1):
    for _ in range(n):
        freezer.tick(timedelta(seconds=step))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def walk(hass, freezer, seconds, step=60):
    """Advance `seconds`, sweeping every `step`."""
    steps = int(seconds // step)
    await tick(hass, freezer, step=step, n=steps)
    rest = seconds - steps * step
    if rest > 0:
        freezer.tick(timedelta(seconds=rest))


async def past_grace(hass, freezer):
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)


async def reload(hass):
    assert await hass.config_entries.async_reload(entry_of(hass).entry_id)
    await hass.async_block_till_done()
    return entry_of(hass).runtime_data


async def _quiet(*_args, **_kwargs):
    return None


def _take_states(hass):
    """Remove every other integration's entity state and return them.

    A real start begins with an empty state machine: Device Sentinel can
    set up before the integrations it watches, and a router integration
    may answer minutes later. Device Sentinel's own entities are left to
    its unload and setup.
    """
    registry = er.async_get(hass)
    taken = []
    for state in list(hass.states.async_all()):
        entry = registry.async_get(state.entity_id)
        if entry is None or entry.platform == "device_sentinel":
            continue
        taken.append((state.entity_id, state.state, dict(state.attributes)))
        hass.states.async_remove(state.entity_id)
    return taken


async def restart(
    hass, freezer, down=120, before_setup=None, unload=False, keep_states=False,
    placeholders=False,
):
    """A Home Assistant restart: a clean stop, `down` seconds off, and a
    start.

    The new run starts with no states for the other integrations'
    entities, and they arrive after Device Sentinel has set up, as on a
    real boot, so ties and verdicts form from states that come late.
    By default each arrives as a first state, as for an integration
    that finishes after Device Sentinel and before Home Assistant's
    start event. `placeholders=True` is an integration finishing after
    that event: Home Assistant's "unavailable" placeholder comes first.
    `keep_states=True` keeps the state machine as it stood, for a test
    that needs states present at setup. States are taken after
    `before_setup`, so one it removes stays away.

    Home Assistant does not unload an integration when it stops: it
    fires its stop event, Device Sentinel's stop handler saves, and the
    process ends. So the real stop handler runs and its save is the
    last write; the old coordinator is then torn down with every later
    write silenced, as a process that has ended writes nothing, and a
    fresh one starts from the stored files.

    `unload=True` is the other door: an entry reloaded or disabled from
    the Integrations page, whose unload writes as usual.
    """
    entry = entry_of(hass)
    if not unload:
        coordinator = entry.runtime_data
        await coordinator._on_hass_stop(None)
        await hass.async_block_till_done()
        # The process has ended: nothing of the old run writes again,
        # not even a minute check still in flight.
        coordinator._stopped = True
        coordinator._save_now = _quiet
        coordinator._routine_save = _quiet
        coordinator._save_routine_main = _quiet
        coordinator.async_flush_answers = _quiet
        coordinator.async_probe_stop = _quiet
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    if not unload:
        # A minute check that began its save before the stop finishes
        # it now, before anything stands in for the file on disk: in a
        # real restart it lands before the process ends.
        async with coordinator._save_lock:
            pass
        await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=down))
    if before_setup:
        before_setup()
    taken = [] if keep_states else _take_states(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if placeholders and taken:
        # Home Assistant's start writes "unavailable" with restored: True
        # for every registry entity still without a state, so a late
        # integration's first state replaces that placeholder.
        registry = er.async_get(hass)
        for entity_id, _state, _attributes in taken:
            entry_of_entity = registry.async_get(entity_id)
            if entry_of_entity is not None and hass.states.get(entity_id) is None:
                entry_of_entity.write_unavailable_state(hass)
        await hass.async_block_till_done()
    # The other integrations come up after Device Sentinel.
    for entity_id, state, attributes in taken:
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    return entry.runtime_data


def verdict(record):
    return record.get(DEV_FROZEN_CATEGORY), record.get(DEV_FROZEN_SINCE)


def rec(coord, device_id):
    return coord.data[DATA_DEVICES][device_id]
