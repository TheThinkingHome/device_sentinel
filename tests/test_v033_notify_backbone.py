"""0.3.3 tests: the notification backbone (config surface only)."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import (
    _discover_notify_targets,
)
from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_PIERCES_QUIET,
    CONF_NOTIFY_TARGETS,
    CONF_QUIET_START,
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
    assert set(result["menu_options"]) == {"thresholds", "notifications"}


async def test_notifications_step_round_trip(hass: HomeAssistant):
    hass.services._services.setdefault("notify", {})
    hass.services._services["notify"]["mobile_app_s24"] = object()
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "notifications"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NOTIFY_TARGETS: ["notify.mobile_app_s24"],
            CONF_QUIET_START: "23:00:00",
            "quiet_end": "06:30:00",
            CONF_REMINDER_TIME: "08:15:00",
            CONF_HIGH_PRIORITY_PIERCES_QUIET: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == ["notify.mobile_app_s24"]
    assert entry.options[CONF_QUIET_START] == "23:00:00"
    assert entry.options[CONF_HIGH_PRIORITY_PIERCES_QUIET] is True


async def test_thresholds_still_work_through_menu(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "thresholds"}
    )
    assert result["step_id"] == "thresholds"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"low_threshold": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.low_threshold == 30.0
