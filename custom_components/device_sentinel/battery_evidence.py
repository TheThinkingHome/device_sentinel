# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: battery_evidence.py, Version: 0.27.1 (2026-10-23)

"""What a better battery forecast will need, kept from now (#737, #739).

James, 23 October 2026: "anything we can do so that in the future, we
can build it more accurate." Two records, neither read by any judgment:

Each day, for each watched battery device heard that day, one row: the
battery voltage, the device's own temperature and its running count of
events (#737). A lithium cell's percentage holds near full until its end
while its voltage still moves; a busy device may drain faster than a
quiet sister; cold lowers a loaded cell's voltage. Each value is read
from the device's own entities only (#463) and is None where it has none.
The rows sit with the daily series: the newest thirty in the main file,
the rest in the history file, kept for the History setting's days.

Each time a battery is replaced, one row for the battery that ended
(#739): its model and battery type, the days it went in and came out,
its first kept and last level, the last day the device was heard, and
whether its start was seen. These are the finished lives a survival
model learns from, and the house keeps them for good. A replacement
cancelled takes its row with it; a day the person gives moves it.

A battery's start is never read from its kept history, which the
History setting trims to 90 days by default while a coin cell lasts
years. It is the replacement on record, detected, confirmed or given by
the person, and is then seen; with none, the day Device Sentinel first
saw the device, a start not seen: the battery was in by then, and its
life was at least that long (James, 23 October 2026).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_LIVES_KEEP,
    DATA_BATTERY_LIVES,
    DATA_DEVICES,
    DEV_BATTERY_EVIDENCE,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    EVIDENCE_TEMPERATURE_RANGE,
    EVIDENCE_VOLTAGE_RANGE,
)
from .device_fields import device_field
from .normalise import life_row_ok

# A day's evidence row: [day, volts, temperature in C, events so far].
EV_DAY, EV_VOLTS, EV_TEMPERATURE, EV_EVENTS = range(4)
# A finished life's row.
(
    LIFE_DEVICE, LIFE_MAKER, LIFE_MODEL, LIFE_TYPE, LIFE_QUANTITY, LIFE_START, LIFE_START_SEEN,
    LIFE_END, LIFE_FIRST_DAY, LIFE_FIRST_LEVEL, LIFE_LAST_LEVEL, LIFE_LAST_HEARD, LIFE_STAMP,
) = range(13)
LIFE_FIELDS = 13


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


class BatteryEvidenceMixin:
    """The daily evidence and the lives log."""

    # ------------------------------------------------------------ daily

    def battery_evidence_fold(self, day: date) -> None:
        """One row a day for each battery device heard that day."""
        start = dt_util.start_of_local_day(day).timestamp()
        stamp = day.isoformat()
        keep = max(1, int(getattr(self, "retention_days", 0) or 0))
        registry = er.async_get(self.hass)  # type: ignore[attr-defined]
        for device_id, record in self.watched_records():  # type: ignore[attr-defined]
            if device_id not in self._battery_entity:  # type: ignore[attr-defined]
                continue
            heard = record.get(DEV_LAST_ACTIVITY)
            if not isinstance(heard, (int, float)) or isinstance(heard, bool) or heard < start:
                continue
            rows = record.setdefault(DEV_BATTERY_EVIDENCE, [])
            if rows and isinstance(rows[-1], list) and rows[-1] and rows[-1][EV_DAY] == stamp:
                continue
            events = record.get(DEV_EVENT_COUNT)
            rows.append([
                stamp,
                self._evidence_voltage(device_id, registry),
                self._evidence_temperature(device_id, registry),
                int(events) if isinstance(events, int) and not isinstance(events, bool) and events >= 0 else None,
            ])
            del rows[:-keep]

    def _own_readings(self, device_id: str, registry: Any, device_class: str) -> list[tuple[str, Any]]:
        """The device's own sensors of one device class with their states,
        a battery one first."""
        found = []
        for entity_id in self._own_entities.get(device_id, ()):  # type: ignore[attr-defined]
            entry = registry.async_get(entity_id)
            if entry is None or entry.domain != "sensor" or entry.disabled_by is not None:
                continue
            if (entry.device_class or entry.original_device_class) != device_class:
                continue
            state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
            if state is None:
                continue
            found.append((entity_id, state))
        found.sort(key=lambda pair: ("batt" not in pair[0], pair[0]))
        return found

    def _evidence_voltage(self, device_id: str, registry: Any) -> float | None:
        """The battery voltage in volts: a voltage sensor of the device's
        own, in V or mV, or ZHA's battery_voltage on the battery sensor."""
        low, high = EVIDENCE_VOLTAGE_RANGE
        for _entity_id, state in self._own_readings(device_id, registry, "voltage"):
            value = _number(state.state)
            unit = state.attributes.get("unit_of_measurement")
            if value is None or unit not in ("V", "mV"):
                continue
            volts = value / 1000 if unit == "mV" else value
            if low <= volts <= high:
                return round(volts, 3)
        battery = self._battery_entity.get(device_id)  # type: ignore[attr-defined]
        state = self.hass.states.get(battery[0]) if battery else None  # type: ignore[attr-defined]
        reported = _number(state.attributes.get("battery_voltage")) if state is not None else None
        return round(reported, 3) if reported is not None and low <= reported <= high else None

    def _evidence_temperature(self, device_id: str, registry: Any) -> float | None:
        """The device's own temperature in degrees Celsius, or None."""
        low, high = EVIDENCE_TEMPERATURE_RANGE
        for _entity_id, state in self._own_readings(device_id, registry, "temperature"):
            value = _number(state.state)
            unit = state.attributes.get("unit_of_measurement")
            if value is None or unit not in ("°C", "°F"):
                continue
            celsius = (value - 32) * 5 / 9 if unit == "°F" else value
            if low <= celsius <= high:
                return round(celsius, 1)
        return None

    def battery_evidence_view(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """The newest day's evidence for the device page, with the day
        before's events taken away to give that day's messages."""
        rows = [row for row in record.get(DEV_BATTERY_EVIDENCE) or [] if isinstance(row, list) and len(row) == 4]
        if not rows:
            return None
        last = rows[-1]
        messages = None
        if len(rows) > 1 and isinstance(last[EV_EVENTS], int) and isinstance(rows[-2][EV_EVENTS], int):
            gap = (date.fromisoformat(last[EV_DAY]) - date.fromisoformat(rows[-2][EV_DAY])).days
            if gap == 1 and last[EV_EVENTS] >= rows[-2][EV_EVENTS]:
                messages = last[EV_EVENTS] - rows[-2][EV_EVENTS]
        return {
            "day": last[EV_DAY], "volts": last[EV_VOLTS], "temperature": last[EV_TEMPERATURE],
            "messages": messages, "days": len(rows),
        }

    # ------------------------------------------------------------ lives

    def _lives(self) -> list[list[Any]]:
        lives = self.data.get(DATA_BATTERY_LIVES)  # type: ignore[attr-defined]
        if not isinstance(lives, list):
            lives = []
            self.data[DATA_BATTERY_LIVES] = lives  # type: ignore[attr-defined]
        return lives

    def battery_start(self, device_id: str, record: dict[str, Any]) -> tuple[date, bool] | None:
        """The day the battery in the device now went in, and whether that
        was seen: the replacement on record, or else the day the device
        was first seen, a start not seen. Read before a replacement
        changes it, for the battery that ends."""
        entry = self._battery_entry(device_id, record)  # type: ignore[attr-defined]
        if entry is not None:
            try:
                return date.fromisoformat(str(entry["day"])[:10]), True
            except ValueError:
                pass
        first = first_seen_day(record)
        return (first, False) if first is not None else None

    def battery_life_ended(
        self, device_id: str, record: dict[str, Any], end_day: date | None, start: tuple[date, bool] | None,
    ) -> None:
        """Write the row for the battery a replacement just ended (#739)."""
        try:
            row = self._life_row(device_id, record, end_day, start)
        except Exception:  # noqa: BLE001 - a record never stops a replacement
            return
        if row is None or not life_row_ok(row):
            # A row the load check would refuse drops the whole log there.
            return
        lives = self._lives()
        lives.append(row)
        del lives[:-BATTERY_LIVES_KEEP]

    def battery_life_withdrawn(self, device_id: str, stamp: Any) -> None:
        """A replacement taken back takes its row with it."""
        lives = self._lives()
        for index in range(len(lives) - 1, -1, -1):
            row = lives[index]
            if isinstance(row, list) and len(row) == LIFE_FIELDS and row[LIFE_DEVICE] == device_id and row[LIFE_STAMP] == stamp:
                del lives[index]
                return

    def battery_life_redated(
        self, device_id: str, record: dict[str, Any], end_day: date,
        start: tuple[date, bool] | None, correcting: bool,
    ) -> None:
        """A day the person gave: the history is split again there, and the
        battery before that day is written again. When the day corrects a
        replacement already on record (a detection still waiting, or a
        rise that was the replacement the person had dated), the device's
        newest row is that battery's and is rewritten, keeping its start;
        otherwise the person named a replacement nothing detected, and a
        row is added from the start read before it."""
        lives = self._lives()
        newest = None
        for index in range(len(lives) - 1, -1, -1):
            old = lives[index]
            if isinstance(old, list) and len(old) == LIFE_FIELDS and old[LIFE_DEVICE] == device_id:
                newest = index
                break
        if correcting and newest is not None:
            kept = lives[newest]
            start = (date.fromisoformat(kept[LIFE_START]), bool(kept[LIFE_START_SEEN]))
        try:
            row = self._life_row(device_id, record, end_day, start)
        except Exception:  # noqa: BLE001 - a record never stops a replacement
            return
        if row is None or not life_row_ok(row):
            return
        if correcting and newest is not None:
            lives[newest] = row
            return
        lives.append(row)
        del lives[:-BATTERY_LIVES_KEEP]

    def _life_row(
        self, device_id: str, record: dict[str, Any], end_day: date | None, start: tuple[date, bool] | None,
    ) -> list[Any] | None:
        old = self.battery_previous_dated_levels(record)  # type: ignore[attr-defined]
        if not old:
            return None
        current = self.battery_dated_levels(record)  # type: ignore[attr-defined]
        end = end_day or (current[0][0] if current else old[-1][0] + timedelta(days=1))
        device = dr.async_get(self.hass).async_get(device_id)  # type: ignore[attr-defined]
        power = self.power_of(device_id) or {}  # type: ignore[attr-defined]
        quantity = power.get("quantity")
        # The start on record, never the history's first kept day, which
        # retention trims; a kept day older than the start says the
        # battery was in earlier than the record knew, a start not seen.
        began, seen = start if start is not None else (old[0][0], False)
        if old[0][0] < began:
            began, seen = old[0][0], False
        stamp = record.get("battery_replaced_at")
        return [
            device_id,
            device_field(device, "manufacturer") or None,
            device_field(device, "model") or None,
            power.get("type") if power.get("kind") == "battery" else None,
            quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None,
            began.isoformat(),
            seen,
            end.isoformat(),
            old[0][0].isoformat(),
            round(old[0][1], 1),
            round(old[-1][1], 1),
            old[-1][0].isoformat(),
            stamp if isinstance(stamp, str) else None,
        ]

    def battery_lives_view(self) -> list[dict[str, Any]]:
        """The lives log for the diagnostics download, newest first."""
        devices = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        out = []
        for row in reversed(self._lives()):
            if not (isinstance(row, list) and len(row) == LIFE_FIELDS):
                continue
            end = date.fromisoformat(row[LIFE_END])
            heard = date.fromisoformat(row[LIFE_LAST_HEARD])
            out.append({
                "device_id": row[LIFE_DEVICE], "still_here": row[LIFE_DEVICE] in devices,
                "maker": row[LIFE_MAKER], "model": row[LIFE_MODEL],
                "battery_type": row[LIFE_TYPE], "quantity": row[LIFE_QUANTITY],
                "start": row[LIFE_START], "start_seen": row[LIFE_START_SEEN], "end": row[LIFE_END],
                "days": (end - date.fromisoformat(row[LIFE_START])).days,
                "first_kept_day": row[LIFE_FIRST_DAY],
                "first_level": row[LIFE_FIRST_LEVEL], "last_level": row[LIFE_LAST_LEVEL],
                "last_heard": row[LIFE_LAST_HEARD], "silent_days": (end - heard).days,
            })
        return out


def first_seen_day(record: dict[str, Any]) -> date | None:
    """The local day Device Sentinel first saw the device, or None."""
    moment = dt_util.parse_datetime(str(record.get(DEV_FIRST_OBSERVED) or ""))
    return dt_util.as_local(moment).date() if moment is not None else None
