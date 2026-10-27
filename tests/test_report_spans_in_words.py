# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_report_spans_in_words.py, Version: 0.27.9 (2026-10-27)

"""The maintainer reports' gap cells read in words from two days up, as
the Daily Brief does (rule GEN-09); a gap held at the history length
still reads "more than" it."""

from homeassistant.core import HomeAssistant

from .helpers import setup_coordinator

DAY = 86400.0


async def test_two_days_and_more_read_in_words(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert coord._fmt_gap(5.5 * DAY) == "5 and a half days"
    assert coord._fmt_gap(3 * 3600.0) == "3.0h"
    assert coord._fmt_gap(None) == "-"
    cap = coord.gap_cap()
    if cap is not None:
        assert coord._fmt_gap(cap + DAY).startswith("more than")
