# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v033_notify_backbone.py, Version: 0.3.10 (2026-07-16)

"""Notification backbone tests (config surface only, no engine).

0.3.3 introduced it; 0.3.4 rebuilt it to mirror Sentinel Notify:
two target lists (high pierces quiet hours, normal is held), the
persistent card, quiet hours, and the daily reminder mode and time.
"""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import (
    _discover_notify_targets,
)
from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
)

DOMAIN = "device_sentinel"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_discovery_includes_persistent_and_notify_services(hass):
    hass.services._services.setdefault("notify", {})
    hass.services._services["notify"]["mobile_app_s24"] = object()
    hass.services._services["notify"]["mobile_app_pad"] = object()
    targets = _discover_notify_targets(hass)
    assert "persistent_notification" in targets
    assert "notify.mobile_app_s24" in targets
    assert "notify.mobile_app_pad" in targets
    assert targets == sorted(targets)


async def test_options_menu_branches(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "exclusions", "battery", "notifications", "signal", "freeze",
    }


async def test_two_lists_and_both_means_high(hass: HomeAssistant):
    hass.services._services.setdefault("notify", {})
    for name in ("mobile_app_mine", "mobile_app_wife"):
        hass.services._services["notify"][name] = object()
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    assert result["step_id"] == "notifications"

    # Mine is high; wife is normal; a shared target is listed in both.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HIGH_PRIORITY_TARGETS: [
                "notify.mobile_app_mine",
                "notify.mobile_app_wife",
            ],
            CONF_NORMAL_PRIORITY_TARGETS: ["notify.mobile_app_wife"],
            CONF_PERSISTENT_ENABLED: True,
            CONF_QUIET_ENABLED: True,
            CONF_QUIET_START: "22:00:00",
            "quiet_hours_end": "07:00:00",
            CONF_REMINDER_MODE: "overnight",
            CONF_REMINDER_TIME: "08:00:00",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The shared target normalized out of the normal list (both = high).
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == [
        "notify.mobile_app_mine",
        "notify.mobile_app_wife",
    ]
    assert entry.options[CONF_NORMAL_PRIORITY_TARGETS] == []
    assert entry.options[CONF_QUIET_ENABLED] is True
    assert entry.options[CONF_REMINDER_MODE] == "overnight"


async def test_empty_lists_allowed(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HIGH_PRIORITY_TARGETS: [],
            CONF_NORMAL_PRIORITY_TARGETS: [],
            CONF_PERSISTENT_ENABLED: False,
            CONF_QUIET_ENABLED: False,
            CONF_QUIET_START: "22:00:00",
            "quiet_hours_end": "08:00:00",
            CONF_REMINDER_MODE: "none",
            CONF_REMINDER_TIME: "08:00:00",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == []
    assert entry.options[CONF_NORMAL_PRIORITY_TARGETS] == []


async def test_thresholds_still_work_through_menu(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    assert result["step_id"] == "battery"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"low_threshold": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.low_threshold == 30.0
