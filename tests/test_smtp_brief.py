# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_smtp_brief.py, Version: 0.23.0 (2026-09-24)

"""The daily brief by email through smtp.send_message.

Home Assistant retires the old-style notify action per SMTP recipient
in 2027.3 and raises a Repairs card for each use until then. Since
2026.8 each recipient is a notify entity, and smtp.send_message is the
action that still carries an HTML body; notify.send_message refuses
one. The owner ruled on 24 September: offer SMTP recipients beside the
old actions, send to them through smtp.send_message, and leave a
chosen old action working as it did until Home Assistant removes it.
The tests that are not guards fail on 0.22.28.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.config_flow import (
    _discover_notify_targets,
    _smtp_recipients,
)
from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    REMINDER_MODE_DAILY,
)
from custom_components.device_sentinel.repairs import missing_targets

from .helpers import setup_entry

TEXT = "# Device Sentinel Daily Brief\n\nNothing needs attention.\n"


def _recipient(hass: HomeAssistant, key: str = "admin") -> str:
    entry = er.async_get(hass).async_get_or_create(
        "notify", "smtp", key, suggested_object_id=f"the_panorama_{key}",
        original_name="The Panorama (Admin)",
    )
    return entry.entity_id


async def test_the_picker_offers_smtp_recipients(hass: HomeAssistant):
    entity_id = _recipient(hass)
    options = _smtp_recipients(hass)
    assert [option["value"] for option in options] == [f"smtp:{entity_id}"]
    assert "The Panorama (Admin)" in options[0]["label"]


async def test_the_picker_no_longer_offers_send_message(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    async_mock_service(hass, "notify", "the_panorama_admin")
    targets = _discover_notify_targets(hass)
    assert "notify.send_message" not in targets
    assert "notify.the_panorama_admin" in targets


async def test_the_brief_goes_through_smtp_send_message(hass: HomeAssistant):
    entity_id = _recipient(hass)
    sent = async_mock_service(hass, "smtp", "send_message")
    entry = await setup_entry(hass, {
        CONF_BRIEF_TARGETS: [f"smtp:{entity_id}"],
        CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
    })
    assert await entry.runtime_data.async_send_brief(TEXT) == 1
    assert len(sent) == 1
    data = sent[0].data
    assert entity_id in (data["entity_id"] if isinstance(data["entity_id"], list) else [data["entity_id"]])
    assert data["message"] == TEXT
    assert data["html"].lstrip().lower().startswith("<!doctype html")


async def test_an_old_action_is_sent_as_before(hass: HomeAssistant):
    """Guard: a chosen old-style action keeps working, HTML and all."""
    old = async_mock_service(hass, "notify", "the_panorama_admin")
    entry = await setup_entry(hass, {
        CONF_BRIEF_TARGETS: ["notify.the_panorama_admin"],
        CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
    })
    assert await entry.runtime_data.async_send_brief(TEXT) == 1
    assert old[0].data["message"] == TEXT
    assert "html" in old[0].data["data"]


async def test_a_recipient_is_missing_only_when_it_is_gone(hass: HomeAssistant):
    entity_id = _recipient(hass)
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [f"smtp:{entity_id}"]})
    assert missing_targets(hass, entry) == [f"smtp:{entity_id}"], (
        "smtp.send_message does not exist yet"
    )
    async_mock_service(hass, "smtp", "send_message")
    assert missing_targets(hass, entry) == []
    er.async_get(hass).async_remove(entity_id)
    assert missing_targets(hass, entry) == [f"smtp:{entity_id}"]


async def test_the_restore_notice_reaches_a_recipient(hass: HomeAssistant):
    entity_id = _recipient(hass)
    sent = async_mock_service(hass, "smtp", "send_message")
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [f"smtp:{entity_id}"]})
    assert await entry.runtime_data.async_announce_restore("Restored", "Details") == 1
    assert sent[0].data["title"]
