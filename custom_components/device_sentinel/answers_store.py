# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/answers_store.py, Version: 0.25.2 (2026-10-09)

"""The one file that holds what the owner set with a pencil (0.25.1).

Every answer a person types on a device page lives here: what powers
the device and what the device is. Nothing else in Device Sentinel's
storage is typed by hand, so this file keeps a last-good copy taken
before each save (ruling #370's rule, given to the power file in 0.25.0)
and is restored from it at start when it cannot be read.

The file:
    {"power": {"models": {...}, "devices": {...}},
     "types": {"models": {...}, "devices": {...}}}

"models" holds an answer per model, keyed by model_key; "devices" holds
the answer of a device with no manufacturer or no model.

Until 0.25.1 the power answers lived in device_sentinel.power. The
first start of 0.25.1 moves them here, reads the new file back, and
only then deletes the old file and its last-good copy (James, 8 October
2026). A rollback to an older release finds no power answers; that is
said in the release note. The move is removed at 1.0.0.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from homeassistant.util import dt as dt_util

from .const import BACKUP_LAST_GOOD_SUFFIX, LOGGER, TRIM_BACKUP_DIR
from .power_source import power_words

ANSWERS_STORE_KEY = "device_sentinel.answers"
ANSWERS_STORE_VERSION = 1
# Read once, by the move, then deleted. Remove at 1.0.0.
LEGACY_POWER_KEY = "device_sentinel.power"

# Why an answer is held rather than shown on a watched device.
HELD_GONE = "not in Home Assistant"
HELD_NOT_WATCHED = "not watched"
HELD_MODEL_CHANGED = "now reports another model"


def _path(hass: Any, key: str, suffix: str = "") -> str:
    return hass.config.path(".storage", key + (f".{suffix}" if suffix else ""))


def _rotate_last_good(hass: Any) -> None:
    """Rename the live answers file to last-good; nothing if there is none."""
    live = _path(hass, ANSWERS_STORE_KEY)
    if os.path.exists(live):
        os.replace(live, _path(hass, ANSWERS_STORE_KEY, BACKUP_LAST_GOOD_SUFFIX))


def _read_last_good(hass: Any, key: str) -> dict[str, Any] | None:
    """The data of a last-good file, or None if it is missing or unusable."""
    try:
        with open(_path(hass, key, BACKUP_LAST_GOOD_SUFFIX), encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    data = document.get("data") if isinstance(document, dict) else None
    return data if isinstance(data, dict) else None


def _remove_legacy_last_good(hass: Any) -> None:
    with suppress(FileNotFoundError):
        os.remove(_path(hass, LEGACY_POWER_KEY, BACKUP_LAST_GOOD_SUFFIX))


def _copy_answers_evidence(hass: Any) -> list[str]:
    """Copy the answers file, its backup and any old power file aside,
    raw, before a repair writes over them (0.25.2, #340's rule given to
    the answers file). Returns the names written."""
    directory = hass.config.path(TRIM_BACKUP_DIR)
    stamp = dt_util.now().strftime("%Y-%m-%d_%H%M%S")
    written: list[str] = []
    sources = sorted(
        glob.glob(_path(hass, ANSWERS_STORE_KEY) + "*") + glob.glob(_path(hass, LEGACY_POWER_KEY) + "*")
    )
    if not sources:
        return written
    os.makedirs(directory, exist_ok=True)
    for source in sources:
        name = f"device_sentinel_{stamp}.{os.path.basename(source)[len('device_sentinel.'):]}.evidence"
        # Contents only, with today's time: the trim_backups pruning
        # judges age by the file's time, and the answers file can be
        # months old, so a copy that kept it was pruned the same night
        # (0.25.2, found by review).
        shutil.copyfile(source, os.path.join(directory, name))
        written.append(name)
    return written


def _bad_tables(payload: dict[str, Any], sections: tuple[str, ...]) -> list[str]:
    """The tables in a payload that are there but are not tables.

    A section or its models or devices that a hand edit or a damaged
    write turned into a list, a string or null held every answer in it,
    and reading it as empty lost them all without a word (0.25.2, found
    by testing). An absent table is not damage: a file from before it
    existed simply has none.
    """
    bad = []
    for name in sections:
        section = payload.get(name) if name else payload
        label = name or "old power file"
        if name and name in payload and not isinstance(section, dict):
            bad.append(label)
            continue
        if not isinstance(section, dict):
            continue
        for table in ("models", "devices"):
            if table in section and not isinstance(section[table], dict):
                bad.append(f"{label} {table}")
    return bad


def _live_on_disk(hass: Any) -> bool:
    return os.path.exists(_path(hass, ANSWERS_STORE_KEY))


def _legacy_on_disk(hass: Any) -> bool:
    return any(
        os.path.exists(_path(hass, LEGACY_POWER_KEY, suffix))
        for suffix in ("", BACKUP_LAST_GOOD_SUFFIX)
    )


async def _load(store: Store[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """A store's data, or None when it is missing or cannot be read.

    Home Assistant raises more than its own error for a file that is
    valid text in the wrong shape: a missing version or data field, a
    list or null at the top. A hand edit or a half-restored backup can
    leave one, and none may stop a start (0.25.1, found by testing).
    """
    try:
        payload = await store.async_load()
    except (
        HomeAssistantError, ValueError, OSError, KeyError, TypeError, AttributeError, NotImplementedError
    ) as err:
        # NotImplementedError: a version below 1 asks for a migration
        # this file has never had (found by review).
        LOGGER.warning("Device Sentinel cannot read %s (%s: %s)", key, type(err).__name__, err)
        return None
    return payload if isinstance(payload, dict) else None


class AnswersMixin:
    """The coordinator's side of the answers file."""

    _answers_store: Store[dict[str, Any]] | None = None
    _answers_pending: bool = False
    _answers_timer: Callable[[], None] | None = None
    _answers_lock: asyncio.Lock
    _answers_rotation_armed: bool = False
    # Held by PowerMixin and TypeMixin; named here for the type checker.
    _power_models: dict[str, dict[str, Any]]
    _power_entries: dict[str, dict[str, Any]]

    async def async_load_answers(self) -> None:
        """Read the owner's answers; nothing here can stop a start."""
        hass = self.hass  # type: ignore[attr-defined]
        self._answers_store = Store(hass, ANSWERS_STORE_VERSION, ANSWERS_STORE_KEY)
        self._answers_pending = False
        self._answers_timer = None
        self._answers_lock = asyncio.Lock()
        self._power_reset()  # type: ignore[attr-defined]
        self._type_reset()  # type: ignore[attr-defined]
        # Sentences for the events log, recorded once the session has
        # loaded (0.25.2, #342's rule: a repair nobody can see did not
        # happen as far as the person is concerned).
        self._answers_notes: list[str] = []
        self._answers_evidence_kept = False
        self._merge_dropped = 0

        # Asked before the read: Home Assistant renames a file it cannot
        # parse to .corrupt.<time> inside the read, so afterwards it
        # looks missing and an empty start went unreported (0.25.2,
        # found by testing).
        on_disk = await hass.async_add_executor_job(_live_on_disk, hass)
        payload = await _load(self._answers_store, ANSWERS_STORE_KEY)
        restored = False
        damaged = payload is None and on_disk
        if payload is None:
            # Missing or unreadable: Home Assistant moves a file it
            # cannot parse aside and answers nothing. The last clean
            # file is the person's own typing, which nothing else can
            # rebuild (0.25.0).
            payload = await hass.async_add_executor_job(_read_last_good, hass, ANSWERS_STORE_KEY)
            restored = payload is not None
            if restored:
                await self._keep_answers_evidence()
                # A stop between the rename to last-good and the write
                # leaves no file at all, which is not damage (found by
                # review).
                self._answers_notes.append(
                    "the answers set on device pages "
                    + ("could not be read" if on_disk else "were missing")
                    + ", so they were restored from their backup; a copy was kept in trim_backups"
                )
                LOGGER.warning(
                    "Device Sentinel restored the answers you set on device pages from %s.%s, "
                    "because %s could not be read",
                    ANSWERS_STORE_KEY, BACKUP_LAST_GOOD_SUFFIX, ANSWERS_STORE_KEY,
                )

        if payload is None:
            # A damaged file is kept and reported before anything is
            # taken from the old power file, which would otherwise
            # write over it with power answers alone and lose the type
            # answers without a word (0.25.2, found by review).
            legacy = await self._legacy_power()
            if damaged:
                await self._keep_answers_evidence()
                self._answers_notes.append(
                    "the answers set on device pages could not be read and had no "
                    "backup, so "
                    + ("only the power answers in the old power file were kept"
                       if legacy is not None else "they start empty")
                    + "; a copy was kept in trim_backups"
                )
            if legacy is not None:
                dropped = self._power_read(legacy, legacy=True)  # type: ignore[attr-defined]
                await self._note_dropped(dropped)
                await self._note_bad_tables(_bad_tables(legacy, ("",)))
                self._answers_rotation_armed = False
                await self._move_legacy_power()
                return
            payload = {}
            from_answers = False
        else:
            from_answers = True

        power = payload.get("power")
        types = payload.get("types")
        dropped = self._power_read(power if isinstance(power, dict) else {})  # type: ignore[attr-defined]
        dropped += self._type_read(types if isinstance(types, dict) else {})  # type: ignore[attr-defined]
        await self._note_dropped(dropped)
        bad = _bad_tables(payload, ("power", "types"))
        await self._note_bad_tables(bad)
        # A file read whole becomes last-good at the next save; a
        # restored or damaged one never does (ruling #370's rule).
        # A damaged file with no backup is not rotated either: the next
        # save would make it last-good (found by review).
        self._answers_rotation_armed = not restored and not dropped and not bad and not damaged
        if not from_answers or not await self._legacy_left():
            return
        # Both files: either a stop came between the move and its delete,
        # or the owner went back to an older release, which started with
        # no power answers and wrote the old file again for what was set
        # there, and then came forward. Each answer in the old file is
        # taken when it was set later than the answer here, or when there
        # is none here; nothing here is removed. File times are not used:
        # a backup copied back by hand gets a new one (found by review).
        # Only the file itself is read: its last-good copy can be from
        # before the move, so a damaged file leaves this one in charge.
        legacy = await _load(Store(hass, 1, LEGACY_POWER_KEY), LEGACY_POWER_KEY)
        self._merge_dropped = 0
        taken = self._merge_legacy_power(legacy) if legacy is not None else 0
        await self._note_dropped(self._merge_dropped)
        if legacy is not None:
            await self._note_bad_tables(_bad_tables(legacy, ("",)))
        if taken:
            LOGGER.info(
                "Device Sentinel took power answers set later from %s, saved by an older release",
                LEGACY_POWER_KEY,
            )
            await self._move_legacy_power()
            return
        await self._remove_legacy_power()

    def _merge_legacy_power(self, legacy: dict[str, Any]) -> int:
        """Merge the old file's power answers in, the later set winning.
        Returns how many were taken."""
        here_models = dict(self._power_models)  # type: ignore[attr-defined]
        here_entries = dict(self._power_entries)  # type: ignore[attr-defined]
        self._power_reset()  # type: ignore[attr-defined]
        self._merge_dropped = self._power_read(legacy, legacy=True)  # type: ignore[attr-defined]
        old_models = self._power_models  # type: ignore[attr-defined]
        old_entries = self._power_entries  # type: ignore[attr-defined]
        self._power_models, self._power_entries = here_models, here_entries  # type: ignore[attr-defined]

        def later(old: dict[str, Any], here: dict[str, Any] | None) -> bool:
            if here is None:
                return True
            return str(old.get("set") or "") > str(here.get("set") or "")

        taken = 0
        for key, entry in old_models.items():
            if later(entry, here_models.get(key)):
                here_models[key] = entry
                taken += 1
        for device_id, entry in old_entries.items():
            if later(entry, here_entries.get(device_id)):
                here_entries[device_id] = entry
                taken += 1
        return taken

    @staticmethod
    def _warn_dropped(dropped: int) -> None:
        if dropped:
            LOGGER.warning(
                "Device Sentinel left out %d answer%s set on device pages that it could not read",
                dropped, "" if dropped == 1 else "s",
            )

    async def _note_dropped(self, dropped: int) -> None:
        """Answers left out at load: the log, a copy of the files as they
        were, and a line in the events log the brief shows (0.25.2)."""
        if not dropped:
            return
        self._warn_dropped(dropped)
        await self._keep_answers_evidence()
        self._answers_notes.append(
            f"{dropped} answer{'' if dropped == 1 else 's'} set on device pages could not "
            "be read and were left out; a copy was kept in trim_backups"
        )

    async def _note_bad_tables(self, bad: list[str]) -> None:
        """Whole tables that could not be read: the log, a copy, a line."""
        if not bad:
            return
        LOGGER.warning(
            "Device Sentinel could not read part of the answers set on device pages (%s) and left it out",
            ", ".join(bad),
        )
        await self._keep_answers_evidence()
        self._answers_notes.append(
            f"part of the answers set on device pages ({', '.join(bad)}) could not be read "
            "and was left out; a copy was kept in trim_backups"
        )

    async def _keep_answers_evidence(self) -> None:
        """Copy the files aside once per start, before anything writes."""
        if getattr(self, "_answers_evidence_kept", False):
            return
        self._answers_evidence_kept = True
        hass = self.hass  # type: ignore[attr-defined]
        try:
            written = await hass.async_add_executor_job(_copy_answers_evidence, hass)
        except OSError as err:
            LOGGER.warning("Answers evidence copy failed: %s", err)
            return
        if written:
            LOGGER.warning("Answers evidence copied to trim_backups: %s", ", ".join(written))

    def answers_notes(self) -> list[str]:
        """Take the sentences waiting for the events log."""
        notes = list(getattr(self, "_answers_notes", None) or [])
        self._answers_notes = []
        return notes

    # ------------------------------------------------- the move from 0.25.0

    async def _legacy_power(self) -> dict[str, Any] | None:
        """The old power file's data, from its last-good copy if the file
        itself cannot be read; None when neither is there."""
        hass = self.hass  # type: ignore[attr-defined]
        payload = await _load(Store(hass, 1, LEGACY_POWER_KEY), LEGACY_POWER_KEY)
        if payload is None:
            payload = await hass.async_add_executor_job(_read_last_good, hass, LEGACY_POWER_KEY)
        return payload

    async def _legacy_left(self) -> bool:
        """Whether any of the old power file is still there."""
        hass = self.hass  # type: ignore[attr-defined]
        if await hass.async_add_executor_job(_legacy_on_disk, hass):
            return True
        return await _load(Store(hass, 1, LEGACY_POWER_KEY), LEGACY_POWER_KEY) is not None

    async def _move_legacy_power(self) -> None:
        """Write the answers file now, read it back, and delete the old
        power file only when what was read back is what was written.

        A save Home Assistant could not make is logged by Home Assistant
        and not raised, so reading back is the only proof. On any
        failure the old file stays, and the next start moves it again.
        """
        hass = self.hass  # type: ignore[attr-defined]
        payload = self._answers_payload()
        if self._answers_store is None:
            return
        if self._answers_rotation_armed:
            # Coming forward after a rollback: the answers file being
            # replaced is kept as last-good, as before any save.
            try:
                await hass.async_add_executor_job(_rotate_last_good, hass)
            except OSError as err:
                LOGGER.warning("Answers last-good rotation failed: %s", err)
        await self._answers_store.async_save(payload)
        self._answers_rotation_armed = True
        written = await _load(Store(hass, ANSWERS_STORE_VERSION, ANSWERS_STORE_KEY), ANSWERS_STORE_KEY)
        if written != payload:
            LOGGER.warning(
                "Device Sentinel could not confirm %s was written, so it kept %s; "
                "the move is tried again at the next start",
                ANSWERS_STORE_KEY, LEGACY_POWER_KEY,
            )
            return
        await self._remove_legacy_power()
        LOGGER.info(
            "Device Sentinel moved %d power answer%s from %s into %s and deleted the old file",
            self._answers_count("power"),
            "" if self._answers_count("power") == 1 else "s",
            LEGACY_POWER_KEY, ANSWERS_STORE_KEY,
        )

    async def _remove_legacy_power(self) -> None:
        hass = self.hass  # type: ignore[attr-defined]
        try:
            await Store(hass, 1, LEGACY_POWER_KEY).async_remove()
            await hass.async_add_executor_job(_remove_legacy_last_good, hass)
        except OSError as err:
            LOGGER.warning("Device Sentinel could not delete %s: %s", LEGACY_POWER_KEY, err)

    # ------------------------------------------------------------- saving

    def _answers_payload(self) -> dict[str, Any]:
        return {
            "power": self._power_payload(),  # type: ignore[attr-defined]
            "types": self._type_payload(),  # type: ignore[attr-defined]
        }

    def _answers_count(self, part: str) -> int:
        if part == "power":
            return len(self._power_models) + len(self._power_entries)  # type: ignore[attr-defined]
        return len(self._type_models) + len(self._type_entries)  # type: ignore[attr-defined]

    def _answers_save(self) -> None:
        """Write a second from now, so a burst of pencil saves makes one write."""
        if self._answers_store is None:
            return
        self._answers_pending = True
        cancel = getattr(self, "_answers_timer", None)
        if cancel is not None:
            cancel()
        hass = self.hass  # type: ignore[attr-defined]

        @callback
        def _due(_now: Any) -> None:
            self._answers_timer = None
            hass.async_create_task(self._answers_write())

        self._answers_timer = async_call_later(hass, 1, _due)

    async def _answers_write(self) -> None:
        """Write the file, the previous clean one kept as last-good.
        Saves take turns."""
        if self._answers_store is None or not getattr(self, "_answers_pending", False):
            return
        async with self._answers_lock:
            if not self._answers_pending:
                return
            self._answers_pending = False
            hass = self.hass  # type: ignore[attr-defined]
            if getattr(self, "_answers_rotation_armed", False):
                try:
                    await hass.async_add_executor_job(_rotate_last_good, hass)
                except OSError as err:
                    LOGGER.warning("Answers last-good rotation failed: %s", err)
            await self._answers_store.async_save(self._answers_payload())
            self._answers_rotation_armed = True

    async def async_flush_answers(self) -> None:
        """Write an answer still inside its one-second wait.

        The unload and Home Assistant's stop both call this (0.25.1: the
        stop did not, so a restart inside the second lost the answer).
        A write the timer already started is waited for, so a reload
        never reads the file while it is between its rotation and its
        save (0.25.1, found by testing).
        """
        cancel = getattr(self, "_answers_timer", None)
        if cancel is not None:
            cancel()
            self._answers_timer = None
        lock = getattr(self, "_answers_lock", None)
        if lock is not None:
            async with lock:
                pass
        await self._answers_write()

    # ------------------------------------------------------- diagnostics

    def answers_diagnostics(self) -> dict[str, Any]:
        """How many answers the file holds, and the ones held for devices
        Device Sentinel does not watch (0.25.1).

        An answer stays when its device is excluded or set aside, so it
        is back on the page if the device is watched again. Those are
        listed here in one place; deleting a device from Home Assistant
        still deletes its answers.
        """
        return {
            "file": ANSWERS_STORE_KEY,
            "power_models": len(self._power_models),  # type: ignore[attr-defined]
            "power_devices": len(self._power_entries),  # type: ignore[attr-defined]
            "type_models": len(self._type_models),  # type: ignore[attr-defined]
            "type_devices": len(self._type_entries),  # type: ignore[attr-defined]
            "held": self.answers_held(),
        }

    def answers_held(self) -> list[dict[str, Any]]:
        """Answers that cover no watched device, each with the devices it
        belongs to and why none of them is watched."""
        hass = self.hass  # type: ignore[attr-defined]
        registry = dr.async_get(hass)
        watched = set(self._watched)  # type: ignore[attr-defined]
        set_aside = self._set_aside  # type: ignore[attr-defined]
        power_models = self._power_models  # type: ignore[attr-defined]
        type_models = self._type_models  # type: ignore[attr-defined]
        power_entries = self._power_entries  # type: ignore[attr-defined]
        type_entries = self._type_entries  # type: ignore[attr-defined]

        def who(device_id: str, of_model: bool = True) -> dict[str, Any]:
            """of_model False: the device set the answer but is no
            longer that model, so the answer covers nothing."""
            aside = set_aside.get(device_id)
            known = registry.async_get(device_id) is not None
            if known:
                name = self._device_name(device_id)  # type: ignore[attr-defined]
            else:
                name = aside[0] if aside else None
            if aside:
                why = aside[2]
            elif not known:
                why = HELD_GONE
            elif not of_model:
                why = HELD_MODEL_CHANGED
            else:
                why = HELD_NOT_WATCHED
            return {"device_id": device_id, "name": name, "why": why}

        def words(power: dict[str, Any] | None, kind: dict[str, Any] | None) -> dict[str, Any]:
            sets = [str(e["set"]) for e in (power, kind) if e and e.get("set")]
            return {
                "power": power_words(power["type"], power["quantity"]) if power else None,
                "type": kind["type"] if kind else None,
                "set": max(sets) if sets else None,
            }

        by_model: dict[str, list[str]] = {}
        keys = set(power_models) | set(type_models)
        if keys:
            for device in self._registry_devices(registry):  # type: ignore[attr-defined]
                key = self._power_key(device.id)  # type: ignore[attr-defined]
                if key in keys:
                    by_model.setdefault(key, []).append(device.id)

        held: list[dict[str, Any]] = []
        for key in sorted(keys):
            members = by_model.get(key, [])
            if any(d in watched for d in members):
                continue
            power = power_models.get(key)
            kind = type_models.get(key)
            if members:
                devices = [who(d) for d in sorted(members)]
            else:
                setters = {e["device_id"] for e in (power, kind) if e and e.get("device_id")}
                devices = [who(d, of_model=False) for d in sorted(setters)]
            try:
                model: Any = json.loads(key)
            except ValueError:
                model = key
            held.append({"model": model, **words(power, kind), "devices": devices})
        for device_id in sorted(set(power_entries) | set(type_entries)):
            if device_id in watched:
                continue
            held.append({
                "model": None,
                **words(power_entries.get(device_id), type_entries.get(device_id)),
                "devices": [who(device_id)],
            })
        return held
