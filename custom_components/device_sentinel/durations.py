# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: durations.py, Version: 0.30.11 (2026-11-25)

"""A duration in the words a person reads, and in a table cell.

Hours lose their meaning past a couple of days: "1485.3h" tells a
person nothing they can use. Past two days a duration reads
in days, and past a week and a half in weeks, in halves, rounded down
so the number is never larger than the truth (rule GEN-09).

    60 hours   2 and a half days
    10 days    10 days
    11 days    a week and a half
    43 days    6 weeks
    62 days    8 and a half weeks

Below two days a table cell reads in the compact form, minutes then
hours (`compact_span`), which is the scale a rhythm is read
at; a sentence keeps the words above.
"""

from __future__ import annotations

from math import isfinite

from .phrases import number, say

DAY = 86400.0
WEEK = 7 * DAY
# Two days: where hours stop being the scale a person reads.
LONG_SPAN_SECONDS = 2 * DAY
# A week and a half: where days stop and weeks begin.
WEEK_SPAN_SECONDS = 1.5 * WEEK


# The words for a whole count, a half, one and a half, and more and a
# half, of a day and of a week (rule GEN-12).
_HALVES = {
    "day": ("common.span.day.whole", "common.span.day.half",
            "common.span.day.one_and_a_half", "common.span.day.and_a_half"),
    "week": ("common.span.week.whole", "common.span.week.half",
             "common.span.week.one_and_a_half", "common.span.week.and_a_half"),
}


def _halves(value: float, noun: str) -> str:
    """Return the value in halves, rounded down, in words; noun is
    "day" or "week"."""
    whole_key, half_key, one_and_a_half_key, and_a_half_key = _HALVES[noun]
    halves = int(value * 2)
    whole, half = divmod(halves, 2)
    if not half:
        return say(whole_key, count=whole)
    if whole == 0:
        return say(half_key)
    if whole == 1:
        return say(one_and_a_half_key)
    return say(and_a_half_key, count=whole)


def long_span(seconds: float) -> str:
    """Return a duration of two days or more, in days or weeks.

    A value that is not a real number reads as unknown rather than
    raising. Storage refuses a non-finite number, so this
    guards the paths that never touch a file.
    """
    if not isfinite(seconds):
        return say("common.span.unknown")
    seconds = max(0.0, seconds)
    if seconds >= WEEK_SPAN_SECONDS:
        return _halves(seconds / WEEK, "week")
    return _halves(seconds / DAY, "day")


def compact_span(seconds: float, cap: float | None = None) -> str:
    """A duration for a table cell: 45s, 74m, 4.1h, 2.3d, 3.5w.

    The one compact format, so the same length never reads "1062s",
    "18m" and "0.3h" in different places (rule GEN-09). Seconds mean
    nothing to a person past ninety of them, minutes past ninety, hours
    past two days, and days past two weeks. Below ninety a length reads
    in seconds, so a device's short daily gaps do not all read "<1m".
    One decimal where the unit is coarse.

    A gap held at the retention reads "more than" it when the cap is
    given (rule FRZ-13). A value that is not a real number reads as
    unknown rather than raising.
    """
    if not isfinite(seconds):
        return say("common.span.unknown")
    seconds = max(0.0, seconds)
    if cap is not None and seconds >= cap:
        return say("common.span.more_than_days", count=round(cap / DAY))
    if seconds < 90:
        return say("common.span.seconds", value=number(seconds, 0))
    if seconds < 90 * 60:
        return say("common.span.minutes", value=number(seconds / 60, 0))
    if seconds < 2 * DAY:
        return say("common.span.hours", value=number(seconds / 3600, 1))
    if seconds < 2 * WEEK:
        return say("common.span.days", value=number(seconds / DAY, 1))
    return say("common.span.weeks", value=number(seconds / WEEK, 1))

