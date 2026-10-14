# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_history_file_campaign.py, Version: 0.26.2 (2026-10-13)

"""Random sequences against the history file (ruling #661).

Folds, days added, rows written either side of the line, trims from
Advanced, retention changes, saves, clean restarts, damaged main files,
damaged history files and stops between the four steps, in random
order, on real files.

The reference is a single-file run: the same record saved whole, as a
release before 0.26.2 wrote it, and loaded through the same load path.
The load itself changes some things on purpose (a row past the
retention, a gap longer than a new device's watch), so a start is
compared with the start of the whole file, never with memory. A clean
restart must equal the single-file start of the newest save; a restore
or a stop must equal the single-file start of one of the saves, never a
mixture, so no day is doubled, lost or shifted.
"""

from __future__ import annotations

import json
import os
import random
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import history_file
from custom_components.device_sentinel.const import (
    CONF_RETENTION_DAYS,
    CONF_TRIM_DEVICES,
    DATA_DEVICES,
    DATA_HISTORY_LINE,
    DATA_SYSTEM_EVENTS,
)

from .helpers import register_device, setup_entry
from .test_history_file import SERIES_FIELDS, furnish, learned, restart_with
from .test_history_file_disk import HIST, LIVE, Stop, put_back, snapshot

DAY = 86400.0
STEPS = ("after_rename", "after_history", "after_main", "after_copy")
VALUE = {
    "daily_max": 400.0,
    "battery_daily_value": 50.0,
    "battery_daily_previous": 50.0,
    "signal_daily_count": 0,
    "signal_daily_rail": 0,
    "signal_daily_sd": 1.0,
}


def comparable(coord) -> dict:
    """The learned series, and the campaign's rows."""
    view = {k: v for k, v in learned(coord).items() if k != "rows"}
    view["events"] = [
        row
        for row in coord.data.get(DATA_SYSTEM_EVENTS) or []
        if isinstance(row, dict) and row.get("kind") == "campaign"
    ]
    return view


def whole_file(coord) -> bytes:
    """The record as a release before 0.26.2 would write it."""
    return json.dumps(
        {"version": 1, "minor_version": 1, "key": LIVE, "data": coord._trim_backup_storage()}
    ).encode()


@pytest.mark.parametrize("seed", range(8))
async def test_random_sequences_match_a_single_file_run(
    hass: HomeAssistant, real_disk, seed
):
    rng = random.Random(seed)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    ids = []
    for i in range(4):
        device, _ = register_device(hass, f"camp{seed}_{i}", f"Campaign {i}")
        ids.append(device.id)
    coord._rebuild_registry_view()
    for device_id in ids:
        furnish(coord.data[DATA_DEVICES][device_id], rng.randint(20, 70))
    wholes: list[bytes] = []
    ops: list[str] = []
    counted = {"restart": 0, "restore": 0, "stop": 0, "history_damage": 0}
    # Every main-file write of the run is recorded as the whole record
    # it wrote, whatever wrote it: a save, a fold, a trim, a setup or a
    # stop. The single-file starts made for reference are not.
    recording = {"on": True}
    mixin = type(coord)
    real_write_main = mixin._write_main_files

    async def recorded_write(self, **kwargs):
        await real_write_main(self, **kwargs)
        if recording["on"]:
            wholes.append(whole_file(self))

    patcher = patch.object(mixin, "_write_main_files", recorded_write)
    patcher.start()

    async def save():
        current = entry.runtime_data
        current._critical = True
        await current._save_now()

    async def single_file_start(whole: bytes) -> dict:
        """Start on the whole file alone: the single-file run."""

        def only_whole():
            put_back(real_disk, {LIVE: whole})

        recording["on"] = False
        try:
            return comparable(await restart_with(hass, entry, only_whole))
        finally:
            recording["on"] = True

    async def start_on(files: dict[str, bytes], edit=None):
        def lay_down():
            put_back(real_disk, files)
            if edit is not None:
                edit()

        return await restart_with(hass, entry, lay_down)

    await save()
    for _step in range(60):
        coord = entry.runtime_data
        op = rng.choice(
            ["day", "day", "day", "event", "fold", "trim", "retention",
             "save", "restart", "restart", "damage_main", "damage_history", "stop"]
        )
        ops.append(op)
        if op == "day":
            record = coord.data[DATA_DEVICES][rng.choice(ids)]
            field = rng.choice(SERIES_FIELDS)
            if isinstance(record.get(field), list):
                record[field].append(VALUE.get(field, -55.0))
        elif op == "event":
            line = coord.data[DATA_HISTORY_LINE]
            coord.data[DATA_SYSTEM_EVENTS].append(
                {"when": line + rng.choice([-40, -5, 1, 3]) * DAY, "kind": "campaign",
                 "scope": "system", "detail": None, "duration": None}
            )
        elif op == "fold":
            await coord._on_midnight(None)
        elif op == "trim":
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_TRIM_DEVICES: [rng.choice(ids)]}
            )
            await hass.async_block_till_done()
        elif op == "retention":
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_RETENTION_DAYS: rng.choice([30, 45, 60, 180, 360])}
            )
            await hass.async_block_till_done()
            await save()
        elif op == "save":
            await save()
        elif op in ("restart", "damage_history"):
            await save()
            files = snapshot(real_disk)
            newest = wholes[-1]
            want = await single_file_start(newest)

            def damage_history():
                path = os.path.join(real_disk, HIST)
                if os.path.exists(path):
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("{not json")

            got = comparable(
                await start_on(files, damage_history if op == "damage_history" else None)
            )
            assert got == want, f"seed {seed}: {op} after {ops[-8:]}"
            counted["restart" if op == "restart" else "history_damage"] += 1
            await save()
        elif op == "damage_main":
            await save()
            files = snapshot(real_disk)
            # The main file's last-good copy is one save back, or older
            # after a start that restored; any save is a whole state.
            wants = [await single_file_start(w) for w in wholes[-4:]]

            def damage_main():
                with open(os.path.join(real_disk, LIVE), "w", encoding="utf-8") as handle:
                    handle.write("{not json")

            restored = await start_on(files, damage_main)
            got = comparable(restored)
            assert got in wants, f"seed {seed}: restore after {ops[-8:]}"
            counted["restore"] += 1
            await save()
        elif op == "stop":
            # Something older changes, then the power goes at a step.
            record = coord.data[DATA_DEVICES][rng.choice(ids)]
            record["daily_max"].append(401.0)
            before = wholes[-1]
            after = whole_file(coord)
            at = rng.choice(STEPS)
            real_write = history_file.write_copy
            real_save = coord._store.async_save

            async def write_copy(hass_, body, last_good, at=at, real_write=real_write):
                if at == "after_rename" and not last_good:
                    raise Stop
                if last_good and at == "after_main":
                    raise Stop
                await real_write(hass_, body, last_good)

            async def save_main(data, at=at, real_save=real_save):
                if at == "after_history":
                    raise Stop
                await real_save(data)

            coord._critical = True
            with patch.object(history_file, "write_copy", write_copy), patch.object(
                coord._store, "async_save", save_main
            ):
                try:
                    await coord._save_now()
                except Stop:
                    pass
            files = snapshot(real_disk)
            wants = [await single_file_start(before), await single_file_start(after)]
            got = comparable(await start_on(files))
            assert got in wants, f"seed {seed}: stop {at} after {ops[-8:]}"
            counted["stop"] += 1
            await save()
    patcher.stop()
    assert sum(counted.values()) > 0
