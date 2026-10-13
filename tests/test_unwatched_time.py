# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_unwatched_time.py, Version: 0.26.0 (2026-10-12)

"""A device taken back is judged from the moment it is watched again (ruling #648).

Disabled, excluded or removed, then watched again, a dead device is
judged frozen a full window after its return: the time nobody watched
it is not its silence. The return is saved with the record, so a
restart neither forgives the watched time since nor makes the restart
look like the return; a second stretch dates its own return; a device
already past its window when it was set aside reads frozen again at
once. Found by the adversarial rounds of 12 October 2026.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_TODAY_MAX,
    FREEZE_CATEGORY_FROZEN,
)
from tests.helpers import register_device, registry_settled, setup_coordinator
from .outage_helpers import (
    PIN, arm, entry_of, past_grace, rec, restart, walk,
)


async def _ready(hass, freezer, uid):
    freezer.move_to(PIN)
    device, eids = register_device(hass, uid, entity_count=1)
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    hass.states.async_set(eids[0], "21.5")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(eids[0], "21.6")
    await hass.async_block_till_done()
    rec(coord, device.id)[DEV_TODAY_MAX] = None
    return coord, device, eids


async def _aside(hass, device, how, on):
    if how == "disable":
        dr.async_get(hass).async_update_device(
            device.id, disabled_by=dr.DeviceEntryDisabler.USER if on else None)
        await registry_settled(hass)
    else:
        entry = entry_of(hass)
        options = dict(entry.options)
        options[CONF_EXCLUDED_DEVICES] = [device.id] if on else []
        hass.config_entries.async_update_entry(entry, options=options)
        await hass.async_block_till_done()
        await registry_settled(hass)
    return entry_of(hass).runtime_data


async def _frozen_at(hass, freezer, coord, device, limit):
    """Walk a minute at a time until frozen; seconds walked, or None."""
    record = rec(coord, device.id)
    for step in range(int(limit // 60)):
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            return step * 60
        await walk(hass, freezer, 60)
    return None


@pytest.mark.parametrize("how", ["disable", "exclude"])
async def test_judged_from_watched_again(hass: HomeAssistant, freezer, how):
    """Last report, ten minutes, set aside for two hours, back: a dead
    device is judged frozen a full window after its return."""
    coord, device, eids = await _ready(hass, freezer, f"b01{how}")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, how, True)
    await walk(hass, freezer, 7200)
    coord = await _aside(hass, device, how, False)
    took = await _frozen_at(hass, freezer, coord, device, window + 3600)
    # Judged from the moment it was watched again: a full window.
    assert took is not None and abs(took - window) <= 180, (took, window)


@pytest.mark.parametrize("how", ["disable", "exclude"])
async def test_restart_after_watched_again(hass: HomeAssistant, freezer, how):
    """As above, and Home Assistant restarts (two minutes off) an hour
    after the device is watched again. The hour watched before the
    restart is still the device's silence: frozen comes when it would
    have without the restart, plus at most the time off."""
    coord, device, eids = await _ready(hass, freezer, f"b02{how}")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, how, True)
    await walk(hass, freezer, 7200)
    coord = await _aside(hass, device, how, False)
    await walk(hass, freezer, 3600)
    coord = await restart(hass, freezer, down=120)
    expected_left = window - 3600
    took = await _frozen_at(hass, freezer, coord, device, window + 7200)
    assert took is not None and took <= expected_left + 600, (
        "restart re-dated the watched-again moment", took, expected_left)


@pytest.mark.parametrize("how", ["disable", "exclude"])
async def test_set_aside_twice_without_a_report(hass: HomeAssistant, freezer, how):
    """Set aside for ten minutes, back for ten, set aside again for three
    hours, back. The second unwatched stretch is not the device's silence
    either; nothing may be judged frozen for it."""
    coord, device, eids = await _ready(hass, freezer, f"b03{how}")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 300)
    coord = await _aside(hass, device, how, True)
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, how, False)
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, how, True)
    await walk(hass, freezer, 3 * 3600)
    coord = await _aside(hass, device, how, False)
    await walk(hass, freezer, 120)
    record = rec(coord, device.id)
    watched_silence = 300 + 600 + 120
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_FROZEN, (
        "frozen for the second unwatched stretch", watched_silence, window)


async def test_removal_hold_and_return(hass: HomeAssistant, freezer):
    """Removed from Home Assistant (held), re-added with the same id three
    hours later, dead. The clock restarts at the return (#622), so frozen
    comes `window` after it."""
    coord, device, eids = await _ready(hass, freezer, "b04")
    window = coord._freeze_window(rec(coord, device.id))
    source_id = getattr(device, "config_entry_id", None) or next(iter(device.config_entries))
    identifiers = device.identifiers
    dr.async_get(hass).async_remove_device(device.id)
    await registry_settled(hass)
    await walk(hass, freezer, 3 * 3600)
    again = dr.async_get(hass).async_get_or_create(config_entry_id=source_id, identifiers=identifiers, name="b04")
    from homeassistant.helpers import entity_registry as er
    ent = er.async_get(hass).async_get_or_create("sensor", "test", "b04", device_id=again.id,
                                           config_entry=hass.config_entries.async_get_entry(source_id))
    hass.states.async_set(ent.entity_id, "21.6")
    await registry_settled(hass)
    took = await _frozen_at(hass, freezer, coord, again, window + 3600)
    assert took is None or took >= window - 180, (took, window)


async def test_a_frozen_device_taken_back_reads_frozen_at_once(hass: HomeAssistant, freezer):
    """Frozen, excluded an hour, taken back, still dead: it was down before
    anyone stopped watching it, so it reads frozen again at once."""
    from homeassistant.helpers import device_registry as dr  # noqa: F401

    from custom_components.device_sentinel.const import FREEZE_CATEGORY_FROZEN as FROZEN

    coord, device, eids = await _ready(hass, freezer, "b05")
    window = coord._freeze_window(rec(coord, device.id))
    took = await _frozen_at(hass, freezer, coord, device, window + 3600)
    assert took is not None
    await walk(hass, freezer, 1800)
    coord = await _aside(hass, device, "exclude", True)
    await walk(hass, freezer, 3600)
    coord = await _aside(hass, device, "exclude", False)
    again = await _frozen_at(hass, freezer, coord, device, 3600)
    assert again is not None and again <= 300, again
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FROZEN
