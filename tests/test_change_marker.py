# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_change_marker.py, Version: 0.28.12 (2026-11-11)

"""The dashboard's change marker across a restart and a reload
(rule DASH-14).

The panel lights "Refresh: new data" only when a marker it is sent is
greater than the marker of the snapshot on screen (panel.js
_paintRefresh). Home Assistant's frontend resubscribes an open tab when
it reconnects after a restart (dashboard_api.ws_subscribe_changes says
so), but the coordinator's marker starts at 0 in every session, so a tab
left open across a restart is sent markers smaller than the one it
shows and never offers the refresh, until the new session has made as
many changes as the old one had. After a reload the tab's subscription
stays on the old coordinator and is sent nothing at all.

Each test asserts the correct behaviour, so a failure is the finding.
"""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import SYS_RESTART
from tests.helpers import setup_entry
from tests.test_history_file import restart_with


async def test_the_marker_after_a_restart_passes_the_one_shown_before(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    for _ in range(25):
        coord._record_system_event(SYS_RESTART)
    shown_before = coord.change_marker
    assert shown_before >= 25

    coord = await restart_with(hass, entry)
    # One change in the new session: an open tab showing the old
    # snapshot must be told there is something newer.
    coord._record_system_event(SYS_RESTART)
    assert coord.change_marker > shown_before


async def test_a_subscription_open_across_a_reload_still_hears_changes(
    hass: HomeAssistant, hass_ws_client
):
    entry = await setup_entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_sentinel/subscribe_changes"})
    reply = await client.receive_json()
    assert reply["success"]
    first = await client.receive_json()
    seen = first["event"]["marker"]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data._record_system_event(SYS_RESTART)
    await hass.async_block_till_done()

    # The tab must either be sent the new session's change or have its
    # subscription ended so it can ask again; silence leaves it stale.
    pushed = await asyncio.wait_for(client.receive_json(), timeout=5)
    if pushed.get("type") == "event":
        assert pushed["event"]["marker"] > seen
