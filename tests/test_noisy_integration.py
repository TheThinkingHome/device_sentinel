# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_noisy_integration.py, Version: 0.22.0 (2026-09-18)

"""Which integrations are worth excluding for their noise (ruling #457).

The second fleet's brief advised excluding zha, the house's own
Zigbee stack, because it republished its whole fleet twice in a day.
Both times the coordinator had just been pulled for a test. A storm
inside an outage, a maintenance window or a restart is the house
recovering, not an integration polling, so it stays out of the
tally, and the advice waits for three unexplained storms a day on
two days of the last seven.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_STORM_DAYS,
    DATA_SYSTEM_EVENTS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_INTERVAL,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_KIND,
    SYS_MAINTENANCE_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_WHEN,
)

from tests.helpers import setup_coordinator

T = 1_800_000_000.0


def _event(when: float, kind: str, scope: str = "zha") -> dict:
    return {SYS_WHEN: when, SYS_KIND: kind, SYS_SCOPE: scope}


async def test_a_storm_inside_an_open_outage_is_explained(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [_event(T - 600, SYS_BRIDGE_DOWN)]
    assert coord._storm_explained(T) is True


async def test_a_storm_soon_after_a_return_is_explained(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(T - 900, SYS_BRIDGE_DOWN),
        _event(T - 299, SYS_BRIDGE_UP),
    ]
    assert coord._storm_explained(T) is True


async def test_a_storm_long_after_a_return_is_not_explained(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(T - 900, SYS_BRIDGE_DOWN),
        _event(T - 301, SYS_BRIDGE_UP),
    ]
    assert coord._storm_explained(T) is False


async def test_a_storm_after_a_restart_or_inside_maintenance_is_explained(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [_event(T - 120, SYS_RESTART, "system")]
    assert coord._storm_explained(T) is True
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(T - 3000, SYS_MAINTENANCE_OPEN, "system")
    ]
    assert coord._storm_explained(T) is True


async def test_an_outage_elsewhere_that_closed_long_ago_explains_nothing(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(T - 9000, SYS_BRIDGE_DOWN),
        _event(T - 8000, SYS_BRIDGE_UP),
        _event(T - 7000, SYS_RESTART, "system"),
    ]
    assert coord._storm_explained(T) is False


def _day(days_ago: int) -> str:
    return (dt_util.now().date() - timedelta(days=days_ago)).isoformat()


def _row(domain: str, days_ago: int, count: int, interval: float = 14.0) -> dict:
    return {
        STORM_DAY_DATE: _day(days_ago),
        STORM_DAY_DOMAIN: domain,
        STORM_DAY_COUNT: count,
        STORM_DAY_INTERVAL: interval,
    }


async def test_a_poller_on_two_days_is_advised(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [
        _row("poller", 3, 4429), _row("poller", 1, 5507, 13.7)
    ]
    said = coord._noisy_integration_advice()
    assert len(said) == 1
    assert "the poller integration is a poller" in said[0]
    assert "publishing its fleet data every 14 seconds" in said[0]


async def test_one_bad_day_is_not_advised(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [_row("zha", 1, 3)]
    assert coord._noisy_integration_advice() == []


async def test_two_a_day_is_not_advised(hass: HomeAssistant):
    """The second fleet's zha pair of 16 September, on two days."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [_row("zha", 4, 2), _row("zha", 1, 2)]
    assert coord._noisy_integration_advice() == []


async def test_days_outside_the_window_do_not_count(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [_row("poller", 9, 900), _row("poller", 1, 900)]
    assert coord._noisy_integration_advice() == []
