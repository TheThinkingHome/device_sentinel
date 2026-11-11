# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storage_never_missing.py, Version: 0.28.11 (2026-11-10)

"""The main storage file is never missing (rule STOR-04).

A house on Docker reported "found device_sentinel.storage missing" at a
restart. Before each clean save the main file was renamed to last-good,
and while Home Assistant is stopping its Store holds every save back
until the final-write stage. So from the stop event to the final write
there was no main file, and a process killed in that time, by Docker's
ten seconds or a stage that timed out, started next with none.

Last-good is now kept by a hard link, or a copy where links are
refused, and the live file never leaves its place:

- Home Assistant stopping, the stop's save made and the final write not
  reached: the main file is there, and the next start restores nothing;
- a stop at each step of a save leaves a readable main file, and
  last-good is never newer than it;
- the link writes no data; the copy is the fallback;
- the history and answers files are kept the same way;
- the restore writes through a temporary name, never over a live name
  that may share its contents with last-good.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import CoreState, HomeAssistant

from custom_components.device_sentinel import backup
from custom_components.device_sentinel.backup import keep_as_last_good
from custom_components.device_sentinel.const import STORAGE_KEY

from .test_history_file import restart_with
from .helpers import register_device, setup_entry

LAST_GOOD = f"{STORAGE_KEY}.last-good"


def _read(directory: str, name: str):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["data"]


async def _house(hass):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    register_device(hass, "disk0", "Disk Device 0")
    coord._rebuild_registry_view()
    await coord._save_now()
    await coord._save_now()
    return entry, coord


async def test_a_shutdown_killed_before_the_final_write_keeps_the_main_file(
    hass: HomeAssistant, real_disk
):
    """The order Home Assistant stops in: the stop's save is made while
    stopping, and the final write never comes."""
    entry, coord = await _house(hass)
    main = os.path.join(real_disk, STORAGE_KEY)
    before = _read(real_disk, STORAGE_KEY)
    assert coord._rotation_armed
    hass.set_state(CoreState.stopping)
    await coord._save_main(final=True)
    await hass.async_block_till_done()
    # Before the final write: the main file is still there, as it was.
    assert os.path.exists(main)
    assert _read(real_disk, STORAGE_KEY) == before
    assert _read(real_disk, LAST_GOOD) == before
    # The process dies here. The next start reads the main file and
    # restores nothing.
    hass.set_state(CoreState.running)
    coord2 = await restart_with(hass, entry)
    assert coord2._restored_from is None


async def test_the_final_write_still_lands(hass: HomeAssistant, real_disk):
    """A shutdown that finishes writes the stop's save, and last-good
    holds the file from before it."""
    entry, coord = await _house(hass)
    before = _read(real_disk, STORAGE_KEY)
    hass.set_state(CoreState.stopping)
    await coord._save_main(final=True)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    assert _read(real_disk, LAST_GOOD) == before
    assert _read(real_disk, STORAGE_KEY)["saved_at"] >= before["saved_at"]
    assert os.stat(os.path.join(real_disk, STORAGE_KEY)).st_ino != os.stat(
        os.path.join(real_disk, LAST_GOOD)
    ).st_ino


async def test_a_stop_at_each_step_leaves_a_readable_main_file(
    hass: HomeAssistant, real_disk
):
    """Before the copy, after it, and part way through the write."""
    entry, coord = await _house(hass)

    class Stop(Exception):
        pass

    for step in ("before_copy", "after_copy", "in_write"):
        coord._rotation_armed = True
        real_keep = backup.keep_as_last_good

        def keep(live, copy, _step=step, _real=real_keep):
            if _step == "before_copy":
                raise Stop
            return _real(live, copy)

        async def save(data, _step=step):
            raise Stop

        with patch.object(backup, "keep_as_last_good", keep), patch.object(
            coord._store, "async_save", save
        ):
            try:
                await coord._save_main()
            except Stop:
                pass
        main = _read(real_disk, STORAGE_KEY)
        last = _read(real_disk, LAST_GOOD)
        assert main is not None, step
        assert last is not None, step
        assert os.path.getmtime(os.path.join(real_disk, LAST_GOOD)) <= os.path.getmtime(
            os.path.join(real_disk, STORAGE_KEY)
        ), step
    coord2 = await restart_with(hass, entry)
    assert coord2._restored_from is None


def test_a_link_writes_no_data_and_keeps_the_old_contents(tmp_path):
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("old")
    assert keep_as_last_good(live, copy) == "link"
    assert os.stat(live).st_ino == os.stat(copy).st_ino
    # Home Assistant's write: a temporary file swapped in.
    (tmp_path / "file.new").write_text("new")
    os.replace(tmp_path / "file.new", live)
    assert live.read_text() == "new" and copy.read_text() == "old"
    assert not (tmp_path / "file.last-good.tmp").exists()


def test_a_copy_where_links_are_refused(tmp_path):
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("old")
    with patch.object(os, "link", side_effect=OSError("not supported")):
        assert keep_as_last_good(live, copy) == "copy"
    assert os.stat(live).st_ino != os.stat(copy).st_ino
    assert copy.read_text() == "old" and live.read_text() == "old"


def test_no_live_file_keeps_nothing(tmp_path):
    assert keep_as_last_good(tmp_path / "none", tmp_path / "none.last-good") is None
    assert not (tmp_path / "none.last-good").exists()


def test_a_stale_temporary_copy_is_replaced(tmp_path):
    """A stop between the link and the swap leaves a temporary name;
    the next save starts again from the live file."""
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("now")
    (tmp_path / "file.last-good.tmp").write_text("stale")
    assert keep_as_last_good(live, copy) == "link"
    assert copy.read_text() == "now"


async def test_the_restore_never_writes_over_a_shared_file(
    hass: HomeAssistant, real_disk
):
    """A missing main file is still restored from last-good, and the
    restore leaves last-good as it was."""
    entry, coord = await _house(hass)
    kept = {}

    def remove():
        # After the stop's own save, which kept last-good afresh.
        kept["last_good"] = _read(real_disk, LAST_GOOD)
        os.remove(os.path.join(real_disk, STORAGE_KEY))

    coord2 = await restart_with(hass, entry, remove)
    assert coord2._restored_from is not None
    assert _read(real_disk, LAST_GOOD) == kept["last_good"]
    assert not os.path.exists(os.path.join(real_disk, f"{STORAGE_KEY}.tmp"))


async def test_the_history_file_stays_in_place_too(hass: HomeAssistant, real_disk):
    from custom_components.device_sentinel import history_file

    live = os.path.join(real_disk, "device_sentinel.history")
    with open(live, "w", encoding="utf-8") as handle:
        handle.write('{"data": {}}')
    assert history_file.keep_last_good(hass)
    assert os.path.exists(live)
    assert os.path.exists(f"{live}.last-good")


def test_the_copy_never_writes_through_a_link_left_at_its_name(tmp_path):
    """Where links are refused, the copy goes into a new file only: a
    link left at the temporary name is refused, never written through."""
    from custom_components.device_sentinel.backup import _copy_new

    live = tmp_path / "file"
    live.write_text("data")
    target = tmp_path / "elsewhere"
    target.write_text("untouched")
    planted = tmp_path / "file.last-good.tmp"
    planted.symlink_to(target)
    try:
        _copy_new(live, planted)
    except FileExistsError:
        pass
    assert target.read_text() == "untouched"


def test_a_second_keep_of_the_same_file_leaves_nothing_behind(tmp_path):
    """After a stop between the keep and the save, live and last-good
    are one file. The next keep does nothing and leaves no temporary
    name, which a later copy would otherwise write through."""
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("old")
    keep_as_last_good(live, copy)
    assert keep_as_last_good(live, copy) == "link"
    assert not (tmp_path / "file.last-good.tmp").exists()


def test_the_copy_keeps_the_time_its_contents_were_written(tmp_path):
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("old")
    os.utime(live, (1_700_000_000, 1_700_000_000))
    with patch.object(os, "link", side_effect=OSError("not supported")):
        keep_as_last_good(live, copy)
    assert os.path.getmtime(copy) == 1_700_000_000


def test_a_last_good_that_is_a_symlink_is_made_a_real_copy(tmp_path):
    """A symlink to the live file is the same file by name, and would
    show the new file after the next save: no backup at all."""
    live, copy = tmp_path / "file", tmp_path / "file.last-good"
    live.write_text("old")
    copy.symlink_to(live)
    keep_as_last_good(live, copy)
    assert not copy.is_symlink()
    (tmp_path / "file.new").write_text("new")
    os.replace(tmp_path / "file.new", live)
    assert copy.read_text() == "old"
