# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_planted_links.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: planted links in Device Sentinel's own folders.

Someone who can write into config/.storage or config/device_sentinel
(an add-on, a Samba share, a backup restored from elsewhere) plants a
symbolic link where Device Sentinel will write or read, aiming at a file
outside its folders. Device Sentinel must never write through such a
link, and never take a planted link's target in as its own storage.

Every test asserts the SAFE behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import backup
from custom_components.device_sentinel.backup import _copy_new, keep_as_last_good
from custom_components.device_sentinel.const import (
    BACKUP_LAST_GOOD_SUFFIX,
    REPORT_WWW_DIR,
    STORAGE_KEY,
)
from custom_components.device_sentinel.report_maintainer import MaintainerReportMixin
from custom_components.device_sentinel.reports import ReportWritingMixin

ORIGINAL = "ORIGINAL CONTENTS OUTSIDE THE FOLDER"


def _victim(tmp_path: Path) -> Path:
    victim = tmp_path / "outside" / "secrets.yaml"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text(ORIGINAL, encoding="utf-8")
    return victim


def test_a_report_never_writes_through_a_planted_temporary_link(tmp_path):
    """Every report is written to "<name>.tmp" with open(..., "w"),
    which follows a link left at that name, and then moved over the
    report. A link planted at brief.html.tmp makes the next report
    overwrite the file it points to. Safe: the outside file is
    untouched."""
    victim = _victim(tmp_path)
    folder = tmp_path / "config" / "device_sentinel"
    folder.mkdir(parents=True)
    os.symlink(victim, folder / "brief.html.tmp")
    try:
        ReportWritingMixin._write_file(str(folder / "brief.html"), "REPORT TEXT")
    except OSError:
        pass
    assert victim.read_text(encoding="utf-8") == ORIGINAL


def test_a_report_never_writes_through_a_link_at_its_own_name(tmp_path):
    """The report's own name planted as a link (expected to hold: the
    move replaces the link)."""
    victim = _victim(tmp_path)
    folder = tmp_path / "config" / "device_sentinel"
    folder.mkdir(parents=True)
    os.symlink(victim, folder / "frozen.md")
    ReportWritingMixin._write_file(str(folder / "frozen.md"), "REPORT TEXT")
    assert victim.read_text(encoding="utf-8") == ORIGINAL


def test_the_probe_file_never_appends_through_a_planted_link(tmp_path):
    """The Extended Diagnostics probe file is appended to in place.
    A link planted at stack_probe.md makes every probe line land at the
    end of the file it points to. Safe: the outside file is untouched."""
    victim = _victim(tmp_path)
    folder = tmp_path / "config" / "device_sentinel"
    folder.mkdir(parents=True)
    path = folder / "stack_probe.md"
    os.symlink(victim, path)
    host = SimpleNamespace(_probe_lock=threading.Lock(), _probe_header=lambda: ["| h |"])
    try:
        MaintainerReportMixin._probe_append(host, str(folder), str(path), ["| line |"], False)
    except OSError:
        pass
    assert victim.read_text(encoding="utf-8") == ORIGINAL


def test_last_good_never_writes_through_planted_links(tmp_path):
    """keep_as_last_good with a link at the copy and at its temporary
    name (expected to hold)."""
    victim = _victim(tmp_path)
    storage = tmp_path / ".storage"
    storage.mkdir()
    live = storage / "device_sentinel.storage"
    live.write_text('{"version": 1, "data": {}}', encoding="utf-8")
    os.symlink(victim, storage / "copy.tmp")
    keep_as_last_good(live, storage / "copy")
    os.symlink(victim, storage / "copy2")
    keep_as_last_good(live, storage / "copy2")
    assert victim.read_text(encoding="utf-8") == ORIGINAL
    assert not (storage / "copy2").is_symlink()


def test_a_copy_refuses_a_planted_link(tmp_path):
    """_copy_new refuses a destination that is a link (expected to hold)."""
    victim = _victim(tmp_path)
    source = tmp_path / "source"
    source.write_text("NEW", encoding="utf-8")
    os.symlink(victim, tmp_path / "dest")
    try:
        _copy_new(source, tmp_path / "dest")
    except OSError:
        pass
    assert victim.read_text(encoding="utf-8") == ORIGINAL


async def test_the_restore_never_takes_in_a_planted_last_good_link(hass: HomeAssistant):
    """When the main file will not parse, the last-good copy is copied
    over it. A link planted at device_sentinel.storage.last-good,
    pointing at any JSON file the process can read (another
    integration's storage, say), is followed and that file becomes
    Device Sentinel's main storage file, which the diagnostics download
    then carries. Safe: a last-good that is a link is not restored from."""
    storage = Path(hass.config.path(".storage"))
    storage.mkdir(parents=True, exist_ok=True)
    outside = Path(hass.config.path("outside_auth.json"))
    outside.write_text(
        json.dumps({"version": 1, "data": {"devices": {"x": {}}, "refresh_token": "SECRET-TOKEN"}}),
        encoding="utf-8",
    )
    live = storage / STORAGE_KEY
    copy = storage / f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
    live.write_text("{not json", encoding="utf-8")
    os.symlink(outside, copy)
    try:
        await backup.async_restore_main_file(hass)
        assert "SECRET-TOKEN" not in live.read_text(encoding="utf-8")
    finally:
        for path in (live, copy, outside, storage / f"{STORAGE_KEY}.tmp"):
            if path.is_symlink() or path.exists():
                path.unlink()


async def test_a_directory_at_the_main_file_never_crashes_the_restore(hass: HomeAssistant):
    """A directory where the main file belongs (expected to hold:
    the restore reports it could not, and raises nothing)."""
    storage = Path(hass.config.path(".storage"))
    storage.mkdir(parents=True, exist_ok=True)
    live = storage / STORAGE_KEY
    copy = storage / f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
    live.mkdir()
    copy.write_text(json.dumps({"version": 1, "data": {"devices": {"a": {}}}}), encoding="utf-8")
    try:
        assert await backup.async_restore_main_file(hass) == (False, None)
    finally:
        live.rmdir()
        copy.unlink()
        tmp = storage / f"{STORAGE_KEY}.tmp"
        if tmp.exists():
            tmp.unlink()


async def test_retiring_the_www_folder_never_deletes_through_a_link(hass: HomeAssistant):
    """www/device_sentinel planted as a link to another folder: the
    retirement must not empty the folder it points to (expected to
    hold: rmtree refuses a link)."""
    from custom_components.device_sentinel import _async_retire_www_folder

    outside = Path(hass.config.path("keep_me"))
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "photo.jpg").write_text("x", encoding="utf-8")
    link = Path(hass.config.path(REPORT_WWW_DIR))
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, link)
    try:
        await _async_retire_www_folder(hass)
        assert (outside / "photo.jpg").exists()
    finally:
        if link.is_symlink():
            link.unlink()
        (outside / "photo.jpg").unlink(missing_ok=True)
        outside.rmdir()
