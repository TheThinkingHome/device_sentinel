# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notify_group_of_phones.py, Version: 0.28.12 (2026-11-11)

"""A push to a notify group of Companion-app phones (rule NOTE-02).

Fitting a message once stripped every `data` key for a notify group, so a
Signal or Slack member could not refuse the whole message. The cost
falls on the commonest group there is, "notify.all_phones" with only
mobile_app members: the phones lose the push's tag (so pushes stack
instead of replacing their own last one) and the silent flags (so a
recovery, which rule NOTE-04 sends silently, plays a sound on every
phone, at any hour for a high-priority target).

Home Assistant's group (components/group/notify.py) keeps its members as
GroupNotifyPlatform.entities, [{"action": "mobile_app_x"}, ...], so the
members can be read and a group whose members are all phones fitted as
a phone is.

Correct behaviour: each phone in the group gets the recovery with its
tag and its silent flags, and never the brief's HTML page.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component

from tests.helpers import setup_coordinator


async def test_recovery_to_a_group_of_phones_stays_silent(hass: HomeAssistant) -> None:
    got: list[dict] = []

    async def phone(call: ServiceCall) -> None:
        got.append(dict(call.data))

    hass.services.async_register("notify", "mobile_app_pixel", phone)
    hass.services.async_register("notify", "mobile_app_iphone", phone)
    assert await async_setup_component(
        hass,
        "notify",
        {
            "notify": [
                {
                    "platform": "group",
                    "name": "all_phones",
                    "services": [{"action": "mobile_app_pixel"}, {"action": "mobile_app_iphone"}],
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.services.has_service("notify", "all_phones")

    coord = await setup_coordinator(hass, {"high_priority_targets": ["notify.all_phones"]})
    await coord._push_family_event("battery", "At 3:00 am, Door battery is back.", True)
    await hass.async_block_till_done()

    assert len(got) == 2, got
    for call in got:
        data = call.get("data") or {}
        assert data.get("tag"), call
        # Silent on both phone platforms, as every recovery is (rule NOTE-04).
        assert data.get("importance") == "low", call
        assert (data.get("push") or {}).get("interruption-level") == "passive", call
        assert "html" not in data, call
