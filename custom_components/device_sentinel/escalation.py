# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: escalation.py, Version: 0.22.27 (2026-09-23)

"""A problem replaced by a worse one, told as the change it is.

The reference rig's watering sensor moved from frozen to unavailable
at the nightly reboot. The problem list wrote two rows in the same
pass: the unavailable one opened and the frozen one closed. 0.22.26
marked the closing row as superseded and stopped crediting the reboot,
but no reader looked at the mark, so the brief, its table, its counts
and the dashboard still said the device "recovered after 31.6h". A
battery forecast coming true did the same: "running down" closed as
"recovered" in the second the battery was marked low.

Readers pass their rows through `fold` first. A superseded closing is
joined to the worse opening of the same family written beside it, and
the pair becomes one row that the composer tells in the owner's words,
"was marked unavailable from frozen" and "battery was marked low from
running down" (0.22.27). The copy carries the lesser kind under
`ESCALATED_FROM`; stored rows are never touched, so the key never
reaches a file.

Only the same family pairs. A device going silent can clear its signal
rail in the same pass, and a silence is not a worse signal, so that
row reads as it always did. A superseded closing with no opening
beside it, because a trim or a repair removed it, also reads as it
always did, as does any row written before 0.22.26.
"""

from __future__ import annotations

from typing import Any

from .const import (
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_SUPERSEDED,
    INC_WHEN,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FAMILIES,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_SEVERITY,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
)

# Held on a reader's copy of the worse opening, never stored.
ESCALATED_FROM = "escalated_from"

# The two rows are written in one pass of the problem list, a few
# microseconds apart. A second is generous and still far shorter than
# any gap in which a device could recover and break again.
PAIR_SECONDS = 1.0

# What each kind is called in "was marked X from Y".
STATE_WORD = {
    TODO_KIND_FROZEN: "frozen",
    TODO_KIND_UNAVAILABLE: "unavailable",
    TODO_KIND_UNKNOWN: "unknown",
    TODO_KIND_NEVER_REPORTED: "never reported",
    TODO_KIND_LOW_BATTERY: "low",
    TODO_KIND_FALLING_BATTERY: "running down",
    TODO_KIND_RAILED_SIGNAL: "railed",
}


def _rank(kind: Any) -> int:
    """Return a kind's place in the severity order, unknown last."""
    if kind in TODO_KIND_SEVERITY:
        return TODO_KIND_SEVERITY.index(kind)
    return len(TODO_KIND_SEVERITY)


def _family(kind: Any) -> str | None:
    """Return a kind's family, or None for a kind this release lacks."""
    return TODO_KIND_FAMILIES.get(kind) if isinstance(kind, str) else None


def state_word(kind: Any) -> str:
    """Return a kind as the state a device was marked."""
    return STATE_WORD.get(kind, str(kind).replace("_", " "))


def fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the rows with each escalation told once.

    Order is kept. Each superseded closing is matched to the worst
    opening for the same device, of a worse kind in the same family,
    within PAIR_SECONDS. The closing is dropped and the opening is
    replaced by a copy that names the kind it replaced; where several
    lesser kinds went in the same pass, the copy names the worst of
    them, the one a reader last knew the device by.
    """
    openings = [
        index
        for index, row in enumerate(rows)
        if row.get(INC_EVENT) == INCIDENT_OPENED
    ]
    dropped: set[int] = set()
    lesser_for: dict[int, Any] = {}
    for index, row in enumerate(rows):
        if row.get(INC_EVENT) != INCIDENT_RESOLVED or not row.get(
            INC_SUPERSEDED
        ):
            continue
        when = row.get(INC_WHEN)
        if not isinstance(when, (int, float)):
            continue
        kind = row.get(INC_KIND)
        family = _family(kind)
        candidates = [
            other
            for other in openings
            if rows[other].get(INC_DEVICE_ID) == row.get(INC_DEVICE_ID)
            and family is not None
            and _family(rows[other].get(INC_KIND)) == family
            and _rank(rows[other].get(INC_KIND)) < _rank(kind)
            and isinstance(rows[other].get(INC_WHEN), (int, float))
            and abs(rows[other][INC_WHEN] - when) <= PAIR_SECONDS
        ]
        if not candidates:
            continue
        target = min(
            candidates, key=lambda other: _rank(rows[other].get(INC_KIND))
        )
        dropped.add(index)
        held = lesser_for.get(target)
        if held is None or _rank(kind) < _rank(held):
            lesser_for[target] = kind
    folded: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index in dropped:
            continue
        if index in lesser_for:
            row = {**row, ESCALATED_FROM: lesser_for[index]}
        folded.append(row)
    return folded
