# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: backup.py, Version: 0.10.11 (2026-07-31)

"""A one-shot copy of both storage files, taken before a release removes
something it cannot put back.

Why this exists (#130). The two-file split was built so that stepping
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

import shutil
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from .const import (
    BACKUP_TAKEN_KEY,
    LOGGER,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)


def _storage_path(hass: HomeAssistant, key: str) -> Path:
    """Return the on-disk path of a Store, given its key."""
    return Path(hass.config.path(STORAGE_DIR)) / key


def _copy_one(source: Path, destination: Path) -> bool:
    """Copy one file, reporting whether the copy now exists.

    A missing source is not a failure. The clocks file does not exist
    until the first save after 0.8.8, and a house that has never run
    that far has nothing to preserve; the caller's job is to protect
    what is there, not to invent what is not.
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
