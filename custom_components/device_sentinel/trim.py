# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: trim.py, Version: 0.16.7 (2026-08-20)

"""Erasing one device's or one integration's learned history.

The only place in the integration that destroys a person's data on
purpose (ruling #307). It exists for support: a fault found by
reading somebody's diagnostics used to need a bespoke repair written
into a release, which is what the 0.16.2 one-time trim was, and that
does not scale past the first few people. The measure of this module
is whether a support message can read "go to the Advanced tab, pick
that device, save."

Three properties it has to hold, and each is a rule rather than an
implementation detail.

It is idempotent. Picking a device with nothing left to delete is
allowed and does nothing but write its event, because a faulty record
can read as empty and the empty-looking device is exactly the one a
person will be told to pick. A trim that refused the second time
would make the support instruction unreliable.

It never touches the nightly last-good pair. The copy it takes is its
own stamped file, so a sequence of trims cannot bury the state the
first one started from, and the pair the fold maintains stays exactly
what the fold left.

It erases history and nothing else. Muting and exclude entries
survive, because a trimmed device is rediscovered within seconds and
trimming data is not a statement about wanting the device gone
(ruling #307). Bridge, broker, pairing and storm state survive,
because they describe the house's plumbing rather than a device's
learned history, and clearing them would fabricate gaps in the
attribution windows other devices depend on.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DATA_TODO_JOURNAL,
    INC_DEVICE_ID,
    LOGGER,
    TODO_DEVICE_ID,
    TRIM_BACKUP_DIR,
)


def _stamp(directory: str, now: datetime) -> str:
    """Return a filename stamp no existing copy already uses.

    Local time to the second, and then a suffix if that second is
    taken. Two trims inside one second sounded impossible when this
    was written and the comment said so; the adversarial pass did it
    on the first attempt, and a person saving the screen twice in
    quick succession does the same. The copy is the only way back,
    and the case where somebody trims twice in a hurry is exactly
    the case where they are most likely to want the first one, so a
    silent overwrite is the wrong failure. The suffix keeps the
    promise the help text makes: one file per trim, never
    overwritten.
    """
    base = now.strftime("%Y-%m-%d_%H%M%S")
    stamp = base
    suffix = 2
    while os.path.exists(
        os.path.join(directory, f"device_sentinel_{stamp}.storage.json")
    ):
        stamp = f"{base}_{suffix}"
        suffix += 1
    return stamp


def write_backup(
    directory: str,
    now: datetime,
    storage: dict[str, Any],
    clocks: dict[str, Any],
) -> str:
    """Copy both storage files, return the stamp that names them.

    Raises rather than returning a failure, and the caller deletes
    nothing when it raises: a trim whose copy did not land is a trim
    that must not proceed, since the copy is the only way back.
    """
    os.makedirs(directory, exist_ok=True)
    stamp = _stamp(directory, now)
    for name, payload in (
        ("storage", storage),
        ("clocks", clocks),
    ):
        path = os.path.join(
            directory, f"device_sentinel_{stamp}.{name}.json"
        )
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    return stamp


def trim_devices(
    data: dict[str, Any],
    device_ids: set[str],
) -> dict[str, int]:
    """Erase these devices' history in place, return what went.

    Everything keyed on the device: the record with its second-scale
    block, the silence episodes, the incidents, the problem-list
    items and their journal entries. The clock file needs no separate
    pass because it is derived from the records at save time, so
    deleting the record deletes the clock entry with it. The device is
    rediscovered on its next event with a fresh record, learning from
    nothing, and its never-reported clock starts again, so it is
    exempt from a freeze verdict for the next forty-eight hours
    whatever it does.

    System events are not filtered. They belong to the house rather
    than to any device, and a restart that happened is still a
    restart that happened.
    """
    removed = {
        "records": 0,
        "episodes": 0,
        "incidents": 0,
        "todo_items": 0,
        "journal": 0,
    }
    devices = data.get(DATA_DEVICES)
    if isinstance(devices, dict):
        for device_id in device_ids:
            if devices.pop(device_id, None) is not None:
                removed["records"] += 1

    for key, field, counter in (
        (DATA_EPISODES, INC_DEVICE_ID, "episodes"),
        (DATA_INCIDENTS, INC_DEVICE_ID, "incidents"),
        (DATA_TODO_ITEMS, TODO_DEVICE_ID, "todo_items"),
        (DATA_TODO_JOURNAL, TODO_DEVICE_ID, "journal"),
    ):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        kept = [
            row
            for row in rows
            if not (
                isinstance(row, dict)
                and row.get(field) in device_ids
            )
        ]
        removed[counter] = len(rows) - len(kept)
        data[key] = kept
    return removed


def describe(
    removed: dict[str, int], names: list[str], domains: list[str]
) -> str:
    """Return the event's detail line: what was picked and what went.

    Names rather than counts alone, because the question asked of an
    event log months later is which device this was, and a count
    cannot answer it. Long lists are truncated: the backup file holds
    the whole truth and the event is a pointer to it.
    """
    picked: list[str] = []
    if domains:
        picked.append(", ".join(sorted(domains)))
    if names:
        shown = sorted(names)
        if len(shown) > 6:
            picked.append(
                ", ".join(shown[:6]) + f" and {len(shown) - 6} more"
            )
        else:
            picked.append(", ".join(shown))
    counts = ", ".join(
        f"{value} {label.replace('_', ' ')}"
        for label, value in removed.items()
        if value
    )
    # "Nothing recorded" said on its own read as a failed trim on the
    # first live one, when an excluded television was picked and had
    # no record to delete because an excluded device's record goes at
    # the fold. The trim did exactly what it should; the sentence has
    # to say that rather than leave a person wondering whether the
    # tool works.
    outcome = counts or "nothing was recorded for it, so nothing went"
    return f"{'; '.join(picked)}: {outcome}"


def log_result(
    stamp: str, removed: dict[str, int], names: list[str]
) -> None:
    """Say what happened at info, where a person can find it.

    The one destructive act the integration performs, so it says so
    plainly, says what actually went, and names the file that holds
    the way back. The counts were accepted and dropped on the floor
    until ruling #329: a person reading this line after a trim that
    matched a device with no record needs to see the zero rather
    than infer it from a name with nothing beside it.
    """
    went = (
        ", ".join(
            f"{kind} {count}"
            for kind, count in sorted(removed.items())
            if count
        )
        or "nothing recorded"
    )
    LOGGER.info(
        "Trimmed %d device(s): %s. Erased: %s. Storage copied first "
        "to %s/device_sentinel_%s.storage.json",
        len(names),
        ", ".join(sorted(names)) or "none",
        went,
        TRIM_BACKUP_DIR,
        stamp,
    )
