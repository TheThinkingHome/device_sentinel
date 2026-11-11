# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_stacked_detections.py, Version: 0.28.12 (2026-11-11)

"""Two detected replacements waiting at once must not lose the oldest
battery history (rule BAT-06: "The old history is kept, unread"; rule
BAT-07: Cancel joins the history back).

Real-house trigger: an outdoor coin-cell sensor whose voltage-derived
level sags through a cold spell of a day or more and comes back on the
thaw. Each thaw that lands at 95 or more after a whole cold day is taken
for a new battery (left to the person by rule BAT-06). Nobody answers
the first card before the next thaw; the second detection overwrites
the kept history with only the days since the first, so the days before
the first false detection are gone, and Cancel cannot bring them back.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_VALUE,
)
from custom_components.device_sentinel.detect_battery import note_battery_sample

from tests.helpers import setup_coordinator


def _record(start: float):
    from custom_components.device_sentinel.records import _new_device_record

    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_BATTERY_VALUE] = start
    note_battery_sample(record, start)
    return record


MILD = [94.0, 94.0, 100.0, 100.0, 100.0, 96.0, 96.0]
COLD = [50.0, 50.0, 58.0, 58.0, 58.0, 45.0, 45.0]
THAW = [70.0, 70.0, 100.0, 100.0, 100.0, 96.0, 96.0]


async def test_two_waiting_detections_keep_every_day(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(96.0)
    days = [MILD] * 5 + [COLD] * 2 + [THAW] + [MILD] * 4 + [COLD] * 2 + [THAW] + [MILD] * 3
    stamps = set()
    for heard in days:
        for level in heard:
            record[DEV_BATTERY_VALUE] = level
            note_battery_sample(record, level)
        coord._roll_battery(record, "dev-battery")
        if record.get(DEV_BATTERY_REPLACED_AT):
            stamps.add(record[DEV_BATTERY_REPLACED_AT])
    kept = len(record.get(DEV_BATTERY_DAILY) or []) + len(record.get(DEV_BATTERY_DAILY_PREVIOUS) or [])
    # Every day folded is still held, in the cell in the device or the
    # one set aside, so a Cancel can join it back.
    assert kept == len(days), (kept, len(days), len(stamps))
