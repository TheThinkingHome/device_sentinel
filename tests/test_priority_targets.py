# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_priority_targets.py, Version: 0.28.11 (2026-11-10)

"""Who gets a push, and when (rules NOTE-02, NOTE-07, BRIEF-11).

High-priority targets get every push, Quiet Hours included.
Normal-priority targets get every push except during Quiet Hours. The
Daily Brief goes only to Send the Full Brief To. A typed email address
in either priority list is refused on Submit, as in the brief's, because
each alert to it would be lost.
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


# A typed email address in the instant alert targets (rule NOTE-02).

ADDRESS = "someone@example.com"


async def _notifications_screen(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )


def _screen(high, normal):
    from tests.test_brief_targets import _submit
    form = _submit([])
    form["instant"][CONF_HIGH_PRIORITY_TARGETS] = high
    form["instant"][CONF_NORMAL_PRIORITY_TARGETS] = normal
    return form


async def test_an_address_in_either_priority_list_is_refused(hass: HomeAssistant):
    from homeassistant.data_entry_flow import FlowResultType
    from tests.test_brief_targets import _default

    for high, normal in (([ADDRESS], []), ([], [ADDRESS]), ([ADDRESS], [ADDRESS])):
        entry = await setup_entry(hass)
        result = await _notifications_screen(hass, entry)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _screen(high, normal)
        )
        assert result["type"] is FlowResultType.FORM, (high, normal)
        assert result["errors"] == {"instant": "priority_target_is_address"}
        assert ADDRESS not in (entry.options.get(CONF_HIGH_PRIORITY_TARGETS) or [])
        assert ADDRESS not in (entry.options.get(CONF_NORMAL_PRIORITY_TARGETS) or [])
        # The screen keeps what was entered.
        assert _default(result, "instant", CONF_HIGH_PRIORITY_TARGETS) == high
        assert _default(result, "instant", CONF_NORMAL_PRIORITY_TARGETS) == normal
        await hass.config_entries.async_remove(entry.entry_id)


async def test_a_notify_action_is_kept_and_a_saved_address_can_go(hass: HomeAssistant):
    from homeassistant.data_entry_flow import FlowResultType

    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [ADDRESS]})
    result = await _notifications_screen(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _screen(["notify.mobile_app_phone"], ["notify.mobile_app_tablet"])
    )
    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == ["notify.mobile_app_phone"]
    assert entry.options[CONF_NORMAL_PRIORITY_TARGETS] == ["notify.mobile_app_tablet"]


def test_the_refusal_is_worded_in_both_files():
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent / "custom_components" / "device_sentinel"
    for name in ("strings.json", "translations/en.json"):
        text = json.loads((root / name).read_text(encoding="utf-8"))
        words = text["options"]["error"]["priority_target_is_address"]
        assert "High-Priority Targets" in words and "not an email address" in words


def _choices(result, field):
    """The options a picker on the notifications screen offers."""
    from homeassistant.helpers import selector

    for section in result["data_schema"].schema.values():
        inner = getattr(section, "schema", None)
        schema = getattr(inner, "schema", None) or {}
        for key, value in schema.items():
            if str(key) == field and isinstance(value, selector.SelectSelector):
                return [o if isinstance(o, str) else o["value"] for o in value.config["options"]]
    raise AssertionError(f"no picker {field}")


async def test_the_persistent_notification_is_not_a_push_target(hass: HomeAssistant):
    """A push goes to notify actions; chosen here, the persistent
    notification reached nobody. The card has its own switch (rule
    NOTE-11), and the brief still offers it."""
    from custom_components.device_sentinel.const import CONF_BRIEF_TARGETS, PERSISTENT_TARGET

    entry = await setup_entry(hass)
    result = await _notifications_screen(hass, entry)
    assert PERSISTENT_TARGET not in _choices(result, CONF_HIGH_PRIORITY_TARGETS)
    assert PERSISTENT_TARGET not in _choices(result, CONF_NORMAL_PRIORITY_TARGETS)
    assert PERSISTENT_TARGET in _choices(result, CONF_BRIEF_TARGETS)
    # One already saved keeps its place, so the screen shows it.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_HIGH_PRIORITY_TARGETS: [PERSISTENT_TARGET]}
    )
    result = await _notifications_screen(hass, entry)
    assert PERSISTENT_TARGET in _choices(result, CONF_HIGH_PRIORITY_TARGETS)


async def test_the_persistent_notification_typed_in_is_refused(hass: HomeAssistant):
    """Typed into either list, it is refused on Submit, as an address
    is: it would reach nobody. The card has its own switch."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.device_sentinel.const import PERSISTENT_TARGET

    for high, normal in (([PERSISTENT_TARGET], []), ([], [" Persistent_Notification "])):
        entry = await setup_entry(hass)
        result = await _notifications_screen(hass, entry)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _screen(high, normal)
        )
        assert result["type"] is FlowResultType.FORM, (high, normal)
        assert result["errors"] == {"instant": "priority_target_is_persistent"}
        assert PERSISTENT_TARGET not in (entry.options.get(CONF_HIGH_PRIORITY_TARGETS) or [])
        await hass.config_entries.async_remove(entry.entry_id)
