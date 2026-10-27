# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_unwatched_time_cases.py, Version: 0.27.10 (2026-10-27)

"""The return from being set aside is dated once (rule WATCH-08).

A device is judged from the moment it is watched again, and that moment
is fixed when it comes back: a later settings change, a restart or an
upgrade never re-dates it, so a standing freeze is never cleared by a
slider. Each stretch set aside is read on its own, a clock set back
while the device is set aside does not count the time nobody watched
it, and a return made while Device Sentinel was reloading or disabled
is still dated. How the trouble began is kept across a restart
(rule UNAV-07), and a damaged saved value is not trusted.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    DATA_DEVICES,
    DEV_DOWN_BEGAN_AS,
    DEV_FROZEN_CATEGORY,
    DEV_TODAY_MAX,
    DEV_WATCHED_FROM,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    STORAGE_KEY,
)

from .helpers import record_events, register_device, registry_settled, setup_coordinator
from .outage_helpers import PIN, arm, entry_of, past_grace, rec, restart, tick, walk

H = 3600


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


async def _options(hass, **changes):
    entry = entry_of(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **changes})
    await hass.async_block_till_done()
    await registry_settled(hass)
    return entry_of(hass).runtime_data


async def _aside(hass, device, on):
    return await _options(hass, **{CONF_EXCLUDED_DEVICES: [device.id] if on else []})


async def _until(hass, freezer, record, category, limit):
    """Seconds walked until the verdict reads `category`, or None."""
    for step in range(int(limit // 60)):
        if record[DEV_FROZEN_CATEGORY] == category:
            return step * 60
        await walk(hass, freezer, 60)
    return None


async def _frozen_at(hass, freezer, coord, device_id, limit):
    return await _until(hass, freezer, rec(coord, device_id), FREEZE_CATEGORY_FROZEN, limit)


def _downs(events, device_id):
    return [e.get("down_for") for e in events if e.get("device_id") == device_id]


async def test_a_slider_change_does_not_clear_a_standing_freeze(hass: HomeAssistant, freezer):
    """Frozen, excluded an hour, taken back (frozen again at once), and
    six hours later both Freeze Detection sliders are raised. The return
    was dated when it happened; the change does not re-date it, so the
    dead device stays frozen and no recovery is told."""
    coord, device, eids = await _ready(hass, freezer, "u01")
    window = coord._freeze_window(rec(coord, device.id))
    assert await _frozen_at(hass, freezer, coord, device.id, window + H) is not None
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, H)
    coord = await _aside(hass, device, False)
    assert await _frozen_at(hass, freezer, coord, device.id, 600) is not None
    events = record_events(hass, EVENT_RECOVERED)
    await walk(hass, freezer, 6 * H)
    coord = await _options(hass, **{CONF_FREEZE_DELTA_LOW: 8, CONF_FREEZE_DELTA_HIGH: 12})
    record = rec(coord, device.id)
    seen = []
    for _ in range(5):
        await walk(hass, freezer, 60)
        seen.append(record[DEV_FROZEN_CATEGORY])
    assert all(v == FREEZE_CATEGORY_FROZEN for v in seen), seen
    assert not _downs(events, device.id)


async def test_the_upgrade_does_not_clear_a_standing_freeze(hass: HomeAssistant, hass_storage, freezer):
    """Storage from an older release: a device taken back and frozen
    since still carries its set-aside stamp and no return. The load
    keeps it frozen; the upgrade is not its return (rule WATCH-08)."""
    coord, device, eids = await _ready(hass, freezer, "u02")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, H)
    coord = await _aside(hass, device, False)
    assert await _frozen_at(hass, freezer, coord, device.id, window + H) is not None
    await walk(hass, freezer, 2 * H)
    events = record_events(hass, EVENT_RECOVERED)

    def as_0256():
        for stored in hass_storage[STORAGE_KEY]["data"][DATA_DEVICES].values():
            if isinstance(stored, dict):
                stored.pop(DEV_WATCHED_FROM, None)

    coord = await restart(hass, freezer, down=120, before_setup=as_0256)
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    seen = []
    for _ in range(5):
        await walk(hass, freezer, 60)
        seen.append(record[DEV_FROZEN_CATEGORY])
    assert all(v == FREEZE_CATEGORY_FROZEN for v in seen), seen
    assert not _downs(events, device.id)


async def test_a_second_stretch_frozen_when_set_aside_reads_frozen_at_once(hass: HomeAssistant, freezer):
    """Excluded ten minutes after its last report, back, frozen a window
    after the return, excluded again while frozen, back again: it was
    past its window when set aside the second time, so it reads frozen
    at once, not a window later."""
    coord, device, eids = await _ready(hass, freezer, "u03")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, H)
    coord = await _aside(hass, device, False)
    assert await _frozen_at(hass, freezer, coord, device.id, window + H) is not None
    await walk(hass, freezer, 1800)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, H)
    coord = await _aside(hass, device, False)
    again = await _frozen_at(hass, freezer, coord, device.id, window + H)
    assert again is not None and again <= 300, (again, window)


async def test_a_second_stretch_is_read_on_its_own(hass: HomeAssistant, freezer):
    """Ten minutes watched, set aside five hours (longer than the window),
    back, thirty minutes watched, set aside an hour, back. Forty minutes
    of watched silence is not past the window: the first long stretch
    does not make the second return read frozen at once."""
    coord, device, eids = await _ready(hass, freezer, "u04")
    window = coord._freeze_window(rec(coord, device.id))
    assert window < 5 * H
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, 5 * H)
    coord = await _aside(hass, device, False)
    await walk(hass, freezer, 1800)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, H)
    coord = await _aside(hass, device, False)
    took = await _frozen_at(hass, freezer, coord, device.id, window + H)
    assert took is not None and took >= window - 2400 - 180, (took, window)


async def test_a_freeze_cleared_without_a_report_does_not_count_unwatched_hours(
    hass: HomeAssistant, freezer
):
    """Excluded three hours, back, frozen a window after the return, and
    cleared by a slider change with no report. The recovery counts from
    when it was watched again, not across the three unwatched hours
    (rule UNAV-07)."""
    coord, device, eids = await _ready(hass, freezer, "u05")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, 3 * H)
    coord = await _aside(hass, device, False)
    back = dt_util.utcnow().timestamp()
    assert await _frozen_at(hass, freezer, coord, device.id, window + H) is not None
    events = record_events(hass, EVENT_RECOVERED)
    await walk(hass, freezer, 1800)
    coord = await _options(hass, **{CONF_FREEZE_DELTA_LOW: 8, CONF_FREEZE_DELTA_HIGH: 12})
    await walk(hass, freezer, 180)
    downs = _downs(events, device.id)
    assert downs and downs[-1] is not None
    told = downs[-1]
    cleared = dt_util.utcnow().timestamp()
    assert told <= cleared - back + 60 and told >= cleared - back - 600, (told, cleared - back)
    incidents = [
        i.get("duration") for i in coord.data.get("incidents") or []
        if i.get("device_id") == device.id and i.get("duration") is not None
    ]
    assert incidents and abs(incidents[-1] - told) < 1, (incidents, told)


async def test_a_device_taken_back_then_frozen_counts_from_its_return(
    hass: HomeAssistant, freezer
):
    """Excluded three hours, back, frozen a window after the return, then
    it reports: down for counts from when it was watched again
    (rule UNAV-07)."""
    coord, device, eids = await _ready(hass, freezer, "u10")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    await walk(hass, freezer, 3 * H)
    coord = await _aside(hass, device, False)
    back = dt_util.utcnow().timestamp()
    assert await _frozen_at(hass, freezer, coord, device.id, window + H) is not None
    events = record_events(hass, EVENT_RECOVERED)
    await walk(hass, freezer, 1200)
    hass.states.async_set(eids[0], "30")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    want = dt_util.utcnow().timestamp() - back
    downs = _downs(events, device.id)
    assert downs and abs(downs[-1] - want) <= 180, (downs, want)


async def test_a_clock_set_back_while_set_aside(hass: HomeAssistant, freezer):
    """Excluded ten minutes after its last report, the clock set back six
    hours, taken back three hours later, dead: frozen a window after the
    return, not at once."""
    coord, device, eids = await _ready(hass, freezer, "u06")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    coord = await _aside(hass, device, True)
    box = {"off": 0.0}
    coord._monotonic = lambda: time.monotonic() + box["off"]
    await walk(hass, freezer, 300)
    await tick(hass, freezer, step=60)
    freezer.tick(timedelta(seconds=-6 * H))
    box["off"] += 6 * H
    freezer.tick(timedelta(seconds=60))
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    for _ in range(180):
        freezer.tick(timedelta(seconds=60))
        await coord._on_render_tick(None)
    await hass.async_block_till_done()
    coord = await _aside(hass, device, False)
    coord._monotonic = lambda: time.monotonic() + box["off"]
    record = rec(coord, device.id)
    took = None
    for step in range(int((window + 2 * H) // 60)):
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            took = step * 60
            break
        freezer.tick(timedelta(seconds=60))
        await coord._on_render_tick(None)
        await hass.async_block_till_done()
    assert took is not None and took >= window - 900, (took, window)


async def test_a_freeze_turned_unavailable_keeps_its_start_across_a_restart(
    hass: HomeAssistant, freezer
):
    """Frozen, unavailable twenty minutes later, a restart, back: the
    trouble began as a freeze, so it counts from the last report, in the
    event and in the brief, restart or not (rule UNAV-07)."""
    coord, device, eids = await _ready(hass, freezer, "u07")
    record = rec(coord, device.id)
    last = dt_util.utcnow().timestamp()
    assert await _until(hass, freezer, record, FREEZE_CATEGORY_FROZEN, 4 * H) is not None
    await walk(hass, freezer, 1200)
    hass.states.async_set(eids[0], "unavailable")
    await hass.async_block_till_done()
    assert await _until(hass, freezer, record, FREEZE_CATEGORY_UNAVAILABLE, 900) is not None
    coord = await restart(hass, freezer, down=120)
    events = record_events(hass, EVENT_RECOVERED)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 900)
    hass.states.async_set(eids[0], "30")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    want = dt_util.utcnow().timestamp() - last
    downs = _downs(events, device.id)
    assert downs and abs(downs[-1] - want) <= 300, (downs, want)
    incidents = [
        i.get("duration") for i in coord.data.get("incidents") or []
        if i.get("device_id") == device.id and i.get("duration") is not None
        and not i.get("superseded")
    ]
    assert incidents and abs(incidents[-1] - want) <= 300, (incidents, want)


@pytest.mark.parametrize("how", ["exclude", "disable"])
async def test_a_return_made_while_device_sentinel_was_unloaded_is_dated(
    hass: HomeAssistant, freezer, how
):
    """Set aside ten minutes after its last report, three hours unwatched,
    Device Sentinel unloaded, the device taken back meanwhile, Device
    Sentinel loaded again: judged a window after the return, not at once
    (rule WATCH-08)."""
    coord, device, eids = await _ready(hass, freezer, f"u08{how}")
    window = coord._freeze_window(rec(coord, device.id))
    await walk(hass, freezer, 600)
    registry = dr.async_get(hass)
    if how == "exclude":
        coord = await _aside(hass, device, True)
    else:
        registry.async_update_device(device.id, disabled_by=dr.DeviceEntryDisabler.USER)
        await registry_settled(hass)
    await walk(hass, freezer, 3 * H)
    entry = entry_of(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    if how == "exclude":
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_EXCLUDED_DEVICES: []})
    else:
        registry.async_update_device(device.id, disabled_by=None)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    took = await _frozen_at(hass, freezer, coord, device.id, window + H)
    assert took is None or took >= window - 900, (took, window)


@pytest.mark.parametrize("value", ["fro zen", "unavailable", 7])
async def test_a_damaged_start_kind_does_not_shorten_a_freeze(
    hass: HomeAssistant, hass_storage, freezer, value
):
    """A standing freeze whose saved start kind is damaged, or names
    another kind: a freeze began as a freeze, so the recovery counts from
    the last report (rule UNAV-07)."""
    coord, device, eids = await _ready(hass, freezer, f"u09{str(value).replace(' ', '')}")
    record = rec(coord, device.id)
    last = dt_util.utcnow().timestamp()
    assert await _until(hass, freezer, record, FREEZE_CATEGORY_FROZEN, 4 * H) is not None
    await walk(hass, freezer, 1200)

    def damage():
        hass_storage[STORAGE_KEY]["data"][DATA_DEVICES][device.id][DEV_DOWN_BEGAN_AS] = value

    coord = await restart(hass, freezer, down=120, before_setup=damage)
    events = record_events(hass, EVENT_RECOVERED)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 600)
    hass.states.async_set(eids[0], "30")
    await hass.async_block_till_done()
    await tick(hass, freezer)
    want = dt_util.utcnow().timestamp() - last
    downs = _downs(events, device.id)
    assert downs and abs(downs[-1] - want) <= 300, (downs, want)
