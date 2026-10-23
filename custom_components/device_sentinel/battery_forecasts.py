# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: battery_forecasts.py, Version: 0.27.0 (2026-10-22)

"""Each battery forecast kept, and scored when the battery gets there (#732).

No battery on either house had been watched from new to replaced when
0.27.0 was built, so no forecast method could be checked against a
real date: a backtest of 1,350 forecasts on 28 batteries could only
use drops of a few points. James, 22 October 2026: record the
predictions at the fold, so that a range said in October can be put
beside the day the battery really got there.

At each midnight, each battery Device Sentinel judges falling or
accelerating, at or under three times the low threshold, gains one row
on its record: the day, its level, whether it was accelerating, the
level the time left runs to (the threshold) and the range in days.
When the battery reaches that level, each of its open rows is scored:
inside the range, earlier than its near end, or later than its far
end. A row whose far end has passed with the battery still above is
later at once. A battery replaced before it got there leaves its rows
scored as replaced, which says nothing about the forecast. Every
scored row also counts once in a tally for the house that never
expires, so months of evidence outlive the History setting.

Nothing here changes how a battery is judged. The tally is what a
later ruling can use to set the width of the range.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .report_battery import battery_calendar
from .const import (
    DATA_BATTERY_FORECAST_TALLY,
    DATA_DEVICES,
    DEV_BATTERY_FORECASTS,
    DEV_BATTERY_REPLACED_AT,
    FORECAST_EARLIER,
    FORECAST_INSIDE,
    FORECAST_KEEP_ROWS,
    FORECAST_LATER,
    FORECAST_OUTCOMES,
    FORECAST_REPLACED,
    READING_ACCELERATING,
)

# The fields of a row, in order. A list rather than a mapping, as the
# firmware history is, so a record carries no field names per row.
ROW_DAY, ROW_LEVEL, ROW_ACCELERATING, ROW_TARGET, ROW_NEAR, ROW_FAR, ROW_OUTCOME, ROW_ARRIVED = range(8)


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def score_row(row: list[Any], arrived: date | None, today: date, replaced: date | None) -> str | None:
    """The outcome of one open forecast, or None while it is still open.

    arrived is the first day after the forecast the battery read at or
    under its target; replaced, the day a new battery went in."""
    made = _day(row[ROW_DAY])
    if made is None:
        return None
    near = float(row[ROW_NEAR])
    far = row[ROW_FAR]
    if arrived is not None and arrived > made:
        took = (arrived - made).days
        if took < near:
            return FORECAST_EARLIER
        if far is not None and took > float(far):
            return FORECAST_LATER
        return FORECAST_INSIDE
    if replaced is not None and replaced > made:
        return FORECAST_REPLACED
    if far is not None and (today - made).days > float(far):
        return FORECAST_LATER
    return None


class BatteryForecastMixin:
    """The forecast log: written and scored at the midnight fold."""

    def battery_forecasts_fold(self, day: date) -> None:
        """Score the open rows, then write today's forecasts.

        day is the day the fold closed, the newest day of each battery
        history. Scoring first, so a battery that reached its threshold
        today closes the rows before it, and a battery now under the
        threshold writes no new row (its time left runs to empty, which
        nobody can see arrive)."""
        tally = self._forecast_tally()
        devices = self.data[DATA_DEVICES]  # type: ignore[attr-defined]
        for record in devices.values():
            rows = record.get(DEV_BATTERY_FORECASTS)
            if not isinstance(rows, list) or not rows:
                continue
            self._score_open_rows(record, rows, day, tally)
        try:
            judged = self._battery_rows()["falling"]  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a log never stops the fold
            return
        stamp = day.isoformat()
        for row in judged:
            record = devices.get(row.get("device_id"))
            target = row.get("target")
            projection = row.get("projection")
            if not isinstance(record, dict) or not projection:
                continue
            if not isinstance(target, (int, float)) or target <= 0:
                continue
            rows = record.setdefault(DEV_BATTERY_FORECASTS, [])
            if rows and rows[-1][ROW_DAY] == stamp:
                continue
            rows.append([
                stamp,
                round(float(row["level"]), 1),
                row.get("reading") == READING_ACCELERATING,
                round(float(target), 1),
                projection["near"],
                projection["far"],
                None,
                None,
            ])
            del rows[:-FORECAST_KEEP_ROWS]

    def _score_open_rows(self, record: dict[str, Any], rows: list[Any], day: date, tally: dict[str, int]) -> None:
        series = self.battery_dated_levels(record)  # type: ignore[attr-defined]
        replaced = _day(record.get(DEV_BATTERY_REPLACED_AT))
        for row in rows:
            if row[ROW_OUTCOME] is not None:
                continue
            made = _day(row[ROW_DAY])
            arrived = next(
                (when for when, level in series if made is not None and when > made and level <= float(row[ROW_TARGET])),
                None,
            )
            outcome = score_row(row, arrived, day, replaced)
            if outcome is None:
                continue
            row[ROW_OUTCOME] = outcome
            row[ROW_ARRIVED] = arrived.isoformat() if arrived is not None and outcome != FORECAST_REPLACED else None
            if outcome in tally:
                tally[outcome] += 1

    def _forecast_tally(self) -> dict[str, int]:
        """The house's running tally, made whole if it is missing a count."""
        tally = self.data.get(DATA_BATTERY_FORECAST_TALLY)  # type: ignore[attr-defined]
        if not isinstance(tally, dict):
            tally = {}
            self.data[DATA_BATTERY_FORECAST_TALLY] = tally  # type: ignore[attr-defined]
        for outcome in FORECAST_OUTCOMES:
            if not isinstance(tally.get(outcome), int) or isinstance(tally.get(outcome), bool):
                tally[outcome] = 0
        return tally

    def battery_dated_levels(self, record: dict[str, Any]) -> list[tuple[date, float]]:
        """Each heard day of the battery history with its date, oldest
        first, ending yesterday."""
        series = battery_calendar(record)
        end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
        start = end - timedelta(days=len(series) - 1)
        return [
            (start + timedelta(days=index), float(level))
            for index, level in enumerate(series)
            if isinstance(level, (int, float)) and not isinstance(level, bool)
        ]

    def battery_forecast_view(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """A device page's Earlier Forecasts, newest first."""
        rows = record.get(DEV_BATTERY_FORECASTS)
        if not isinstance(rows, list):
            return []
        return [
            {
                "day": row[ROW_DAY],
                "level": row[ROW_LEVEL],
                "accelerating": bool(row[ROW_ACCELERATING]),
                "target": row[ROW_TARGET],
                "left": self.battery_time_left_range(row[ROW_NEAR], row[ROW_FAR]),  # type: ignore[attr-defined]
                "outcome": row[ROW_OUTCOME],
                "arrived": row[ROW_ARRIVED],
            }
            for row in reversed(rows)
        ]
