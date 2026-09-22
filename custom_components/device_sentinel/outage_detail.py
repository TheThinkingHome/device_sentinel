# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: outage_detail.py, Version: 0.22.23 (2026-09-22)

"""Which config entry an integration outage was, and which device.

An integration outage was recorded by the integration's name alone.
SwitchBot, TP-Link and Brother make one config entry per device, so on
the second fleet one freezer sensor with a dead battery read as "the
switchbot integration went down", two such sensors could not be told
apart, and one coming back closed the other's outage (0.22.23).

The entry, the one watched device it carries when it carries one, and
whether it failed to start or went down after running, travel in the
event's `detail`, a string by the storage shape:

    entry:01ABC... device:9f3e... failed

An event written before 0.22.23 has no detail and reads as it did.
"""

from __future__ import annotations

from typing import Any

FAILED = "failed"
DOWN = "down"


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
        elif part in (FAILED, DOWN):
            how = part
    return entry_id, device_id, how


def pair_key(kind: Any, scope: Any, detail: Any) -> tuple[Any, Any, str | None]:
    """The key an opener and its closer are paired by.

    Kind and scope, as ever, and for an integration outage the entry
    too, so two entries of one integration are two outages. Rows with
    no entry pair as they always did.
    """
    return kind, scope, parse_detail(detail)[0]
