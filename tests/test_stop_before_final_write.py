# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stop_before_final_write.py, Version: 0.28.12 (2026-11-11)

"""A restart killed before Home Assistant's final-write stage (rule FRZ-20).

While Home Assistant is stopping, its Store holds every save back until
the final-write stage. Device Sentinel's stop handler sets the clean-stop
marker (rule FRZ-20) and saves, but that save only reaches the disk at
the final write. A container that Docker kills ten seconds after asking
it to stop never reaches it, so the file on disk
carries no clean-stop marker and the next start is read as an unclean
stop: every clock not on the Problem List restarts, and the brief says
Home Assistant did not shut down cleanly, after an ordinary restart.

The correct behaviour asserted here: the stop's own save, made at the
stop event, is on disk before the final-write stage, so a process
killed after it starts next as after a clean stop.
"""

from __future__ import annotations

import json
import os

from homeassistant.core import CoreState, HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_CLEAN_STOP,
    DATA_SYSTEM_EVENTS,
    STORAGE_KEY,
    SYS_UNCLEAN_RESTART,
)

from tests.helpers import register_device, setup_entry
from tests.test_history_file import restart_with


def _snapshot(directory: str) -> dict[str, bytes]:
    files = {}
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            with open(os.path.join(directory, name), "rb") as handle:
                files[name] = handle.read()
    return files


def _put_back(directory: str, files: dict[str, bytes]) -> None:
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            os.remove(os.path.join(directory, name))
    for name, body in files.items():
        with open(os.path.join(directory, name), "wb") as handle:
            handle.write(body)


async def test_the_stop_save_is_on_disk_before_the_final_write(
    hass: HomeAssistant, real_disk
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    register_device(hass, "stop0", "Stop Device 0")
    coord._rebuild_registry_view()
    await coord._save_now()
    await coord._save_now()

    # Home Assistant's stop: the state moves to stopping, then the stop
    # event runs Device Sentinel's handler. The final write never comes.
    hass.set_state(CoreState.stopping)
    await coord._on_hass_stop(None)
    await hass.async_block_till_done()
    killed = _snapshot(real_disk)
    hass.set_state(CoreState.running)

    with open(os.path.join(real_disk, STORAGE_KEY), encoding="utf-8") as handle:
        on_disk = json.load(handle)["data"]
    assert on_disk.get(DATA_CLEAN_STOP) is True, (
        "the stop's save had not reached the disk before the final write"
    )

    # The next start, from the files as the kill left them.
    coord2 = await restart_with(hass, entry, lambda: _put_back(real_disk, killed))
    kinds = [row.get("kind") for row in coord2.data.get(DATA_SYSTEM_EVENTS) or []]
    assert SYS_UNCLEAN_RESTART not in kinds
