# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: clock.py, Version: 0.30.10 (2026-11-25)

"""Times and dates as the house's owner chose to read them (rule GEN-11).

Home Assistant keeps each account's Localization choices on the server:
language, time format (12 or 24 hours, or as the language or the browser
has it) and date format (day-month-year, month-day-year, year-month-day,
or as the language or the browser has it). The dashboard follows the
person looking at it. What the server writes, the Daily Brief, the
pushes, the Problem List and the reports, goes to everyone, so it
follows the owner account's choices. A choice only a browser can make,
"use system locale", falls back to the language, and so does a house
with no owner or no choice saved.

The words, month names and AM and PM, come from the phrase files in the
house's language (rule GEN-12); only English ships, so they read English.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import phrases

# Languages whose clock is 12 hours, as Home Assistant's own "use my
# language" reads them; every other language reads 24 hours.
HOUR12_LANGUAGES = frozenset({
    "en", "en-US", "en-AU", "en-CA", "en-IN", "en-NZ", "en-PH", "en-ZA",
    "es-US", "es-MX", "hi", "bn", "ur", "ar", "ko", "zh-Hant", "zh-TW", "fil",
})
# Languages that put the month first; those that put the year first.
MDY_LANGUAGES = frozenset({"en", "en-US", "en-PH", "es-US", "fil"})
YMD_LANGUAGES = frozenset({"zh-Hans", "zh-Hant", "zh-TW", "ja", "ko", "hu", "lt", "sv", "fr-CA", "en-CA", "en-ZA", "eu"})
ORDERS = ("DMY", "MDY", "YMD")
MONTHS = (
    "common.month.1", "common.month.2", "common.month.3", "common.month.4",
    "common.month.5", "common.month.6", "common.month.7", "common.month.8",
    "common.month.9", "common.month.10", "common.month.11", "common.month.12",
)
MONTHS_SHORT = (
    "common.month_short.1", "common.month_short.2", "common.month_short.3", "common.month_short.4",
    "common.month_short.5", "common.month_short.6", "common.month_short.7", "common.month_short.8",
    "common.month_short.9", "common.month_short.10", "common.month_short.11", "common.month_short.12",
)

_SOURCE: dict[str, Any] = {"store": None, "language": "en"}


def bind(store: Any, language: str | None) -> None:
    """Read the owner's choices from this store (Home Assistant's own,
    kept up to date as the person changes them), and fall back to this
    language."""
    _SOURCE["store"] = store
    _SOURCE["language"] = language or "en"


def _choices() -> dict[str, Any]:
    store = _SOURCE.get("store")
    data = getattr(store, "data", None)
    chosen = data.get("language") if isinstance(data, dict) else None
    return chosen if isinstance(chosen, dict) else {}


def _language() -> str:
    chosen = _choices().get("language")
    return chosen if isinstance(chosen, str) and chosen else str(_SOURCE.get("language") or "en")


def language() -> str:
    """The house's language: the owner's choice, or Home Assistant's own;
    the test language while the house is in testing mode. Times and
    dates keep the owner's real language for their format."""
    if phrases.testing():
        return phrases.TEST
    return _language()


def hour12() -> bool:
    """Whether times read on a 12-hour clock with AM and PM."""
    chosen = _choices().get("time_format")
    if chosen == "12":
        return True
    if chosen == "24":
        return False
    return _language() in HOUR12_LANGUAGES


def order() -> str:
    """DMY, MDY or YMD."""
    chosen = _choices().get("date_format")
    if chosen in ORDERS:
        return str(chosen)
    language = _language()
    if language in MDY_LANGUAGES:
        return "MDY"
    if language in YMD_LANGUAGES or language.split("-")[0] in {"ja", "ko", "hu", "lt", "zh"}:
        return "YMD"
    return "DMY"


def time_text(moment: datetime, seconds: bool = False) -> str:
    """5:34 AM, or 05:34; with seconds, 5:34:07 AM or 05:34:07."""
    tail = f":{moment.second:02d}" if seconds else ""
    if hour12():
        half = phrases.say("common.am" if moment.hour < 12 else "common.pm")
        return f"{moment.hour % 12 or 12}:{moment.minute:02d}{tail} {half}"
    return f"{moment.hour:02d}:{moment.minute:02d}{tail}"


def minute_text(minute: int) -> str:
    """A time of day given as minutes after midnight."""
    hour, mins = divmod(int(minute) % 1440, 60)
    return time_text(datetime(2000, 1, 1, hour, mins))


def day_text(moment: date | datetime, year: bool = False, long: bool = False) -> str:
    """Nov 23, 23 Nov or 2026 Nov 23; with the year, Nov 23, 2026 or
    23 Nov 2026; long spells the month out."""
    month = phrases.say((MONTHS if long else MONTHS_SHORT)[moment.month - 1])
    way = order()
    if way == "YMD":
        return f"{moment.year} {month} {moment.day}" if year else f"{month} {moment.day}"
    if way == "DMY":
        return f"{moment.day} {month} {moment.year}" if year else f"{moment.day} {month}"
    return f"{month} {moment.day}, {moment.year}" if year else f"{month} {moment.day}"


def day_time_text(moment: datetime, seconds: bool = False) -> str:
    """Nov 23, 5:34 AM, or 23 Nov, 05:34."""
    return f"{day_text(moment)}, {time_text(moment, seconds)}"


def report_text(moment: datetime) -> str:
    """A date and time as a report's heading says it: the month spelled out,
    the year, then the time."""
    return phrases.say("common.day_at_time", day=day_text(moment, year=True, long=True), time=time_text(moment))
