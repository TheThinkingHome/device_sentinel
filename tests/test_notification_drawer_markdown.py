# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notification_drawer_markdown.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: Markdown injection through a device's name into the
Home Assistant notification drawer and repair cards.

A device's name is set by the device or its cloud account (ESPHome,
BLE, a shared cloud). Home Assistant renders a persistent notification
and a repair card's placeholders as Markdown, so a name such as
"![p](https://evil.example/p.png)" loads an outside picture (a beacon
that reveals the viewer's address) and "[Sign in again](https://...)"
draws a phishing link inside Home Assistant's own UI.

Every test asserts the SAFE behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_QUIET_ENABLED,
    DOMAIN,
)
from custom_components.device_sentinel.messenger import _UNESCAPED_BRACKET
from custom_components.device_sentinel.notifier import _card_text
from custom_components.device_sentinel.problem_list import ProblemListMixin

from tests.helpers import setup_entry

IMAGE = "![p](https://evil.example/p.png)"
LINK = "[Sign in again](https://evil.example/login)"
HTML = '<img src="https://evil.example/q.png">'

# A "[" or "<" not preceded by an odd number of backslashes draws in
# Markdown; "](" right after one is the link's or picture's target.
_LIVE_BRACKET = re.compile(r"(?<!\\)(?:\\\\)*[\[<]")


def _drawn(text: str) -> bool:
    """True when the text would draw a link, a picture or a tag as Markdown."""
    return bool(_LIVE_BRACKET.search(text)) and "](" in text or bool(
        re.search(r"(?<!\\)(?:\\\\)*<img", text)
    )


def _notifications(hass: HomeAssistant) -> list[dict]:
    from homeassistant.components.persistent_notification import (
        _async_get_or_create_notifications,
    )

    return list(_async_get_or_create_notifications(hass).values())


async def _notifications_screen(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )


async def test_notify_persistent_notification_is_refused_as_a_push_target(
    hass: HomeAssistant,
):
    """The refusal of the persistent notification as a push target
    checks only the bare word "persistent_notification". The notify
    integration's own notify.persistent_notification action is the same
    drawer, renders the raw push (device names included) as Markdown,
    and is not refused. Safe: refused like the bare word."""
    from homeassistant.data_entry_flow import FlowResultType

    from tests.test_priority_targets import _screen

    assert await async_setup_component(hass, "notify", {})
    for high, normal in (
        (["notify.persistent_notification"], []),
        ([], ["persistent_notification.create"]),
    ):
        entry = await setup_entry(hass)
        result = await _notifications_screen(hass, entry)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _screen(high, normal)
        )
        assert result["type"] is FlowResultType.FORM, (high, normal)
        assert result.get("errors"), (high, normal)


async def test_notify_persistent_notification_is_not_offered_for_pushes(
    hass: HomeAssistant,
):
    """The picker for High and Normal targets offers every notify action,
    notify.persistent_notification among them. Safe: not offered."""
    from tests.test_priority_targets import _choices

    assert await async_setup_component(hass, "notify", {})
    entry = await setup_entry(hass)
    result = await _notifications_screen(hass, entry)
    for field in (CONF_HIGH_PRIORITY_TARGETS, CONF_NORMAL_PRIORITY_TARGETS):
        assert "notify.persistent_notification" not in _choices(result, field)


async def test_a_hostile_name_pushed_to_the_drawer_draws_nothing(
    hass: HomeAssistant,
):
    """A push to notify.persistent_notification carries the event line
    with the device's raw name. Safe: the drawer shows the name as text,
    never as a picture, a link or a tag."""
    assert await async_setup_component(hass, "notify", {})
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.persistent_notification"],
            CONF_QUIET_ENABLED: False,
        },
    )
    coord = entry.runtime_data
    for name in (IMAGE, LINK, HTML):
        line = ProblemListMixin._event_line(
            "unavailable", name, "3:04 pm", False, None, None
        )
        await coord._push_family_event("freeze", line, False)
        await hass.async_block_till_done()
    shown = [n["message"] for n in _notifications(hass)]
    assert shown, "the push reached the drawer"
    for message in shown:
        assert not _drawn(message), message


async def test_a_shared_address_card_draws_nothing_from_its_address(
    hass: HomeAssistant,
):
    """The shared-address repair card escapes each device name but
    prints the address as the router's tracker reported it. Safe: the
    card's placeholder draws nothing whatever the address holds."""
    from custom_components.device_sentinel.repairs import (
        async_evaluate_shared_addresses,
    )

    entry = await setup_entry(hass)
    async_evaluate_shared_addresses(
        hass, entry, {IMAGE: ["Plug A", "Plug B"]}
    )
    issues = [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_placeholders
    ]
    assert issues
    for issue in issues:
        for value in issue.translation_placeholders.values():
            assert not _drawn(value), value


async def test_a_shared_address_card_escapes_hostile_names(hass: HomeAssistant):
    """The names on the same card (expected to hold)."""
    from custom_components.device_sentinel.repairs import (
        async_evaluate_shared_addresses,
    )

    entry = await setup_entry(hass)
    async_evaluate_shared_addresses(
        hass, entry, {"192.168.1.20": [IMAGE, LINK + "\\" , HTML]}
    )
    for (domain, _), issue in ir.async_get(hass).issues.items():
        if domain != DOMAIN or not issue.translation_placeholders:
            continue
        for value in issue.translation_placeholders.values():
            assert not _drawn(value), value


def test_card_text_escapes_every_hostile_name():
    """The state card's escape (expected to hold), backslash games included."""
    for name in (
        IMAGE, LINK, HTML, "\\" + IMAGE, "\\\\" + LINK, "a\n# Heading\n" + IMAGE,
        "a " + IMAGE, "`code` **bold** ~~x~~ " + LINK,
    ):
        out = _card_text(name)
        assert "\n" not in out
        assert not _drawn(out), (name, out)


def test_the_brief_to_the_drawer_escapes_every_bracket():
    """messenger's bracket escape on a brief carrying hostile names in
    sentences (expected to hold)."""
    for name in (IMAGE, LINK, HTML, "\\" + IMAGE, "\\\\" + IMAGE, "\\\\\\" + LINK):
        text = f"# Brief\n\nAt 3 pm, {name} stopped reporting.\n"
        out = _UNESCAPED_BRACKET.sub(r"\1\\\2", text)
        assert not _drawn(out), (name, out)
