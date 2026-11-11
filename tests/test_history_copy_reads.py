# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_history_copy_reads.py, Version: 0.28.12 (2026-11-11)

"""Reading the two history copies on a
real disk (history_file.read_copy).

1. A history file that is valid JSON in the wrong shape (no "version",
   or a list) makes Home Assistant's Store raise KeyError or TypeError,
   not HomeAssistantError. read_copy catches only HomeAssistantError,
   ValueError and OSError, so the error escapes _join_history_at_load
   and setup fails, at every start, even though last-good holds the
   same generation. The answers file's reader catches these
   (answers_store._load); the history reader does not.

2. A damaged history last-good copy is set aside by Home Assistant with
   a CRITICAL, persistent storage_corruption card telling the person to
   restore the whole system. The live file joins and Device Sentinel
   writes last-good again, but async_clear_corruption_of is called only
   for the live key, so the card for the last-good key stays.

Each test asserts the correct behaviour.
"""

from __future__ import annotations

import json
import os

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from tests.test_history_file import learned, restart_with
from tests.test_history_file_disk import HIST, HIST_COPY, devices_only, house


def _cards(hass: HomeAssistant, key: str) -> list[str]:
    prefix = f"storage_corruption_{key}_"
    return [i for (_d, i) in ir.async_get(hass).issues if i.startswith(prefix)]


@pytest.mark.parametrize(
    "body",
    [
        '{"data": {}}',  # no version: KeyError in Store
        "[]",  # a list at the top: TypeError in Store
    ],
    ids=["no-version", "list"],
)
async def test_a_wrong_shape_live_history_file_never_stops_a_start(
    hass: HomeAssistant, real_disk, body
):
    entry, coord, _ids = await house(hass)
    before = devices_only(learned(coord))

    def damage():
        path = os.path.join(real_disk, HIST)
        os.remove(path)  # never write through a link last-good may share
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    damage()
    from tests.helpers import start_storage_as_home_assistant_does

    await start_storage_as_home_assistant_does(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2._history_state["joined"] == "last-good"
    assert devices_only(learned(coord2)) == before


async def test_a_damaged_history_last_good_leaves_no_critical_card(
    hass: HomeAssistant, real_disk
):
    entry, coord, _ids = await house(hass)
    before = devices_only(learned(coord))

    def damage():
        path = os.path.join(real_disk, HIST_COPY)
        os.remove(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._history_state["joined"] == "live"
    assert devices_only(learned(coord2)) == before
    # Last-good was written again from the live file.
    with open(os.path.join(real_disk, HIST_COPY), encoding="utf-8") as handle:
        assert isinstance(json.load(handle)["data"], dict)
    # Home Assistant's card advising a whole-system restore is gone.
    assert _cards(hass, HIST_COPY) == []
