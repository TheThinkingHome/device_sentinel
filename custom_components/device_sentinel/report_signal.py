# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_signal.py, Version: 0.27.10 (2026-10-27)

"""The signal cells of the telemetry, and the bad-day judgment.

The dashboard's Signal Trends tab shows the signal history and reads
the judgment kept here (rule SIG-12).

The judgment replaces the dwell line. Dwell asked whether a device sat
near its own floor, and the floor descends to meet a degraded device,
so a broken link reads its way back to healthy within a week. The
judgment asks the question a person can act on instead: did this
device just get worse than it has been (rules SIG-08, SIG-13).

Still a file split rather than a boundary (rule CODE-11). These
methods are mixed into the coordinator and read its state freely,
so `self` is the coordinator throughout and nothing here stands
alone.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DEV_SIGNAL_DAILY_P5,
    SIGNAL_DAYS_KEEP,
)
from .daily_dates import FAMILY_SIGNAL, dates_for


class SignalReportMixin:
    """The signal cells of the telemetry, and the bad-day judgment."""

    # ------------------------------------------------ reading the days

    def _badday_line(self, reading: dict[str, Any]) -> float:
        """Return the level a day must fall below to be a bad day.

        Its normal less the larger of the fixed drop and the sensitivity
        times its own spread. One formula, read by the telemetry report
        and by the dashboard, so the two cannot draw different lines.
        """
        return reading["baseline"] - max(
            reading["drop_gate"],
            self._badday_sensitivity() * reading["spread"],
        )

    def signal_day_judgment(
        self, record: dict[str, Any], index: int
    ) -> dict[str, Any] | None:
        """Return one day's judgment: its normal, its line, and whether
        it was a bad day. Worked out from the daily history, once per
        window of days and settings, so a past day always
        reads with today's settings and nothing new is stored.
        """
        reading = self.signal_badday(record, index)
        if reading is None:
            return None
        return {
            "normal": reading["baseline"],
            "line": self._badday_line(reading),
            "bad": bool(reading["bad"]),
        }

    # ---------------------------------------------------- the drawings

    # ------------------------------------------------------ the page

    def _signal_today_cells(self, record: dict[str, Any]) -> tuple[str, str]:
        """Return today's normal and bad-day line, as the dashboard shows them.

        Weak links are raised by the bad-day model, not by the floor's
        weekly drift (rule SIG-08). Both figures
        come from the same judgment the device page reads, for the
        newest day, so the file and the page cannot disagree.
        """
        series = record.get(DEV_SIGNAL_DAILY_P5) or []
        today = self.signal_day_judgment(record, len(series) - 1) if series else None
        if today is None:
            return "-", "-"
        return f"{today['normal']:.1f}", f"{today['line']:.1f}"

    def _format_signal_lows_cell(self, record: dict[str, Any]) -> str:
        """Render the daily P5 series newest-first, bad days struck.

        Each value is the day's time-weighted 5th percentile, over the
        thirty days the report shows (rule SIG-05). A day the
        bad-day model judged bad is ~~struck~~, the same days the
        device page marks red; the lowest day is bold at its
        earliest occurrence, the dashboard's "lowest day"; a rail-only
        day's null shows as a dash.
        """
        full = list(record.get(DEV_SIGNAL_DAILY_P5) or [])
        # The last thirty calendar days, as the device page reads them
        # (rule SIG-06): thirty rows reached back about sixty days on a
        # device with silent days.
        end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
        dates = dates_for(record, FAMILY_SIGNAL, len(full), end)
        first = end - timedelta(days=SIGNAL_DAYS_KEEP - 1)
        offset = next(
            (i for i, when in enumerate(dates) if when >= first), len(full)
        )
        stored = full[offset:]
        if not stored:
            return "-"
        real = [
            value
            for value in stored
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ]
        lowest = min(real) if real else None
        lowest_index = None
        if lowest is not None:
            for index, value in enumerate(stored):
                if value == lowest:
                    lowest_index = index
                    break
        parts = []
        for index in reversed(range(len(stored))):
            value = stored[index]
            if value not in real:
                # A null from a rail-only day (rule SIG-05), or a
                # damaged entry: the page
                # is written whatever a series holds.
                parts.append("-")
                continue
            cell = f"{value:g}"
            if index == lowest_index:
                cell = f"**{cell}**"
            judgment = self.signal_day_judgment(record, offset + index)
            if judgment is not None and judgment["bad"]:
                cell = f"~~{cell}~~"
            parts.append(cell)
        return " ".join(parts)

