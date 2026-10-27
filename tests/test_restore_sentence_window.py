# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_restore_sentence_window.py, Version: 0.27.8 (2026-10-27)

"""The restore sentence leads only the brief whose window holds the
restore (rule BRIEF-02); before, it led every brief until a restart."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .helpers import setup_coordinator

DAY = 86400.0
TOLD = "Device Sentinel restored its storage from a backup."


async def test_only_the_brief_holding_the_restore_says_it(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord._restore_told = TOLD
    coord._restore_told_at = now - DAY / 2
    folder = hass.config.path("www", "device_sentinel")
    first = coord._write_brief(folder, "manual", now - DAY, now, complete=True)
    later = coord._write_brief(folder, "manual", now, now + DAY, complete=True)
    earlier = coord._write_brief(folder, "manual", now - 3 * DAY, now - 2 * DAY, complete=True)
    assert TOLD in first
    assert TOLD not in later
    assert TOLD not in earlier


async def test_a_restore_is_dated_and_told_once(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert coord._restore_told_at is None
    coord._restored_from = dt_util.utcnow().timestamp() - 200000.0
    coord._restore_evidence = "2026-08-26_140000"
    before = dt_util.utcnow().timestamp()
    await coord._announce_restore()
    await hass.async_block_till_done()
    at = coord._restore_told_at
    assert at is not None and before <= at <= dt_util.utcnow().timestamp()
    folder = hass.config.path("www", "device_sentinel")
    holding = coord._write_brief(folder, "manual", at - DAY, at + 1, complete=True)
    next_day = coord._write_brief(folder, "manual", at + 1, at + DAY, complete=True)
    assert coord.restore_told in holding
    assert coord.restore_told not in next_day
