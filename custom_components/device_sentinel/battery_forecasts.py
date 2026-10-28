# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: battery_forecasts.py, Version: 0.27.10 (2026-10-27)

"""Each battery forecast kept, and scored when the battery gets there.

A forecast can only be checked against the day a battery really runs
down, so each one is recorded at the fold and scored later (rule BAT-15).

At each midnight, each battery Device Sentinel judges falling or
accelerating, at or under three times the low threshold, and gives a
time left from its six-week range, gains one row on its record: the day, its level, whether it was accelerating, the
level the time left runs to (the threshold) and the range in days.
When the battery reaches that level, each of its open rows is scored:
inside the range, earlier than its near end, or later than its far
end. A row whose far end has passed with the battery still above is
later at once. A battery replaced before it got there leaves its rows
scored as replaced, which says nothing about the forecast. Every
scored row also counts once in a tally for the house that never
expires, so months of evidence outlive the History setting.

A cell judged low gets forecasts to empty, from its first low until a
new battery goes in. Few devices are seen reaching 0 percent, because
most stop reporting first. So a forecast to empty closes on the first
reading of 0, or, when the device went silent for at least
FORECAST_SILENT_DAYS before its battery was replaced, on the day it
was last heard, the day it gave out; otherwise as replaced. Forecasts
to empty are counted in a tally of their own (rules BAT-13, BAT-15).

Nothing here changes how a battery is judged. The tallies are there to
set the width of the range later.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .daily_dates import FAMILY_BATTERY_PREVIOUS, dates_for
from .report_battery import battery_calendar
from .const import (
    DATA_BATTERY_EMPTY_TALLY,
    DATA_BATTERY_FORECAST_TALLY,
    DATA_DEVICES,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_FIRST_LOW,
    DEV_BATTERY_FORECASTS,
    DEV_BATTERY_LOW,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_SINCE,
    FORECAST_EARLIER,
    FORECAST_INSIDE,
    FORECAST_KEEP_ROWS,
    FORECAST_LATER,
    FORECAST_OUTCOMES,
    FORECAST_REPLACED,
    FORECAST_SILENT_DAYS,
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


def _first_low_stands(record: dict[str, Any]) -> bool:
    """Whether the first-low time is after the last replacement."""
    first = _day(record.get(DEV_BATTERY_FIRST_LOW))
    replaced = _day(record.get(DEV_BATTERY_REPLACED_AT))
    return first is not None and (replaced is None or first >= replaced)


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
        history. Scoring comes first, so a battery that reached its
        target today closes the rows before it. A forecast to the
        threshold and one to empty are written the same way and counted
        in separate tallies (rule BAT-15)."""
        tallies = {False: self._forecast_tally(DATA_BATTERY_FORECAST_TALLY), True: self._forecast_tally(DATA_BATTERY_EMPTY_TALLY)}
        devices = self.data[DATA_DEVICES]  # type: ignore[attr-defined]
        for record in devices.values():
            if not isinstance(record, dict):
                continue
            # A cell already low before forecasts to empty existed has no
            # first-low time; written here so the latch outlives its
            # recovery (rule BAT-13).
            if record.get(DEV_BATTERY_LOW) and not _first_low_stands(record):
                record[DEV_BATTERY_FIRST_LOW] = record.get(DEV_BATTERY_SINCE) or dt_util.utcnow().isoformat()
            rows = record.get(DEV_BATTERY_FORECASTS)
            if not isinstance(rows, list) or not rows:
                continue
            self._score_open_rows(record, rows, day, tallies)
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
            if not isinstance(target, (int, float)) or target < 0:
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

    def _score_open_rows(
        self, record: dict[str, Any], rows: list[Any], day: date, tallies: dict[bool, dict[str, int]]
    ) -> None:
        current = self.battery_dated_levels(record)
        previous = self.battery_previous_dated_levels(record)
        # The new cell's first heard day, when it went in, unless its
        # history has been cut shorter than its life; never later than
        # the day the replacement was noticed.
        noticed = _day(record.get(DEV_BATTERY_REPLACED_AT))
        first = current[0][0] if current and previous else None
        replaced = min((when for when in (first, noticed) if when is not None), default=None)
        last_heard = previous[-1][0] if previous else None
        for row in rows:
            if row[ROW_OUTCOME] is not None:
                continue
            made = _day(row[ROW_DAY])
            if made is None:
                continue
            target = float(row[ROW_TARGET])
            # A forecast made before the last replacement is about the
            # old cell, read from its history; one made after, the new.
            cell = previous if replaced is not None and made < replaced else current
            arrived = next((when for when, level in cell if when > made and level <= target), None)
            if (
                arrived is None and target <= 0 and cell is previous
                and last_heard is not None and replaced is not None and last_heard >= made
                and (replaced - last_heard).days >= FORECAST_SILENT_DAYS
            ):
                # The device went silent before its battery was replaced,
                # so it gave out on the day it was last heard (rule BAT-15).
                arrived = last_heard
            outcome = score_row(row, arrived, day, replaced)
            if outcome is None:
                continue
            row[ROW_OUTCOME] = outcome
            row[ROW_ARRIVED] = arrived.isoformat() if arrived is not None and outcome != FORECAST_REPLACED else None
            tally = tallies[target <= 0]
            if outcome in tally:
                tally[outcome] += 1

    def _forecast_tally(self, key: str) -> dict[str, int]:
        """A running tally of the house's, made whole if it is missing a count."""
        tally = self.data.get(key)  # type: ignore[attr-defined]
        if not isinstance(tally, dict):
            tally = {}
            self.data[key] = tally  # type: ignore[attr-defined]
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

    def battery_previous_dated_levels(self, record: dict[str, Any]) -> list[tuple[date, float]]:
        """The replaced cell's heard days with their dates, oldest first."""
        series = list(record.get(DEV_BATTERY_DAILY_PREVIOUS) or [])
        if not series:
            return []
        current = self.battery_dated_levels(record)
        fallback = (current[0][0] if current else dt_util.as_local(dt_util.utcnow()).date()) - timedelta(days=1)
        dates = dates_for(record, FAMILY_BATTERY_PREVIOUS, len(series), fallback)
        return [
            (when, float(level))
            for when, level in zip(dates, series, strict=False)
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
