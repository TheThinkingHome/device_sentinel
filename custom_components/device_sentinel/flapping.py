# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: flapping.py, Version: 0.23.2 (2026-09-24)

"""A device that keeps dropping out, learned and held (0.23.2).

The second fleet's S73 Door tilt sensor Shed3-Bay2 went unavailable
for three to four and a half minutes 53 times in 17 hours. Each drop
outlasted the three-minute wait, so each opened a problem, closed it,
and would have pushed twice. The owner ruled on 24 September: three
drops within two hours make a device flapping. While it flaps, the
longest it stayed back between drops is learned, from the current run
only, so a repaired device is never judged on an old run. It stays
flapping until it has stayed back longer than that plus the freeze
grace for a gap that size, the curve the two delta settings shape; then
the run ends and the next is learned afresh.

A drop is a verdict of unavailable, counted once by the moment it
began, so the drops are read from the same rows the list reads and a
restart that re-reads a standing verdict does not count it twice. The
run is stored on the device's record.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DEV_FLAP_BACK,
    DEV_FLAP_DROPS,
    DEV_FLAP_LONGEST,
    DEV_FLAP_SINCE,
    FLAP_DROPS_TO_START,
    FLAP_WINDOW_SECONDS,
    TODO_KIND_UNAVAILABLE,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class FlapMixin:
    """Learn each device's run of drops and say when it is a flap."""

    def _track_flaps(self, rows: list[dict[str, Any]], now: float) -> None:
        """Fold this pass's unavailable verdicts into each device's run.

        Called with the rows the list is built from, before it is
        built, so a flap that begins on this pass is on the list on
        this pass: the third drop is announced as a flap, not as a
        third unavailable device.
        """
        down: dict[str, float] = {}
        for row in rows:
            if row.get("category") != TODO_KIND_UNAVAILABLE:
                continue
            since = _number(row.get("since"))
            if since is not None:
                down[row["device_id"]] = since
        devices = self.data[DATA_DEVICES]
        for device_id, record in devices.items():
            if not isinstance(record, dict):
                continue
            drops = [
                value
                for value in (record.get(DEV_FLAP_DROPS) or [])
                if _number(value) is not None
            ]
            since_down = down.get(device_id)
            if since_down is None and not drops:
                continue
            changed = self._fold_flap(record, drops, since_down, now)
            if changed:
                self._dirty = True
                self._critical = True

    def _fold_flap(
        self,
        record: dict[str, Any],
        drops: list[float],
        since_down: float | None,
        now: float,
    ) -> bool:
        """Advance one device's run; return whether the record changed."""
        before = (
            list(record.get(DEV_FLAP_DROPS) or []),
            record.get(DEV_FLAP_SINCE),
            record.get(DEV_FLAP_BACK),
            record.get(DEV_FLAP_LONGEST),
        )
        back = _number(record.get(DEV_FLAP_BACK))
        longest = _number(record.get(DEV_FLAP_LONGEST)) or 0.0
        flapping = _number(record.get(DEV_FLAP_SINCE))

        if since_down is not None:
            if not drops or since_down > drops[-1]:
                # A new drop. The time back that ended with it is one
                # of the gaps the flap is learned from.
                if back is not None and drops:
                    longest = max(longest, since_down - back)
                drops.append(since_down)
            back = None
        elif drops and back is None:
            # Back since the last pass.
            back = now

        if flapping is None:
            # Not yet a flap: only the last two hours count toward one.
            drops = [value for value in drops if now - value <= FLAP_WINDOW_SECONDS]
            if not drops:
                back, longest = None, 0.0
            elif len(drops) >= FLAP_DROPS_TO_START:
                flapping = drops[0]
        elif back is not None:
            # A flap ends when the device has stayed back longer than
            # it ever did between drops, plus the grace a gap that
            # size is given before it is called frozen.
            hold = longest + self._freeze_grace(max(longest, 1.0))
            if now - back > hold:
                drops, flapping, back, longest = [], None, None, 0.0

        record[DEV_FLAP_DROPS] = drops
        record[DEV_FLAP_SINCE] = flapping
        record[DEV_FLAP_BACK] = back
        record[DEV_FLAP_LONGEST] = longest
        return before != (
            record[DEV_FLAP_DROPS],
            record[DEV_FLAP_SINCE],
            record[DEV_FLAP_BACK],
            record[DEV_FLAP_LONGEST],
        )

    def is_flapping(self, device_id: str) -> bool:
        """Return whether a device is in a flap."""
        record = self.data[DATA_DEVICES].get(device_id)
        return isinstance(record, dict) and _number(record.get(DEV_FLAP_SINCE)) is not None

    @property
    def flapping_list(self) -> list[dict[str, Any]]:
        """The devices in a flap, for the list, the pages and the brief.

        Muted devices are left out, as they are from every other
        problem.
        """
        rows = []
        for device_id, record in self.data[DATA_DEVICES].items():
            if not isinstance(record, dict):
                continue
            since = _number(record.get(DEV_FLAP_SINCE))
            if since is None:
                continue
            if device_id not in self._watched or device_id in self._muted_devices:
                continue
            if self._freeze_muted(device_id):
                continue
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "since": since,
                "drops": len(record.get(DEV_FLAP_DROPS) or []),
            })
        rows.sort(key=lambda row: row["since"])
        return rows

    def flap_words(self, device_id: str) -> str:
        """The words a flapping device is listed with.

        "flapping, dropped out 53 times since 7:00 AM": the count and
        the start of the run, because a flap's size is its point.
        """
        record = self.data[DATA_DEVICES].get(device_id) or {}
        drops = len(record.get(DEV_FLAP_DROPS) or [])
        since = _number(record.get(DEV_FLAP_SINCE))
        if since is None:
            return "flapping"
        when = self._format_report_time(
            dt_util.as_local(dt_util.utc_from_timestamp(since))
        )
        return f"flapping, dropped out {drops} times since {when}"
