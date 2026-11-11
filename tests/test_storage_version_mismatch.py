# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storage_version_mismatch.py, Version: 0.28.12 (2026-11-11)

"""A storage document whose version is below 1.

Home Assistant's Store answers a document with "version": 0 by asking
for a migration; the base Store has none and raises NotImplementedError
out of async_load. The answers file already catches that error
(answers_store._load), but the main file, the clocks file and the history
file catch only HomeAssistantError, ValueError, KeyError, TypeError,
AttributeError and RecursionError, so the error stops the whole start
with a traceback instead of being answered like any other unreadable
file (rules STOR-08, STOR-10).

Each test asserts the correct behaviour.
"""

from __future__ import annotations

import json
import os

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_DEVICES, STORAGE_CLOCKS_KEY

from tests.test_history_file import restart_with
from tests.test_history_file_disk import HIST, LIVE, house


def _set_version_zero(directory: str, name: str) -> None:
    path = os.path.join(directory, name)
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    document["version"] = 0
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


async def test_a_clocks_file_at_version_zero_does_not_stop_the_start(
    hass: HomeAssistant, real_disk
):
    """The clocks file is expendable (rule STOR-10): one Device Sentinel
    cannot read is set aside and rebuilt, never a reason not to run."""
    entry, _coord, ids = await house(hass)
    coord2 = await restart_with(hass, entry, lambda: _set_version_zero(real_disk, STORAGE_CLOCKS_KEY))
    assert set(ids) <= set(coord2.data[DATA_DEVICES])


async def test_a_main_file_at_version_zero_is_restored_from_last_good(
    hass: HomeAssistant, real_disk
):
    """An unreadable main file beside a usable last-good copy is restored
    (rule STOR-08), whatever the Store raised."""
    entry, _coord, ids = await house(hass)
    coord2 = await restart_with(hass, entry, lambda: _set_version_zero(real_disk, LIVE))
    assert set(ids) <= set(coord2.data[DATA_DEVICES])
    assert coord2._restored_from is not None


async def test_a_history_file_at_version_zero_does_not_stop_the_start(
    hass: HomeAssistant, real_disk
):
    """A live history file that cannot be read is answered by its
    last-good copy (rule STOR-03), never a failed start."""
    entry, _coord, ids = await house(hass)
    coord2 = await restart_with(hass, entry, lambda: _set_version_zero(real_disk, HIST))
    assert set(ids) <= set(coord2.data[DATA_DEVICES])
    assert coord2._history_state["joined"] == "last-good"
