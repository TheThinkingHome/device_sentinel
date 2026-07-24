# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v087_split_phase_a.py, Version: 0.8.7 (2026-07-24)

"""0.8.7 tests: the storage split, phase A.

The clocks file is written on the same triggers as storage and never
read. That is the whole safety argument, so it is what these assert:
the shadow exists and carries the right fields, the running system
still loads everything from the original file, and a shadow that is
entirely wrong changes nothing.
"""

import json
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BACKUP_SUFFIX_PRE_SPLIT,
    CLOCK_FIELDS,
    DATA_DEVICES,
    DATA_SPLIT_BACKUP,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
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


async def _entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _clocks(hass_storage):
    """The shadow as the harness stored it; storage is mocked here."""
    return hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]


# ------------------------------------------------------ the shadow

async def test_the_clocks_file_is_written(
    hass: HomeAssistant, hass_storage
):
    device, entity_id = _register(hass, "c1", "Clock Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    await coord._save_now()

    assert STORAGE_CLOCKS_KEY in hass_storage
    clocks = _clocks(hass_storage)
    assert device.id in clocks
    assert set(clocks[device.id]) == set(CLOCK_FIELDS)


async def test_the_shadow_agrees_with_storage(
    hass: HomeAssistant, hass_storage
):
    """What the rig will check daily, asserted here once."""
    device, entity_id = _register(hass, "c2", "Agreeing Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    await coord._save_now()

    clocks = _clocks(hass_storage)
    for device_id, record in coord.data[DATA_DEVICES].items():
        for field in CLOCK_FIELDS:
            assert clocks[device_id][field] == record.get(field), (
                device_id,
                field,
            )


async def test_the_shadow_carries_only_the_hot_fields(
    hass: HomeAssistant, hass_storage
):
    """Cold data stays cold: a shadow carrying the learned series
    would save nothing at cutover."""
    device, entity_id = _register(hass, "c3", "Cold Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    coord.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] = [1.0, 2.0]
    await coord._save_now()
    assert DEV_DAILY_MAX not in _clocks(hass_storage)[device.id]


async def test_nothing_reads_the_shadow(
    hass: HomeAssistant, hass_storage
):
    """The safety argument for the whole phase: corrupt the shadow
    completely, restart, and the system is unaffected because it
    still loads everything from storage."""
    device, entity_id = _register(hass, "c4", "Ignored Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = 1234.0
    await coord._save_now()

    hass_storage[STORAGE_CLOCKS_KEY]["data"] = {"clocks": "nonsense"}

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data
    assert reloaded.data[DATA_DEVICES][device.id][
        DEV_LAST_ACTIVITY
    ] == 1234.0


# ------------------------------------------------------ the backup

async def test_the_backup_marker_is_set_once(hass: HomeAssistant):
    """The marker means a later start does not try again."""
    entry = await _entry(hass)
    assert entry.runtime_data.data[DATA_SPLIT_BACKUP] is True


async def test_the_backup_copies_and_never_overwrites(
    hass: HomeAssistant,
):
    """The restore point for the whole split. Written from the real
    file, and refusing to overwrite, which is why retaking it is
    harmless and needs no save of its own."""
    entry = await _entry(hass)
    coord = entry.runtime_data
    source = hass.config.path(".storage", STORAGE_KEY)
    backup = source + BACKUP_SUFFIX_PRE_SPLIT
    os.makedirs(os.path.dirname(source), exist_ok=True)
    for path in (source, backup):
        if os.path.isfile(path):
            os.remove(path)
    with open(source, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "data": {"devices": {"d": {}}}}, handle)

    assert await coord._take_pre_split_backup()
    with open(backup, encoding="utf-8") as handle:
        assert "devices" in json.load(handle)["data"]

    # A second call finds the file already there and leaves it alone.
    with open(source, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "data": {"devices": {}}}, handle)
    assert await coord._take_pre_split_backup()
    with open(backup, encoding="utf-8") as handle:
        assert json.load(handle)["data"]["devices"] == {"d": {}}
    os.remove(source)
    os.remove(backup)

async def test_the_shadow_exists_from_the_first_moment(
    hass: HomeAssistant, hass_storage
):
    """0.8.8: setup writes storage directly rather than through
    _save_now, so without an explicit write here the clocks file did
    not appear until the first coalesced save up to a window later,
    and a system restarting inside that window never produced one.

    It mirrors whatever storage held at that instant, so on a fresh
    install it is legitimately empty and on an existing one it
    carries every device from the first moment.
    """
    _register(hass, "s1", "Immediate Sensor")
    entry = await _entry(hass)
    assert STORAGE_CLOCKS_KEY in hass_storage
    assert "clocks" in hass_storage[STORAGE_CLOCKS_KEY]["data"]

    # Once devices are known, the next save carries them.
    await entry.runtime_data._save_now()
    assert hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]


async def test_the_split_state_reaches_diagnostics(
    hass: HomeAssistant,
):
    """It was confirmable only from a terminal, which is no way to
    verify a release (0.8.8)."""
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _register(hass, "d1", "Diag Sensor")
    entry = await _entry(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    split = diag["split"]
    assert split["pre_split_backup_taken"] is True
    assert set(split["clock_fields"]) == set(CLOCK_FIELDS)
    assert split["clock_devices"] >= 1
