# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/battery_replacement.py, Version: 0.26.7 (2026-10-19)

"""Battery Last Replaced, and a person's answer to a detected one (0.26.7).

Device Sentinel has detected a new cell since 0.20.20 (#397, #405): a
rise held over two readings starts the battery history again, so the
trend, the days left and the charts describe the cell in the device.
A wrong date makes all three wrong, and nothing let a person say so.

What James ruled (#701, #702, 18 and 19 October 2026):

- A battery device's page shows "Battery Last Replaced", or "No
  battery replacement yet", with a pencil. A device on mains has no
  row.
- Unanswered, a detected replacement is used at once, as before, and a
  Confirm Battery Replacement card and a Brief line wait for a person.
- Confirm saves the detected day in the answers file. A day the person
  enters or corrects is saved there instead, and the detected day is
  no longer shown; the history splits at the person's day. Cancel joins
  the history back to the replacement before. Cancel leaves the
  Log-Normal day count as it stands (#709, amending #702): it regrows
  over 42 days, as after any detection since 0.24.0.
- A day in the future is refused; a day older than the oldest kept day
  makes the whole kept history the new cell's.
- A replacement detected before 0.26.7 counts as confirmed.
- A device whose power answer is Rechargeable reads "charged".

The day shown for a detection is the day the new level first appeared,
the new cell's first dated entry, not the midnight that confirmed it
(#405). Every daily entry carries its date since 0.24.4.

One entry per device in the answers file holds what the row says (the
design James approved on 19 October 2026, after four review rounds on
a day worked out again at every reading): the day, how it came
(detected, confirmed or entered), the stamp of the detection it
belongs to, whether it waits for a person, and the replacements before
it, the newest last, which Cancel goes back through.
The latest event writes it and the row shows it as stored. A stamp no
entry carries, a replacement detected before 0.26.7 or by 0.26.6 after
a downgrade, is dated once from the new cell's first kept day, stored
as confirmed, and never worked out again.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_REPLACED_PENDING,
    DEV_BATTERY_VALUE,
    SYS_DEVICE_PAGE,
)
from .daily_dates import (
    _block,
    FAMILY_BATTERY,
    FAMILY_BATTERY_PREVIOUS,
    dates_for,
    set_dates,
)

# How the day came: detected and not yet answered, confirmed by a
# person (or detected before 0.26.7, which counts as confirmed), or
# entered by a person.
HOW_DETECTED = "detected"
HOW_CONFIRMED = "confirmed"
HOW_ENTERED = "entered"
HOWS = (HOW_DETECTED, HOW_CONFIRMED, HOW_ENTERED)
# Days after a day the person entered within which a detection is that
# same replacement: the day was given before the device reported its
# new level (found by review).
SAME_REPLACEMENT_DAYS = 7
# Earlier replacements an entry keeps for Cancel to go back to.
HISTORY_KEPT = 5

KIND_BATTERY_CONFIRM = "battery_confirm"
RECHARGEABLE = "Rechargeable"


def _iso_day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def resplit_battery(record: dict[str, Any], split_day: date | None, keep: int) -> None:
    """Join the battery history and split it again at a day (#702).

    The two kept parts, the cell before and the cell in the device, are
    read as one dated history and cut where the day falls: entries on
    or after it belong to the cell in the device. With no day, nothing
    is set aside. A day before the oldest kept entry gives the whole
    history to the cell in the device.
    """
    current = list(record.get(DEV_BATTERY_DAILY) or [])
    previous = list(record.get(DEV_BATTERY_DAILY_PREVIOUS) or [])
    yesterday = dt_util.now().date() - timedelta(days=1)
    current_days = dates_for(record, FAMILY_BATTERY, len(current), yesterday)
    before_current = current_days[0] - timedelta(days=1) if current_days else yesterday
    previous_days = dates_for(record, FAMILY_BATTERY_PREVIOUS, len(previous), before_current)
    pairs = sorted(
        zip(previous_days + current_days, previous + current, strict=True),
        key=lambda pair: pair[0],
    )
    if split_day is None:
        cut = 0
    else:
        cut = next((i for i, (day, _v) in enumerate(pairs) if day >= split_day), len(pairs))
    older, newer = pairs[:cut], pairs[cut:]
    # Each part keeps the History setting's days, as the fold keeps them.
    older, newer = older[-keep:] if keep else older, newer[-keep:] if keep else newer
    record[DEV_BATTERY_DAILY_PREVIOUS] = [value for _d, value in older]
    record[DEV_BATTERY_DAILY] = [value for _d, value in newer]
    set_dates(record, FAMILY_BATTERY_PREVIOUS, [day for day, _v in older])
    set_dates(record, FAMILY_BATTERY, [day for day, _v in newer])


class BatteryReplacementMixin:
    """The coordinator's Battery Last Replaced row and its answers."""

    # ------------------------------------------------------- the entries

    def _battery_answers(self) -> dict[str, dict[str, Any]]:
        found = getattr(self, "_battery_replacement_answers", None)
        if not isinstance(found, dict):
            found = {}
            self._battery_replacement_answers: dict[str, dict[str, Any]] = found
        return found

    @staticmethod
    def _entry_ok(entry: Any) -> dict[str, Any] | None:
        """An entry in its shape, or None (#370's rule)."""
        if not isinstance(entry, dict) or _iso_day(entry.get("day")) is None:
            return None
        if entry.get("how") not in HOWS:
            return None
        stamp = entry.get("stamp")
        return {
            "day": str(entry["day"])[:10],
            "how": str(entry["how"]),
            "stamp": stamp if isinstance(stamp, str) else None,
            "waiting": entry.get("waiting") is True,
        }

    def _battery_answers_read(self, payload: Any) -> int:
        """Take the entries from the answers file; a malformed one is
        dropped and counted (#370's rule), and so is a malformed earlier
        replacement in an entry's history."""
        kept: dict[str, dict[str, Any]] = {}
        dropped = 0
        if isinstance(payload, dict):
            for device_id, raw in payload.items():
                entry = self._entry_ok(raw)
                if entry is None:
                    dropped += 1
                    continue
                earlier = raw.get("history")
                history = []
                for item in earlier if isinstance(earlier, list) else []:
                    found = self._entry_ok(item)
                    if found is None:
                        dropped += 1
                    else:
                        history.append(found)
                if earlier is not None and not isinstance(earlier, list):
                    dropped += 1
                entry["history"] = history[-HISTORY_KEPT:]
                kept[str(device_id)] = entry
        elif payload is not None:
            dropped += 1
        self._battery_replacement_answers = kept
        return dropped

    def _battery_answers_payload(self) -> dict[str, dict[str, Any]]:
        return {device_id: dict(entry) for device_id, entry in self._battery_answers().items()}

    # ---------------------------------------------------------- reading

    def _battery_powered(self, device_id: str) -> bool:
        """A device with a battery reading, or one answered as running on
        a battery (#701: a device on mains has no row)."""
        record = self.data.get(DATA_DEVICES, {}).get(device_id)  # type: ignore[attr-defined]
        power = self.power_of(device_id)  # type: ignore[attr-defined]
        if power is not None:
            return power.get("kind") == "battery"
        return isinstance(record, dict) and record.get(DEV_BATTERY_VALUE) is not None

    def _rechargeable(self, device_id: str) -> bool:
        power = self.power_of(device_id)  # type: ignore[attr-defined]
        return power is not None and power.get("type") == RECHARGEABLE

    def battery_words(self, device_id: str) -> dict[str, str]:
        """The row's and the card's words, "charged" for a rechargeable
        cell (#701)."""
        if self._rechargeable(device_id):
            return {
                "row": "Battery Last Charged",
                "none": "No battery charge seen yet",
                "card": "Confirm Battery Charge",
                "done": "charged",
            }
        return {
            "row": "Battery Last Replaced",
            "none": "No battery replacement yet",
            "card": "Confirm Battery Replacement",
            "done": "replaced",
        }

    def _first_kept_day(self, record: dict[str, Any], stamp: str) -> date | None:
        """The day a replacement no entry carries began, from the dates
        every daily entry carries (0.24.4): the new cell's first dated
        entry while its history is whole, else the day after the old
        cell's last dated entry. The confirming stamp, minus a day, only
        where neither has a date. Worked out once, then stored."""
        yesterday = dt_util.now().date() - timedelta(days=1)
        keep = int(getattr(self, "retention_days", 0) or 0)
        series = record.get(DEV_BATTERY_DAILY)
        if isinstance(series, list) and series and (not keep or len(series) < keep):
            found = _dated(record, FAMILY_BATTERY, len(series), yesterday)
            if found:
                return found[0]
        previous = record.get(DEV_BATTERY_DAILY_PREVIOUS)
        if isinstance(previous, list) and previous:
            found = _dated(record, FAMILY_BATTERY_PREVIOUS, len(previous), yesterday)
            if found:
                return found[-1] + timedelta(days=1)
        moment = dt_util.parse_datetime(stamp)
        return dt_util.as_local(moment).date() - timedelta(days=1) if moment is not None else None

    def _battery_entry(self, device_id: str, record: dict[str, Any]) -> dict[str, Any] | None:
        """The entry the row shows. Reading changes nothing: a stamp no
        entry carries is answered with the entry it will be stored as at
        the next start or midnight (`_settle_battery_entries`)."""
        entry = self._battery_answers().get(device_id)
        stamp = record.get(DEV_BATTERY_REPLACED_AT)
        stamp = stamp if isinstance(stamp, str) else None
        if entry is None or entry.get("stamp") == stamp:
            if entry is not None or stamp is None:
                return entry
        if stamp is None:
            # The record knows no replacement the entry speaks of, as
            # after the main file was restored from an older copy: the
            # replacement before stands, and nothing waits (found by
            # review).
            earlier = list(entry.get("history") or []) if entry else []
            return {**earlier[-1], "waiting": False, "history": earlier[:-1]} if earlier else None
        day = self._first_kept_day(record, stamp)
        if day is None:
            return entry
        return {"day": day.isoformat(), "how": HOW_CONFIRMED, "stamp": stamp,
                "waiting": False, "history": _history(entry)}

    def _settle_battery_entries(self) -> None:
        """Store each entry a reading would answer with, once: at a start
        and at each midnight, on Home Assistant's own thread."""
        devices = self.data.get(DATA_DEVICES, {})  # type: ignore[attr-defined]
        answers = self._battery_answers()
        # An entry goes with its device's record, as power and type
        # answers do (found by review).
        changed = False
        for device_id in [d for d in answers if d not in devices]:
            del answers[device_id]
            changed = True
        for device_id, record in devices.items():
            if not isinstance(record, dict):
                continue
            entry = self._battery_entry(device_id, record)
            if entry is not answers.get(device_id):
                if entry is None:
                    answers.pop(device_id, None)
                else:
                    answers[device_id] = entry
                changed = True
        if changed:
            self._answers_save()  # type: ignore[attr-defined]

    def battery_replacement_view(self, device_id: str) -> dict[str, Any] | None:
        """The device page's row, or None for a device not on a battery."""
        if not self._battery_powered(device_id):
            return None
        record = self.data.get(DATA_DEVICES, {}).get(device_id)  # type: ignore[attr-defined]
        entry = self._battery_entry(device_id, record if isinstance(record, dict) else {})
        return {
            "words": self.battery_words(device_id),
            "day": entry["day"] if entry else None,
            "how": entry["how"] if entry else None,
            "waiting": bool(entry and entry["waiting"]),
        }

    def battery_confirm_rows(self) -> list[dict[str, Any]]:
        """Each watched battery device with a detected replacement nobody
        has answered, for the Confirm Battery Replacement card (#701). A
        device not on a battery has no row to answer from."""
        devices = self.data.get(DATA_DEVICES, {})  # type: ignore[attr-defined]
        rows = []
        for device_id in self._watched:  # type: ignore[attr-defined]
            record = devices.get(device_id)
            if not isinstance(record, dict) or not self._battery_powered(device_id):
                continue
            entry = self._battery_entry(device_id, record)
            if entry and entry["waiting"]:
                rows.append({"device_id": device_id, "day": entry["day"],
                             "words": self.battery_words(device_id)})
        return rows

    # --------------------------------------------------------- detecting

    def _note_detected_replacement(
        self, record: dict[str, Any], device_id: str, rise_day: date | None, replaced_before: Any,
    ) -> None:
        """A replacement the midnight roll just confirmed (#701).

        It waits for a person, dated by the rise day the split just
        wrote, with the entry before it kept for Cancel. A detection
        within SAME_REPLACEMENT_DAYS after a day the person entered is
        that same replacement: their day stands and nothing waits.
        """
        stamp = record.get(DEV_BATTERY_REPLACED_AT)
        answers = self._battery_answers()
        before_record = dict(record)
        before_record[DEV_BATTERY_REPLACED_AT] = replaced_before
        before = self._battery_entry(device_id, before_record)
        if (
            before is not None and before["how"] == HOW_ENTERED
            and _same_replacement(_iso_day(before["day"]), rise_day)
        ):
            answers[device_id] = {**before, "stamp": stamp}
        elif rise_day is not None:
            answers[device_id] = {
                "day": rise_day.isoformat(), "how": HOW_DETECTED, "stamp": stamp,
                "waiting": True, "history": _history(before),
            }
        self._answers_save()  # type: ignore[attr-defined]

    def _entered_just_before(self, device_id: str, rise_day: date) -> bool:
        """Whether a rise falls within SAME_REPLACEMENT_DAYS after a day
        the person entered: the same replacement."""
        entry = self._battery_answers().get(device_id)
        return bool(entry and entry["how"] == HOW_ENTERED and _same_replacement(_iso_day(entry["day"]), rise_day))

    # --------------------------------------------------------- answering

    def battery_answer(self, device_id: str, action: str, day: str | None = None) -> None:
        """Confirm, cancel, or set the day of a device's replacement.

        Confirm keeps the detected day as the person's. Cancel joins the
        history back to the replacement before (#709: the Log-Normal
        count is left as it stands). A day the person gives splits the
        history there and stands (#701, #702). Each is saved at once,
        the history with it; nothing is taken once Device Sentinel is
        stopping (found by review).
        """
        if getattr(self, "_stopped", False):
            raise ValueError("Device Sentinel is stopping")
        record = self.data.get(DATA_DEVICES, {}).get(device_id)  # type: ignore[attr-defined]
        if not isinstance(record, dict) or not self._battery_powered(device_id):
            raise ValueError("Device Sentinel has no battery history for that device")
        answers = self._battery_answers()
        keep = int(getattr(self, "retention_days", 0) or 0)
        words = self.battery_words(device_id)["done"]
        entry = self._battery_entry(device_id, record)
        waiting = bool(entry and entry["waiting"])
        if action == "confirm":
            if not waiting or entry is None:
                raise ValueError("No detected replacement is waiting")
            answers[device_id] = {**entry, "how": HOW_CONFIRMED, "waiting": False}
            said = f"battery {words} on {entry['day']} confirmed"
        elif action == "cancel":
            if not waiting or entry is None:
                raise ValueError("No detected replacement is waiting")
            earlier = list(entry.get("history") or [])
            before = earlier[-1] if earlier else None
            resplit_battery(record, _iso_day(before["day"]) if before else None, keep)
            record[DEV_BATTERY_REPLACED_AT] = before["stamp"] if before else None
            if before:
                answers[device_id] = {**before, "history": earlier[:-1]}
            else:
                answers.pop(device_id, None)
            said = f"detected battery {'charge' if words == 'charged' else 'replacement'} cancelled"
        elif action == "date":
            given = _iso_day(day)
            if given is None:
                raise ValueError("That is not a day")
            if given > dt_util.now().date():
                raise ValueError("That day has not come yet")
            resplit_battery(record, given, keep)
            stamp = record.get(DEV_BATTERY_REPLACED_AT)
            answers[device_id] = {
                "day": given.isoformat(), "how": HOW_ENTERED,
                "stamp": stamp if isinstance(stamp, str) else None, "waiting": False,
                "history": _history(entry if entry and not entry["waiting"] else None,
                                    entry.get("history") if entry else None),
            }
            # A rise still waiting for its second night is answered too:
            # the next midnight confirms nothing over it (found by review).
            record[DEV_BATTERY_REPLACED_PENDING] = None
            said = f"battery {words} on {given.isoformat()}, set by hand"
        else:
            raise ValueError("Device Sentinel cannot do that")
        self._answers_save()  # type: ignore[attr-defined]
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_DEVICE_PAGE, detail=f"{said}, from its device page", device_id=device_id
        )
        self._mark_changed()  # type: ignore[attr-defined]
        # The answer and the split history are saved together, now, not
        # at the next routine save (found by review).
        self.hass.async_create_task(self._save_now())  # type: ignore[attr-defined]

def _dated(record: dict[str, Any], family: str, length: int, end: date) -> list[date]:
    """A history's dates where it carries them (0.24.4), else none: a
    day counted back from today is not a date (found by review)."""
    return dates_for(record, family, length, end) if _block(record, family) is not None else []


def _history(entry: dict[str, Any] | None, earlier: list[Any] | None = None) -> list[dict[str, Any]]:
    """The replacements before a new entry, the newest last: the entry
    it follows, with that entry's own, at most HISTORY_KEPT."""
    if entry is None:
        kept = list(earlier or [])
    else:
        kept = [*(entry.get("history") or []), {k: v for k, v in entry.items() if k != "history"}]
    # Each keeps its own waiting: a Cancel that goes back to a detection
    # nobody answered asks about it again (found by review).
    return [dict(item) for item in kept][-HISTORY_KEPT:]


def _same_replacement(given: date | None, detected: date | None) -> bool:
    """A detection a few days after a day the person entered."""
    return (
        given is not None and detected is not None
        and given <= detected <= given + timedelta(days=SAME_REPLACEMENT_DAYS)
    )
