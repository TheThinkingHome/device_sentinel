# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_routine_save_checked.py, Version: 0.27.8 (2026-10-27)

"""A routine save is checked and rotated like any other (rules STOR-04,
STOR-06): before, a save with a cold row waiting wrote the main file
unchecked and kept the last good copy from rotating."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_FIRST_OBSERVED

from .test_history_file_disk import LIVE, LIVE_COPY, house, read, snapshot


async def test_a_routine_save_repairs_what_it_writes(hass: HomeAssistant, real_disk):
    _entry, coord, ids = await house(hass)
    coord._critical = True
    await coord._save_now()
    coord.data[DATA_DEVICES][ids[0]][DEV_FIRST_OBSERVED] = 12345   # damaged
    coord._repair_notice = None
    coord._cold_dirty = True
    coord._next_routine_save = 0.0
    await coord._routine_save()
    on_disk = read(real_disk, LIVE)
    assert on_disk[DATA_DEVICES][ids[0]][DEV_FIRST_OBSERVED] != 12345
    assert coord._repair_notice is not None


async def test_a_clean_routine_save_rotates(hass: HomeAssistant, real_disk):
    _entry, coord, ids = await house(hass)
    coord._critical = True
    await coord._save_now()
    await coord._save_now()
    before_copy = snapshot(real_disk)[LIVE_COPY]
    coord.data[DATA_DEVICES][ids[0]]["routine_marker"] = "x"
    coord._cold_dirty = True
    coord._next_routine_save = 0.0
    await coord._routine_save()
    assert read(real_disk, LIVE)[DATA_DEVICES][ids[0]].get("routine_marker") == "x"
    assert snapshot(real_disk)[LIVE_COPY] != before_copy
