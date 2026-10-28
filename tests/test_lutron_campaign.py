# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_lutron_campaign.py, Version: 0.27.10 (2026-10-27)

"""A real Lutron campaign of two hubs, replayed (rules STACK-09, STACK-10).

Home Assistant's own Lutron Caseta integration and the Lutron library it
pins, with only the network faked: each hub's connection is a fake that
answers while the hub is up and fails while it is down, and the
library's own monitor loop drops and retries the session as it does in
a house. The two hubs come from a real house, with names and serials
replaced (tests/fixtures/lutron_two_hubs.json): a Basement hub with
dimmers, a switch and three Picos, a Garage hub with two switches.

The day, in the house's own times (America/Chicago): seven Pico
presses from 11:37 to 11:41, the Basement hub unplugged 11:44:24 to
11:48:39 and 11:50:19 to 11:56:04, the Garage hub 13:21:25 to 13:25:50
and 13:28:30 to 13:32:40, then unplugged again at 13:34:20 and Home
Assistant restarted at 13:38 with it still out, back at 13:44:21.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    STARTUP_GRACE_SECONDS,
)

from .helpers import record_events, setup_coordinator

smartbridge = pytest.importorskip("pylutron_caseta.smartbridge")

CHICAGO = ZoneInfo("America/Chicago")
HUBS = json.loads((Path(__file__).parent / "fixtures" / "lutron_two_hubs.json").read_text())


def _at(clock: str) -> datetime:
    hour, minute, second = (int(part) for part in clock.split(":"))
    return datetime(2026, 9, 20, hour, minute, second, tzinfo=CHICAGO)


class Hub:
    """One hub's network: up or down, and its current connection."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.data = HUBS[title]
        self.up = True
        self.dropped = asyncio.Event()
        self.plugged = asyncio.Event()
        self.bridge = None

    async def connect(self):
        if not self.up:
            # A hub that is off does not answer: the attempt waits until
            # it is back, then fails, and the library tries again. Waiting
            # rather than failing at once keeps the library's own retry
            # loop from spinning under the frozen clock.
            await self.plugged.wait()
            raise ConnectionError(f"Connect call failed ({self.title})")
        self.dropped = asyncio.Event()
        hub = self

        class Leap:
            def subscribe_unsolicited(self, _callback):
                return None

            async def run(self):
                await hub.dropped.wait()

            def close(self):
                return None

        return Leap()

    def unplug(self):
        self.up = False
        self.plugged = asyncio.Event()
        self.dropped.set()

    def plug_in(self):
        self.up = True
        self.plugged.set()


async def _login(bridge, hub: Hub):
    bridge.devices = copy.deepcopy(hub.data["devices"])
    bridge.buttons = copy.deepcopy(hub.data["buttons"])
    bridge.areas = copy.deepcopy(hub.data["areas"])
    bridge.occupancy_groups = copy.deepcopy(hub.data["occupancy_groups"])
    bridge.smart_away_state = hub.data["smart_away_state"]
    if not bridge._login_completed.done():
        bridge._login_completed.set_result(None)


async def _forever(*_args):
    await asyncio.sleep(10**6)


def _create_tls(hubs: dict[str, Hub]):
    def create(hostname, keyfile, certfile, ca_certs, port=8081, on_connect_callback=None):
        hub = hubs[hostname]
        bridge = smartbridge.Smartbridge(hub.connect, on_connect_callback=on_connect_callback)
        hub.bridge = bridge

        async def login():
            await _login(bridge, hub)

        bridge._login = login
        bridge._ping = _forever
        return bridge

    return create


async def _until(hass, freezer, when: datetime, hubs=()):
    """Move to a moment, a minute at a time, letting the library loop run."""
    while dt_util.utcnow() < when:
        step = min(timedelta(seconds=20), when - dt_util.utcnow())
        freezer.tick(step)
        async_fire_time_changed(hass)
        await _settle_library()
        await hass.async_block_till_done()


async def _settle_library():
    # The clock is frozen, so the library's own reconnect delay is set to
    # nothing and its loop is let run by yielding, never by sleeping.
    for _ in range(50):
        await asyncio.sleep(0)


async def _reload(hass, entry):
    """Restart one hub's integration, as Home Assistant's restart does."""
    task = hass.async_create_background_task(
        hass.config_entries.async_reload(entry.entry_id), "reload lutron")
    for _ in range(2000):
        await asyncio.sleep(0)
        if task.done():
            break
    assert task.done()
    await hass.async_block_till_done()


@pytest.fixture
def lutron_house():
    hubs = {"192.0.2.187": Hub("Basement"), "192.0.2.250": Hub("Garage")}
    with patch.object(smartbridge.Smartbridge, "create_tls", side_effect=_create_tls(hubs)), \
            patch.object(smartbridge, "RECONNECT_DELAY", 0):
        yield hubs


async def _setup(hass, freezer, hubs):
    freezer.move_to(_at("11:30:00"))
    entries = {}
    for host, hub in hubs.items():
        entry = MockConfigEntry(domain="lutron_caseta", title=hub.title, data={
            "host": host, "keyfile": "k.pem", "certfile": "c.pem", "ca_certs": "ca.pem"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        entries[hub.title] = entry
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    reg = dr.async_get(hass)
    hub_ids = {
        title: next(d.id for d in dr.async_entries_for_config_entry(reg, entry.entry_id) if d.via_device_id is None)
        for title, entry in entries.items()
    }
    return coord, entries, hub_ids


def _items(coord):
    return {i["device_id"]: i["summary"] for i in coord.todo_items}


async def test_his_day_reads_as_five_hub_outages_and_nothing_else(hass: HomeAssistant, freezer, lutron_house):
    hubs = lutron_house
    basement, garage = hubs["192.0.2.187"], hubs["192.0.2.250"]
    coord, entries, hub_ids = await _setup(hass, freezer, hubs)
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    presses = record_events(hass, "lutron_caseta_button_event")

    assert coord.is_hub(hub_ids["Basement"]) and coord.is_hub(hub_ids["Garage"])
    controlled = {d: coord.hub_of(d) for d in coord._watched if coord.hub_of(d)}
    assert sum(1 for h in controlled.values() if h == hub_ids["Basement"]) == 17
    assert sum(1 for h in controlled.values() if h == hub_ids["Garage"]) == 2

    # Seven presses across the three Picos, 11:37 to 11:41, through the
    # library's own button subscribers, as the hub would deliver them.
    pico_buttons = {}
    for button in basement.data["buttons"].values():
        pico_buttons.setdefault(button["parent_device"], []).append(button["device_id"])
    picos = sorted(pico_buttons)
    order = [picos[0], picos[0], picos[1], picos[2], picos[1], picos[0], picos[2]]
    for minute, device in zip((37, 37, 38, 39, 39, 40, 41), order):
        await _until(hass, freezer, _at(f"11:{minute}:10"))
        button = pico_buttons[device][0]
        basement.bridge._button_subscribers[button]("Press")
        basement.bridge._button_subscribers[button]("Release")
        await hass.async_block_till_done()
    assert len([p for p in presses if p.get("action") == "press"]) == 7
    pressed = {p["device_id"] for p in presses}
    for device_id in pressed:
        assert coord.data[DATA_DEVICES][device_id][DEV_EVENT_COUNT] >= 1

    timeline = [
        (basement, "11:44:24", "11:48:39"),
        (basement, "11:50:19", "11:56:04"),
        (garage, "13:21:25", "13:25:50"),
        (garage, "13:28:30", "13:32:40"),
    ]
    for hub, down, back in timeline:
        await _until(hass, freezer, _at(down))
        hub.unplug()
        await _settle_library()
        assert hub.bridge._leap is None
        assert hub.bridge.is_connected() is True  # the public call never moves (rule STACK-08)
        await _until(hass, freezer, _at(back))
        hub_id = hub_ids[hub.title]
        assert hub_id in _items(coord), f"{hub.title} at {back}"
        assert _items(coord)[hub_id].endswith("Hub down, 17 devices that it controls" if hub is basement
                                              else "Hub down, 2 devices that it controls")
        # Nothing the hub controls is listed on its own.
        assert set(_items(coord)) == {hub_id}
        hub.plug_in()
        await _settle_library()
        assert hub.bridge._leap is not None
        # Back within a minute check of its return, before the next
        # unplug; its row waits a minute before it leaves (rule LIST-06).
        await _until(hass, freezer, _at(back) + timedelta(seconds=75))
        assert set(_items(coord)) <= set(coord._parked)

    hub_faults = [f["device_id"] for f in faults]
    assert hub_faults == [hub_ids["Basement"]] * 2 + [hub_ids["Garage"]] * 2
    # The last return is still in its minute's wait (rule LIST-06).
    assert [r["device_id"] for r in recovered] + list(coord._parked) == hub_faults
    # Each outage dated from the first minute check that saw it, not
    # from the check that confirmed it a minute later.
    since = [f.get("since") for f in faults]
    for (hub, down, _), stamp in zip(timeline, since):
        began = datetime.fromisoformat(stamp)
        assert _at(down) <= began <= _at(down) + timedelta(seconds=61)

    # The fifth: unplugged at 13:34:20, Home Assistant restarted at 13:38
    # with the hub still out. The Garage entry cannot start and its two
    # switches and its hub read unavailable: the hub is down, one row,
    # and neither switch is listed on its own.
    await _until(hass, freezer, _at("13:34:20"))
    garage.unplug()
    await _settle_library()
    await _until(hass, freezer, _at("13:38:00"))
    # The integration's own wait for a hub that does not answer runs out
    # at once here: the clock moves only when the test moves it, and Home
    # Assistant retries the setup on its own while the hub is out.
    with patch("homeassistant.components.lutron_caseta.CONNECT_TIMEOUT", 0):
        await _reload(hass, entries["Garage"])
        assert entries["Garage"].state is ConfigEntryState.SETUP_RETRY
        await _until(hass, freezer, _at("13:44:00"))
    for device_id in coord.hub_members(hub_ids["Garage"]):
        assert device_id not in _items(coord)
    # One row: the Garage hub's, as when it went down with Home
    # Assistant running.
    assert [i["device_id"] for i in coord.todo_items] == [hub_ids["Garage"]]
    assert coord.todo_items[0]["summary"].endswith("Hub down, 2 devices that it controls")
    garage.plug_in()
    await _reload(hass, entries["Garage"])
    assert entries["Garage"].state is ConfigEntryState.LOADED
    await _until(hass, freezer, _at("13:50:00"))
    # Back, and its third drop in a quarter of an hour leaves it listed as
    # dropping out, as any device that keeps dropping out is (rule UNAV-06);
    # nothing it controls is listed.
    assert list(_items(coord)) == [hub_ids["Garage"]]
    assert ": dropped out 3 times" in _items(coord)[hub_ids["Garage"]]

    # Through the whole day: no Lutron device frozen or never reported.
    for device_id in controlled:
        assert coord.data[DATA_DEVICES][device_id].get(DEV_FROZEN_CATEGORY) not in (
            FREEZE_CATEGORY_FROZEN, FREEZE_CATEGORY_NEVER_REPORTED)
