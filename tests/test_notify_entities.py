# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notify_entities.py, Version: 0.29.7 (2026-11-18)

"""Notify entities as targets (rule NOTE-02).

Home Assistant moves notify targets to entities. A Telegram chat under
the Telegram bot integration is a notify entity with no old-style
action, so it was offered nowhere. It is now offered for alerts and the
brief, stored as "entity:notify.<entity>", and sent through Telegram's
own action as plain text, silent for a recovery. Any other notify
entity, such as ntfy or Discord, goes through notify.send_message.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.config_flow import _notify_entities
from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_REMINDER_MODE,
    REMINDER_MODE_DAILY,
)
from custom_components.device_sentinel.notifier import TELEGRAM_LONGEST, notify_platform
from custom_components.device_sentinel.repairs import missing_targets

from .helpers import setup_entry

TEXT = "# Device Sentinel Daily Brief\n\nNothing needs attention.\n"


def _entity(hass: HomeAssistant, platform: str, key: str, object_id: str, name: str | None = None, **kw) -> str:
    return er.async_get(hass).async_get_or_create(
        "notify", platform, key, suggested_object_id=object_id, original_name=name, **kw,
    ).entity_id


async def test_a_telegram_chat_is_offered(hass: HomeAssistant):
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum", None)
    hass.states.async_set(chat, "unknown", {"friendly_name": "ottpossum"})
    options = _notify_entities(hass)
    assert [o["value"] for o in options] == [f"entity:{chat}"]
    assert options[0]["label"] == "Telegram: ottpossum (notify.ottpossum)"


async def test_what_is_not_offered_again(hass: HomeAssistant):
    """SMTP has its own list, the Companion app its own action, an
    entity whose old-style action exists is that action, and a disabled
    entity reaches nobody."""
    _entity(hass, "smtp", "admin", "mail_admin", "Admin")
    _entity(hass, "mobile_app", "pixel", "pixel_9", "Pixel 9")
    _entity(hass, "ntfy", "both", "alerts", "Alerts")
    async_mock_service(hass, "notify", "alerts")
    _entity(hass, "ntfy", "off", "quiet", "Quiet", disabled_by=er.RegistryEntryDisabler.USER)
    topic = _entity(hass, "ntfy", "topic", "house_topic", "House")
    assert [o["value"] for o in _notify_entities(hass)] == [f"entity:{topic}"]


async def test_a_push_reaches_a_telegram_chat_as_plain_text(hass: HomeAssistant):
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum")
    sent = async_mock_service(hass, "telegram_bot", "send_message")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [f"entity:{chat}"]})
    coord = entry.runtime_data
    assert notify_platform(hass, f"entity:{chat}") == "telegram"
    await coord._push_family_event("freeze", "At 1:01 pm, door_hall froze.", False)
    await coord._push_family_event("freeze", "At 1:09 pm, door_hall is back.", True)
    await hass.async_block_till_done()
    assert len(sent) == 2
    first, back = sent[0].data, sent[1].data
    assert first["entity_id"] == [chat] or first["entity_id"] == chat
    assert first["parse_mode"] == "plain_text"
    assert "door_hall" in first["message"] and first.get("title")
    assert "disable_notification" not in first
    assert back["disable_notification"] is True, "a recovery is silent"


async def test_a_push_reaches_any_other_notify_entity(hass: HomeAssistant):
    topic = _entity(hass, "ntfy", "topic", "house_topic", "House")
    sent = async_mock_service(hass, "notify", "send_message")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [f"entity:{topic}"]})
    await entry.runtime_data._push_family_event("freeze", "At 1:01 pm, a test.", False)
    await hass.async_block_till_done()
    assert len(sent) == 1
    data = sent[0].data
    assert data["entity_id"] == [topic] or data["entity_id"] == topic
    assert set(data) - {"entity_id"} <= {"message", "title"}, "notify.send_message takes no data"


async def test_one_bad_target_never_stops_the_rest(hass: HomeAssistant):
    gone = "entity:notify.removed_chat"
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [gone, "notify.phone"]})
    await entry.runtime_data._push_family_event("freeze", "At 1:01 pm, a test.", False)
    await hass.async_block_till_done()
    assert len(phone) == 1


async def test_the_brief_reaches_a_telegram_chat_cut_to_its_length(hass: HomeAssistant):
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum")
    sent = async_mock_service(hass, "telegram_bot", "send_message")
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [f"entity:{chat}"], CONF_REMINDER_MODE: REMINDER_MODE_DAILY})
    long_text = TEXT + ("A device line, with_underscores_here.\n" * 400)
    assert await entry.runtime_data.async_send_brief(long_text) == 1
    data = sent[0].data
    assert data["parse_mode"] == "plain_text"
    assert len(data["message"]) <= TELEGRAM_LONGEST
    assert "html" not in data


async def test_the_restore_notice_reaches_a_notify_entity(hass: HomeAssistant):
    topic = _entity(hass, "ntfy", "topic", "house_topic", "House")
    sent = async_mock_service(hass, "notify", "send_message")
    entry = await setup_entry(hass, {CONF_BRIEF_TARGETS: [f"entity:{topic}"]})
    assert await entry.runtime_data.async_announce_restore("Restored", "Details") == 1
    assert sent[0].data["title"]


async def test_an_entity_target_is_missing_only_when_it_cannot_be_sent_to(hass: HomeAssistant):
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [f"entity:{chat}"]})
    assert missing_targets(hass, entry) == [f"entity:{chat}"], "telegram_bot.send_message does not exist yet"
    async_mock_service(hass, "telegram_bot", "send_message")
    assert missing_targets(hass, entry) == []
    er.async_get(hass).async_update_entity(chat, disabled_by=er.RegistryEntryDisabler.USER)
    assert missing_targets(hass, entry) == [f"entity:{chat}"]
    er.async_get(hass).async_remove(chat)
    assert missing_targets(hass, entry) == [f"entity:{chat}"]


async def test_the_settings_screen_offers_and_keeps_an_entity_target(hass: HomeAssistant):
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [f"entity:{chat}", "entity:notify.old_chat"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if result.get("step_id") != "notifications":
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "notifications"})
    assert result["step_id"] == "notifications"

    def values(node, seen=None):
        """Every option value a selector on the screen offers."""
        found = []
        config = getattr(node, "config", None)
        if isinstance(config, dict) and isinstance(config.get("options"), list):
            for option in config["options"]:
                found.append(option["value"] if isinstance(option, dict) else option)
        inner = getattr(node, "schema", None)
        if isinstance(inner, dict):
            for value in inner.values():
                found += values(value)
        elif inner is not None and inner is not node:
            found += values(inner)
        return found

    text = repr(values(result["data_schema"]))
    assert f"entity:{chat}" in text, "offered on the notifications screen"
    assert "entity:notify.old_chat" in text, "a saved one whose entity has gone keeps its place"


async def test_a_chat_typed_as_an_action_name_is_its_entity(hass: HomeAssistant):
    """Typed into the list before it was offered, "notify.ottpossum"
    names no action: it is the chat's entity, sent to and never missing."""
    chat = _entity(hass, "telegram_bot", "123_456", "ottpossum")
    sent = async_mock_service(hass, "telegram_bot", "send_message")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: [chat],
                                     CONF_BRIEF_TARGETS: [chat], CONF_REMINDER_MODE: REMINDER_MODE_DAILY})
    assert missing_targets(hass, entry) == []
    await entry.runtime_data._push_family_event("freeze", "At 1:01 pm, a test.", False)
    assert await entry.runtime_data.async_send_brief(TEXT) == 1
    await hass.async_block_till_done()
    assert len(sent) == 2 and all(c.data["parse_mode"] == "plain_text" for c in sent)


async def test_an_action_of_the_same_name_is_still_the_action(hass: HomeAssistant):
    _entity(hass, "ntfy", "both", "alerts", "Alerts")
    action = async_mock_service(hass, "notify", "alerts")
    entity = async_mock_service(hass, "notify", "send_message")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.alerts"]})
    await entry.runtime_data._push_family_event("freeze", "At 1:01 pm, a test.", False)
    await hass.async_block_till_done()
    assert len(action) == 1 and entity == []
