# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_targets.py, Version: 0.28.9 (2026-11-10)

"""Send the Full Brief To takes a service, never an email address
(rule BRIEF-11).

The field allows a typed value, because an old notify action can be
typed by name. An email address typed there was saved, and each morning
the brief was handed to an action named after the address, which does
not exist, so it was never sent. A value holding "@" is refused on
Submit: the screen stays open with what was entered, the Daily Brief
section opens on the refusal, and nothing is saved. An SMTP recipient
and a notify action are kept. An install that already holds a typed
address opens the screen and saves once the address is removed.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    CONF_REPORT_LINKS,
    REPORT_LINKS_NONE,
)
from custom_components.device_sentinel.repairs import missing_targets

from tests.helpers import setup_entry

ADDRESS = "someone@example.com"
TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "device_sentinel"


def _recipient(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_or_create(
        "notify", "smtp", "admin", suggested_object_id="house_admin",
        original_name="House (Admin)",
    ).entity_id


async def _open(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )


def _submit(brief_targets: list[str], quiet_start: str = "22:00:00") -> dict:
    return {
        "instant": {
            CONF_HIGH_PRIORITY_TARGETS: [],
            CONF_NORMAL_PRIORITY_TARGETS: [],
            CONF_PERSISTENT_ENABLED: True,
        },
        "quiet": {
            CONF_QUIET_ENABLED: True,
            CONF_QUIET_START: quiet_start,
            CONF_QUIET_END: "07:00:00",
        },
        "brief": {
            CONF_REMINDER_MODE: "daily",
            CONF_REMINDER_TIME: "07:00:00",
            CONF_BRIEF_TARGETS: brief_targets,
            CONF_REPORT_LINKS: REPORT_LINKS_NONE,
        },
    }


def _default(result, section_name: str, key: str):
    """The value a field shows, read from the form's schema."""
    for marker, value in result["data_schema"].schema.items():
        if str(marker) == section_name:
            for inner, _ in value.schema.schema.items():
                if str(inner) == key:
                    return inner.default()
    raise KeyError(key)


def _section_collapsed(result, section_name: str) -> bool:
    for marker, value in result["data_schema"].schema.items():
        if str(marker) == section_name:
            return value.options["collapsed"]
    raise KeyError(section_name)


async def test_a_typed_address_is_refused(hass: HomeAssistant):
    entry = await setup_entry(hass)
    result = await _open(hass, entry)
    assert _section_collapsed(result, "brief") is True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit([ADDRESS], quiet_start="23:00:00")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"brief": "brief_target_is_address"}
    assert CONF_BRIEF_TARGETS not in entry.options or ADDRESS not in entry.options[CONF_BRIEF_TARGETS]
    # The screen keeps what was entered, and opens the brief's section.
    assert _default(result, "brief", CONF_BRIEF_TARGETS) == [ADDRESS]
    assert _default(result, "quiet", CONF_QUIET_START) == "23:00:00"
    assert _section_collapsed(result, "brief") is False


async def test_a_recipient_and_a_notify_action_are_kept(hass: HomeAssistant):
    recipient = f"smtp:{_recipient(hass)}"
    entry = await setup_entry(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit([recipient, "notify.mobile_app_phone"])
    )
    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_BRIEF_TARGETS] == [recipient, "notify.mobile_app_phone"]


async def test_an_address_already_saved_can_be_removed(hass: HomeAssistant):
    """An install may already hold a typed address. Its screen
    opens showing it, refuses it while it stays, and saves once it is
    removed."""
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [ADDRESS]})
    result = await _open(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert _default(result, "brief", CONF_BRIEF_TARGETS) == [ADDRESS]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit([ADDRESS])
    )
    assert result["errors"] == {"brief": "brief_target_is_address"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit([])
    )
    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_BRIEF_TARGETS] == []


async def test_the_repairs_card_reports_a_typed_address(hass: HomeAssistant):
    """A typed address is not a service, so the card that lists missing
    targets lists it, in words that fit a value that never was one."""
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [ADDRESS]})
    assert missing_targets(hass, entry) == [ADDRESS]
    text = json.loads((TRANSLATIONS / "translations" / "en.json").read_text(encoding="utf-8"))
    card = text["issues"]["notify_target_missing"]["fix_flow"]["step"]["init"]["description"]
    assert "does not have" in card and "an email address was typed" in card
    assert "no longer has" not in card


def test_the_help_and_the_error_say_it_in_both_files():
    for name in ("strings.json", "translations/en.json"):
        text = json.loads((TRANSLATIONS / name).read_text(encoding="utf-8"))
        help_line = text["options"]["step"]["notifications"]["sections"]["brief"]["data_description"][CONF_BRIEF_TARGETS]
        assert help_line.startswith("The email or other services that will be used to send the Daily Brief.")
        assert "(https://github.com/TheThinkingHome/device_sentinel/wiki/Sending-the-Daily-Brief-by-Email)" in help_line
        assert "brief_target_is_address" in text["options"]["error"]
