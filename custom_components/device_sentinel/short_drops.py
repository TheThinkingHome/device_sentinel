# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: short_drops.py, Version: 0.28.0 (2026-11-03)

"""Each drop a device makes, recorded (rule SIG-16).

A drop is a device going unavailable as a whole and coming back on its
own. Each is kept with when the device went, how long it was gone, the
freeze window it was judged against then, the signal at the drop, the
signal at the recovery and the device's usual signal, so a later rule
can tell a weak-signal drop from one with a strong signal at both ends.
A drop no longer than its window is a short drop.

This release records and shows; it judges nothing. Notifications, the
Problem List and the mutes are as before. The rule that will read these
rows comes with the next release.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_SHORT_DROPS,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_VALUE,
    DROP_DEVICE_ID,
    DROP_LENGTH,
    DROP_SIGNAL_BACK,
    DROP_SIGNAL_USUAL,
    DROP_SIGNAL_WENT,
    DROP_WENT,
    DROP_WINDOW,
    SHORT_DROP_HOURS,
    SHORT_DROP_SIGNAL_BACK_SECONDS,
    SHORT_DROP_USUAL_DAYS,
)


def _reading(value: Any) -> float | None:
    """A signal reading, or None for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def usual_signal(record: dict[str, Any]) -> float | None:
    """The middle of the device's daily typical signal over its last
    days, or None with no such day (rule SIG-16)."""
    days = [
        value
        for value in (record.get(DEV_SIGNAL_DAILY_P50) or [])[-SHORT_DROP_USUAL_DAYS:]
        if _reading(value) is not None
    ]
    return float(median(days)) if days else None


def is_short(row: dict[str, Any]) -> bool:
    """A drop no longer than the freeze window it was judged against."""
    window = row.get(DROP_WINDOW)
    length = row.get(DROP_LENGTH)
    if not isinstance(window, (int, float)) or isinstance(window, bool):
        return False
    if not isinstance(length, (int, float)) or isinstance(length, bool):
        return False
    return length <= window


class ShortDropMixin:
    """Records each drop and answers what the device page shows."""

    def _note_drop(
        self, device_id: str, record: dict[str, Any], went: float, back: float
    ) -> None:
        """Record one drop that ended now (rule SIG-16).

        Only a drop the device made on its own: not one its broker,
        bridge, network or integration took it down with, and not one
        that spans Device Sentinel's own restart, whose end measures
        the restart rather than the device. The signal at the recovery
        is the first reading after it, filled in when it arrives.
        """
        if not (isinstance(went, (int, float)) and isinstance(back, (int, float))):
            return
        if back <= went:
            return
        started = getattr(self, "_started_at", None)
        if isinstance(started, (int, float)) and went < started:
            return
        if self.upstream_down_since(device_id) is not None:  # type: ignore[attr-defined]
            return
        try:
            window = self._freeze_window(record)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a record nobody can judge yet
            window = None
        row = {
            DROP_DEVICE_ID: device_id,
            DROP_WENT: float(went),
            DROP_LENGTH: float(back - went),
            DROP_WINDOW: float(window) if isinstance(window, (int, float)) else None,
            DROP_SIGNAL_WENT: _reading(record.get(DEV_SIGNAL_VALUE)),
            DROP_SIGNAL_BACK: None,
            DROP_SIGNAL_USUAL: usual_signal(record),
        }
        self.data.setdefault(DATA_SHORT_DROPS, []).append(row)  # type: ignore[attr-defined]
        self._drop_awaiting_signal[device_id] = (row, float(back))  # type: ignore[attr-defined]
        self._mark_cold_dirty()  # type: ignore[attr-defined]

    def _drop_signal_back(self, device_id: str, value: float, now: float) -> None:
        """The first signal reading after a drop is its recovery signal,
        if it comes within a few minutes of the return (rule SIG-16)."""
        waiting = self._drop_awaiting_signal.pop(device_id, None)  # type: ignore[attr-defined]
        if waiting is None:
            return
        row, back = waiting
        if now - back > SHORT_DROP_SIGNAL_BACK_SECONDS:
            return
        row[DROP_SIGNAL_BACK] = _reading(value)
        self._mark_cold_dirty()  # type: ignore[attr-defined]

    def short_drops_of(self, device_id: str, now: float | None = None) -> dict[str, Any] | None:
        """The device page's Short drop-outs row: how many short drops in
        the last 12 hours, the longest and when the last one went, or
        None with none (rules SIG-16, DASH-08)."""
        now = dt_util.utcnow().timestamp() if now is None else now
        since = now - SHORT_DROP_HOURS * 3600.0
        rows = [
            row
            for row in self.data.get(DATA_SHORT_DROPS) or []  # type: ignore[attr-defined]
            if isinstance(row, dict)
            and row.get(DROP_DEVICE_ID) == device_id
            and isinstance(row.get(DROP_WENT), (int, float))
            and row[DROP_WENT] >= since
            and is_short(row)
        ]
        if not rows:
            return None
        return {
            "count": len(rows),
            "longest": max(row[DROP_LENGTH] for row in rows),
            "last": dt_util.utc_from_timestamp(max(row[DROP_WENT] for row in rows)).isoformat(),
            "hours": SHORT_DROP_HOURS,
        }
