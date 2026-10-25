# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_priority_targets.py, Version: 0.27.4 (2026-10-25)

"""Who gets a push, and when (rules NOTE-02, NOTE-07, BRIEF-11).

High-priority targets get every push, Quiet Hours included.
Normal-priority targets get every push except during Quiet Hours. The
Daily Brief goes only to Send the Full Brief To. Before 0.27.4 Quiet
Hours stopped every push, high priority included, and normal-priority
targets were never sent anything.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    REMINDER_MODE_DAILY,
)
from custom_components.device_sentinel.repairs import delivery_is_configured

from tests.helpers import setup_entry
from tests.test_notifications import _Harness

QUIET_ALL_DAY = {
    CONF_QUIET_ENABLED: True,
    CONF_QUIET_START: "00:00:00",
    CONF_QUIET_END: "23:59:59",
}


def _targets(h):
    return [f"{domain}.{service}" for domain, service, _ in h.sent]


async def test_high_priority_gets_a_push_inside_quiet_hours():
    h = _Harness(["notify.high"], battery=[{"name": "X", "level": 10}])
    h.entry.options = {CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"], **QUIET_ALL_DAY}
    await h.async_fire_events([("battery", "At 3 am, X low.", False)])
    assert _targets(h) == ["notify.high"]


async def test_normal_priority_gets_a_push_outside_quiet_hours():
    h = _Harness(["notify.high"], battery=[{"name": "X", "level": 10}])
    h.entry.options = {CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"], CONF_QUIET_ENABLED: False}
    await h.async_fire_events([("battery", "At 3 pm, X low.", False)])
    assert _targets(h) == ["notify.high", "notify.normal"]


async def test_a_house_with_only_normal_priority_targets_gets_pushes():
    h = _Harness([], battery=[{"name": "X", "level": 10}])
    h.entry.options = {CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"], CONF_QUIET_ENABLED: False}
    await h.async_fire_events([("battery", "At 3 pm, X low.", False)])
    assert _targets(h) == ["notify.normal"]
    h.sent.clear()
    h.entry.options = {CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"], **QUIET_ALL_DAY}
    await h.async_fire_events([("battery", "At 3 am, X low.", False)])
    assert h.sent == []


async def test_upstream_push_follows_the_same_tiers(hass: HomeAssistant):
    high = async_mock_service(hass, "notify", "high")
    normal = async_mock_service(hass, "notify", "normal")
    entry = await setup_entry(hass, {
        CONF_HIGH_PRIORITY_TARGETS: ["notify.high"],
        CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"],
        **QUIET_ALL_DAY,
    })
    coord = entry.runtime_data
    await coord.async_push_upstream("z2m", 0, recovered=True)
    assert len(high) == 1 and normal == []

    high.clear()
    coord.hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_QUIET_ENABLED: False}
    )
    await hass.async_block_till_done()
    coord = entry.runtime_data
    await coord.async_push_upstream("z2m", 0, recovered=True)
    assert len(high) == 1 and len(normal) == 1


async def test_the_brief_goes_to_no_priority_target(hass: HomeAssistant):
    high = async_mock_service(hass, "notify", "high")
    normal = async_mock_service(hass, "notify", "normal")
    entry = await setup_entry(hass, {
        CONF_HIGH_PRIORITY_TARGETS: ["notify.high"],
        CONF_NORMAL_PRIORITY_TARGETS: ["notify.normal"],
        CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
    })
    assert await entry.runtime_data.async_send_brief("## In Short\n\nAll clear.\n") == 0
    await hass.async_block_till_done()
    assert high == [] and normal == []
    # A house whose only targets are normal priority is reachable.
    assert delivery_is_configured(entry) is True
