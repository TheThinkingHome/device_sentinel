# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: backup.py, Version: 0.18.0 (2026-08-25)

"""A one-shot copy of both storage files, taken before a release removes
something it cannot put back.

Why this exists (ruling #130). The two-file split was built so that stepping
back to an earlier version was free at every stage: the main file went
on carrying the clock fields unused, so an older build loaded a
complete record and lost nothing. The phase that removes those fields
closes that window. Afterwards, going back means loading a file whose
clocks stopped at the moment of the strip, and every device would come
up with an activity time hours or days stale. So the release that
strips takes a copy of what it is about to change, before it changes
it.

Why it ships inert. The mechanism that did this for the earlier phases
was removed in 0.10.1 once its one-shot copies had been taken, which
left the ruled requirement with nothing behind it. Rebuilding it in the
release that also strips would mean the backup's first exercise is the
one run that matters. It is therefore built, tested and shipped here
with no caller, so the strip release adds only the call.

The copy is deliberately a byte copy of the files on disk rather than a
serialization of what is in memory. What a rollback needs is the file
the older version would have read, and the only thing certain to be
exactly that is the file itself.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util import dt as dt_util

from .const import (
    BACKUP_LAST_GOOD_SUFFIX,
    BACKUP_TAKEN_KEY,
    LOGGER,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    TRIM_BACKUP_DIR,
)


def _storage_path(hass: HomeAssistant, key: str) -> Path:
    """Return the on-disk path of a Store, given its key."""
    return Path(hass.config.path(STORAGE_DIR)) / key


def _copy_one(source: Path, destination: Path) -> bool:
    """Copy one file, reporting whether the copy now exists.

    A missing source is not a failure. The clocks file is the second
    half of the storage split and does not exist until a version that
    writes it has saved at least once (it arrived in 0.8.8), and a
    house that has never run that far has nothing to preserve; the
    caller's job is to protect what is there, not to invent what is
    not.
    """
    if not source.exists():
        LOGGER.debug(
            "Storage backup: %s does not exist, nothing to copy",
            source.name,
        )
        return True
    shutil.copyfile(source, destination)
    return destination.exists()


async def async_take_backup(
    hass: HomeAssistant, data: dict[str, Any], suffix: str
) -> bool:
    """Copy both storage files once, under the given suffix.

    Returns True when the backup is in place or was already taken, and
    False when it could not be made. A caller that is about to remove
    data must treat False as a stop: doing nothing is harmless, while
    stripping without a copy is the one step that cannot be undone.

    The marker recording that a suffix has been taken lives in the
    storage payload the caller passes in, so it is saved with
    everything else and a second boot does not overwrite the copy with
    a file the new version has already changed. That last point is the
    whole reason the marker exists rather than a simple existence test
    on the file: after the strip, the live file is no longer the thing
    worth preserving.
    """
    taken = data.get(BACKUP_TAKEN_KEY) or []
    if suffix in taken:
        LOGGER.debug("Storage backup '%s' was already taken", suffix)
        return True

    pairs = [
        (
            _storage_path(hass, key),
            _storage_path(hass, f"{key}.{suffix}"),
        )
        for key in (STORAGE_KEY, STORAGE_CLOCKS_KEY)
    ]

    def _copy_all() -> bool:
        return all(
            _copy_one(source, destination) for source, destination in pairs
        )

    try:
        copied = await hass.async_add_executor_job(_copy_all)
    except OSError as err:
        LOGGER.error(
            "Storage backup '%s' failed and nothing has been changed: %s",
            suffix,
            err,
        )
        return False

    if not copied:
        LOGGER.error(
            "Storage backup '%s' did not produce the expected files and "
            "nothing has been changed",
            suffix,
        )
        return False

    data[BACKUP_TAKEN_KEY] = [*taken, suffix]
    LOGGER.info(
        "Storage backup '%s' taken: %s and %s copied beside the originals",
        suffix,
        STORAGE_KEY,
        STORAGE_CLOCKS_KEY,
    )
    return True


async def async_refresh_last_good(hass: HomeAssistant) -> bool:
    """Overwrite the rolling last-good copy of both storage files.

    Unlike async_take_backup this is not once-per-suffix: it is meant
    to be taken again and again, and the newest copy is the one worth
    having. What makes it safe to overwrite is that the caller only
    calls it after a shape check reported nothing (ruling #278), so
    the copy is by construction of a file the checks passed. A boot or
    a fold that found a fault does not call this, and last-good is
    left as the previous clean copy: it lags a repaired boot by one,
    which is the direction it should lag.

    Returns True when both files were copied, False on any failure. A
    False here is a log line and nothing else; a backup that could not
    be refreshed is a stale backup, not a broken integration.
    """
    pairs = [
        (
            _storage_path(hass, key),
            _storage_path(hass, f"{key}.{BACKUP_LAST_GOOD_SUFFIX}"),
        )
        for key in (STORAGE_KEY, STORAGE_CLOCKS_KEY)
    ]

    def _copy_all() -> bool:
        return all(
            _copy_one(source, destination) for source, destination in pairs
        )

    try:
        copied = await hass.async_add_executor_job(_copy_all)
    except OSError as err:
        LOGGER.warning(
            "Storage last-good copy could not be refreshed: %s", err
        )
        return False
    if not copied:
        LOGGER.warning(
            "Storage last-good copy did not produce the expected files"
        )
        return False
    LOGGER.debug("Storage last-good copy refreshed")
    return True


async def async_copy_evidence(hass: HomeAssistant) -> str | None:
    """Copy both storage files and both last-good files aside, raw.

    Called when a load has verified faulty, before the first save
    (ruling #340). The live pair is the evidence: the coordinator's
    own first save re-serializes the file after migrations have
    touched it, so without this copy the original of what actually
    went wrong is destroyed by the process that found it. The
    last-good pair rides along because it is what every later repair
    reads, and a session that is about to act on either should
    preserve both first.

    Raw bytes, not a re-serialization: `shutil.copy2` of whichever of
    the four files exist. Nothing in the integration ever reads these
    copies back; the directory is the person's way back, pruned at
    the fold by the same retention setting as everything else
    (ruling #343).

    Returns the stamp that names the copies, or None when nothing
    could be copied. A failure is a log line, not a stop: refusing to
    load because an evidence copy failed would turn a full disk into
    a dead integration.
    """
    directory = hass.config.path(TRIM_BACKUP_DIR)
    now = dt_util.now()

    def _copy_all() -> str | None:
        os.makedirs(directory, exist_ok=True)
        base = now.strftime("%Y-%m-%d_%H%M%S")
        stamp = base
        suffix = 2
        while os.path.exists(
            os.path.join(
                directory, f"device_sentinel_{stamp}.storage.evidence"
            )
        ):
            stamp = f"{base}_{suffix}"
            suffix += 1
        sources = [
            (_storage_path(hass, STORAGE_KEY), f"{stamp}.storage.evidence"),
            (
                _storage_path(hass, STORAGE_CLOCKS_KEY),
                f"{stamp}.clocks.evidence",
            ),
            (
                _storage_path(
                    hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
                ),
                f"{stamp}.storage.last-good",
            ),
            (
                _storage_path(
                    hass, f"{STORAGE_CLOCKS_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
                ),
                f"{stamp}.clocks.last-good",
            ),
        ]
        copied = 0
        for source, name in sources:
            if not os.path.exists(source):
                continue
            shutil.copy2(
                source, os.path.join(directory, f"device_sentinel_{name}")
            )
            copied += 1
        return stamp if copied else None

    try:
        return await hass.async_add_executor_job(_copy_all)
    except OSError as err:
        LOGGER.warning("Storage evidence copy failed: %s", err)
        return None


async def async_last_good_taken(hass: HomeAssistant) -> float | None:
    """Return when the last-good pair was last refreshed.

    The pair is written together, so the older of the two stamps is
    the honest answer: a pair with one fresh file and one stale one
    is only as current as the stale one. Read from the files rather
    than from memory so the answer survives a restart (ruling #341).
    """
    paths = [
        _storage_path(hass, f"{key}.{BACKUP_LAST_GOOD_SUFFIX}")
        for key in (STORAGE_KEY, STORAGE_CLOCKS_KEY)
    ]

    def _oldest() -> float | None:
        stamps = []
        for path in paths:
            if not os.path.exists(path):
                return None
            stamps.append(os.path.getmtime(path))
        return min(stamps) if stamps else None

    try:
        return await hass.async_add_executor_job(_oldest)
    except OSError:
        return None


async def async_prune_backups(
    hass: HomeAssistant, retention_days: int
) -> int:
    """Delete trim-backup files older than the retention window.

    The same `history_days` setting that bounds every daily series
    bounds this directory, one retention idea rather than two
    (ruling #343). No file is special: a copy older than the window
    describes a fleet state older than anything else the integration
    still remembers.

    Returns how many files were removed.
    """
    directory = hass.config.path(TRIM_BACKUP_DIR)
    horizon = dt_util.utcnow().timestamp() - retention_days * 86400.0

    def _prune() -> int:
        if not os.path.isdir(directory):
            return 0
        removed = 0
        for name in os.listdir(directory):
            if not name.startswith("device_sentinel_"):
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.getmtime(path) < horizon:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
        return removed

    try:
        return await hass.async_add_executor_job(_prune)
    except OSError as err:
        LOGGER.warning("Trim-backup pruning failed: %s", err)
        return 0
