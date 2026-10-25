# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_problem_words.py, Version: 0.27.4 (2026-10-25)

"""One set of words for each problem, the Daily Brief's (rules NOTE-01,
NOTE-10, LIST-02, LIST-10, UNAV-08).

The push said "was detected frozen", the Problem List "frozen", while
the brief said "stopped reporting". The push, the card and the Problem
List now use the brief's word for each problem, each in its own
sentence shape, and the push no longer adds "This is a battery
device...". A never-reported device's time reads "discovered", as the
brief has it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_FLAP_DROPS,
    DEV_FLAP_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    TODO_DESCRIPTION,
    TODO_KIND_FLAPPING,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_SUMMARY,
)
from custom_components.device_sentinel.problem_list import ProblemListMixin

from tests.helpers import card_message, setup_entry


def _device(hass, uid, name, battery=False):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=name)
    reg = er.async_get(hass)
    ent = reg.async_get_or_create("sensor", "test", f"{uid}_0", device_id=device.id, config_entry=source)
    if battery:
        reg.async_get_or_create("sensor", "test", f"{uid}_pct", device_id=device.id,
                                config_entry=source, original_device_class="battery")
    return device, ent.entity_id


def _phone(hass):
    calls = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", "phone", handler)
    return calls


async def _house(hass):
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"],
                                     CONF_PERSISTENT_ENABLED: True})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    return coord, _phone(hass)


async def _judge(hass, coord, device, category, eid):
    hass.states.async_set(eid, "21.5")
    rec = coord.data[DATA_DEVICES][device.id]
    rec[DEV_DAILY_MAX] = []  # nothing learned: pushed at once
    rec[DEV_FROZEN_CATEGORY] = category
    rec[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 600
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4000
    coord._sync_problem_list()
    await hass.async_block_till_done()


async def test_every_surface_uses_the_brief_words(hass: HomeAssistant):
    frozen, e1 = _device(hass, "f1", "Frozen Sensor")
    never, e2 = _device(hass, "n1", "Never Sensor")
    coord, calls = await _house(hass)
    await _judge(hass, coord, frozen, FREEZE_CATEGORY_FROZEN, e1)
    await _judge(hass, coord, never, FREEZE_CATEGORY_NEVER_REPORTED, e2)
    await coord.async_update_card()
    await hass.async_block_till_done()

    pushed = " ".join(c["message"] for c in calls)
    assert "Frozen Sensor stopped reporting." in pushed
    assert "Never Sensor never reported." in pushed
    assert "detected" not in pushed
    # The push's Summary line, the card and the brief agree.
    assert "Summary: Frozen Sensor stopped reporting" in pushed
    assert "Frozen Sensor stopped reporting" in card_message(hass)
    brief = {row[0]: row[1] for row in coord._brief_now_rows()}
    assert brief["Frozen Sensor"] == "stopped reporting"
    assert brief["Never Sensor"] == "never reported"

    items = {i[TODO_SUMMARY]: i[TODO_DESCRIPTION] for i in coord.todo_items}
    assert "Frozen Sensor: stopped reporting" in items
    assert items["Frozen Sensor: stopped reporting"].startswith("Stopped reporting at ")
    # Never reported is dated "discovered", as in the brief (rule LIST-10).
    assert items["Never Sensor: never reported"].startswith("Never reported, discovered ")


async def test_unavailable_push_has_no_battery_sentence(hass: HomeAssistant):
    dev, eid = _device(hass, "b1", "Battery Door", battery=True)
    coord, calls = await _house(hass)
    assert dev.id in coord._battery_entity
    await _judge(hass, coord, dev, FREEZE_CATEGORY_UNAVAILABLE, eid)
    pushed = " ".join(c["message"] for c in calls)
    assert "Battery Door became unavailable." in pushed
    assert "battery device" not in pushed


async def test_a_hub_went_down(hass: HomeAssistant):
    dev, _eid = _device(hass, "h1", "Lutron Bridge")
    coord, _calls = await _house(hass)
    coord.unavailable_words = lambda device_id: ("went down", "down")
    coord._collect_event(TODO_KIND_UNAVAILABLE, "Lutron Bridge", False, dev.id)
    assert coord._pending_events[-1][1].endswith(", Lutron Bridge went down.")


async def test_railed_and_dropping_out_words(hass: HomeAssistant):
    assert ProblemListMixin._kind_word(TODO_KIND_RAILED_SIGNAL, None) == "signal railed"
    assert ProblemListMixin._event_line(
        TODO_KIND_RAILED_SIGNAL, "Plug", "5:29 pm", False, None
    ) == "At 5:29 pm, Plug signal railed."

    dev, _eid = _device(hass, "p1", "Plug")
    coord, _calls = await _house(hass)
    rec = coord.data[DATA_DEVICES][dev.id]
    now = dt_util.utcnow().timestamp()
    rec[DEV_FLAP_DROPS] = [now - 300, now - 200, now - 100]
    rec[DEV_FLAP_SINCE] = now - 300
    words = coord.flap_words(dev.id)
    assert words.startswith("dropped out 3 times since ")
    coord._collect_event(TODO_KIND_FLAPPING, "Plug", False, dev.id)
    assert coord._pending_events[-1][1].endswith(f", Plug {words}.")
