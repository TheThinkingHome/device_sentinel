# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storage_restore_real_start.py, Version: 0.28.12 (2026-11-11)

"""A restore works on a real start of Home Assistant (rule STOR-08).

At start Home Assistant lists the files in .storage once, and a Store
whose file was not on that list reads as missing from then on, without
looking at the disk. The restore put the main file back from last-good
and read it back through the Store, which still answered "missing", so
the start went on empty: the next saves wrote over last-good and
removed the history files. The harness never makes the list, so every
test passed. A real Home Assistant showed it.

These tests start Home Assistant's storage as a real start does
(helpers.start_storage_as_home_assistant_does):

- a main file missing beside a last-good copy is restored, and the
  devices, the copy and the history files are all still there after
  the saves that follow;
- a start that has to begin empty, beside a copy it could not use and
  history files, never takes their place in that session;
- the history file's last-good copy, kept by a link the Store never
  sees, still reads in the run that made it: the copy written through
  the Store at the fourth step of each history save puts it on the
  list, so it needs no read from the disk.
"""

from __future__ import annotations

import json
import os

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_DEVICES, STORAGE_HISTORY_KEY, STORAGE_KEY

from .helpers import start_storage_as_home_assistant_does
from .test_history_file import furnished, restart_with

LAST_GOOD = f"{STORAGE_KEY}.last-good"
HISTORY_LAST_GOOD = f"{STORAGE_HISTORY_KEY}.last-good"


def _devices(directory: str, name: str) -> int | None:
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return len(json.load(handle)["data"].get(DATA_DEVICES) or {})


async def _house(hass: HomeAssistant):
    """Two devices, forty days each: a main file, its last-good copy,
    and both history files."""
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()
    await coord._save_now()
    return entry, coord, ids


async def test_the_scan_is_what_hid_the_fault(hass: HomeAssistant, real_disk):
    """The premise: after the scan a Store reads a file put back on
    disk as missing. Without it, as the harness ran, it reads it."""
    from homeassistant.helpers.storage import Store

    path = os.path.join(real_disk, "device_sentinel.scan_probe")
    await start_storage_as_home_assistant_does(hass)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "minor_version": 1, "key": "device_sentinel.scan_probe", "data": {"x": 1}}, handle)
    assert await Store(hass, 1, "device_sentinel.scan_probe").async_load() is None
    os.remove(path)


async def test_a_missing_main_file_is_restored_on_a_real_start(
    hass: HomeAssistant, real_disk
):
    entry, coord, ids = await _house(hass)
    before = _devices(real_disk, LAST_GOOD)
    assert before == len(ids)
    assert os.path.exists(os.path.join(real_disk, STORAGE_HISTORY_KEY))

    coord2 = await restart_with(
        hass, entry, lambda: os.remove(os.path.join(real_disk, STORAGE_KEY))
    )
    assert coord2._restored_from is not None
    assert set(ids) <= set(coord2.data[DATA_DEVICES])
    # The saves that follow keep everything.
    await coord2._save_now()
    await coord2._save_now()
    assert _devices(real_disk, STORAGE_KEY) == len(ids)
    assert _devices(real_disk, LAST_GOOD) == len(ids)
    assert os.path.exists(os.path.join(real_disk, STORAGE_HISTORY_KEY))
    # And the next start finds a whole house, with nothing to restore.
    coord3 = await restart_with(hass, entry)
    assert coord3._restored_from is None
    assert set(ids) <= set(coord3.data[DATA_DEVICES])


async def test_an_empty_start_never_takes_the_place_of_what_was_kept(
    hass: HomeAssistant, real_disk
):
    """The main file missing and its copy unusable: the start begins
    empty, as before, but its saves leave the copy and the history
    files as they were."""
    entry, coord, ids = await _house(hass)
    copy = os.path.join(real_disk, LAST_GOOD)

    def damage():
        os.remove(os.path.join(real_disk, STORAGE_KEY))
        with open(copy, "a", encoding="utf-8") as handle:
            handle.write("not json")

    coord2 = await restart_with(hass, entry, damage)
    with open(copy, encoding="utf-8") as handle:
        kept_copy = handle.read()
    with open(os.path.join(real_disk, STORAGE_HISTORY_KEY), encoding="utf-8") as handle:
        kept_history = handle.read()
    assert coord2._fresh_beside_kept
    for _ in range(3):
        coord2._dirty = True
        await coord2._save_now()
    with open(copy, encoding="utf-8") as handle:
        assert handle.read() == kept_copy
    with open(os.path.join(real_disk, STORAGE_HISTORY_KEY), encoding="utf-8") as handle:
        assert handle.read() == kept_history
    assert os.path.exists(os.path.join(real_disk, HISTORY_LAST_GOOD))
    # And they were copied aside, so a later start, which reads the new
    # main file as clean, cannot take the only copy.
    evidence = hass.config.path("device_sentinel", "trim_backups")
    names = os.listdir(evidence)
    assert any(name.endswith(".history.evidence") for name in names), names
    assert any(name.endswith(".storage.last-good") for name in names), names


async def test_a_genuine_first_install_is_not_held_back(hass: HomeAssistant, real_disk):
    """Nothing beside it: the first install saves and rotates as ever."""
    from .helpers import setup_entry

    await start_storage_as_home_assistant_does(hass)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert not coord._fresh_beside_kept


async def test_the_history_copy_is_read_when_the_history_file_is_gone(
    hass: HomeAssistant, real_disk
):
    """The copy is kept by a link, which Home Assistant's list of files
    never hears of. Read in the same run that made it, it is found,
    because the fourth step of the history save writes it through the
    Store first."""
    from custom_components.device_sentinel import history_file

    # The list is made before the house writes its files, as on a
    # first start: the copy is made later in the same run.
    await start_storage_as_home_assistant_does(hass)
    entry, coord, ids = await _house(hass)
    assert os.path.exists(os.path.join(real_disk, HISTORY_LAST_GOOD))
    data, why = await history_file.read_copy(hass, last_good=True)
    assert why is None and isinstance(data, dict)
