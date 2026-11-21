# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: battery_curves.py, Version: 0.30.1 (2026-11-21)

"""Keep the curve: each battery's whole shape, kept for good (rule BAT-20).

A better battery forecast needs batteries watched from new to the end.
The daily levels are kept only as long as How Much History to Keep, so
the start of a long battery is gone before its end arrives. Each week a
battery is in its device keeps one row here instead, never trimmed:

    [week start, battery start, median level, lowest, highest,
     lowest volts, highest volts, messages that week, mean temperature]

The rows of the weeks still held day by day are worked out again from
those days at each midnight; a week older than the days kept stays as it
was written. When a battery ends, its rows, the daily detail of its last
weeks and how it ended make its curve. A device keeps its newest good,
full curve: one whose start was seen and that has readings in at least
four of every five of its weeks. Nothing reads the curves yet; they are
the data a later forecast is built from, and the diagnostics download
carries them with one combined curve per make and model.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

from .const import (
    LOGGER,
    BATTERY_CURVES_KEEP,
    BATTERY_REPORT_CEILING_FACTOR,
    BATTERY_WEEKS_KEEP,
    CURVE_RAN_OUT_DAYS,
    CURVE_TAIL_DAYS,
    CURVE_WEEKS_SHARE,
    DATA_BATTERY_CURVES,
    DATA_BATTERY_WEEKS,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAY_RANGES,
    DEV_BATTERY_EVIDENCE,
)
from .normalise import curve_ok, week_row_ok

# A week's row.
(
    WK_START, WK_BATTERY, WK_MEDIAN, WK_LOW, WK_HIGH, WK_VOLTS_LOW, WK_VOLTS_HIGH, WK_MESSAGES, WK_TEMPERATURE,
) = range(9)
WEEK_FIELDS = 9
# How a battery ended.
ENDED_RAN_OUT = "ran_out"
ENDED_REPLACED = "replaced"


def week_of(day: date) -> date:
    """The Monday that starts a day's week."""
    return day - timedelta(days=day.weekday())


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ranges(record: dict[str, Any]) -> dict[date, list[Any]]:
    """The day ranges by day: [low, high, volts low, volts high]."""
    out: dict[date, list[Any]] = {}
    for row in record.get(DEV_BATTERY_DAY_RANGES) or []:
        if isinstance(row, list) and len(row) == 5:
            day = _day(row[0])
            if day is not None:
                out[day] = row[1:]
    return out


def _evidence(record: dict[str, Any]) -> dict[date, list[Any]]:
    """The evidence rows by day: [volts, temperature, events so far]."""
    out: dict[date, list[Any]] = {}
    for row in record.get(DEV_BATTERY_EVIDENCE) or []:
        if isinstance(row, list) and len(row) == 4:
            day = _day(row[0])
            if day is not None:
                out[day] = row[1:]
    return out


def weekly_rows(
    levels: list[tuple[date, float]],
    ranges: dict[date, list[Any]],
    evidence: dict[date, list[Any]],
    battery_start: date,
) -> list[list[Any]]:
    """One row for each week the levels reach, oldest first."""
    weeks: dict[date, list[tuple[date, float]]] = {}
    for day, level in levels:
        if day >= battery_start:
            weeks.setdefault(week_of(day), []).append((day, level))
    rows: list[list[Any]] = []
    for start in sorted(weeks):
        days = weeks[start]
        values = [level for _day_, level in days]
        lows, highs, volts_low, volts_high, temperatures, events = [], [], [], [], [], []
        for day, level in days:
            held = ranges.get(day)
            low = _number(held[0]) if held else None
            high = _number(held[1]) if held else None
            lows.append(low if low is not None else level)
            highs.append(high if high is not None else level)
            if held:
                if _number(held[2]) is not None:
                    volts_low.append(float(held[2]))
                if _number(held[3]) is not None:
                    volts_high.append(float(held[3]))
            seen = evidence.get(day)
            if seen:
                if _number(seen[1]) is not None:
                    temperatures.append(float(seen[1]))
                if _number(seen[2]) is not None:
                    events.append(int(seen[2]))
        # Messages that week, from the running count: only where it never
        # fell, since a count that starts again says nothing of the week.
        messages = None
        if len(events) >= 2 and events == sorted(events):
            messages = events[-1] - events[0]
        rows.append([
            start.isoformat(),
            battery_start.isoformat(),
            round(median(values), 1),
            # A day's range and its level are read at different moments, so
            # the week's lowest and highest take in the levels too.
            round(min(lows + values), 1),
            round(max(highs + values), 1),
            round(min(volts_low), 3) if volts_low else None,
            round(max(volts_high), 3) if volts_high else None,
            messages,
            round(sum(temperatures) / len(temperatures), 1) if temperatures else None,
        ])
    return rows


class BatteryCurvesMixin:
    """The weekly rows and the finished curves (rule BAT-20)."""

    def _weeks_table(self) -> dict[str, list[list[Any]]]:
        table = self.data.get(DATA_BATTERY_WEEKS)  # type: ignore[attr-defined]
        if not isinstance(table, dict):
            table = {}
            self.data[DATA_BATTERY_WEEKS] = table  # type: ignore[attr-defined]
        return table

    def _curves_table(self) -> dict[str, dict[str, Any]]:
        table = self.data.get(DATA_BATTERY_CURVES)  # type: ignore[attr-defined]
        if not isinstance(table, dict):
            table = {}
            self.data[DATA_BATTERY_CURVES] = table  # type: ignore[attr-defined]
        return table

    def battery_weeks_fold(self) -> None:
        """At midnight, each battery's weeks worked out again from the days
        still kept; a week older than those days stays as written. Also
        how a house that upgrades gets the weeks of the days it holds."""
        devices = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        table = self._weeks_table()
        for device_id in [d for d in table if d not in devices]:
            # A device gone from the house takes its weeks with it; its
            # finished curves stay.
            del table[device_id]
        for device_id, record in devices.items():
            if not isinstance(record, dict) or not record.get(DEV_BATTERY_DAILY):
                continue
            try:
                self._fold_weeks(device_id, record, table)
            except Exception as err:  # noqa: BLE001 - one device never stops the fold
                LOGGER.debug("device_sentinel: battery weeks not folded for %s: %s", device_id, err)

    def _fold_weeks(self, device_id: str, record: dict[str, Any], table: dict[str, list[list[Any]]]) -> None:
        levels = self.battery_dated_levels(record)  # type: ignore[attr-defined]
        if not levels:
            return
        start = self.battery_start(device_id, record)  # type: ignore[attr-defined]
        began = start[0] if start is not None else levels[0][0]
        began = min(began, levels[0][0])
        fresh = weekly_rows(levels, _ranges(record), _evidence(record), began)
        if not fresh:
            return
        first = fresh[0][WK_START]
        battery = fresh[0][WK_BATTERY]
        began_week = week_of(began).isoformat()
        # Kept: this battery's weeks older than the days still held, and an
        # earlier battery's weeks up to the week this one went in. A row
        # from a battery that went in later, or an earlier one's week after
        # this one went in, is a replacement taken back or moved to
        # another day.
        kept = [
            row for row in table.get(device_id, [])
            if week_row_ok(row) and (
                (row[WK_BATTERY] == battery and row[WK_START] < first)
                or (row[WK_BATTERY] < battery and row[WK_START] <= began_week)
            )
        ]
        rows = sorted(kept + fresh, key=lambda row: (row[WK_START], row[WK_BATTERY]))
        table[device_id] = rows[-BATTERY_WEEKS_KEEP:]

    def battery_curve_ended(self, device_id: str, record: dict[str, Any], life: list[Any]) -> None:
        """Make the curve of the battery a life row just ended, and keep it
        when it is good and full (rule BAT-20)."""
        try:
            curve = self._curve_of(device_id, record, life)
        except Exception:  # noqa: BLE001 - a curve never stops a replacement
            return
        if curve is None or not curve.get("good") or not curve_ok(curve):
            return
        curves = self._curves_table()
        kept = curves.get(device_id)
        # A full curve, from a fresh battery, is not given up for a shorter
        # one; a curve made again for the same replacement always replaces.
        if (
            isinstance(kept, dict) and kept.get("full") and not curve.get("full")
            and kept.get("stamp") != curve.get("stamp")
        ):
            return
        curves.pop(device_id, None)
        curves[device_id] = curve
        while len(curves) > BATTERY_CURVES_KEEP:
            del curves[next(iter(curves))]

    def battery_curve_withdrawn(self, device_id: str, stamp: Any) -> None:
        """A replacement taken back takes the curve it made with it."""
        curves = self._curves_table()
        curve = curves.get(device_id)
        if isinstance(curve, dict) and curve.get("stamp") == stamp:
            del curves[device_id]

    def _curve_of(self, device_id: str, record: dict[str, Any], life: list[Any]) -> dict[str, Any] | None:
        (_device, maker, model, battery_type, quantity, start, start_seen, end,
         _first_day, _first_level, _last_level, last_heard, stamp) = life
        began, ended, heard = _day(start), _day(end), _day(last_heard)
        if began is None or ended is None or heard is None:
            return None
        levels = [(d, v) for d, v in self.battery_previous_dated_levels(record) if began <= d <= ended]  # type: ignore[attr-defined]
        ranges = _ranges(record)
        fresh = weekly_rows(levels, ranges, _evidence(record), began)
        first = fresh[0][WK_START] if fresh else None
        # The weeks older than the days kept, from the battery's own start.
        # Picked by date, since the start the weekly fold knew can differ
        # from the one the life row settled on.
        older = [
            row for row in self._weeks_table().get(device_id, [])
            if week_row_ok(row) and row[WK_START] >= week_of(began).isoformat()
            and (first is None or row[WK_START] < first)
        ]
        weeks = older + fresh
        if not weeks:
            return None
        threshold = float(self.threshold_for(device_id))  # type: ignore[attr-defined]
        under = next((d for d, v in levels if v <= threshold), None)
        empty = next((d for d, v in levels if v <= 0), None)

        def volts(day: date | None) -> float | None:
            held = ranges.get(day) if day is not None else None
            return _number(held[3]) if held else None

        span = (week_of(ended) - week_of(began)).days // 7 + 1
        # Good: the kept readings reach back to three times the threshold,
        # where a time left begins (rule BAT-10), and run from the last week
        # at or over it to the end with readings in four weeks of five.
        # Full: the battery was seen going in, and the whole life is covered.
        ceiling = BATTERY_REPORT_CEILING_FACTOR * threshold
        over = [row for row in weeks if (_number(row[WK_HIGH]) or _number(row[WK_MEDIAN]) or 0.0) >= ceiling]
        from_week = _day(over[-1][WK_START]) if over else None
        if from_week is not None:
            stretch = (week_of(ended) - from_week).days // 7 + 1
            weeks_heard = sum(1 for row in weeks if row[WK_START] >= from_week.isoformat())
            good = weeks_heard >= CURVE_WEEKS_SHARE * stretch
        else:
            good = False
        full = bool(start_seen) and good and len(weeks) >= CURVE_WEEKS_SHARE * span
        tail = [
            [d.isoformat(), round(v, 1), *(ranges.get(d) or [None, None, None, None])]
            for d, v in levels[-CURVE_TAIL_DAYS:]
        ]
        return {
            "device_id": device_id,
            "maker": maker,
            "model": model,
            "battery_type": battery_type,
            "quantity": quantity,
            "start": start,
            "start_seen": start_seen,
            "end": end,
            "last_heard": last_heard,
            "stamp": stamp,
            # Ran out: the device went quiet before the replacement.
            # Replaced: it still reported, so the battery was stopped early.
            "ended": ENDED_RAN_OUT if (ended - heard).days >= CURVE_RAN_OUT_DAYS else ENDED_REPLACED,
            "threshold": threshold,
            "first_under": under.isoformat() if under else None,
            "volts_under": volts(under),
            "first_empty": empty.isoformat() if empty else None,
            "volts_last": volts(heard),
            "weeks": weeks,
            "tail": tail,
            "from_week": from_week.isoformat() if from_week else None,
            "good": good,
            "full": full,
        }

    def battery_curves_view(self) -> dict[str, Any]:
        """The weeks and curves for the diagnostics download, by device id,
        maker and model, never a name, with one combined curve for each
        make and model (rule BAT-20)."""
        curves = [dict(c) for c in self._curves_table().values() if isinstance(c, dict)]
        models: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for curve in curves:
            models.setdefault((curve.get("maker"), curve.get("model")), []).append(curve)
        combined = []
        for (maker, model), group in sorted(models.items(), key=lambda item: str(item[0])):
            by_week: dict[int, list[float]] = {}
            lasted, from_line, to_line = [], [], []
            for curve in group:
                began, ended = _day(curve["start"]), _day(curve["end"])
                if ended is None:
                    continue
                for row in curve["weeks"]:
                    # Weeks before the battery ended: a curve whose start was
                    # not seen still lines up with every other at its end.
                    index = (week_of(ended) - date.fromisoformat(row[WK_START])).days // 7
                    by_week.setdefault(index, []).append(row[WK_MEDIAN])
                if curve.get("full") and began is not None:
                    lasted.append((ended - began).days / 7)
                frm, under = _day(curve.get("from_week")), _day(curve.get("first_under"))
                if frm is not None and under is not None and under >= frm:
                    to_line.append((under - frm).days / 7)
                if frm is not None:
                    from_line.append((ended - frm).days / 7)
            combined.append({
                "maker": maker,
                "model": model,
                "curves": len(group),
                "full": sum(1 for curve in group if curve.get("full")),
                # From full curves only: a start not seen says nothing of a life.
                "weeks_lasted": round(median(lasted), 1) if lasted else None,
                # From the week at three times the threshold.
                "weeks_to_threshold": round(median(to_line), 1) if to_line else None,
                "weeks_to_end": round(median(from_line), 1) if from_line else None,
                # The middle level of each week before the end, and how many
                # curves reach that week.
                "levels_before_end": [[k, round(median(v), 1), len(v)] for k, v in sorted(by_week.items())],
            })
        return {
            "weeks": {d: rows for d, rows in self._weeks_table().items()},
            "curves": curves,
            "models": combined,
        }
