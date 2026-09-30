# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: durations.py, Version: 0.23.19 (2026-09-30)

"""A duration in the words a person reads, and in a table cell.

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

Below two days a table cell reads in the compact form, minutes then
hours (`compact_span`, 0.23.19), which is the scale a rhythm is read
at; a sentence keeps the words above.
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


def compact_span(seconds: float, cap: float | None = None) -> str:
    """A duration for a table cell: 45s, 74m, 4.1h, 2.3d, 3.5w.

    The one compact format (ruling #546), after six formatters in five
    files had printed the same length as "1062s", "18m" and "0.3h". It
    is the format the owner asked for with the resurrection cap's label
    (ruling #166), extended both ways: seconds mean nothing to a person
    past ninety of them, minutes past ninety, hours past two days, and
    days past two weeks. Seconds below ninety were ruled in after the
    adversarial round, where "<1m" left a Bluetooth device's fourteen
    daily gaps reading the same. One decimal where the unit is coarse.

    A gap held at the retention (ruling #543) reads "more than" it
    when the cap is given. A value that is not a real number reads as
    unknown rather than raising.
    """
    if not isfinite(seconds):
        return "?"
    seconds = max(0.0, seconds)
    if cap is not None and seconds >= cap:
        return f"more than {cap / DAY:.0f} days"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f}m"
    if seconds < 2 * DAY:
        return f"{seconds / 3600:.1f}h"
    if seconds < 2 * WEEK:
        return f"{seconds / DAY:.1f}d"
    return f"{seconds / WEEK:.1f}w"

