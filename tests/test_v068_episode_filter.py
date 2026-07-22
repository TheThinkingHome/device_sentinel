# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v068_episode_filter.py, Version: 0.6.8 (2026-07-22)

"""0.6.8 tests: what earns a silence-episode row.

The first live file exposed two faults. Trivial silences from
fast-reporting devices filled it, because a rhythm of seconds is
exceeded constantly; the threshold now scales with each device's own
grace. And devices whose freeze judgment is suppressed appeared at
all, though they can never produce the verdict the file exists to
explain.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    EPISODE_OPEN_SHARE,
    FREEZE_ARMING_DAYS,
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


def _rhythm(coord, device_id, basis_seconds, silent_seconds):
    coord._grace_until = 0.0
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [basis_seconds] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - silent_seconds
    )


async def test_share_is_half(hass: HomeAssistant):
    """#105: a row opens halfway from rhythm to freeze line."""
    assert EPISODE_OPEN_SHARE == 0.5


async def test_fast_device_ignores_a_trivial_silence(
    hass: HomeAssistant,
):
    """The 0.6.7 noise case: a 36-second rhythm silent for 50
    seconds is a device behaving normally, not an episode."""
    device, entity_id = _register(hass, "f1", "Fast Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 36.0, 50.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_fast_device_opens_once_it_spends_its_patience(
    hass: HomeAssistant,
):
    """The same device silent well into its grace does open a row,
    so the filter suppresses noise without going blind."""
    device, entity_id = _register(hass, "f2", "Fast Sensor Two")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [36.0] * (FREEZE_ARMING_DAYS + 2)
    window = coord._freeze_window(record)
    coord._grace_until = 0.0
    # Silence at three quarters of the way to the freeze line.
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - (36.0 + 0.75 * (window - 36.0))
    )
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1


async def test_globally_excluded_device_is_skipped(
    hass: HomeAssistant,
):
    """#106: no verdict is possible, so no episode explains one."""
    device, entity_id = _register(hass, "g1", "Global Excluded")
    coord = await _coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_freeze_excluded_device_is_skipped(hass: HomeAssistant):
    device, entity_id = _register(hass, "z1", "Freeze Excluded")
    coord = await _coordinator(
        hass, {CONF_FREEZE_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_battery_excluded_device_still_counts(
    hass: HomeAssistant,
):
    """Excluded for battery only: still judged for freeze, so its
    silences still belong in the file."""
    device, entity_id = _register(hass, "b1", "Battery Excluded")
    coord = await _coordinator(
        hass, {CONF_BATTERY_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1
