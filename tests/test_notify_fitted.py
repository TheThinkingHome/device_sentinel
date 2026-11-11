# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notify_fitted.py, Version: 0.28.12 (2026-11-11)

"""Each message as its notify action can take it (rule NOTE-02).

- The Companion app gets its data (a tag, a silent flag), never the
  brief's page, which a phone cannot show and its push relay would not
  carry.
- A group of phones only is a phone, and a group of Telegram chats only
  is Telegram. Any other notify group gets no data: it passes data to
  each member and keeps a member's refusal to itself, so a Signal or
  Slack member would get nothing and nobody would know.
- Telegram is told the message is plain text, since its Markdown refuses
  a message whose underscores do not pair, and gets no more than it takes.
- Any other action gets the message as it is, and is asked again without
  data if it refuses it.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.notifier import TELEGRAM_LONGEST, fitted_for, notify_platform


def _services(hass: HomeAssistant) -> None:
    hass.data["notify_services"] = {
        "mobile_app": [SimpleNamespace(_service_name="mobile_app", registered_targets={"mobile_app_pixel": "x"})],
        "group": [SimpleNamespace(_service_name="family", registered_targets={})],
        "telegram": [SimpleNamespace(_service_name="telegram_home", registered_targets={})],
        "signal_messenger": [SimpleNamespace(_service_name="signal_home", registered_targets={})],
    }


PUSH = {"title": "t", "message": "Kitchen_Motion stopped", "data": {"tag": "x", "channel": "Device Sentinel"}}
BRIEF = {"title": "t", "message": "brief", "data": {"html": "<html>" + "x" * 9000 + "</html>"}}


async def test_the_platform_behind_each_action_is_found(hass: HomeAssistant):
    _services(hass)
    assert notify_platform(hass, "notify.mobile_app_pixel") == "mobile_app"
    assert notify_platform(hass, "notify.family") == "group"
    assert notify_platform(hass, "notify.telegram_home") == "telegram"
    assert notify_platform(hass, "notify.unknown_thing") is None


async def test_the_phone_keeps_its_data_but_never_the_page(hass: HomeAssistant):
    _services(hass)
    assert fitted_for(hass, "notify.mobile_app_pixel", PUSH) == PUSH
    assert "data" not in fitted_for(hass, "notify.mobile_app_pixel", BRIEF)


async def test_a_group_gets_no_data(hass: HomeAssistant):
    _services(hass)
    assert "data" not in fitted_for(hass, "notify.family", PUSH)
    assert "data" not in fitted_for(hass, "notify.family", BRIEF)


async def test_telegram_gets_plain_text_no_longer_than_it_takes(hass: HomeAssistant):
    _services(hass)
    push = fitted_for(hass, "notify.telegram_home", PUSH)
    assert push["data"] == {"parse_mode": "plain_text"}
    long = fitted_for(hass, "notify.telegram_home", {**BRIEF, "message": "y" * 9000})
    assert long["data"] == {"parse_mode": "plain_text"}
    assert len(long["message"]) <= TELEGRAM_LONGEST


async def test_any_other_action_gets_it_as_it_is(hass: HomeAssistant):
    _services(hass)
    assert fitted_for(hass, "notify.signal_home", PUSH) == PUSH


def _groups(hass: HomeAssistant) -> None:
    _services(hass)
    hass.data["notify_services"]["group"] = [
        SimpleNamespace(_service_name="phones", registered_targets={},
                        entities=[{"action": "mobile_app_pixel"}, {"action": "mobile_app_iphone"}]),
        SimpleNamespace(_service_name="chats", registered_targets={},
                        entities=[{"action": "telegram_home"}]),
        SimpleNamespace(_service_name="mixed", registered_targets={},
                        entities=[{"action": "mobile_app_pixel"}, {"action": "signal_home"}]),
        SimpleNamespace(_service_name="everyone", registered_targets={},
                        entities=[{"action": "phones"}, {"action": "mobile_app_tablet"}]),
    ]


async def test_a_group_of_phones_is_a_phone(hass: HomeAssistant):
    """A group of phones only keeps the tag and the silent flag, so its
    pushes replace each other and a recovery stays quiet."""
    _groups(hass)
    assert notify_platform(hass, "notify.phones") == "mobile_app"
    assert notify_platform(hass, "notify.everyone") == "mobile_app"
    assert fitted_for(hass, "notify.phones", PUSH) == PUSH
    assert "data" not in fitted_for(hass, "notify.phones", BRIEF)


async def test_a_group_of_telegram_chats_is_telegram(hass: HomeAssistant):
    _groups(hass)
    assert fitted_for(hass, "notify.chats", PUSH)["data"] == {"parse_mode": "plain_text"}


async def test_a_mixed_group_gets_no_data(hass: HomeAssistant):
    _groups(hass)
    assert notify_platform(hass, "notify.mixed") == "group"
    assert "data" not in fitted_for(hass, "notify.mixed", PUSH)


async def test_a_silent_recovery_is_silent_on_telegram(hass: HomeAssistant):
    """Rule NOTE-04: a recovery plays no sound; Telegram is told so."""
    _services(hass)
    silent = {"title": "t", "message": "back", "data": {"tag": "x", "channel": "Device Sentinel", "importance": "low"}}
    assert fitted_for(hass, "notify.telegram_home", silent)["data"] == {
        "parse_mode": "plain_text", "disable_notification": True,
    }
    assert "disable_notification" not in fitted_for(hass, "notify.telegram_home", PUSH)["data"]
