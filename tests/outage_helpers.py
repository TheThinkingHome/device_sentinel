# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: outage_helpers.py, Version: 0.26.0 (2026-10-12)

"""Helpers for the outage and unwatched-time tests (rulings #647 and #648):
a device armed with a dated rhythm, minute walks, reloads and restarts."""
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


async def restart(hass, freezer, down=120, before_setup=None):
    """A clean stop, `down` seconds off, and a start."""
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=down))
    if before_setup:
        before_setup()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def verdict(record):
    return record.get(DEV_FROZEN_CATEGORY), record.get(DEV_FROZEN_SINCE)


def rec(coord, device_id):
    return coord.data[DATA_DEVICES][device_id]
