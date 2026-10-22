# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_history_file_disk.py, Version: 0.26.8 (2026-10-21)

"""The history file on disk: the four steps, a stop between any two,
the restores, the evidence, the backups and the uninstall (ruling #660).

Real files through Home Assistant's own storage code (the real_disk
fixture). A stop is a save that raises at a chosen step: the files on
disk at that moment are kept, the integration is stopped, the files are
put back as the stop left them, and the next start must join a whole
history with no day doubled or lost. The rig's and Tim's houses are
split and joined day for day at the end.
"""

from __future__ import annotations

import copy
import json
import os
import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import async_remove_entry, history_file
from custom_components.device_sentinel.backup import (
    async_copy_evidence,
    async_prune_backups,
)
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_HISTORY_GENERATION,
    DATA_HISTORY_LINE,
    TRIM_BACKUP_DIR,
)

from .conftest import fleet_data, fleet_param
from .helpers import register_device, setup_entry
from .test_history_file import SERIES_FIELDS, furnish, learned, restart_with, series

LIVE = "device_sentinel.storage"
LIVE_COPY = "device_sentinel.storage.last-good"
HIST = "device_sentinel.history"
HIST_COPY = "device_sentinel.history.last-good"


class Stop(Exception):
    """The power going out at a chosen step."""


def read(directory: str, name: str):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]


def snapshot(directory: str) -> dict[str, bytes]:
    out = {}
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            with open(os.path.join(directory, name), "rb") as handle:
                out[name] = handle.read()
    return out


def put_back(directory: str, files: dict[str, bytes]) -> None:
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            os.remove(os.path.join(directory, name))
    for name, body in files.items():
        with open(os.path.join(directory, name), "wb") as handle:
            handle.write(body)


async def house(hass, n=40):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    ids = []
    for i in range(2):
        device, _ = register_device(hass, f"disk{i}", f"Disk Device {i}")
        ids.append(device.id)
    coord._rebuild_registry_view()
    for device_id in ids:
        furnish(coord.data[DATA_DEVICES][device_id], n)
    await coord._save_now()
    return entry, coord, ids


def devices_only(view: dict) -> dict:
    return {k: v for k, v in view.items() if k != "rows"}


async def test_the_four_steps_leave_two_matching_copies(hass: HomeAssistant, real_disk):
    """After a save that changes history: live and last-good history are
    the same file, and the main file records their generation."""
    _entry, coord, ids = await house(hass)
    main = read(real_disk, LIVE)
    live = read(real_disk, HIST)
    copy_ = read(real_disk, HIST_COPY)
    assert live == copy_
    assert main[DATA_HISTORY_GENERATION] == live["generation"]
    assert len(main[DATA_DEVICES][ids[0]]["daily_max"]) == 30
    assert live["devices"][ids[0]]["daily_max"] == series("daily_max", 40)[:10]


@pytest.mark.parametrize(
    ("stop_at", "expect_new"),
    [
        ("after_rename", False),
        ("after_history", False),
        ("after_main", True),
        ("after_copy", True),
    ],
)
async def test_a_stop_between_any_two_steps_doubles_and_loses_nothing(
    hass: HomeAssistant, real_disk, stop_at, expect_new
):
    """The day appended is either all there or not there at all."""
    entry, coord, ids = await house(hass)
    old = devices_only(learned(coord))
    coord.data[DATA_DEVICES][ids[0]]["daily_max"].append(999.0)
    new = devices_only(learned(coord))

    real_write = history_file.write_copy
    real_save = coord._store.async_save

    async def write_copy(hass_, body, last_good):
        if stop_at == "after_rename" and not last_good:
            raise Stop
        if last_good and stop_at == "after_main":
            raise Stop
        await real_write(hass_, body, last_good)

    async def save_main(data):
        if stop_at == "after_history":
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
    left = snapshot(real_disk)
    if stop_at == "after_rename":
        assert HIST not in left and HIST_COPY in left

    coord2 = await restart_with(hass, entry, lambda: put_back(real_disk, left))
    joined = devices_only(learned(coord2))
    assert joined == (new if expect_new else old)
    assert len(coord2.data[DATA_DEVICES][ids[0]]["daily_max"]) == (41 if expect_new else 40)


async def test_a_damaged_main_file_is_restored_with_its_matching_history(
    hass: HomeAssistant, real_disk
):
    """The main file's last-good copy pairs with a history copy."""
    entry, coord, ids = await house(hass)
    coord._critical = True
    await coord._save_now()
    before = devices_only(learned(coord))

    def damage():
        with open(os.path.join(real_disk, LIVE), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._restored_from is not None
    assert coord2._history_state["joined"] in ("live", "last-good")
    assert devices_only(learned(coord2)) == before


async def test_a_damaged_live_history_file_is_answered_by_last_good(
    hass: HomeAssistant, real_disk
):
    """Home Assistant sets the unreadable file aside; last-good joins."""
    entry, coord, ids = await house(hass)
    before = devices_only(learned(coord))

    def damage():
        with open(os.path.join(real_disk, HIST), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._history_state["joined"] == "last-good"
    assert devices_only(learned(coord2)) == before


async def test_no_matching_copy_starts_with_thirty_days_and_keeps_evidence(
    hass: HomeAssistant, real_disk, caplog
):
    """Both history copies gone: the main file's thirty days, a warning,
    and the files copied aside first."""
    entry, coord, ids = await house(hass)

    def lose_both():
        os.remove(os.path.join(real_disk, HIST))
        os.remove(os.path.join(real_disk, HIST_COPY))

    coord2 = await restart_with(hass, entry, lose_both)
    assert coord2.data[DATA_DEVICES][ids[0]]["daily_max"] == series("daily_max", 40)[-30:]
    assert "No history file matches the storage file" in caplog.text
    folder = hass.config.path(TRIM_BACKUP_DIR)
    assert any(name.endswith(".storage.evidence") for name in os.listdir(folder))


async def test_evidence_copies_take_both_history_files(hass: HomeAssistant, real_disk):
    await house(hass)
    stamp, copied = await async_copy_evidence(hass)
    assert "the history file" in copied and "the history backup" in copied
    folder = hass.config.path(TRIM_BACKUP_DIR)
    assert os.path.exists(os.path.join(folder, f"device_sentinel_{stamp}.history.evidence"))


async def test_a_trim_writes_the_history_file_at_once_on_disk(
    hass: HomeAssistant, real_disk
):
    """The trimmed device leaves both history copies in the same save,
    and a start after a stop right then cannot bring it back."""
    entry, coord, ids = await house(hass)
    target = ids[0]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "trim_devices": [target]}
    )
    await hass.async_block_till_done()
    for name in (HIST, HIST_COPY):
        assert target not in read(real_disk, name)["devices"]
    left = snapshot(real_disk)
    coord2 = await restart_with(hass, entry, lambda: put_back(real_disk, left))
    assert coord2.data[DATA_DEVICES][target]["daily_max"] == []


async def test_uninstall_removes_the_history_files(hass: HomeAssistant, real_disk):
    entry, _coord, _ids = await house(hass)
    assert os.path.exists(os.path.join(real_disk, HIST))
    assert await hass.config_entries.async_unload(entry.entry_id)
    await async_remove_entry(hass, entry)
    for name in (HIST, HIST_COPY):
        assert not os.path.exists(os.path.join(real_disk, name))


async def test_backup_copies_go_after_thirty_days_except_the_newest(
    hass: HomeAssistant,
):
    """Every copy, all its files alike, after thirty days; the newest
    for the full retention (ruling #634)."""
    folder = hass.config.path(TRIM_BACKUP_DIR)
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))
    now = time.time()

    def make(stamp, age_days):
        for kind in ("storage.json", "clocks.json"):
            path = os.path.join(folder, f"device_sentinel_{stamp}.{kind}")
            with open(path, "w") as handle:
                handle.write("{}")
            os.utime(path, (now - age_days * 86400, now - age_days * 86400))

    make("2026-06-01_120000", 100)
    make("2026-08-01_120000", 40)
    removed = await async_prune_backups(hass, 90)
    assert removed == 2
    assert sorted(os.listdir(folder)) == [
        "device_sentinel_2026-08-01_120000.clocks.json",
        "device_sentinel_2026-08-01_120000.storage.json",
    ]
    make("2026-10-01_120000", 5)
    assert await async_prune_backups(hass, 90) == 2
    assert all("2026-10-01" in name for name in os.listdir(folder))


@pytest.mark.parametrize(
    "path",
    [
        fleet_param("reference", "device_sentinel.storage", id="reference"),
        fleet_param("second", "device_sentinel_storage.json", id="second"),
        fleet_param("fourth", "device_sentinel_storage.json", id="fourth"),
        fleet_param("upgrade", "reference", "device_sentinel.storage", id="upgrade_reference"),
        fleet_param("upgrade", "second", "device_sentinel_storage.json", id="upgrade_second"),
    ],
)
def test_a_real_house_splits_and_joins_day_for_day(path):
    """Every device's series and every row come back identical.

    The houses on 0.26.8 are read whole, their history file joined back
    in, so the split has their full history to cut; the upgrade houses,
    written before the history file existed, are one whole file as they
    stand, which is the split an upgrade makes at its first save."""
    data = fleet_data(path)
    data.setdefault(DATA_HISTORY_LINE, history_file.fold_line())
    original = copy.deepcopy(data)
    view, part = history_file.split(data)
    assert data == original
    for record in view[DATA_DEVICES].values():
        for field in SERIES_FIELDS:
            values = record.get(field)
            assert not isinstance(values, list) or len(values) <= 30
    body = json.loads(json.dumps({"generation": 1, **part}))
    assert history_file.check_payload(body) is None
    joined = json.loads(json.dumps(view))
    history_file.join(joined, body)
    assert joined == json.loads(json.dumps(original))


async def test_nothing_older_removes_both_history_files_on_disk(
    hass: HomeAssistant, real_disk
):
    """Retention down to thirty, folded: no history file, no copy."""
    entry, coord, ids = await house(hass)
    for device_id in ids:
        for field in SERIES_FIELDS:
            del coord.data[DATA_DEVICES][device_id][field][:-30]
    coord._critical = True
    await coord._save_now()
    for name in (HIST, HIST_COPY):
        assert not os.path.exists(os.path.join(real_disk, name))
    assert DATA_HISTORY_GENERATION not in read(real_disk, LIVE)


async def test_a_damaged_main_file_after_the_history_file_went_restores_thirty_days(
    hass: HomeAssistant, real_disk
):
    """Retention down to thirty removes both history files; the main
    file's last-good is then the main file of that save, so a damaged
    main file restores the thirty days rather than a copy that asks for
    a history file no longer there (found by the second campaign, seed
    150, 14 October)."""
    entry, coord, ids = await house(hass)
    for device_id in ids:
        for field in SERIES_FIELDS:
            del coord.data[DATA_DEVICES][device_id][field][:-30]
    coord._critical = True
    await coord._save_now()
    before = devices_only(learned(coord))
    assert DATA_HISTORY_GENERATION not in read(real_disk, LIVE_COPY)

    def damage():
        with open(os.path.join(real_disk, LIVE), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._restored_from is not None
    assert devices_only(learned(coord2)) == before
