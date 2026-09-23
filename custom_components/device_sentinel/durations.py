# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: durations.py, Version: 0.22.26 (2026-09-23)

"""A long duration in the words a person reads.

Hours carried past the point of meaning: a battery flat since July
read "1485.3h" in one report and "61.9d" in another, and a device's
rhythm chart labelled its axis 1032h. Past two days a duration reads
in days, and past a week and a half in weeks, in halves, rounded down
so the number is never larger than the truth (0.22.25).

    60 hours   2 and a half days
    10 days    10 days
    11 days    a week and a half
    43 days    6 weeks
    62 days    8 and a half weeks

Below two days nothing changes: the reports keep their hours, minutes
and seconds, which is the scale a rhythm is read at.
"""

from __future__ import annotations

from math import isfinite

DAY = 86400.0
WEEK = 7 * DAY
# Two days: where hours stop being the scale a person reads.
LONG_SPAN_SECONDS = 2 * DAY
# A week and a half: where days stop and weeks begin.
WEEK_SPAN_SECONDS = 1.5 * WEEK


def _halves(value: float, noun: str) -> str:
    """Return the value in halves, rounded down, in words."""
    halves = int(value * 2)
    whole, half = divmod(halves, 2)
    if not half:
        return f"{whole} {noun}{'' if whole == 1 else 's'}"
    if whole == 0:
        return f"half a {noun}"
    if whole == 1:
        return f"a {noun} and a half"
    return f"{whole} and a half {noun}s"


def long_span(seconds: float) -> str:
    """Return a duration of two days or more, in days or weeks.

    A value that is not a real number reads as unknown rather than
    raising (0.22.26). Storage refuses a non-finite number, so this
    guards the paths that never touch a file.
    """
    if not isfinite(seconds):
        return "?"
    seconds = max(0.0, seconds)
    if seconds >= WEEK_SPAN_SECONDS:
        return _halves(seconds / WEEK, "week")
    return _halves(seconds / DAY, "day")
