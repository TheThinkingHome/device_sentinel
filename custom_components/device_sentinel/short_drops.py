# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: short_drops.py, Version: 0.28.2 (2026-11-04)

"""Each drop a device makes, recorded (rule SIG-16).

A drop is a device going unavailable as a whole and coming back on its
own. Each is kept with when the device went, how long it was gone, the
limit it was judged against then, the signal at the drop, the
signal at the recovery and the device's usual signal, so a later rule
can tell a weak-signal drop from one with a strong signal at both ends.
A drop back within its limit is a short drop: the device's freeze
margin, never more than the Short Drop-Out Limit setting.

Each drop is kept as recorded for 7 days, at most 100 a device a day.
At midnight older drops are folded into one row per device per day,
held to the History setting: how many drops, how many short, the total
and longest time out, and the average signal at the drop and at the
return beside the usual signal. A day with no drops writes nothing.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_SHORT_DROP_DAYS,
    DATA_SHORT_DROPS,
    DATA_SYSTEM_EVENTS,
    DROP_DAY,
    DROP_DAY_DROPS,
    DROP_DAY_LONGEST,
    DROP_DAY_SHORT,
    DROP_DAY_SIGNAL_BACK_N,
    DROP_DAY_SIGNAL_WENT_N,
    DROP_DAY_TOTAL,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_VALUE,
    DROP_DEVICE_ID,
    DROP_LENGTH,
    DROP_SIGNAL_BACK,
    DROP_SIGNAL_USUAL,
    DROP_SIGNAL_WENT,
    DROP_WENT,
    DROP_WINDOW,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    CONF_SHORT_DROP_LIMIT,
    DEFAULT_SHORT_DROP_LIMIT,
    SHORT_DROP_DAY_LIMIT,
    SHORT_DROP_LIMIT_MAX,
    SHORT_DROP_LIMIT_MIN,
    SHORT_DROP_HOURS,
    SHORT_DROP_KEEP_DAYS,
    SHORT_DROP_SIGNAL_BACK_SECONDS,
    SHORT_DROP_USUAL_DAYS,
    STARTUP_GRACE_SECONDS,
    SYS_KIND,
    SYS_RESTART,
    SYS_WHEN,
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


def drop_day(moment: float) -> str:
    """The local day a drop went on, as YYYY-MM-DD."""
    return dt_util.as_local(dt_util.utc_from_timestamp(moment)).date().isoformat()


def add_to_day(days: list[Any], row: dict[str, Any], cap: float | None = None) -> None:
    """Count one drop into its device's row for the day it went
    (rule SIG-16)."""
    device_id = row.get(DROP_DEVICE_ID)
    went = row.get(DROP_WENT)
    length = row.get(DROP_LENGTH)
    if not isinstance(device_id, str) or not isinstance(went, (int, float)) or isinstance(went, bool):
        return
    length = float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) else 0.0
    day = drop_day(float(went))
    held = next(
        (d for d in days if isinstance(d, dict) and d.get(DROP_DEVICE_ID) == device_id and d.get(DROP_DAY) == day),
        None,
    )
    if held is None:
        held = {
            DROP_DEVICE_ID: device_id, DROP_DAY: day, DROP_DAY_DROPS: 0, DROP_DAY_SHORT: 0,
            DROP_DAY_TOTAL: 0.0, DROP_DAY_LONGEST: 0.0,
            DROP_SIGNAL_WENT: None, DROP_DAY_SIGNAL_WENT_N: 0,
            DROP_SIGNAL_BACK: None, DROP_DAY_SIGNAL_BACK_N: 0,
            DROP_SIGNAL_USUAL: None,
        }
        days.append(held)
    held[DROP_DAY_DROPS] += 1
    held[DROP_DAY_SHORT] += 1 if is_short(row, cap) else 0
    held[DROP_DAY_TOTAL] = round(held[DROP_DAY_TOTAL] + length, 1)
    held[DROP_DAY_LONGEST] = round(max(held[DROP_DAY_LONGEST], length), 1)
    for field, count in ((DROP_SIGNAL_WENT, DROP_DAY_SIGNAL_WENT_N), (DROP_SIGNAL_BACK, DROP_DAY_SIGNAL_BACK_N)):
        value = _reading(row.get(field))
        if value is None:
            continue
        n = held[count]
        before = held[field] if isinstance(held[field], (int, float)) else 0.0
        held[field] = round((before * n + value) / (n + 1), 2)
        held[count] = n + 1
    usual = _reading(row.get(DROP_SIGNAL_USUAL))
    if usual is not None:
        held[DROP_SIGNAL_USUAL] = usual


def forget_restart_drops(data: dict[str, Any]) -> int:
    """Remove the drops that went inside the startup grace after a
    recorded restart, kept for each device its integration had not
    yet published (rule UP-04). Judged on the
    rows, so it is the same on every load. Returns how many went."""
    starts = [
        row[SYS_WHEN] for row in data.get(DATA_SYSTEM_EVENTS) or []
        if isinstance(row, dict) and row.get(SYS_KIND) == SYS_RESTART
        and isinstance(row.get(SYS_WHEN), (int, float)) and not isinstance(row.get(SYS_WHEN), bool)
    ]
    drops = data.get(DATA_SHORT_DROPS)
    if not starts or not isinstance(drops, list):
        return 0

    def at_a_start(row: Any) -> bool:
        went = row.get(DROP_WENT) if isinstance(row, dict) else None
        if not isinstance(went, (int, float)) or isinstance(went, bool):
            return False
        return any(start <= went < start + STARTUP_GRACE_SECONDS for start in starts)

    kept = [row for row in drops if not at_a_start(row)]
    gone = len(drops) - len(kept)
    if gone:
        data[DATA_SHORT_DROPS] = kept
    return gone


def is_short(row: dict[str, Any], cap: float | None = None) -> bool:
    """A drop no longer than the limit it was judged against, and, with
    `cap`, no longer than the Short Drop-Out Limit now (rule SIG-16).

    An older row carries the device's whole freeze window; the cap
    brings it to the limit in force, so no stored row needs rewriting. A drop back inside the three-minute debounce is no drop
    (rule UNAV-03)."""
    window = row.get(DROP_WINDOW)
    length = row.get(DROP_LENGTH)
    if not isinstance(window, (int, float)) or isinstance(window, bool):
        return False
    if not isinstance(length, (int, float)) or isinstance(length, bool):
        return False
    if length < FREEZE_UNAVAILABLE_DEBOUNCE:
        return False
    limit = min(window, cap) if cap is not None else window
    return length <= limit


class ShortDropMixin:
    """Records each drop and answers what the device page shows."""

    def _short_drop_cap(self) -> float:
        """The Short Drop-Out Limit, in seconds, held to its bounds (rule
        SIG-16)."""
        try:
            minutes = float(self.entry.options.get(CONF_SHORT_DROP_LIMIT, DEFAULT_SHORT_DROP_LIMIT))  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            minutes = float(DEFAULT_SHORT_DROP_LIMIT)
        return max(SHORT_DROP_LIMIT_MIN, min(minutes, SHORT_DROP_LIMIT_MAX)) * 60.0

    def _short_drop_limit(self, record: dict[str, Any]) -> float | None:
        """How long a drop may last and still be short, for this device:
        its freeze margin (the patience on top of its rhythm, from Delta
        Low and Delta High), never more than the Short Drop-Out Limit;
        None for a device with no learned rhythm yet (rule SIG-16). A
        device's rhythm says how often it reports, not how long it takes
        to reconnect, so it is left out."""
        try:
            found = self._freeze_rhythm(record)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a record nobody can judge yet
            return None
        if not found:
            return None
        rhythm = found.get("rhythm")
        if not isinstance(rhythm, (int, float)) or isinstance(rhythm, bool):
            return None
        window = found.get("window")
        if isinstance(window, (int, float)) and not isinstance(window, bool):
            margin = window - rhythm
        else:
            margin = self._freeze_grace(rhythm)  # type: ignore[attr-defined]
        return min(max(float(margin), 0.0), self._short_drop_cap())

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
        # A device back inside the three-minute debounce never turned
        # unavailable, so it made no drop (rules UNAV-03, SIG-16).
        if back - went < FREEZE_UNAVAILABLE_DEBOUNCE:
            return
        started = getattr(self, "_started_at", None)
        if isinstance(started, (int, float)) and went < started:
            return
        # A device unavailable inside the startup grace is waiting for
        # its integration to publish it, as Zigbee2MQTT's devices do for
        # about half a minute after each restart: that is the start, not
        # the device (rule UP-04).
        grace = getattr(self, "_grace_until", None)
        if isinstance(grace, (int, float)) and went < grace:
            return
        if self.upstream_down_since(device_id) is not None:  # type: ignore[attr-defined]
            return
        window = self._short_drop_limit(record)
        row = {
            DROP_DEVICE_ID: device_id,
            DROP_WENT: float(went),
            DROP_LENGTH: float(back - went),
            DROP_WINDOW: float(window) if isinstance(window, (int, float)) else None,
            DROP_SIGNAL_WENT: _reading(record.get(DEV_SIGNAL_VALUE)),
            DROP_SIGNAL_BACK: None,
            DROP_SIGNAL_USUAL: usual_signal(record),
        }
        drops = self.data.setdefault(DATA_SHORT_DROPS, [])  # type: ignore[attr-defined]
        day = drop_day(float(went))
        today = sum(
            1 for r in drops
            if isinstance(r, dict) and r.get(DROP_DEVICE_ID) == device_id
            and isinstance(r.get(DROP_WENT), (int, float)) and drop_day(float(r[DROP_WENT])) == day
        )
        if today >= SHORT_DROP_DAY_LIMIT:
            # Past the day's limit a drop counts in the day's row only
            # (rule SIG-16).
            add_to_day(self.data.setdefault(DATA_SHORT_DROP_DAYS, []), row, self._short_drop_cap())  # type: ignore[attr-defined]
        else:
            drops.append(row)
            self._drop_awaiting_signal[device_id] = (row, float(back))  # type: ignore[attr-defined]
        self._mark_cold_dirty()  # type: ignore[attr-defined]

    def _fold_short_drops(self, now: float, keep_after: float) -> bool:
        """At midnight, fold each drop older than 7 days into its day's
        row, and hold the day rows to the History setting (rule SIG-16).
        Returns whether anything changed."""
        drops = self.data.setdefault(DATA_SHORT_DROPS, [])  # type: ignore[attr-defined]
        days = self.data.setdefault(DATA_SHORT_DROP_DAYS, [])  # type: ignore[attr-defined]
        line = now - SHORT_DROP_KEEP_DAYS * 86400.0
        kept: list[Any] = []
        folded = 0
        for row in drops:
            went = row.get(DROP_WENT) if isinstance(row, dict) else None
            if isinstance(went, (int, float)) and not isinstance(went, bool) and went < line:
                add_to_day(days, row, self._short_drop_cap())
                folded += 1
            else:
                kept.append(row)
        oldest = drop_day(keep_after)
        held = [d for d in days if not isinstance(d, dict) or not isinstance(d.get(DROP_DAY), str) or d[DROP_DAY] >= oldest]
        if folded or len(held) != len(days):
            self.data[DATA_SHORT_DROPS] = kept  # type: ignore[attr-defined]
            self.data[DATA_SHORT_DROP_DAYS] = held  # type: ignore[attr-defined]
            return True
        return False

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
            and is_short(row, self._short_drop_cap())
        ]
        if not rows:
            return None
        return {
            "count": len(rows),
            "longest": max(row[DROP_LENGTH] for row in rows),
            "last": dt_util.utc_from_timestamp(max(row[DROP_WENT] for row in rows)).isoformat(),
            "hours": SHORT_DROP_HOURS,
        }
