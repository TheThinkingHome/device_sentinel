# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: flapping.py, Version: 0.28.1 (2026-11-03)

"""A device with short drop-outs (rule SIG-17).

A short drop is a device going unavailable and coming back on its own
within its freeze window (rule SIG-16). Two short drops within 12 hours
put a device on the Problem List as having short drop-outs; it stays
there until 12 hours pass with no short drop, each short drop starting
the 12 hours again. One push when it is added and one when it is
removed; the drops in between push nothing.

While a device has short drop-outs, a drop that has not yet outlasted
its freeze window is not reported, because it may still prove short. A
drop that outlasts it is reported as the device becoming unavailable,
dated from when it went, as any other.

Short drop-outs are a signal problem: the Signal mute silences them,
and the Unavailable mute does not. The state is kept on the device's
record, read from the stored drops.
"""

from __future__ import annotations

import math
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DATA_SHORT_DROPS,
    DEV_DOWN_FROM,
    DEV_FLAP_BACK,
    DEV_FLAP_DROPS,
    DEV_FLAP_LONGEST,
    DEV_FLAP_SINCE,
    DEV_REMOVED_SINCE,
    DROP_DEVICE_ID,
    DROP_LENGTH,
    DROP_WENT,
    SHORT_DROP_HOURS,
    SHORT_DROPS_TO_START,
)
from .short_drops import is_short


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class FlapMixin:
    """Say which devices have short drop-outs, and since when."""

    def _short_drops_by_device(self) -> dict[str, list[tuple[float, float]]]:
        """Each device's short drops, as (went, came back), oldest first.

        Built once for the table as it stands and kept until a drop is
        added or the table is folded, since the list, the push and each
        device's words all read it on every pass."""
        table = self.data.get(DATA_SHORT_DROPS) or []
        key = (id(table), len(table), id(table[-1]) if table else None)
        cached = getattr(self, "_short_drops_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        found: dict[str, list[tuple[float, float]]] = {}
        for row in table:
            if not isinstance(row, dict) or not is_short(row):
                continue
            device_id = row.get(DROP_DEVICE_ID)
            went = _number(row.get(DROP_WENT))
            length = _number(row.get(DROP_LENGTH))
            if not isinstance(device_id, str) or went is None or length is None:
                continue
            found.setdefault(device_id, []).append((went, went + length))
        for drops in found.values():
            drops.sort()
        self._short_drops_cache = (key, found)
        return found

    def _track_flaps(self, rows: list[dict[str, Any]], now: float) -> None:
        """Add or remove each device's short drop-outs (rule SIG-17).

        Called before the list is built, so a device added on this pass
        is listed on it. `rows` is kept for the caller's sake; the state
        is read from the stored drops.
        """
        del rows
        hold = SHORT_DROP_HOURS * 3600.0
        by_device = self._short_drops_by_device()
        for device_id, record in self.data[DATA_DEVICES].items():
            if not isinstance(record, dict):
                continue
            if record.get(DEV_REMOVED_SINCE) is not None:
                # Held after its removal, so not judged (rule WATCH-07).
                continue
            drops = by_device.get(device_id) or []
            since = _number(record.get(DEV_FLAP_SINCE))
            if since is None and not drops and not record.get(DEV_FLAP_DROPS):
                continue
            before = (since, list(record.get(DEV_FLAP_DROPS) or []), record.get(DEV_FLAP_BACK))
            recent = [drop for drop in drops if now - drop[0] <= hold]
            if since is None:
                if len(recent) >= SHORT_DROPS_TO_START:
                    since = recent[0][0]
            else:
                ran = [drop for drop in drops if drop[0] >= since]
                last_back = max((back for _went, back in ran), default=since)
                if now - last_back > hold:
                    since = None
            record[DEV_FLAP_SINCE] = since
            record[DEV_FLAP_DROPS] = [went for went, _back in drops if since is not None and went >= since]
            record[DEV_FLAP_BACK] = max((back for _w, back in drops), default=None) if since is not None else None
            record[DEV_FLAP_LONGEST] = 0.0
            if before != (since, record[DEV_FLAP_DROPS], record[DEV_FLAP_BACK]):
                self._dirty = True
                self._critical = True

    def is_flapping(self, device_id: str) -> bool:
        """Return whether a device has short drop-outs."""
        record = self.data[DATA_DEVICES].get(device_id)
        return isinstance(record, dict) and _number(record.get(DEV_FLAP_SINCE)) is not None

    def short_drop_waiting(self, device_id: str, since: Any, now: float) -> bool:
        """Whether a device that went unavailable at `since` is still
        inside the wait of a device with short drop-outs: its drop has
        not yet outlasted its freeze window (rule SIG-17)."""
        if not self.is_flapping(device_id):
            return False
        record = self.data[DATA_DEVICES].get(device_id)
        if not isinstance(record, dict):
            return False
        # When the device itself went, saved with the record (rule
        # UNAV-07), or the verdict's own moment.
        went = _number(record.get(DEV_DOWN_FROM))
        if went is None:
            went = _number(since)
        if went is None:
            return False
        try:
            window = self._freeze_window(record)
        except Exception:  # noqa: BLE001 - a record nobody can judge yet
            window = None
        if window is None:
            return False
        return now - went <= window

    @property
    def flapping_list(self) -> list[dict[str, Any]]:
        """The devices with short drop-outs, for the list, the pages and
        the brief. Muted devices are left out, as they are from every
        other problem; the Signal mute takes short drop-outs and the
        Unavailable mute does not (rule MUTE-06)."""
        rows = []
        now = dt_util.utcnow().timestamp()
        for device_id, record in self.data[DATA_DEVICES].items():
            if not isinstance(record, dict):
                continue
            since = _number(record.get(DEV_FLAP_SINCE))
            if since is None:
                continue
            if device_id not in self._watched or device_id in self._muted_devices:
                continue
            if self._signal_muted(device_id):
                continue
            count, _longest = self._recent_short_drops(device_id, now)
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "since": since,
                "drops": count,
            })
        rows.sort(key=lambda row: row["since"])
        return rows

    def _recent_short_drops(self, device_id: str, now: float) -> tuple[int, float]:
        """How many short drops ended in the last 12 hours, and the
        longest: the same 12 hours that keep the device listed, so a
        listed device never reads none."""
        line = now - SHORT_DROP_HOURS * 3600.0
        drops = [
            back - went for went, back in self._short_drops_by_device().get(device_id, [])
            if back >= line
        ]
        return len(drops), max(drops, default=0.0)

    def short_drop_count_words(self, device_id: str) -> str:
        """The device page's words beside "Short drop-outs": "3 in the
        last 12 hours" (rule SIG-17)."""
        count, _longest = self._recent_short_drops(device_id, dt_util.utcnow().timestamp())
        return f"{count} in the last {SHORT_DROP_HOURS} hours"

    def flap_words(self, device_id: str) -> str:
        """The words a device with short drop-outs is listed and pushed
        with: "6 short drop-outs in the last 12 hours, each back within
        21 minutes". Read by the Problem List, the push and the brief
        alike; the push adds "Check its signal." and the list and the
        brief carry the longer check beneath (rules NOTE-01, LIST-02,
        SIG-17)."""
        count, longest = self._recent_short_drops(device_id, dt_util.utcnow().timestamp())
        if not count:
            return f"short drop-outs in the last {SHORT_DROP_HOURS} hours"
        minutes = max(1, math.ceil(longest / 60.0))
        within = f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
        noun = "short drop-out" if count == 1 else "short drop-outs"
        each = "back within" if count == 1 else "each back within"
        return f"{count} {noun} in the last {SHORT_DROP_HOURS} hours, {each} {within}"
