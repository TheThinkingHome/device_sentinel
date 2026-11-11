# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storm_tally_scope.py, Version: 0.28.12 (2026-11-11)

"""An unrelated outage left open must not empty every
integration's storm tally (rules UP-17, UP-18).

A one-device entry that stays down for days (a TP-Link plug unplugged
and put in a drawer, its entry left in setup retry) keeps an
integration_down row open in the system events. `_storm_explained`
answers "any opener still open" with no regard to which integration
stormed, so every storm of every other integration is left out of the
day's tally while that row stays open. The lasting poller verdict known
by storms, and the noisy-integration advice, both read that tally, so
neither can form (or both lapse after 7 days) on that house.

Each test asserts the correct behaviour: a storm on Tado is not
explained by a TP-Link plug's outage.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_DETAIL,
    SYS_INTEGRATION_DOWN,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
)
from custom_components.device_sentinel.outage_detail import DOWN, make_detail
from tests.helpers import setup_coordinator

T = 1_800_000_000.0


def _plug_down_for_days() -> dict:
    return {
        SYS_WHEN: T - 3 * 86400.0,
        SYS_KIND: SYS_INTEGRATION_DOWN,
        SYS_SCOPE: "tplink",
        SYS_DETAIL: make_detail("tplink_plug_entry", "plug_device", DOWN),
    }


async def test_a_storm_elsewhere_is_tallied_beside_an_open_plug_outage(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [_plug_down_for_days()]
    coord._storm_day.clear()
    storm = {
        "start": T,
        "last_met": T + 1.0,
        "stamps": 20,
        "devices": {f"tado_{n}" for n in range(20)},
        "recorded": True,
        "announce": False,
    }
    # "tado_entry" has no config entry, so its domain reads as the id.
    coord._end_storm("tado_entry", storm, T + 6.0)
    assert coord._storm_day.get("tado_entry"), (
        "a Tado storm was left out of the tally because a TP-Link plug's "
        "entry has been down for three days"
    )
