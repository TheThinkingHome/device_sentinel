# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: backup.py, Version: 0.19.11 (2026-08-31)

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

import json
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


async def async_rotate_last_good(hass: HomeAssistant) -> bool:
    """Rename the live main file to last-good, ahead of a clean save.

    The one backup rule (ruling #370): before each clean save, the
    file about to be replaced becomes the last-good copy, so
    last-good is always the most recent clean file. A rename rather
    than a copy, because the atomic write that follows puts a whole
    new file in place and the old one is otherwise discarded; the
    crash window between the rename and the write is the case the
    loader already restores from, a missing live file beside a
    last-good.

    Only the caller knows whether the save is clean and whether the
    live file on disk was itself written clean, so both judgments
    stay with the caller; this renames and nothing more. A missing
    live file is a first save and nothing to rotate. Returns True
    when the rename happened.
    """
    live = _storage_path(hass, STORAGE_KEY)
    copy = _storage_path(hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}")

    def _rotate() -> bool:
        if not live.exists():
            return False
        os.replace(live, copy)
        return True

    try:
        return await hass.async_add_executor_job(_rotate)
    except OSError as err:
        LOGGER.warning("Storage last-good rotation failed: %s", err)
        return False


async def async_delete_clocks_last_good(hass: HomeAssistant) -> bool:
    """Remove the clocks last-good file an earlier version wrote.

    Retired by ruling #370: the clocks file's contents are derived, a
    lost clock restarts honestly at now, and a restore has always
    deleted the file rather than restored it, so a backup of it
    protected nothing. Installs upgraded from 0.19.8 or earlier still
    carry one; it is deleted once here so no dump or evidence copy
    keeps carrying a file nothing reads. Returns True when a file was
    removed.
    """
    stale = _storage_path(
        hass, f"{STORAGE_CLOCKS_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
    )

    def _delete() -> bool:
        if not stale.exists():
            return False
        stale.unlink()
        return True

    try:
        removed = await hass.async_add_executor_job(_delete)
    except OSError as err:
        LOGGER.warning(
            "The retired clocks last-good file could not be removed: %s",
            err,
        )
        return False
    if removed:
        LOGGER.info(
            "Removed %s.%s: the clocks file is derived and its backup "
            "is retired",
            STORAGE_CLOCKS_KEY,
            BACKUP_LAST_GOOD_SUFFIX,
        )
    return removed


async def async_copy_evidence(
    hass: HomeAssistant,
) -> tuple[str | None, list[str]]:
    """Copy both storage files and the last-good file aside, raw.

    Called before any repair touches anything (ruling #340). The live
    pair is the evidence: a repair rewrites the file, so without this
    copy the original of what actually went wrong is destroyed by the
    process that found it. The main last-good copy rides along
    because it is what a restore reads, and a session that is about
    to act on either should preserve both first. The clocks file has
    no last-good since ruling #370.

    Raw bytes, not a re-serialization: `shutil.copy2` of whichever of
    the four files exist. Nothing in the integration ever reads these
    copies back; the directory is the person's way back, pruned at
    the fold by the same retention setting as everything else
    (ruling #343).

    Returns the stamp that names the copies and a plain list of what
    was actually written, or (None, []) when nothing could be copied.
    The list matters because the notice used to name four files
    whatever happened (ruling #349): on a missing storage file there
    was no storage file to copy, and the sentence said there was. A
    failure is a log line, not a stop: refusing to load because an
    evidence copy failed would turn a full disk into a dead
    integration.
    """
    directory = hass.config.path(TRIM_BACKUP_DIR)
    now = dt_util.now()

    def _copy_all() -> tuple[str | None, list[str]]:
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
        # Each source carries the words the notice will use, so the
        # sentence is built from what was copied rather than from an
        # assumption about what existed (ruling #349).
        sources = [
            (
                _storage_path(hass, STORAGE_KEY),
                f"{stamp}.storage.evidence",
                "the storage file",
            ),
            (
                _storage_path(hass, STORAGE_CLOCKS_KEY),
                f"{stamp}.clocks.evidence",
                "the clocks file",
            ),
            (
                _storage_path(
                    hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}"
                ),
                f"{stamp}.storage.last-good",
                "the storage backup",
            ),
        ]
        written: list[str] = []
        for source, name, said in sources:
            if not os.path.exists(source):
                continue
            shutil.copy2(
                source, os.path.join(directory, f"device_sentinel_{name}")
            )
            written.append(said)
        return (stamp if written else None), written

    try:
        return await hass.async_add_executor_job(_copy_all)
    except OSError as err:
        LOGGER.warning("Storage evidence copy failed: %s", err)
        return None, []


async def async_last_good_taken(hass: HomeAssistant) -> float | None:
    """Return when the last-good main file was made.

    One file since ruling #370: the clocks backup is retired, so the
    main copy's own stamp is the whole answer. Read from the file
    rather than from memory so the answer survives a restart
    (ruling #341). Under the rotation this is the moment of the last
    clean save's rename.
    """
    path = _storage_path(hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}")

    def _stamp() -> float | None:
        if not os.path.exists(path):
            return None
        return os.path.getmtime(path)

    try:
        return await hass.async_add_executor_job(_stamp)
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


async def async_restore_main_file(
    hass: HomeAssistant,
) -> tuple[bool, float | None]:
    """Replace an unreadable main storage file from the last-good copy.

    Called from the one place a storage file is found unreadable
    (ruling #345). The alternative to replacing it is not running at
    all, so nobody is asked: a question with one sensible answer is
    not a question.

    Only the main file is replaced. The clocks file is left where it
    is, holding today's counters, because the merge matches by device
    id and tolerates a companion that knows about devices the records
    do not. Restoring it too would roll back a day of live counters to
    buy consistency the merge does not need.

    Returns (restored, taken), where taken is the copy's timestamp so
    the caller can say how old it was and what that cost. A missing
    copy, an unreadable one, or a failed write all return (False,
    None) and the caller behaves exactly as it did before this
    existed: it stops with the sentence #327 gives it. One attempt,
    no retry: a copy that cannot be read now will not read better on
    a second pass, and a loop here is a boot loop.
    """
    live = _storage_path(hass, STORAGE_KEY)
    copy = _storage_path(hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}")

    def _restore() -> tuple[bool, float | None]:
        if not os.path.exists(copy):
            return False, None
        try:
            with open(copy, encoding="utf-8") as handle:
                json.load(handle)
        except (OSError, ValueError):
            # The copy is unreadable too. Say nothing over the live
            # file: a second bad file written over a first is worse
            # than the first alone.
            return False, None
        taken = os.path.getmtime(copy)
        shutil.copy2(copy, live)
        return True, taken

    try:
        return await hass.async_add_executor_job(_restore)
    except OSError as err:
        LOGGER.error(
            "Device Sentinel could not restore %s from its last-good "
            "copy: %s. Nothing has been changed",
            STORAGE_KEY,
            err,
        )
        return False, None


def describe_restore_loss(
    taken: float, now: float, *, embedded: bool = False
) -> str:
    """Say what a backup of that age cost, without inventing a count.

    The backup's timestamp is knowable and the corrupt file's contents
    are not, so this states the window and the kinds of record inside
    it, never how many (ruling #345). Any count of events or readings
    here would be a guess dressed as a fact.

    The number that matters is midnights crossed, not hours elapsed:
    the nightly rollover is what writes a day into the history, so a
    backup taken after last night's rollover has cost no daily history
    at all however old it looks. Dividing hours by 24 gets that wrong
    in both directions.

    Two forms from one arithmetic (ruling #352). The standalone form
    opens "The last-good backup was taken" and stands on its own in
    the repair card and the notification. The embedded form opens
    "which was taken" and follows "restored from the last-good
    backup," in the event detail, so the brief's sentence reads with
    one colon, no capital mid-sentence, and one full stop. The old
    shape embedded the standalone form and produced all three faults
    at once, live on the reference fleet on 27 August.
    """
    local_taken = dt_util.as_local(dt_util.utc_from_timestamp(taken))
    local_now = dt_util.as_local(dt_util.utc_from_timestamp(now))
    midnights = (local_now.date() - local_taken.date()).days
    hours = max(0.0, (now - taken) / 3600.0)
    when = local_taken.strftime("%B %-d at %-I:%M %p")
    head = (
        "which was taken" if embedded else "The last-good backup was taken"
    )

    if midnights <= 0:
        return (
            f"{head} today at {local_taken.strftime('%-I:%M %p')}, "
            f"{hours:.1f} hours prior to the restore. Today's "
            "counters since then are gone. No daily statistics were "
            "lost."
        )
    days = "day" if midnights == 1 else "days"
    return (
        f"{head} on {when}, {hours / 24:.1f} days prior to the "
        f"restore. That means {midnights} {days} of daily statistics "
        "will be lost."
    )


def _last_good_holds_devices(hass: HomeAssistant) -> bool:
    """Say whether the last-good main copy is worth restoring from.

    Ruling #348. Existing is not enough and parsing is not enough: a
    copy that parses to an empty document is indistinguishable from a
    first install, and promoting it over a genuine first install would
    invent a fleet from nothing. So the question asked is the only one
    that matters, does it hold device records.
    """
    copy = _storage_path(hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}")
    try:
        with open(copy, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    devices = data.get("devices")
    return isinstance(devices, dict) and bool(devices)


def _corrupt_siblings(hass: HomeAssistant) -> list[str]:
    """Return Home Assistant's own corrupt-file renames, newest first.

    When a storage file will not parse, Home Assistant renames it to
    `<file>.corrupt.<isotime>`, raises its own repair issue, and hands
    the integration None. It never raises, which is why the exception
    branch below it almost never fires (ruling #348). The presence of
    one of these files is Home Assistant telling us exactly what
    happened, so it is read as evidence rather than guessed at.
    """
    live = _storage_path(hass, STORAGE_KEY)
    directory = os.path.dirname(live)
    prefix = f"{os.path.basename(live)}.corrupt."
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(
        (name for name in names if name.startswith(prefix)), reverse=True
    )


async def async_diagnose_empty_load(
    hass: HomeAssistant,
) -> tuple[str, list[str]]:
    """Say why a load came back empty, and what evidence exists.

    Returns (reason, corrupt file names). The reason is one of:

    `corrupt`   Home Assistant renamed an unparseable file aside, and
                a last-good copy holding devices is available.
    `missing`   No file and no rename, but a last-good copy holding
                devices is available. Deletion, or a write that left
                nothing behind.
    `fresh`     No last-good copy worth restoring from. A genuine
                first install, or a fleet that has never recorded a
                device.

    A last-good copy is required for the first two, so a damaged or
    empty copy can never be promoted over a real first install.
    """

    def _look() -> tuple[str, list[str]]:
        corrupt = _corrupt_siblings(hass)
        if not _last_good_holds_devices(hass):
            return "fresh", corrupt
        return ("corrupt" if corrupt else "missing"), corrupt

    return await hass.async_add_executor_job(_look)


async def async_copy_corrupt_evidence(
    hass: HomeAssistant, names: list[str], stamp: str
) -> int:
    """Copy Home Assistant's corrupt renames into the evidence folder.

    They are the only remaining trace of what went wrong, and Home
    Assistant leaves them beside the live file where a later
    corruption puts a second one (ruling #348). Copied, not moved:
    moving a person's file out from under them is a decision they did
    not ask for, and the trim retention already prunes what we own.
    """
    live = _storage_path(hass, STORAGE_KEY)
    directory = os.path.dirname(live)
    target = hass.config.path(TRIM_BACKUP_DIR)

    def _copy() -> int:
        copied = 0
        os.makedirs(target, exist_ok=True)
        for name in names:
            try:
                shutil.copy2(
                    os.path.join(directory, name),
                    os.path.join(target, f"{stamp}-{name}"),
                )
            except OSError as err:
                LOGGER.warning("Could not copy %s aside: %s", name, err)
                continue
            copied += 1
        return copied

    return await hass.async_add_executor_job(_copy)


def read_main_file_raw(hass: HomeAssistant) -> dict[str, Any] | None:
    """Read the main storage file straight off disk, or None.

    The Store object caches its first parse, so a load that has
    already happened cannot see a file the restore just replaced.
    This reads the file itself, for the one caller that restores
    mid-load (ruling #370). Returns the data payload alone.
    """
    path = _storage_path(hass, STORAGE_KEY)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None


def read_last_good_raw(hass: HomeAssistant) -> dict[str, Any] | None:
    """Read the last-good main copy straight off disk, or None.

    Gate 1 looks before it leaps (ruling #372): a copy carrying the
    same container fault is not worth restoring to, and reading it
    first is cheaper than restoring and finding out. Returns the data
    payload alone.
    """
    path = _storage_path(hass, f"{STORAGE_KEY}.{BACKUP_LAST_GOOD_SUFFIX}")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None
