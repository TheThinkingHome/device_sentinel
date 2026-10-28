# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: outage_detail.py, Version: 0.27.10 (2026-10-27)

"""Which config entry an integration outage was, and which device.

SwitchBot, TP-Link and Brother make one config entry per device, so
an outage named by the integration alone reads one dead device as the
whole integration down, cannot tell two such devices apart, and closes
one's outage when the other comes back (rule UP-10).

The entry, the one watched device it carries when it carries one, and
whether it failed to start or went down after running, travel in the
event's `detail`, a string by the storage shape:

    entry:01ABC... device:9f3e... failed

An older event with no detail reads as it did.
"""

from __future__ import annotations

from typing import Any

FAILED = "failed"
DOWN = "down"
# An entry deleted from Home Assistant while it was down: its outage is
# closed as removed, never told as back (rule UP-10).
REMOVED = "removed"
# An entry still in Home Assistant whose devices Device Sentinel stopped
# watching while it was down, excluded or set aside.
UNWATCHED = "unwatched"


def make_detail(entry_id: str, device_id: str | None, how: str) -> str:
    """Return the detail an integration outage event carries."""
    return f"entry:{entry_id} device:{device_id or '-'} {how}"


def parse_detail(detail: Any) -> tuple[str | None, str | None, str | None]:
    """Return (entry id, device id, how), each None when absent."""
    if not isinstance(detail, str) or not detail.startswith("entry:"):
        return None, None, None
    entry_id = device_id = how = None
    for part in detail.split():
        if part.startswith("entry:"):
            entry_id = part[6:] or None
        elif part.startswith("device:"):
            device_id = None if part[7:] in ("", "-") else part[7:]
        elif part in (FAILED, DOWN, REMOVED, UNWATCHED):
            how = part
    return entry_id, device_id, how


def pair_key(kind: Any, scope: Any, detail: Any) -> tuple[Any, Any, str | None]:
    """The key an opener and its closer are paired by.

    Kind and scope, and for an integration outage the entry too, so two
    entries of one integration are two outages. Rows with no entry pair
    by kind and scope alone.
    """
    return kind, scope, parse_detail(detail)[0]
