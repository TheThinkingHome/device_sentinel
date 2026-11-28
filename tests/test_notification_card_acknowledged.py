# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notification_card_acknowledged.py, Version: 0.30.11 (2026-11-27)

"""The notification card when each problem left is acknowledged (rule NOTE-11).

Acknowledged items are left out of the card's lines, so with nothing else
it said "All devices reporting." while the Problem List was full. It reads
"No new problems. N acknowledged on the Problem List." and links to the
Daily Brief, which holds them. With nothing acknowledged either, it reads
"All devices reporting." as before.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import notifier
from custom_components.device_sentinel.const import CONF_PERSISTENT_ENABLED, DATA_TODO_ITEMS

from .outage_helpers import walk
from .test_lightwave_connectivity import HOUR, _house

LINK = "\n\n[Open the Daily Brief]("


async def _listed(hass, freezer, monkeypatch):
    coord, dev, ids, records = await _house(hass, freezer)
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_PERSISTENT_ENABLED: True}
    )
    await hass.async_block_till_done()
    cards: list[str] = []
    monkeypatch.setattr(
        notifier.persistent_notification, "async_create",
        lambda _hass, message, **_kw: cards.append(message),
    )
    hass.states.async_set(ids["link"], "unavailable")  # judged by their clocks
    await hass.async_block_till_done()
    await walk(hass, freezer, 8 * HOUR, step=600)
    items = coord.data[DATA_TODO_ITEMS]
    assert items, "precondition: something listed"
    return coord, items, cards


async def test_a_list_all_acknowledged_is_not_called_all_reporting(hass: HomeAssistant, freezer, monkeypatch):
    coord, items, cards = await _listed(hass, freezer, monkeypatch)
    for uid in [item["uid"] for item in items]:
        await coord.async_todo_update(uid=uid, status="completed")
    coord._card_written = None  # as after a restart
    await coord.async_update_card()
    count = len(items)
    assert cards[-1].startswith(f"No new problems. {count} acknowledged on the Problem List.{LINK}"), cards[-1]


async def test_one_acknowledged_and_one_open_lists_the_open_one(hass: HomeAssistant, freezer, monkeypatch):
    coord, items, cards = await _listed(hass, freezer, monkeypatch)
    if len(items) < 2:
        return
    await coord.async_todo_update(uid=items[0]["uid"], status="completed")
    await coord.async_update_card()
    assert not cards[-1].startswith("No new problems."), "an open problem is still listed by name"
    assert LINK in cards[-1]


async def test_nothing_listed_reads_all_devices_reporting(hass: HomeAssistant, freezer, monkeypatch):
    coord, dev, ids, records = await _house(hass, freezer)
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_PERSISTENT_ENABLED: True}
    )
    await hass.async_block_till_done()
    cards: list[str] = []
    monkeypatch.setattr(
        notifier.persistent_notification, "async_create",
        lambda _hass, message, **_kw: cards.append(message),
    )
    coord._card_written = None
    await coord.async_update_card()
    assert cards[-1] == "All devices reporting."
