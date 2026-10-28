# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_settings_change_words.py, Version: 0.27.10 (2026-10-27)

"""A changed setting is named by its screen label everywhere (rule BRIEF-07).

In Short, the Last 24 Hours row and the dashboard's Daily Brief tab
each name it "Repeat Offender Threshold", never by its raw option key,
"settings changed (repeat_floor)".
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_OPTIONS_CHANGED,
)

from tests.helpers import setup_coordinator

DAY = 86400.0


async def test_every_row_names_the_label(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = []
    coord._record_system_event(SYS_OPTIONS_CHANGED, detail="repeat_floor")
    now = dt_util.utcnow().timestamp()
    text = coord._write_brief(hass.config.path("www", "device_sentinel"), "manual",
                              now - DAY, now + 1, complete=True)
    in_short, tail = text.split("## Last 24 Hours", 1)
    assert "Repeat Offender Threshold" in in_short
    assert "settings changed (Repeat Offender Threshold)" in tail
    assert "repeat_floor" not in text
    page = coord.dashboard_brief(dt_util.now().date())
    whats = [row.get("what") for row in page["events"]]
    assert "settings changed (Repeat Offender Threshold)" in whats
    row = coord.data[DATA_SYSTEM_EVENTS][-1]
    assert coord._system_event_sentence(row).endswith(": Repeat Offender Threshold.")
