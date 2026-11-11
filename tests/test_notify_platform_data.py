# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notify_platform_data.py, Version: 0.28.12 (2026-11-11)

"""A push and the brief reach notify
platforms that validate their `data` strictly.

Home Assistant's Signal Messenger and Slack notify platforms check the
`data` of every call against a closed schema and refuse a call carrying
a key they do not know. Device Sentinel puts {"tag": ...} on every push
(and the Android/Apple silence keys on a recovery), and {"html": ...}
on every brief to a notify action, so on a real house each push and
each brief to Signal or Slack is refused and only logged.

The two schemas below are copied from Home Assistant 2026.10.4
(components/signal_messenger/notify.py DATA_SCHEMA and
components/slack/notify.py DATA_SCHEMA), because their modules need
libraries the test environment does not install. Each service here
does what the real platform does: validate `data`, raise on refusal.

Correct behaviour: a target receives the push and the brief.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall

from tests.helpers import setup_coordinator

# signal_messenger/notify.py
_TEXTMODE = vol.Optional("text_mode", default="normal")
SIGNAL_DATA_SCHEMA = vol.Any(
    None,
    vol.Schema({_TEXTMODE: vol.In(["normal", "styled"])}),
    vol.Schema({vol.Required("attachments"): [str], _TEXTMODE: vol.In(["normal", "styled"])}),
    vol.Schema({vol.Required("urls"): [str], vol.Optional("verify_ssl", default=True): bool,
                _TEXTMODE: vol.In(["normal", "styled"])}),
)
# slack/notify.py (text-only branch; the file branch needs "file")
SLACK_DATA_SCHEMA = vol.All(
    vol.Schema({
        vol.Optional("username"): str,
        vol.Optional("icon"): str,
        vol.Optional("blocks"): list,
        vol.Optional("blocks_template"): list,
        vol.Optional("thread_ts"): str,
    }),
)


def _register(hass: HomeAssistant, name: str, schema, got: list) -> None:
    async def handler(call: ServiceCall) -> None:
        data = call.data.get("data")
        if name.startswith("slack"):
            data = data or {}
        schema(data)  # raises vol.Invalid as the real platform does
        got.append(name)

    hass.services.async_register("notify", name, handler)


async def test_push_reaches_signal_and_slack(hass: HomeAssistant) -> None:
    got: list[str] = []
    _register(hass, "signal_home", SIGNAL_DATA_SCHEMA, got)
    _register(hass, "slack_house", SLACK_DATA_SCHEMA, got)
    coord = await setup_coordinator(
        hass,
        {"high_priority_targets": ["notify.signal_home", "notify.slack_house"]},
    )
    await coord._push_family_event("battery", "At 8:00 am, Door battery is low.", False)
    await coord._push_family_event("battery", "At 9:00 am, Door battery is no longer low.", True)
    await hass.async_block_till_done()
    assert got.count("signal_home") == 2, got
    assert got.count("slack_house") == 2, got


async def test_brief_reaches_slack(hass: HomeAssistant) -> None:
    got: list[str] = []
    _register(hass, "slack_house", SLACK_DATA_SCHEMA, got)
    coord = await setup_coordinator(
        hass,
        {
            "brief_document_targets": ["notify.slack_house"],
            "daily_reminder_mode": "daily",
        },
    )
    sent = await coord.async_send_brief("# Device Sentinel Daily Brief\n\nAll clear.")
    await hass.async_block_till_done()
    assert sent == 1
    assert got == ["slack_house"]
