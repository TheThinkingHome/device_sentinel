# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_log.py, Version: 0.21.12 (2026-09-17)

"""The brief's Last 24 Hours table as a tester's log (ruling #444).

The second fleet's tester overwrote several screenshots on 16
September and ran two coordinator pulls again to take them, and asked
for a log of what the problem list did instead. The table already
lists every row opened and cleared with its cause. It now gives each
time to the second, and it records the moment a Wi-Fi outage starts
recovering, which until now was visible only on the row itself.
"""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_RECOVERY_WITHDRAWN,
)
from tests.helpers import setup_coordinator
from tests.test_wifi_outage import _declared, _house, _rise
from tests.test_wifi_recovery import _tick


def _kinds(coord):
    return [row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]]


async def test_the_table_gives_each_time_to_the_second(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert re.fullmatch(
        r"[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2}:\d{2} [AP]M",
        coord._brief_log_moment(1789595146.0),
    )


async def test_the_summary_keeps_its_minutes(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert re.fullmatch(
        r"[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M",
        coord._brief_moment(1789595146.0),
    )


async def test_a_wifi_recovery_is_recorded_when_it_begins(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    # Eight of ten back: enough to announce, not enough to close.
    for tracker in trackers[:8]:
        await _rise(hass, tracker)
    await _tick(coord, first + 120.0)
    assert coord.wifi_recovering_at is not None
    assert _kinds(coord).count(SYS_WIFI_RECOVERING) == 1
    row = [
        r for r in coord.data[DATA_SYSTEM_EVENTS]
        if r[SYS_KIND] == SYS_WIFI_RECOVERING
    ][0]
    assert row[SYS_WHEN] == coord.wifi_recovering_at


async def test_the_scan_route_records_it_too(hass: HomeAssistant, freezer):
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    coord.on_wifi_scan_restored(first, first + 60.0)
    await hass.async_block_till_done()
    assert _kinds(coord).count(SYS_WIFI_RECOVERING) == 1


async def test_the_new_lines_read_as_sentences(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    began = {SYS_WHEN: 1789595520.0, SYS_KIND: SYS_WIFI_RECOVERING,
             SYS_SCOPE: "wifi"}
    stalled = {SYS_WHEN: 1789595580.0,
               SYS_KIND: SYS_WIFI_RECOVERY_WITHDRAWN, SYS_SCOPE: "wifi"}
    assert coord._system_event_phrase(began) == (
        "WiFi network came back, devices reconnecting"
    )
    assert coord._system_event_sentence(began).startswith(
        "The WiFi network came back at"
    )
    assert coord._system_event_phrase(stalled) == (
        "WiFi recovery stalled, outage continues"
    )
    assert "outage continues" in coord._system_event_sentence(stalled)


async def test_the_summary_leaves_the_recovery_to_the_table(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    rows = [
        {SYS_WHEN: 1789595520.0, SYS_KIND: SYS_WIFI_RECOVERING,
         SYS_SCOPE: "wifi"},
        {SYS_WHEN: 1789595580.0, SYS_KIND: SYS_WIFI_RECOVERY_WITHDRAWN,
         SYS_SCOPE: "wifi"},
    ]
    assert coord._other_house_sentences(rows) == []
