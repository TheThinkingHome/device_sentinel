# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_registry_bursts.py, Version: 0.24.2 (2026-10-03)

"""A burst of registry changes rebuilds Device Sentinel's view once, not once per change.

Every device, entity or label change rebuilt Device Sentinel's whole
view of the registry at once, on Home Assistant's main loop, where
nothing else runs meanwhile. On a house of 1,500 devices one rebuild
took about 45 ms, so 100 changes held Home Assistant for about 4.5
seconds, and one press of Enable Last Seen on 1,500 entities held it
for over a minute. Found after Frank_Beetz's forum report of Device
Sentinel freezing his system. A 2-second debouncer now rebuilds at
once when no rebuild ran in the last 2 seconds, and otherwise once
when the 2 seconds end. These tests count rebuilds, so they do not
depend on the machine's speed.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import CONF_MUTED_LABELS

from .helpers import register_device, setup_entry


def _count(coord):
    """Wrap the rebuild so each call is counted."""
    tally = [0]
    real = coord._rebuild_registry_view

    def counted(*args, **kwargs):
        tally[0] += 1
        return real(*args, **kwargs)

    coord._rebuild_registry_view = counted
    return tally


async def _quiet(hass, seconds=5):
    """Let every cooldown run out. A trailing rebuild starts a fresh
    cooldown of its own, so time is moved on until none is left."""
    for _ in range(3):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await hass.async_block_till_done()


async def _house(hass, devices=20, options=None):
    made = [register_device(hass, f"rb{i}", f"Device {i}") for i in range(devices)]
    entry = await setup_entry(hass, options)
    coord = entry.runtime_data
    await _quiet(hass)
    return entry, coord, made


def _entity_id(entities):
    first = entities[0]
    return first.entity_id if hasattr(first, "entity_id") else first


async def test_a_burst_of_changes_rebuilds_at_once_then_once_more(hass: HomeAssistant):
    _entry, coord, made = await _house(hass)
    tally = _count(coord)
    ents = er.async_get(hass)
    for i, (_device, entities) in enumerate(made):
        for n in range(5):
            ents.async_update_entity(_entity_id(entities), original_name=f"renamed {i}.{n}")
    await hass.async_block_till_done()
    assert tally[0] == 1, f"{tally[0]} rebuilds for one burst of 100 changes"
    await _quiet(hass)
    assert tally[0] == 2, "the burst's last changes were not rebuilt when the cooldown ended"


async def test_the_enable_sweep_rebuilds_twice_not_once_per_entity(hass: HomeAssistant):
    _entry, coord, made = await _house(hass)
    ents = er.async_get(hass)
    for i, (device, _entities) in enumerate(made):
        ents.async_get_or_create(
            "sensor", "test", f"rb{i}_last_seen", device_id=device.id,
            original_name="Last seen", original_device_class="timestamp",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )
    await _quiet(hass)
    tally = _count(coord)
    await coord.async_enable_last_seen_entities()
    await hass.async_block_till_done()
    await _quiet(hass)
    assert tally[0] <= 2, f"the Enable sweep rebuilt {tally[0]} times"


async def test_a_single_edit_after_a_quiet_spell_rebuilds_at_once(hass: HomeAssistant):
    _entry, coord, made = await _house(hass)
    tally = _count(coord)
    er.async_get(hass).async_update_entity(_entity_id(made[0][1]), original_name="one edit")
    await hass.async_block_till_done()
    assert tally[0] == 1, "a single edit after a quiet spell was not rebuilt at once"


async def test_an_edit_inside_a_cooldown_waits_for_its_end(hass: HomeAssistant):
    _entry, coord, made = await _house(hass)
    tally = _count(coord)
    ents = er.async_get(hass)
    ents.async_update_entity(_entity_id(made[0][1]), original_name="first")
    await hass.async_block_till_done()
    ents.async_update_entity(_entity_id(made[1][1]), original_name="second")
    await hass.async_block_till_done()
    assert tally[0] == 1, "an edit inside the cooldown rebuilt at once"
    await _quiet(hass)
    assert tally[0] == 2, "the edit inside the cooldown was never rebuilt"


async def test_a_new_device_is_watched_once_the_cooldown_ends(hass: HomeAssistant):
    """The cost of the hold: a device added during a cooldown is not yet
    in the view, so its first states are not counted; it is once the
    cooldown ends."""
    _entry, coord, made = await _house(hass)
    er.async_get(hass).async_update_entity(_entity_id(made[0][1]), original_name="opens a cooldown")
    await hass.async_block_till_done()
    device, entities = register_device(hass, "late", "Late Device")
    await hass.async_block_till_done()
    eid = _entity_id(entities)
    assert eid not in coord._entity_map, "the new device was taken in during the cooldown"
    await _quiet(hass)
    assert coord._entity_map.get(eid, (None,))[0] == device.id, "the new device was never taken in"


async def test_a_label_mute_takes_effect_once_the_cooldown_ends(hass: HomeAssistant):
    labels = lr.async_get(hass)
    quiet = labels.async_create("Quiet")
    _entry, coord, made = await _house(hass, options={CONF_MUTED_LABELS: [quiet.label_id]})
    devices = dr.async_get(hass)
    devices.async_update_device(made[1][0].id, name_by_user="opens a cooldown")
    await hass.async_block_till_done()
    devices.async_update_device(made[0][0].id, labels={quiet.label_id})
    await hass.async_block_till_done()
    assert made[0][0].id not in coord._muted_devices, "the label mute applied during the cooldown"
    await _quiet(hass)
    assert coord._muted_devices.get(made[0][0].id) == "label", "the label mute never applied"


async def test_an_entity_moved_between_devices_follows_once_the_cooldown_ends(hass: HomeAssistant):
    _entry, coord, made = await _house(hass)
    ents = er.async_get(hass)
    (first, first_entities), (second, _second) = made[0], made[1]
    eid = _entity_id(first_entities)
    ents.async_update_entity(_entity_id(made[2][1]), original_name="opens a cooldown")
    await hass.async_block_till_done()
    ents.async_update_entity(eid, device_id=second.id)
    await hass.async_block_till_done()
    assert coord._entity_map[eid][0] == first.id, "the move applied during the cooldown"
    await _quiet(hass)
    assert coord._entity_map[eid][0] == second.id, "the move never applied"


async def test_no_rebuild_runs_after_the_entry_unloads(hass: HomeAssistant):
    entry, coord, made = await _house(hass)
    ents = er.async_get(hass)
    ents.async_update_entity(_entity_id(made[0][1]), original_name="first")
    await hass.async_block_till_done()
    ents.async_update_entity(_entity_id(made[1][1]), original_name="pending")
    await hass.async_block_till_done()
    tally = _count(coord)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _quiet(hass)
    assert tally[0] == 0, "a rebuild ran after the entry unloaded"


async def test_a_removed_muted_device_is_named_at_once(hass: HomeAssistant, caplog):
    """Its name exists only until the removal completes, so naming it
    cannot wait for the cooldown."""
    made = [register_device(hass, f"rm{i}", f"Muted {i}") for i in range(3)]
    entry = await setup_entry(hass, {"muted_devices": [made[0][0].id]})
    await _quiet(hass)
    er.async_get(hass).async_update_entity(_entity_id(made[1][1]), original_name="opens a cooldown")
    await hass.async_block_till_done()
    dr.async_get(hass).async_remove_device(made[0][0].id)
    await hass.async_block_till_done()
    assert "Muted 0" in caplog.text and "removed from Home Assistant" in caplog.text
    assert entry.runtime_data is not None


# ----------------------------------------------- inside the 2-second window


async def _everything_runs(hass, entry, coord, device_id):
    """The minute check, the Problem List, the reports, the dashboard,
    the device's own page and the diagnostics, inside the window."""
    from custom_components.device_sentinel import diagnostics

    await coord._on_render_tick(None)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports)
    coord.dashboard_devices()
    coord.dashboard_device(device_id)
    await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    await hass.async_block_till_done()


async def _inside_a_cooldown(hass):
    entry, coord, made = await _house(hass, devices=6)
    er.async_get(hass).async_update_entity(_entity_id(made[5][1]), original_name="opens a cooldown")
    await hass.async_block_till_done()
    return entry, coord, made


async def test_a_device_removed_inside_the_window(hass: HomeAssistant):
    entry, coord, made = await _inside_a_cooldown(hass)
    gone = made[0][0].id
    dr.async_get(hass).async_remove_device(gone)
    await hass.async_block_till_done()
    await _everything_runs(hass, entry, coord, gone)
    await _quiet(hass)
    assert gone not in coord._watched


async def test_an_entity_removed_inside_the_window(hass: HomeAssistant):
    entry, coord, made = await _inside_a_cooldown(hass)
    eid = _entity_id(made[0][1])
    er.async_get(hass).async_remove(eid)
    await hass.async_block_till_done()
    await _everything_runs(hass, entry, coord, made[0][0].id)
    await _quiet(hass)
    assert eid not in coord._entity_map


async def test_an_entity_moved_inside_the_window(hass: HomeAssistant):
    entry, coord, made = await _inside_a_cooldown(hass)
    eid = _entity_id(made[0][1])
    er.async_get(hass).async_update_entity(eid, device_id=made[1][0].id)
    await hass.async_block_till_done()
    await _everything_runs(hass, entry, coord, made[0][0].id)
    await _quiet(hass)
    assert coord._entity_map[eid][0] == made[1][0].id


async def test_a_device_disabled_inside_the_window(hass: HomeAssistant):
    entry, coord, made = await _inside_a_cooldown(hass)
    target = made[0][0].id
    dr.async_get(hass).async_update_device(target, disabled_by=dr.DeviceEntryDisabler.USER)
    await hass.async_block_till_done()
    await _everything_runs(hass, entry, coord, target)
    await _quiet(hass)
    assert target not in coord._watched


async def test_a_label_renamed_inside_the_window(hass: HomeAssistant):
    labels = lr.async_get(hass)
    quiet = labels.async_create("Quiet")
    entry, coord, made = await _house(hass, devices=6, options={CONF_MUTED_LABELS: [quiet.label_id]})
    dr.async_get(hass).async_update_device(made[0][0].id, labels={quiet.label_id})
    await _quiet(hass)
    er.async_get(hass).async_update_entity(_entity_id(made[5][1]), original_name="opens a cooldown")
    await hass.async_block_till_done()
    labels.async_update(quiet.label_id, name="Silent")
    await hass.async_block_till_done()
    await _everything_runs(hass, entry, coord, made[0][0].id)
    await _quiet(hass)
    assert coord._muted_devices.get(made[0][0].id) == "label"
