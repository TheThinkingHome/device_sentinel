# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_hostile_inputs.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: hostile inputs to every WebSocket command, as an admin.

An admin's browser can be driven by a page they visit, or a token can
leak. Safe: every hostile message gets an answer (success or a named
refusal, never Home Assistant's catch-all unknown_error), the
coordinator keeps answering afterwards, nothing is written outside the
config folder, and another integration's device is not renamed.
"""

from __future__ import annotations

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from tests.helpers import register_device, setup_entry

HUGE = "A" * 200_000
TRAVERSAL = "../../../../tmp/device_sentinel_exploit"
UNICODE = "‮퟿﻿\u0000Zalgo̶̶̶ \U0001f4a9"

HOSTILE_IDS = [HUGE, TRAVERSAL, UNICODE, "", "00000000000000000000000000000000", "%2e%2e%2f"]
HOSTILE_DAYS = [HUGE, TRAVERSAL, "9999-99-99", "-0001-01-01", "2026-02-30", "", "2026-11-01T00:00:00"]


def _messages(device_id: str, foreign_id: str) -> list[dict]:
    out: list[dict] = []
    for bad in HOSTILE_IDS + [foreign_id]:
        out += [
            {"type": "device_sentinel/device", "device_id": bad},
            {"type": "device_sentinel/use_trimmed_maximum", "device_id": bad},
            {"type": "device_sentinel/device_day", "device_id": bad, "day": "2026-11-01", "removed": True},
            {"type": "device_sentinel/device_power", "device_id": bad, "choice": HUGE, "quantity": -5, "other": UNICODE},
            {"type": "device_sentinel/device_type", "device_id": bad, "choice": TRAVERSAL, "other": HUGE},
            {"type": "device_sentinel/device_area", "device_id": bad, "area_id": TRAVERSAL},
            {"type": "device_sentinel/device_label", "device_id": bad, "label_id": HUGE, "add": True},
            {"type": "device_sentinel/device_battery", "device_id": bad, "action": "date", "day": TRAVERSAL},
            {"type": "device_sentinel/device_turn_on", "device_id": bad, "kind": "battery"},
            {"type": "device_sentinel/device_mute", "device_id": bad, "kind": "everything", "on": True},
            {"type": "device_sentinel/device_exclude", "device_id": bad, "on": True},
            {"type": "device_sentinel/recommendation_ack", "on": True, "kind": HUGE, "device_id": bad},
            {"type": "device_sentinel/acknowledge", "uid": bad, "acknowledged": True},
        ]
    for day in HOSTILE_DAYS:
        out += [
            {"type": "device_sentinel/device_day", "device_id": device_id, "day": day, "removed": True},
            {"type": "device_sentinel/device_battery", "device_id": device_id, "action": "date", "day": day},
        ]
    for domain in (HUGE, TRAVERSAL, UNICODE, "", "device_sentinel", "homeassistant"):
        out += [
            {"type": "device_sentinel/integration", "domain": domain},
            {"type": "device_sentinel/integration_mute", "domain": domain, "kind": "freeze", "on": True},
            {"type": "device_sentinel/integration_mute", "domain": domain, "kind": "freeze", "on": False},
        ]
    for key in (HUGE[:80], TRAVERSAL, UNICODE, ""):
        out += [
            {"type": "device_sentinel/network", "key": key},
            {"type": "device_sentinel/network_expected", "key": key, "minute": 1439, "on": True},
        ]
    out += [
        {"type": "device_sentinel/action", "action": "maintenance", "minutes": -1},
        {"type": "device_sentinel/network_expected", "key": "mqtt", "minute": -1, "on": True},
        {"type": "device_sentinel/recommendation_ack", "on": True, "line": HUGE},
        {"type": "device_sentinel/recommendation_ack", "on": True, "line": "x", "kind": "y"},
        {"type": "device_sentinel/device_new_area", "device_id": device_id, "name": ""},
        {"type": "device_sentinel/device_new_label", "device_id": device_id, "name": UNICODE},
        {"type": "device_sentinel/device_rename", "device_id": device_id, "name": {"$ne": 1}},
        {"type": "device_sentinel/device_power", "device_id": device_id, "choice": None, "quantity": 2**62},
        {"type": "device_sentinel/device_type", "device_id": device_id, "choice": ["nested", ["deep"]]},
    ]
    return out


async def test_hostile_inputs_never_reach_an_unhandled_error(
    hass: HomeAssistant, hass_ws_client
):
    device, _ = register_device(hass, "ws_target", name="Kitchen Plug")
    foreign, _ = register_device(hass, "ws_foreign", name="Someone Else's Device")
    entry = await setup_entry(hass)
    client = await hass_ws_client(hass)
    unknown = []
    for index, message in enumerate(_messages(device.id, foreign.id), start=1):
        await client.send_json({**message, "id": index})
        reply = await client.receive_json()
        while reply.get("type") == "event":
            reply = await client.receive_json()
        if not reply.get("success") and reply["error"]["code"] == "unknown_error":
            unknown.append((message["type"], {k: (v[:40] if isinstance(v, str) else v) for k, v in message.items()}))
    assert unknown == [], unknown[:10]
    # The coordinator still answers.
    await client.send_json({"id": 100_000, "type": "device_sentinel/status"})
    reply = await client.receive_json()
    assert reply["success"], reply
    assert entry.runtime_data is not None
    # Nothing written outside the config folder.
    assert not os.path.exists("/tmp/device_sentinel_exploit")
    # The other integration's device keeps its name.
    assert dr.async_get(hass).async_get(foreign.id).name_by_user is None
