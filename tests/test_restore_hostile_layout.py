# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_restore_hostile_layout.py, Version: 0.28.12 (2026-11-11)

"""The restore and the empty start beside kept files (rule STOR-08).

Device Sentinel reads the restored main file straight off the disk
(backup.read_main_file_raw, with Home Assistant's own reader), and an empty start beside a
last-good copy or a history file sets _fresh_beside_kept, which stops
that session's saves from rotating over the copy, copying over it or
removing the history files (rule STOR-08).

Someone or something that can write into config/.storage (an add-on, a
Samba share, a backup restored from elsewhere, a hand edit) lays out the
files. Safe: Device Sentinel starts, never hangs, never writes outside
its own names, and never destroys what the house had.

Every test asserts the safe behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import asyncio
import json
import os

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    STORAGE_HISTORY_KEY,
    STORAGE_KEY,
)

LAST_GOOD = f"{STORAGE_KEY}.last-good"
HISTORY_LAST_GOOD = f"{STORAGE_HISTORY_KEY}.last-good"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def _stop(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_fifo_at_last_good_never_hangs_the_start(hass: HomeAssistant, real_disk):
    """The main file missing and a FIFO at the last-good name: every
    open() of last-good (_last_good_holds_devices, through
    async_diagnose_empty_load and kept_beside_a_fresh_start) blocks an
    executor thread until a writer comes. Safe: the start finishes.28.12 adds a second blocking open). The test unblocks
    the reader itself so the run never hangs."""
    from tests.helpers import setup_entry, start_storage_as_home_assistant_does

    entry = await setup_entry(hass)
    await _stop(hass, entry)
    os.remove(os.path.join(real_disk, STORAGE_KEY))
    copy = os.path.join(real_disk, LAST_GOOD)
    if os.path.lexists(copy):
        os.remove(copy)
    os.mkfifo(copy)
    await start_storage_as_home_assistant_does(hass)
    task = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
    done, _ = await asyncio.wait({task}, timeout=15)
    hung = not done
    # Release every blocked reader so the test always ends.
    for _ in range(200):
        if task.done():
            break
        try:
            handle = os.open(copy, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            pass
        else:
            os.close(handle)
        await asyncio.sleep(0.05)
    await task
    await hass.async_block_till_done()
    os.remove(copy)
    assert not hung, "the start hung on a FIFO at last-good"


async def test_a_deeply_nested_last_good_never_stops_the_start(hass: HomeAssistant, real_disk):
    """The main file missing and last-good nested 100,000 deep: read
    as Home Assistant reads it, refused as damaged, never a traceback.
    Safe: the start goes on as a first install with the copy left as
    it is."""
    from tests.helpers import setup_entry, start_storage_as_home_assistant_does

    entry = await setup_entry(hass)
    await _stop(hass, entry)
    os.remove(os.path.join(real_disk, STORAGE_KEY))
    copy = os.path.join(real_disk, LAST_GOOD)
    depth = 100_000
    with open(copy, "w", encoding="utf-8") as handle:
        handle.write('{"version": 1, "data": {"devices": {"x": ' + "[" * depth + "]" * depth + "}}}")
    before = _read(copy)
    await start_storage_as_home_assistant_does(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _read(copy) == before


async def test_a_last_good_hard_linked_to_another_file_never_changes_it(
    hass: HomeAssistant, real_disk
):
    """last-good made a hard link to a JSON file elsewhere in the config
    folder that looks like a Device Sentinel file. The restore copies
    it in; the rotations and copies that follow must replace the name,
    never write through the link """
    from tests.test_history_file import restart_with
    from tests.test_storage_restore_real_start import _house

    entry, coord, ids = await _house(hass)
    victim = hass.config.path("someone_elses.json")
    copy = os.path.join(real_disk, LAST_GOOD)
    with open(copy, encoding="utf-8") as handle:
        document = json.load(handle)
    with open(victim, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    before = _read(victim)

    def plant():
        os.remove(os.path.join(real_disk, STORAGE_KEY))
        os.remove(copy)
        os.link(victim, copy)

    try:
        coord2 = await restart_with(hass, entry, plant)
        for _ in range(3):
            coord2._dirty = True
            await coord2._save_now()
        assert _read(victim) == before
    finally:
        os.remove(victim)


async def test_a_big_integer_in_a_restored_copy_never_stops_every_save(
    hass: HomeAssistant, real_disk
):
    """A field this version does not know, kept as written by a newer
    one (rule STOR-19), holding an integer past 64 bits, which Home
    Assistant's writer cannot write. Read with Home Assistant's own
    reader, the restore refuses it as the Store would, so no session
    starts whose every save would fail."""
    from tests.test_history_file import restart_with
    from tests.test_storage_restore_real_start import _house

    entry, coord, ids = await _house(hass)
    copy = os.path.join(real_disk, LAST_GOOD)
    big = 2**70

    def plant():
        os.remove(os.path.join(real_disk, STORAGE_KEY))
        with open(copy, encoding="utf-8") as handle:
            document = json.load(handle)
        document["data"][DATA_DEVICES][ids[0]]["zz_newer_field"] = big
        with open(copy, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    coord2 = await restart_with(hass, entry, plant)
    assert coord2._restored_from is not None  # the premise
    for _ in range(2):
        coord2._dirty = True
        await coord2._save_now()
    await hass.async_block_till_done()
    assert str(big) not in _read(os.path.join(real_disk, STORAGE_KEY))


async def test_an_empty_start_keeps_the_old_history_however_long_it_runs(
    hass: HomeAssistant, real_disk
):
    """However long the session runs, it writes no history file of
    its own, which would turn the old history file into last-good and
    replace it: that session never takes their place (rule STOR-08)."""
    from tests.test_history_file import furnish, restart_with
    from tests.test_storage_restore_real_start import _house

    entry, coord, ids = await _house(hass)
    copy = os.path.join(real_disk, LAST_GOOD)

    def damage():
        os.remove(os.path.join(real_disk, STORAGE_KEY))
        with open(copy, "a", encoding="utf-8") as handle:
            handle.write("not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._fresh_beside_kept  # the premise
    kept = _read(os.path.join(real_disk, STORAGE_HISTORY_KEY))
    kept_copy = _read(os.path.join(real_disk, HISTORY_LAST_GOOD))
    # Forty days of this session's own learning.
    for device_id in ids:
        record = coord2.data[DATA_DEVICES].get(device_id)
        if record is not None:
            furnish(record, 40)
    for _ in range(3):
        coord2._dirty = True
        await coord2._save_now()
    assert _read(os.path.join(real_disk, STORAGE_HISTORY_KEY)) == kept
    assert _read(os.path.join(real_disk, HISTORY_LAST_GOOD)) == kept_copy


async def test_a_directory_at_the_history_name_never_stops_a_first_start(
    hass: HomeAssistant, real_disk
):
    """A directory where the history file belongs, on a first install:
    the start goes on and its main file saves """
    from tests.helpers import start_storage_as_home_assistant_does, setup_entry

    history = os.path.join(real_disk, STORAGE_HISTORY_KEY)
    os.mkdir(history)
    try:
        await start_storage_as_home_assistant_does(hass)
        entry = await setup_entry(hass)
        coord = entry.runtime_data
        coord._dirty = True
        await coord._save_now()
        assert os.path.isfile(os.path.join(real_disk, STORAGE_KEY))
        await _stop(hass, entry)
    finally:
        os.rmdir(history)
