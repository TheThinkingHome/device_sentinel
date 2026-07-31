# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_backup.py, Version: 0.10.11 (2026-07-31)

"""The copy taken before a release removes what it cannot put back.

#130 amended the split's original plan of one backup for four phases.
Rollback is free at every step while the main file goes on carrying
the clock fields unused, because an older version loads a complete
record and loses nothing. The phase that strips those fields closes
that window: afterwards, stepping back loads a file whose clocks
stopped at the moment of the strip.

This ships with no caller. The mechanism that did the job for the
earlier phases was removed in 0.10.1 once its copies had been taken,
which left the requirement with nothing behind it, and rebuilding it
inside the release that also strips would mean its first exercise is
the one run that matters. So it is built and proven here, and the
strip release adds only the call.

The behaviour that matters most is the failure path: a caller about to
remove data must be able to tell that the copy did not happen, because
doing nothing is harmless and stripping without a copy is the one step
that cannot be undone.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from custom_components.device_sentinel.backup import async_take_backup
from custom_components.device_sentinel.const import (
    BACKUP_SUFFIX_PREPHASE_C,
    BACKUP_TAKEN_KEY,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from .helpers import setup_coordinator

SUFFIX = BACKUP_SUFFIX_PREPHASE_C


@pytest.fixture(autouse=True)
def _clear_storage_files(hass: HomeAssistant):
    """Start every test from a storage directory with no copies in it.

    The harness gives every test the same config directory rather than
    a temporary one, so a file one test writes survives into the next
    and into later runs. These tests write real files, so without this
    a later test finds a backup an earlier one made and reads it as
    proof of something that did not happen here.
    """
    def _sweep():
        directory = hass.config.path(STORAGE_DIR)
        if not os.path.isdir(directory):
            return
        for name in os.listdir(directory):
            if name.startswith(f"{STORAGE_KEY}") or name.startswith(
                f"{STORAGE_CLOCKS_KEY}"
            ):
                os.remove(os.path.join(directory, name))

    _sweep()
    yield
    _sweep()


def _path(hass: HomeAssistant, name: str) -> str:
    return os.path.join(hass.config.path(STORAGE_DIR), name)


def _write(hass: HomeAssistant, name: str, body: str) -> None:
    path = _path(hass, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def _read(hass: HomeAssistant, name: str) -> str:
    with open(_path(hass, name), encoding="utf-8") as handle:
        return handle.read()


async def test_both_files_are_copied(hass: HomeAssistant):
    """The pair is copied, because the merge needs both.

    A copy of the main file alone would restore a record with no
    clocks, which is the exact state the strip creates and the backup
    exists to undo.
    """
    _write(hass, STORAGE_KEY, '{"main": 1}')
    _write(hass, STORAGE_CLOCKS_KEY, '{"clocks": 1}')
    data: dict = {}

    assert await async_take_backup(hass, data, SUFFIX)

    assert _read(hass, f"{STORAGE_KEY}.{SUFFIX}") == '{"main": 1}'
    assert _read(hass, f"{STORAGE_CLOCKS_KEY}.{SUFFIX}") == '{"clocks": 1}'


async def test_the_copy_sits_beside_the_original(hass: HomeAssistant):
    """The original is untouched, and named backups do not collide.

    #130 asks for a name of its own so this copy sits beside the
    pre-split backup rather than replacing it.
    """
    _write(hass, STORAGE_KEY, '{"main": 1}')
    _write(hass, STORAGE_CLOCKS_KEY, '{"clocks": 1}')
    _write(hass, f"{STORAGE_KEY}.pre-split", '{"older": 1}')

    assert await async_take_backup(hass, {}, SUFFIX)

    assert _read(hass, STORAGE_KEY) == '{"main": 1}'
    assert _read(hass, f"{STORAGE_KEY}.pre-split") == '{"older": 1}'


async def test_it_is_taken_once(hass: HomeAssistant):
    """A second boot must not overwrite the copy.

    After the strip the live file is no longer the thing worth
    preserving, so repeating the copy would replace the only good
    record with the stripped one. The marker rides in the storage
    payload, so it is saved with everything else.
    """
    _write(hass, STORAGE_KEY, '{"main": "before"}')
    _write(hass, STORAGE_CLOCKS_KEY, '{"clocks": 1}')
    data: dict = {}
    assert await async_take_backup(hass, data, SUFFIX)
    assert data[BACKUP_TAKEN_KEY] == [SUFFIX]

    _write(hass, STORAGE_KEY, '{"main": "after the strip"}')
    assert await async_take_backup(hass, data, SUFFIX)

    assert _read(hass, f"{STORAGE_KEY}.{SUFFIX}") == '{"main": "before"}'


async def test_a_missing_clocks_file_is_not_a_failure(
    hass: HomeAssistant
):
    """A house that never ran far enough to write one has nothing to
    preserve, and protecting what is there is the whole job."""
    _write(hass, STORAGE_KEY, '{"main": 1}')

    assert await async_take_backup(hass, {}, SUFFIX)

    assert _read(hass, f"{STORAGE_KEY}.{SUFFIX}") == '{"main": 1}'


async def test_a_copy_that_fails_reports_failure(hass: HomeAssistant):
    """The path a caller about to strip depends on.

    False means stop. Doing nothing leaves the install exactly as it
    was, which is harmless; stripping without a copy is not.
    """
    _write(hass, STORAGE_KEY, '{"main": 1}')
    _write(hass, STORAGE_CLOCKS_KEY, '{"clocks": 1}')
    data: dict = {}

    with patch(
        "custom_components.device_sentinel.backup.shutil.copyfile",
        side_effect=OSError("disk full"),
    ):
        assert not await async_take_backup(hass, data, SUFFIX)

    assert BACKUP_TAKEN_KEY not in data
    assert not os.path.exists(_path(hass, f"{STORAGE_KEY}.{SUFFIX}"))


async def test_nothing_in_this_release_calls_it(hass: HomeAssistant):
    """It ships inert (#130).

    An ordinary setup takes no backup, because the release that
    strips is the one that asks for it. If this ever fails, something
    has wired the backbone up early and the copy would be taken from
    a file nobody is about to change.
    """
    coordinator = await setup_coordinator(hass)

    assert BACKUP_TAKEN_KEY not in coordinator.data
    assert not os.path.exists(_path(hass, f"{STORAGE_KEY}.{SUFFIX}"))
