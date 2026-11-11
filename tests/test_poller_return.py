# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_poller_return.py, Version: 0.28.12 (2026-11-11)

"""A known poller's ordinary outage
closes when its entry is loaded again (rules UP-03, UP-08, UP-17).

Scenario on a real house: Alarm.com (or Tado) is a known poller. Its cloud
login fails after an internet drop, the entry sits in SETUP_RETRY for 20
minutes and is told "went down". Then it loads again. Without its own return the
outage closed at the next minute check. Now _poller_stalled() is asked
first: its devices have not been heard for longer than the stop threshold
(they could not be, the entry was down), so it answers "stalled", the
entry is already told, and the loop `continue`s without closing the
outage. The outage stays open, its devices stay claimed and their returning
values read as republished, until a same-value write arrives on the next
poll, so the "back" push and the hand-back are late by up to one poll and
the outage is recorded longer than it was.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import SYS_DETAIL, SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP
from custom_components.device_sentinel.outage_detail import STALLED, parse_detail
from tests.test_poller_stop import _outages, _poller, _silent_since


async def test_a_known_poller_back_from_a_down_is_closed_when_loaded(hass: HomeAssistant, freezer):
    source, fleet, coord = await _poller(hass, freezer)
    now = dt_util.utcnow().timestamp()
    # Healthy: heard a minute ago.
    _silent_since(coord, fleet, 60)
    # The entry fails and retries, past the dwell: told as down.
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now)
    coord._sample_integrations(now + 120)
    down = _outages(coord, SYS_INTEGRATION_DOWN)
    assert len(down) == 1
    assert parse_detail(down[0][SYS_DETAIL])[2] != STALLED
    # Twenty minutes later it loads again.
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 1200)
    assert len(_outages(coord, SYS_INTEGRATION_UP)) == 1, (
        "the outage closes when the entry is loaded, as any integration outage does"
    )
