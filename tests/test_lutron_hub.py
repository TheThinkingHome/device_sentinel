# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_lutron_hub.py, Version: 0.27.7 (2026-10-27)

"""Lutron: judged by its hub (rulings #663 to #665).

A Lutron hub is up or down from its library's session, which the
library clears when the hub stops answering its minute check. The
devices it controls, registered "via" it, are never judged frozen or
"never reported"; a Pico press counts as the Pico reporting. Shaped on
Christopher Robert's house: a Basement hub with dimmers and Picos, and
a Garage hub with two switches, each its own config entry.
"""

from __future__ import annotations

import inspect
import logging
from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    NOTIFY_FAMILY_FREEZE,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_MUTED_DEVICES,
    STARTUP_GRACE_SECONDS,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
)

from .helpers import record_events, setup_coordinator
from .test_freeze_unavailable_split import _mine

PIN = "2026-09-20 16:00:00+00:00"
DOMAIN = "lutron_caseta"
SESSION = object()


def _hub_entry(hass, title, serial, leap=SESSION, bridge=None, entity=True):
    entry = MockConfigEntry(domain=DOMAIN, title=title, data={"host": f"192.168.1.{serial % 250}"})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(
        bridge=bridge if bridge is not None else SimpleNamespace(_leap=leap),
        bridge_device={"serial": serial},
    )
    reg = dr.async_get(hass)
    hub = reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, str(serial))},
        name=f"{title} Lutron Caseta", manufacturer="Lutron Electronics Co., Inc",
        model="L-BDG2-WH (SmartBridge)")
    if entity:
        er.async_get(hass).async_get_or_create(
            "switch", DOMAIN, f"{serial}_smart_away", device_id=hub.id, config_entry=entry,
            suggested_object_id=f"{title.lower()}_smart_away")
    return entry, hub


def _controlled(hass, entry, hub, serial, name, model, platform="light", enabled=True):
    # Registered "via" the hub, by its id from 2026.9 and by its
    # identifier before that (the floor release, 2026.5.0).
    reg = dr.async_get(hass)
    via = ({"via_device_id": hub.id} if "via_device_id" in inspect.signature(reg.async_get_or_create).parameters
           else {"via_device": next(iter(hub.identifiers))})
    device = reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, str(serial))}, name=name,
        manufacturer="Lutron Electronics Co., Inc", model=model, **via)
    entity = er.async_get(hass).async_get_or_create(
        platform, DOMAIN, f"{serial}_{platform}", device_id=device.id, config_entry=entry,
        suggested_object_id=name.lower().replace(" ", "_"),
        disabled_by=None if enabled else er.RegistryEntryDisabler.INTEGRATION)
    return device, entity.entity_id


async def _tick(hass, freezer, step=61, n=1):
    for _ in range(n):
        freezer.tick(timedelta(seconds=step))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def _house(hass, freezer, options=None, hub_entity=True):
    freezer.move_to(PIN)
    basement, b_hub = _hub_entry(hass, "Basement", 52503071, entity=hub_entity)
    garage, g_hub = _hub_entry(hass, "Garage", 60212345)
    kitchen, kitchen_eid = _controlled(hass, basement, b_hub, 11, "Kitchen Main Lights", "PD-6WCL-XX (WallDimmer)")
    pico, _ = _controlled(hass, basement, b_hub, 12, "Upstairs Hallway Pico 1",
                          "PJ2-3BRL-GXX-X01 (Pico3ButtonRaiseLower)", platform="button", enabled=False)
    flood, flood_eid = _controlled(hass, garage, g_hub, 21, "Backyard Flood Lights", "PD-8ANS-XX (WallSwitch)", platform="switch")
    garage_lights, garage_eid = _controlled(hass, garage, g_hub, 22, "Garage Main Lights", "PD-8ANS-XX (WallSwitch)", platform="switch")
    for eid, value in (("switch.basement_smart_away", "off"), ("switch.garage_smart_away", "off"),
                       (kitchen_eid, "on"), (flood_eid, "off"), (garage_eid, "on")):
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()
    coord = await setup_coordinator(hass, options(b_hub, g_hub) if options else None)
    return SimpleNamespace(coord=coord, basement=basement, garage=garage, b_hub=b_hub, g_hub=g_hub,
                           kitchen=kitchen, kitchen_eid=kitchen_eid, pico=pico, flood=flood,
                           garage_lights=garage_lights)


async def _past_grace(hass, freezer):
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _item(coord, device_id):
    return next((i for i in coord.todo_items if i["device_id"] == device_id), None)


async def test_a_hub_and_the_devices_it_controls_are_mapped(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    c = h.coord
    assert c.is_hub(h.b_hub.id) and c.is_hub(h.g_hub.id)
    assert c.hub_of(h.kitchen.id) == h.b_hub.id
    assert c.hub_of(h.pico.id) == h.b_hub.id
    assert sorted(c.hub_members(h.g_hub.id)) == sorted([h.flood.id, h.garage_lights.id])
    assert c.judged_by_hub(h.kitchen.id) and c.judged_by_hub(h.b_hub.id)


async def test_a_hub_whose_session_drops_is_one_problem_naming_what_it_controls(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    await _past_grace(hass, freezer)
    lost_at = dt_util.utcnow().timestamp()
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer)
    assert _item(h.coord, h.g_hub.id) is None  # one reading is not an outage
    await _tick(hass, freezer)
    item = _item(h.coord, h.g_hub.id)
    assert item is not None
    assert item["summary"] == "Garage Lutron Caseta: Hub down, 2 devices that it controls"
    assert "The 2 devices it controls are listed on its page, not on the Problem List, until it is back." in item["description"]
    # Dated from when the session was first seen gone, inside the first minute.
    since = h.coord.data[DATA_DEVICES][h.g_hub.id]["frozen_since"]
    assert lost_at <= since <= lost_at + 62
    # Nothing it controls is listed on its own, and the other hub is untouched.
    for device in (h.flood, h.garage_lights, h.b_hub, h.kitchen):
        assert _item(h.coord, device.id) is None
    assert [f["device_id"] for f in faults] == [h.g_hub.id]


async def test_a_reconnect_of_a_few_seconds_is_not_an_outage(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    h.basement.runtime_data.bridge._leap = None
    await _tick(hass, freezer)
    h.basement.runtime_data.bridge._leap = SESSION
    await _tick(hass, freezer, n=3)
    assert _item(h.coord, h.b_hub.id) is None
    assert h.coord.data[DATA_DEVICES][h.b_hub.id].get(DEV_FROZEN_CATEGORY) is None


async def test_a_hub_that_comes_back_is_recovered(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=5)
    assert _item(h.coord, h.g_hub.id) is not None
    h.garage.runtime_data.bridge._leap = SESSION
    await _tick(hass, freezer, n=2)
    assert _item(h.coord, h.g_hub.id) is None
    assert [r["device_id"] for r in recovered] == [h.g_hub.id]


async def test_a_light_silent_far_past_its_rhythm_is_never_frozen(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.kitchen.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 3)
    record[DEV_TODAY_MAX] = None
    await _past_grace(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "off")
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] is not None
    await _tick(hass, freezer, step=3600, n=30)
    assert record.get(DEV_FROZEN_CATEGORY) is None
    assert _item(h.coord, h.kitchen.id) is None


async def test_a_pico_never_pressed_is_not_never_reported(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, step=3600, n=60)
    assert h.coord.data[DATA_DEVICES][h.pico.id].get(DEV_FROZEN_CATEGORY) is None
    assert _item(h.coord, h.pico.id) is None


async def test_a_pico_press_counts_as_the_pico_reporting(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.pico.id]
    before = record.get(DEV_EVENT_COUNT) or 0
    base = {"serial": 12, "type": "Pico3ButtonRaiseLower", "button_number": 2, "leap_button_number": 0,
            "device_name": "Pico 1", "device_id": h.pico.id, "area_name": "Upstairs Hallway",
            "button_type": "on"}
    hass.bus.async_fire("lutron_caseta_button_event", {**base, "action": "press"})
    hass.bus.async_fire("lutron_caseta_button_event", {**base, "action": "release"})
    await hass.async_block_till_done()
    assert (record.get(DEV_EVENT_COUNT) or 0) == before + 1
    assert abs(record[DEV_LAST_ACTIVITY] - dt_util.utcnow().timestamp()) < 2


async def test_a_press_on_a_device_no_hub_controls_is_ignored(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.kitchen.id]
    before = record.get(DEV_EVENT_COUNT) or 0
    hass.bus.async_fire("lutron_caseta_button_event", {"device_id": "not-a-device", "action": "press"})
    await hass.async_block_till_done()
    assert (record.get(DEV_EVENT_COUNT) or 0) == before


async def test_an_unreadable_session_is_no_opinion(hass: HomeAssistant, freezer, caplog):
    caplog.set_level(logging.INFO)
    freezer.move_to(PIN)
    entry, hub = _hub_entry(hass, "Basement", 52503071, bridge=SimpleNamespace())
    _controlled(hass, entry, hub, 11, "Kitchen Main Lights", "PD-6WCL-XX (WallDimmer)")
    hass.states.async_set("switch.basement_smart_away", "off")
    coord = await setup_coordinator(hass)
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, n=5)
    assert _item(coord, hub.id) is None
    assert caplog.text.count("could not read whether the lutron_caseta hub") == 1


async def test_a_hub_whose_integration_cannot_start_is_down(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    h.garage.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for eid in ("switch.garage_smart_away", "switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=6)
    # One row, the hub's: not one for the integration, and none for the
    # two switches whose entities read unavailable.
    assert set(i["device_id"] for i in h.coord.todo_items) == {h.g_hub.id}
    assert _item(h.coord, h.g_hub.id)["summary"].endswith("Hub down, 2 devices that it controls")


async def test_a_frozen_light_from_before_the_upgrade_stays_until_it_reports(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.kitchen.id]
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record["frozen_since"] = dt_util.utcnow().timestamp() - 3600
    await _past_grace(hass, freezer)
    await _tick(hass, freezer)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    hass.states.async_set(h.kitchen_eid, "off")
    await hass.async_block_till_done()
    await _tick(hass, freezer)
    assert record.get(DEV_FROZEN_CATEGORY) is None


async def test_no_silence_episode_and_no_slow_reporting_offer_for_a_controlled_device(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.kitchen.id]
    record[DEV_DAILY_MAX] = [50 * 3600.0] * (FREEZE_ARMING_DAYS + 3)
    record[DEV_TODAY_MAX] = None
    await _past_grace(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "off")
    await hass.async_block_till_done()
    await _tick(hass, freezer, step=3600, n=200)
    episodes = [e for e in h.coord.data.get("silence_episodes") or [] if e.get("device_id") == h.kitchen.id]
    assert episodes == []
    assert not h.coord._slow_reporter(h.kitchen.id)


async def test_the_device_pages_carry_the_hub(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    now = dt_util.utcnow().timestamp()
    light = h.coord.hub_view(h.kitchen.id, now)
    assert light["name"] == "Basement Lutron Caseta" and light["up"] is True and light["kind"] == "light"
    assert h.coord.hub_view(h.pico.id, now)["kind"] == "remote"
    assert h.coord.hub_view(h.b_hub.id, now) is None
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    page = h.coord.hub_self_view(h.g_hub.id, dt_util.utcnow().timestamp())
    assert page["up"] is False
    assert [m["name"] for m in page["behind"]] == ["Backyard Flood Lights", "Garage Main Lights"]
    assert {m["standing"] for m in page["behind"]} == {"Watched, waiting for its hub"}
    assert page["outages"] and page["outages"][0]["end"] is None
    h.garage.runtime_data.bridge._leap = SESSION
    await _tick(hass, freezer, n=2)
    page = h.coord.hub_self_view(h.g_hub.id, dt_util.utcnow().timestamp())
    assert page["up"] is True and page["outages"][0]["end"] is not None


async def test_classification_says_judged_by_its_hub(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    rows = {r["device_id"]: r for r in h.coord.classification_rows()}
    assert rows[h.kitchen.id]["judged"] == "judged by its hub"
    assert rows[h.b_hub.id]["judged"] == "hub"


async def test_diagnostics_carry_each_hub(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    hubs = h.coord.hub_diagnostics()
    assert hubs[h.g_hub.id]["controls"] == 2 and hubs[h.g_hub.id]["connected"] is True


async def test_the_reader_follows_the_library_through_a_drop(hass: HomeAssistant):
    """pylutron-caseta, as Home Assistant 2026.10 pins it, run through its own
    connect and drop: the session is set while the connection runs and
    cleared when it ends, while is_connected() is not to be trusted (#663)."""
    import asyncio
    from unittest.mock import patch

    import pytest

    smartbridge = pytest.importorskip("pylutron_caseta.smartbridge")
    from custom_components.device_sentinel.hubs import HUB_READERS

    bridge = smartbridge.Smartbridge.create_tls("192.0.2.1", "k", "c", "ca")
    entry = SimpleNamespace(runtime_data=SimpleNamespace(bridge=bridge))
    assert HUB_READERS[DOMAIN](entry) is False
    seen: list[bool] = []
    release = asyncio.Event()

    class FakeLeap:
        def subscribe_unsolicited(self, _callback):
            return None

        async def run(self):
            seen.append(HUB_READERS[DOMAIN](entry))
            await release.wait()
            raise ConnectionError("hub stopped answering")

        def close(self):
            return None

    async def fake_connect():
        return FakeLeap()

    async def no_login():
        await asyncio.sleep(3600)

    async def no_ping():
        await asyncio.sleep(3600)

    with patch.object(bridge, "_connect", fake_connect), patch.object(bridge, "_login", no_login), \
            patch.object(bridge, "_ping", no_ping), patch.object(smartbridge, "RECONNECT_DELAY", 0):
        task = asyncio.ensure_future(bridge._monitor_once())
        await asyncio.sleep(0.05)
        assert HUB_READERS[DOMAIN](entry) is True
        release.set()
        await task
    assert seen == [True]
    assert HUB_READERS[DOMAIN](entry) is False


# Found by the adversarial round of 14 October 2026.


async def test_a_hub_muted_for_unavailable_is_silent_down_and_back(hass: HomeAssistant, freezer):
    """A mute is a mute (James, 14 October 2026). From 17 October 2026 it
    is the unavailable mute that silences a hub going down."""
    h = await _house(hass, freezer, options=lambda b, g: {CONF_UNAVAILABLE_MUTED_DEVICES: [g.id]})
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    assert _item(h.coord, h.g_hub.id) is None
    h.garage.runtime_data.bridge._leap = SESSION
    await _tick(hass, freezer, n=2)
    assert faults == [] and recovered == []


async def test_a_freeze_muted_hub_that_goes_down_is_reported(hass: HomeAssistant, freezer):
    """A freeze mute silences only judgments made from silence (James, 17
    October 2026, reversing the 14 October amendment to #664): a hub
    muted for freeze that goes down is one row, and back is told."""
    h = await _house(hass, freezer, options=lambda b, g: {CONF_FREEZE_MUTED_DEVICES: [g.id]})
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    assert _item(h.coord, h.g_hub.id)["summary"].endswith("Hub down, 2 devices that it controls")
    h.garage.runtime_data.bridge._leap = SESSION
    await _tick(hass, freezer, n=2)
    assert [e["device_id"] for e in faults] == [h.g_hub.id]
    assert [e["device_id"] for e in recovered] == [h.g_hub.id]
    assert _item(h.coord, h.g_hub.id) is None


async def test_a_hub_with_no_entity_still_speaks_for_its_devices(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, hub_entity=False)
    assert h.b_hub.id not in h.coord._watched
    assert h.coord.hub_of(h.kitchen.id) == h.b_hub.id
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, step=3600, n=60)
    assert _item(h.coord, h.pico.id) is None
    # With no watched hub, the integration rule covers its devices as in
    # 0.26.2 (James, 14 October 2026): a Lutron that cannot start is
    # reported as the integration, its light counted under it.
    h.basement.runtime_data.bridge._leap = None
    h.basement.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    hass.states.async_set(h.kitchen_eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=6)
    assert h.basement.entry_id in h.coord._integration_told
    assert _item(h.coord, h.kitchen.id) is None


async def test_a_retry_between_readings_does_not_end_the_outage(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    h.garage.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await _tick(hass, freezer, n=3)
    assert _item(h.coord, h.g_hub.id)["summary"].endswith("Hub down, 2 devices that it controls")
    h.garage.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    await _tick(hass, freezer)
    h.garage.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await _tick(hass, freezer)
    assert _item(h.coord, h.g_hub.id)["summary"].endswith("Hub down, 2 devices that it controls")
    assert recovered == []


async def test_a_light_already_unavailable_is_not_told_recovered_as_its_hub_goes(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=5)
    record = h.coord.data[DATA_DEVICES][h.kitchen.id]
    assert record[DEV_FROZEN_CATEGORY] == "unavailable"
    h.basement.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    assert record[DEV_FROZEN_CATEGORY] == "unavailable"
    assert [r for r in recovered if r["device_id"] == h.kitchen.id] == []


async def test_a_hub_frozen_from_before_is_cleared_while_connected_and_dated_by_its_outage(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    record = h.coord.data[DATA_DEVICES][h.g_hub.id]
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record["frozen_since"] = dt_util.utcnow().timestamp() - 3 * 86400
    await _past_grace(hass, freezer)
    await _tick(hass, freezer)
    assert record.get(DEV_FROZEN_CATEGORY) is None
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record["frozen_since"] = dt_util.utcnow().timestamp() - 3 * 86400
    lost = dt_util.utcnow().timestamp()
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    assert record[DEV_FROZEN_CATEGORY] == "unavailable"
    assert lost <= record["frozen_since"] <= lost + 62


async def test_an_integration_outage_open_from_before_the_upgrade_is_closed(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    c = h.coord
    started = dt_util.utcnow().timestamp() - 600
    c._integration_told.add(h.garage.entry_id)
    c._entry_down_at[h.garage.entry_id] = started
    await _past_grace(hass, freezer)
    await _tick(hass, freezer)
    assert h.garage.entry_id not in c._integration_told
    assert any(row.get("kind") == SYS_INTEGRATION_UP for row in c.data.get("system_events") or [])


async def test_a_device_behind_a_hub_that_cannot_speak_has_an_ordinary_page(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, hub_entity=False)
    await _past_grace(hass, freezer)
    assert h.coord.hub_view(h.kitchen.id, dt_util.utcnow().timestamp()) is None


# Found by the fourth adversarial round of 14 October 2026.


def _kinds(coord, kind):
    return [row for row in coord.data.get("system_events") or [] if row.get("kind") == kind]


async def _garage_fails_to_start(hass, h):
    h.garage.runtime_data.bridge._leap = None
    h.garage.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for eid in ("switch.garage_smart_away", "switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()


async def _garage_back(hass, h):
    h.garage.runtime_data.bridge._leap = SESSION
    h.garage.mock_state(hass, ConfigEntryState.LOADED)
    for eid in ("switch.garage_smart_away", "switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "off")
    await hass.async_block_till_done()


async def _mute_garage(hass, h, muted):
    entry = h.coord.entry
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_UNAVAILABLE_MUTED_DEVICES: [h.g_hub.id] if muted else []})
    await hass.async_block_till_done()


async def test_a_muted_hub_that_cannot_start_is_silent_and_keeps_its_entry(hass: HomeAssistant, freezer):
    """A hub's mute covers its devices (James, 14 October 2026)."""
    h = await _house(hass, freezer, options=lambda b, g: {CONF_UNAVAILABLE_MUTED_DEVICES: [g.id]})
    c = h.coord
    await _past_grace(hass, freezer)
    assert c.hub_takes_over(h.flood.id) and c._unavailable_muted(h.flood.id)
    await _garage_fails_to_start(hass, h)
    await _tick(hass, freezer, n=10)
    assert _kinds(c, SYS_INTEGRATION_DOWN) == []
    assert c.todo_items == []


async def test_unmuting_a_hub_mid_outage_reports_only_the_hub(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, options=lambda b, g: {CONF_UNAVAILABLE_MUTED_DEVICES: [g.id]})
    c = h.coord
    await _past_grace(hass, freezer)
    for eid in ("switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "on")
    await _tick(hass, freezer, n=2)
    await _garage_fails_to_start(hass, h)
    await _tick(hass, freezer, n=10)
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    lights = (h.flood.id, h.garage_lights.id)
    await _mute_garage(hass, h, False)
    await _tick(hass, freezer, n=3)
    assert [i["summary"] for i in c.todo_items] == ["Garage Lutron Caseta: Hub down, 2 devices that it controls"]
    assert _kinds(c, SYS_INTEGRATION_DOWN) == [] and _kinds(c, SYS_INTEGRATION_UP) == []
    assert not any(str(i["device_id"]).startswith("upstream:") for i in c.todo_items)
    # Muted again: silent, and nothing about the lights.
    await _mute_garage(hass, h, True)
    await _tick(hass, freezer, n=3)
    assert c.todo_items == []
    await _mute_garage(hass, h, False)
    await _tick(hass, freezer, n=2)
    await _garage_back(hass, h)
    await _tick(hass, freezer, n=3)
    assert c.todo_items == []
    assert _kinds(c, SYS_INTEGRATION_DOWN) == [] and _kinds(c, SYS_INTEGRATION_UP) == []
    assert [e for e in faults + recovered if e.get("device_id") in lights] == []


async def test_an_outage_from_before_the_upgrade_still_down_waits_for_the_integration(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    c = h.coord
    await _garage_fails_to_start(hass, h)
    c._integration_told.add(h.garage.entry_id)
    c._entry_down_at[h.garage.entry_id] = dt_util.utcnow().timestamp() - 600
    await _past_grace(hass, freezer)
    await _tick(hass, freezer, n=3)
    assert _kinds(c, SYS_INTEGRATION_UP) == []
    assert _item(c, h.g_hub.id)["summary"].endswith("Hub down, 2 devices that it controls")
    assert not any(str(i["device_id"]).startswith("upstream:") for i in c.todo_items)
    await _garage_back(hass, h)
    await _tick(hass, freezer, n=2)
    assert len(_kinds(c, SYS_INTEGRATION_UP)) == 1


async def test_unmuting_a_cut_off_hub_does_not_list_its_lights(hass: HomeAssistant, freezer):
    """The case the fifth and sixth review rounds found (14 October 2026)."""
    h = await _house(hass, freezer, options=lambda b, g: {CONF_UNAVAILABLE_MUTED_DEVICES: [g.id]})
    c = h.coord
    await _past_grace(hass, freezer)
    for eid in ("switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "on")
    await _tick(hass, freezer, n=2)
    h.garage.runtime_data.bridge._leap = None
    for eid in ("switch.garage_smart_away", "switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=6)
    assert c.todo_items == []
    faults = record_events(hass, EVENT_FAULT)
    await _mute_garage(hass, h, False)
    await _tick(hass, freezer, n=3)
    assert [i["summary"] for i in c.todo_items] == ["Garage Lutron Caseta: Hub down, 2 devices that it controls"]
    assert [e["device_id"] for e in faults] == [h.g_hub.id]


async def test_a_muted_hub_page_says_its_devices_are_muted_with_it(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, options=lambda b, g: {CONF_FREEZE_MUTED_DEVICES: [g.id]})
    c = h.coord
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    now = dt_util.utcnow().timestamp()
    page = c.hub_self_view(h.g_hub.id, now)
    assert page["up"] is False
    assert {row["standing"] for row in page["behind"]} == {"Muted with its hub"}
    assert c.hub_view(h.flood.id, now)["up"] is False
    assert c.mute_text(h.flood.id) == "freeze (with its hub)"
    assert c.page_mutes(h.flood.id)["freeze"] == {"on": True, "source": "hub", "here": False}


async def test_a_hub_muted_from_everything_mutes_its_devices(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, options=lambda b, g: {CONF_MUTED_DEVICES: [g.id]})
    c = h.coord
    assert c._muted_devices.get(h.flood.id) == "hub"
    assert c.mute_text(h.flood.id) == "Global (with its hub)"
    assert c.page_mutes(h.flood.id)["everything"]["source"] == "hub"
    assert h.kitchen.id not in c._muted_devices
    entry = c.entry
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_MUTED_DEVICES: []})
    await hass.async_block_till_done()
    assert h.flood.id not in c._muted_devices


# A hub's mute covers its devices, and James's wording rulings, of
# 14 October 2026.


async def test_a_light_still_down_when_its_hub_is_back_is_listed(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    c = h.coord
    await _past_grace(hass, freezer)
    for eid in ("switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "on")
    await _tick(hass, freezer, n=2)
    h.garage.runtime_data.bridge._leap = None
    for eid in ("switch.garage_smart_away", "switch.backyard_flood_lights", "switch.garage_main_lights"):
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=6)
    assert [i["summary"] for i in c.todo_items] == ["Garage Lutron Caseta: Hub down, 2 devices that it controls"]
    h.garage.runtime_data.bridge._leap = SESSION
    hass.states.async_set("switch.garage_smart_away", "off")
    hass.states.async_set("switch.garage_main_lights", "on")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=5)
    assert _item(c, h.flood.id)["summary"] == "Backyard Flood Lights: unavailable"
    assert _item(c, h.garage_lights.id) is None
    assert _item(c, h.g_hub.id) is None


async def test_the_card_and_the_brief_say_hub_down(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    c = h.coord
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer, n=3)
    card = c._family_summary(NOTIFY_FAMILY_FREEZE)
    assert "Garage Lutron Caseta hub down, 2 devices that it controls" in card
    assert "Garage Lutron Caseta unavailable" not in card
    await hass.async_add_executor_job(c._write_reports, "test")
    text = c._last_brief_text
    assert "hub down, 2 devices that it controls" in text
    assert "Garage Lutron Caseta went down at" in text
    assert "Garage Lutron Caseta became unavailable" not in text


# Found by the seventh adversarial round of 14 October 2026.


async def test_a_hub_that_is_not_watched_mutes_nothing(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, hub_entity=False,
                     options=lambda b, g: {CONF_MUTED_DEVICES: [b.id], CONF_FREEZE_MUTED_DEVICES: [b.id]})
    c = h.coord
    assert h.b_hub.id not in c._watched
    assert h.kitchen.id not in c._muted_devices
    assert not c._freeze_muted(h.kitchen.id)
    assert c.mute_text(h.kitchen.id) == ""
    assert c.page_mutes(h.kitchen.id)["everything"]["on"] is False


# ------------------------- unknown on a device a hub controls (0.26.6)


# R2-2. hubs.py 385-391: the hub path has no all-unknown hold. A device a
# hub controls with an unknown verdict standing from 0.26.5, its entity
# still unknown, gets None on the first sweep (detect_freeze.py 670-674
# returns _hub_category directly), the item retires and a recovery is
# fired though the device said nothing. Round one added the hold only
# to the non-hub branch (detect_freeze.py 794-795).
async def test_a_hub_controlled_device_with_a_standing_unknown_is_not_told_recovered(
    hass: HomeAssistant, freezer
):
    h = await _house(hass, freezer)
    c = h.coord
    await _past_grace(hass, freezer)
    await _tick(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "unknown")
    await hass.async_block_till_done()
    record = c.data[DATA_DEVICES][h.kitchen.id]
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNKNOWN
    record["frozen_since"] = dt_util.utcnow().timestamp() - 3600
    c._sync_problem_list()
    await hass.async_block_till_done()
    assert _item(c, h.kitchen.id) is not None, "precondition: the 0.26.5 unknown item stands"
    back = record_events(hass, EVENT_RECOVERED)
    await _tick(hass, freezer, n=3)
    assert not _mine(back, h.kitchen.id), "a rule change is not a recovery (#529)"
    assert _item(c, h.kitchen.id) is not None


# R2-2b. The same hole reached live: a controlled light unavailable (its
# hub up) whose entity passes to unknown is cleared by _hub_category and
# told recovered, though nothing was heard. 0.26.5 held it as unknown.
async def test_a_hub_controlled_device_going_from_unavailable_to_unknown_is_not_recovered(
    hass: HomeAssistant, freezer
):
    h = await _house(hass, freezer)
    c = h.coord
    await _past_grace(hass, freezer)
    await _tick(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=8)
    record = c.data[DATA_DEVICES][h.kitchen.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition"
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(h.kitchen_eid, "unknown")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=3)
    assert not _mine(back, h.kitchen.id), "unknown is not the device speaking"
    assert _item(c, h.kitchen.id) is not None
