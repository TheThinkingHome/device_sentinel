# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storage_envelopes.py, Version: 0.28.12 (2026-11-11)

"""A file that parses but is not
a storage document, on a real disk.

Home Assistant's Store reads `version`, `minor_version` and `data` out of
the parsed document. A document that is valid JSON but not that envelope
(`null`, a list, or a mapping with no `version`, as a hand edit or the
data part pasted alone leaves) makes the real Store raise TypeError or
KeyError. Device Sentinel catches HomeAssistantError and ValueError at
the main and clocks reads, and HomeAssistantError, ValueError and OSError
at the history read, so the error escapes and setup fails with a
traceback at every start, beside a good last-good copy.

The harness hides it: its mocked load raises ValueError for an envelope
missing "version" or "data", which Device Sentinel does catch. On the
real disk the real Store runs.

Each test asserts the correct behaviour (rules STOR-08, STOR-10,
STOR-03): the start goes on, from last-good where there is one.
"""

from __future__ import annotations

import json
import os

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    STORAGE_CLOCKS_KEY,
    STORAGE_HISTORY_KEY,
    STORAGE_KEY,
)

from tests.helpers import start_storage_as_home_assistant_does
from tests.test_history_file import learned
from tests.test_history_file_disk import devices_only, house

LAST_GOOD = f"{STORAGE_KEY}.last-good"


def _devices_in(directory: str, name: str) -> set[str]:
    with open(os.path.join(directory, name), encoding="utf-8") as handle:
        return set(json.load(handle)["data"][DATA_DEVICES])


async def _restart(hass: HomeAssistant, entry, edit) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    edit()
    await start_storage_as_home_assistant_does(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


NOT_ENVELOPES = {
    "null": "null",
    "a_list": "[]",
    "data_part_alone": json.dumps({"devices": {}}),
}


@pytest.mark.parametrize("which", list(NOT_ENVELOPES))
async def test_a_main_file_that_is_not_a_storage_document_is_restored(
    hass: HomeAssistant, real_disk, which
):
    entry, coord, ids = await house(hass)
    await coord._save_now()
    await coord._save_now()
    assert set(ids) <= _devices_in(real_disk, LAST_GOOD)

    def damage():
        with open(os.path.join(real_disk, STORAGE_KEY), "w", encoding="utf-8") as handle:
            handle.write(NOT_ENVELOPES[which])

    await _restart(hass, entry, damage)
    assert entry.state is ConfigEntryState.LOADED, which
    assert set(ids) <= set(entry.runtime_data.data[DATA_DEVICES]), which


@pytest.mark.parametrize("which", list(NOT_ENVELOPES))
async def test_a_clocks_file_that_is_not_a_storage_document_never_stops_a_start(
    hass: HomeAssistant, real_disk, which
):
    entry, coord, ids = await house(hass)

    def damage():
        with open(os.path.join(real_disk, STORAGE_CLOCKS_KEY), "w", encoding="utf-8") as handle:
            handle.write(NOT_ENVELOPES[which])

    await _restart(hass, entry, damage)
    assert entry.state is ConfigEntryState.LOADED, which
    assert set(ids) <= set(entry.runtime_data.data[DATA_DEVICES]), which


@pytest.mark.parametrize("which", list(NOT_ENVELOPES))
async def test_a_history_file_that_is_not_a_storage_document_joins_last_good(
    hass: HomeAssistant, real_disk, which
):
    entry, coord, _ids = await house(hass)
    before = devices_only(learned(coord))

    def damage():
        with open(os.path.join(real_disk, STORAGE_HISTORY_KEY), "w", encoding="utf-8") as handle:
            handle.write(NOT_ENVELOPES[which])

    await _restart(hass, entry, damage)
    assert entry.state is ConfigEntryState.LOADED, which
    coord2 = entry.runtime_data
    assert coord2._history_state["joined"] == "last-good", which
    assert devices_only(learned(coord2)) == before, which
