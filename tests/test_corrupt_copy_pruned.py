# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_corrupt_copy_pruned.py, Version: 0.27.8 (2026-10-27)

"""Home Assistant's corrupt file, copied aside under its own name, goes
with the other backup copies after the thirty days (rule STOR-13)."""

from __future__ import annotations

import os
import time

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.backup import (
    async_copy_corrupt_evidence,
    async_prune_backups,
)
from custom_components.device_sentinel.const import TRIM_BACKUP_DIR


async def test_the_corrupt_copy_goes_after_thirty_days(hass: HomeAssistant):
    storage = hass.config.path(".storage")
    folder = hass.config.path(TRIM_BACKUP_DIR)
    os.makedirs(storage, exist_ok=True)
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))
    corrupt = "device_sentinel.storage.corrupt.2026-01-01T00:00:00.000000+00:00"
    with open(os.path.join(storage, corrupt), "w") as h:
        h.write("{not json")
    old_stamp = "2026-01-01_000000"
    try:
        assert await async_copy_corrupt_evidence(hass, [corrupt], old_stamp) == 1
        old_evidence = f"device_sentinel_{old_stamp}.storage.evidence"
        newest = "device_sentinel_2026-10-25_000000.storage.evidence"
        foreign = "my-device_sentinel notes.txt"
        for name in (old_evidence, newest, foreign):
            open(os.path.join(folder, name), "w").close()
        copied = next(n for n in os.listdir(folder) if n.startswith(f"{old_stamp}-"))
        aged = time.time() - 90 * 86400
        for name in (copied, old_evidence, foreign):
            os.utime(os.path.join(folder, name), (aged, aged))
        await async_prune_backups(hass, 30)
        left = os.listdir(folder)
        assert copied not in left
        assert old_evidence not in left
        assert newest in left           # the newest set is always kept
        assert foreign in left          # not ours, never touched
    finally:
        os.remove(os.path.join(storage, corrupt))
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))


async def test_a_corrupt_copy_taken_today_survives_the_night(hass: HomeAssistant):
    storage = hass.config.path(".storage")
    folder = hass.config.path(TRIM_BACKUP_DIR)
    os.makedirs(storage, exist_ok=True)
    os.makedirs(folder, exist_ok=True)
    corrupt = "device_sentinel.storage.corrupt.2026-09-17T00:00:00+00:00"
    path = os.path.join(storage, corrupt)
    with open(path, "w") as h:
        h.write("{not json")
    aged = time.time() - 40 * 86400       # the file as last written, 40 days ago
    os.utime(path, (aged, aged))
    stamp = "2026-10-27_080000"            # taken this morning
    try:
        assert await async_copy_corrupt_evidence(hass, [corrupt], stamp) == 1
        # a later, ordinary repair the same day makes another set the newest
        open(os.path.join(folder, "device_sentinel_2026-10-27_090000.storage.evidence"), "w").close()
        await async_prune_backups(hass, 90)
        left = os.listdir(folder)
        assert any(n.startswith(f"{stamp}-") for n in left)
    finally:
        os.remove(path)
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
