# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_clock_strip.py, Version: 0.12.13 (2026-08-07)

"""The final phase of the storage split: the main file sheds the clocks.

The two-file split (#101) put the nine per-device clock fields in a
small hot file written every interval, and left copies of them in the
main file purely as a rollback net: an older version loads the main
file alone and loses nothing. This phase removes the copies. The
witness watched the two files disagree zero times across every daily
line of the soak, which is the evidence the copies are dead weight.

Removing them changes two other things, and both are ruled:

The merge rule (#101). Three of the old merge's four exits fell back
to the main file's copies, and after the strip all three would mean a
fleet loading with no clocks at all. The rule is now data-driven:
whether the main file still carries clocks is read from the records
themselves, so the same code is correct on a stripped install, on one
whose backup failed, and on a pre-0.10.0 file with no stamps.

The backup (#130). The strip is the first step in the split that a
rollback cannot survive unaided, so the release that strips takes a
copy of both files before it changes anything, and a copy that cannot
be taken stops the strip rather than the boot: the main file simply
keeps carrying the clocks, which loses nothing.

Three tests were retired with the transition they guarded (ruling #241): the backup that preceded the strip, the gate that kept writing clock copies where it failed, and the merge branch that preferred a main file still carrying them. The strip is unconditional now and the main file never carries clocks, so those states cannot occur.
"""

from __future__ import annotations

import os
import time

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from .helpers import register_device, setup_entry

# Anchored to the run rather than to a calendar date, for the reason
# recorded in test_unclean_restart: a literal epoch ages, and these
# fixtures have to stay inside the retention windows they are read
# against. An hour back leaves room for a hot file stamped later.
NOW = time.time() - 3600.0


@pytest.fixture(autouse=True)
def _clear_storage_files(hass: HomeAssistant):
    """Start and end with no real files under the storage dir.

    The harness intercepts Store reads and writes in memory, but the
    backup copies real files with shutil, and the config directory is
    shared between tests. Without this sweep a copy made by one test
    survives into the next and reads as proof of something that did
    not happen there.
    """
    def _sweep():
        directory = hass.config.path(STORAGE_DIR)
        if not os.path.isdir(directory):
            return
        for name in os.listdir(directory):
            if name.startswith(STORAGE_KEY) or name.startswith(
                STORAGE_CLOCKS_KEY
            ):
                os.remove(os.path.join(directory, name))

    _sweep()
    yield
    _sweep()


def _cold_record(with_clocks=True):
    record = {
        "name": "Phase C Device",
        DEV_EVENT_COUNT: 900 if with_clocks else None,
    }
    if with_clocks:
        record[DEV_LAST_ACTIVITY] = NOW - 300.0
    else:
        record.pop(DEV_EVENT_COUNT)
    return record


def _seed(hass_storage, device_id, *, cold_clocks, hot, hot_at=None):
    """Put a storage pair in the harness as some earlier version left it."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device_id: _cold_record(cold_clocks)},
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SAVED_AT: NOW,
            DATA_CLEAN_STOP: True,
        },
    }
    if hot:
        hass_storage[STORAGE_CLOCKS_KEY] = {
            "version": 1,
            "data": {
                DATA_SAVED_AT: hot_at if hot_at is not None else NOW + 10.0,
                "clocks": {
                    device_id: {
                        DEV_LAST_ACTIVITY: NOW - 60.0,
                        DEV_EVENT_COUNT: 901,
                    }
                },
            },
        }


async def test_the_main_file_sheds_the_clocks(
    hass: HomeAssistant, hass_storage
):
    """The point of the phase, asserted on the file itself.

    After setup's own save, no device record in the main file carries
    any of the clock fields, while the hot file carries all it
    was given. The live in-memory records keep theirs, because every
    reader in this process depends on them; only the file sheds them.
    """
    device, _ = register_device(hass, "pc1", "Phase C Device")
    _seed(hass_storage, device.id, cold_clocks=True, hot=True)

    entry = await setup_entry(hass)

    written = hass_storage[STORAGE_KEY]["data"][DATA_DEVICES][device.id]
    for field in CLOCK_FIELDS:
        assert field not in written, f"{field} still in the main file"
    hot_written = hass_storage[STORAGE_CLOCKS_KEY]["data"]["clocks"]
    assert DEV_LAST_ACTIVITY in hot_written[device.id]
    live = entry.runtime_data.data[DATA_DEVICES][device.id]
    assert DEV_LAST_ACTIVITY in live


async def test_a_stale_hot_file_is_used_once_the_main_file_is_bare(
    hass: HomeAssistant, hass_storage
):
    """The merge's changed exit, and the reason Phase C waited on it.

    A hot file older than the main file means the last write pair was
    torn. While the main file carried copies, refusing the hot file
    was right, because the newer copies were sitting right there.
    Once it is bare there is nothing to fall back to: a slightly
    stale clock heals on the device's next report, while discarding
    it resets the whole fleet, so the hot file is used whatever its
    age.
    """
    device, _ = register_device(hass, "pc4", "Phase C Device")
    _seed(
        hass_storage,
        device.id,
        cold_clocks=False,
        hot=True,
        hot_at=NOW - 500.0,
    )

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_LAST_ACTIVITY] == NOW - 60.0
    assert record[DEV_EVENT_COUNT] == 901


async def test_a_bare_main_file_with_no_hot_file_starts_over(
    hass: HomeAssistant, hass_storage
):
    """The one state with nothing to offer, taken gracefully.

    A stripped main file beside a hand-deleted clocks file has no
    clock anywhere. The fleet starts its clocks from this boot, with
    a warning naming the only way this can happen, and nothing
    crashes.
    """
    device, _ = register_device(hass, "pc6", "Phase C Device")
    _seed(hass_storage, device.id, cold_clocks=False, hot=False)

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record.get(DEV_LAST_ACTIVITY) is None or isinstance(
        record.get(DEV_LAST_ACTIVITY), float
    )


async def test_round_trip_restores_every_clock(
    hass: HomeAssistant, hass_storage
):
    """Save stripped, reload, and the clocks come back from the hot file.

    This is the whole design in one motion: the main file no longer
    carries them, the hot file does, and a reload of the entry sees
    every value it saved.
    """
    device, _ = register_device(hass, "pc7", "Phase C Device")
    _seed(hass_storage, device.id, cold_clocks=True, hot=True)
    entry = await setup_entry(hass)
    before = dict(entry.runtime_data.data[DATA_DEVICES][device.id])

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = entry.runtime_data.data[DATA_DEVICES][device.id]

    for field in (DEV_LAST_ACTIVITY, DEV_EVENT_COUNT):
        assert after[field] == before[field]
