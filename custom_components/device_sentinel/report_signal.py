# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: report_signal.py, Version: 0.23.5 (2026-09-25)

"""The signal cells of the telemetry, and the bad-day judgment.

The signal report page this module drew retired with the www folder
in 0.23.5 (#470): Home Assistant served it to anyone who asked. The
dashboard's Signal Trends tab carries what it showed, and reads the
judgment kept here.

This replaces the dwell chart (ruling #310). Dwell asked whether a
device was sitting near its own floor, and the floor descends to
meet a degraded device, so a link that broke on 18 August read 68,
then 96, then 30 percent while its P5 sat flat at its new lower
level. Give that arrangement a week and a permanently broken link
reads its way back to healthy. The page now asks the question a
person can act on: did this device just get worse than it has been.

Still a file split rather than a boundary (ruling #199). These
methods are mixed into the coordinator and read its state freely,
so `self` is the coordinator throughout and nothing here stands
alone.
"""

from __future__ import annotations

import math
from typing import Any


from .const import (
    DEV_SIGNAL_DAILY_P5,
    SIGNAL_DAYS_KEEP,
)


class SignalReportMixin:
    """The signal cells of the telemetry, and the bad-day judgment."""

    # ------------------------------------------------ reading the days

    def _badday_line(self, reading: dict[str, Any]) -> float:
        """Return the level a day must fall below to be a bad day.

        Its normal less the larger of the fixed drop and the sensitivity
        times its own spread. One formula, read by the report's chart
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
        it was a bad day. Recalculated from the daily history whenever
        asked, so a past day always reads with today's settings and
        nothing new is stored.
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

        device_telemetry.md printed the floor's weekly drift here, a
        figure from the floor-based line, which judges nothing: weak
        links are raised by the bad-day model (0.22.16). Both figures
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
        thirty days the report shows (rulings #126, #322). A day the
        bad-day model judged bad is ~~struck~~, the same days the
        device page marks red (0.22.16); the lowest day is bold at its
        earliest occurrence, the dashboard's "lowest day"; a rail-only
        day's null shows as a dash.
        """
        full = list(record.get(DEV_SIGNAL_DAILY_P5) or [])
        stored = full[-SIGNAL_DAYS_KEEP:]
        if not stored:
            return "-"
        offset = len(full) - len(stored)
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
                # A null from a rail-only day (ruling #305), or a
                # poisoned entry the hostile suite plants: the page
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

