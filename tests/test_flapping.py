# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_flapping.py, Version: 0.23.2 (2026-09-24)

"""A device that keeps dropping out is one problem, not fifty.

The second fleet's S73 Door tilt sensor Shed3-Bay2 went unavailable
for three to four and a half minutes 53 times in 17 hours, each drop
past the three-minute wait, each opening and closing a problem. The
owner ruled on 24 September: three drops in two hours make a flap;
the longest time back between drops is learned from the current run;
the device stays listed until it has been back longer than that plus
the freeze grace for a gap that size; one push when it starts and one
when it clears; every drop still recorded. These tests replay S73's
pattern. The ones that are not guards fail on 0.23.1.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    INC_EVENT,
    INC_KIND,
    INCIDENT_OPENED,
    TODO_KINDS,
    TODO_SUMMARY,
)
from custom_components.device_sentinel.normalise import check_records

from .helpers import register_device, setup_entry

NAME = "S73 Door tilt sensor"


async def _minutes(hass, coord, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(60)
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()


async def _shed(hass: HomeAssistant, freezer):
    device, entities = register_device(hass, "s73", name=NAME)
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "closed")
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 500
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    return coord, device, entity_id, phone


async def _drop(hass, coord, freezer, entity_id, down: int = 4, back: int = 30):
    """One of S73's drops: down four minutes, then back for a while."""
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, down)
    hass.states.async_set(entity_id, "closed")
    await _minutes(hass, coord, freezer, back)


def _item(coord, device_id):
    for item in coord.data[DATA_TODO_ITEMS]:
        if item.get("device_id") == device_id:
            return item
    return None


async def test_three_drops_make_one_flapping_item(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(5):
        await _drop(hass, coord, freezer, entity_id)
    item = _item(coord, device.id)
    assert item is not None
    assert "flapping" in item[TODO_KINDS]
    assert "flapping, dropped out 5 times since" in item[TODO_SUMMARY]
    assert "unavailable" not in item[TODO_SUMMARY]


async def test_the_phone_hears_the_flap_once(hass: HomeAssistant, freezer):
    coord, _device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    before = len(phone)
    for _ in range(6):
        await _drop(hass, coord, freezer, entity_id)
    assert len(phone) == before, [call.data.get("message") for call in phone[before:]]
    assert any("keeps dropping out" in call.data.get("message", "") for call in phone)


async def test_every_drop_is_still_recorded(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(6):
        await _drop(hass, coord, freezer, entity_id)
    opened = [
        row for row in coord.data[DATA_INCIDENTS]
        if row["device_id"] == device.id
        and row[INC_KIND] == "unavailable"
        and row[INC_EVENT] == INCIDENT_OPENED
    ]
    assert len(opened) == 6


async def test_it_clears_after_holding_on_longer_than_the_flap(
    hass: HomeAssistant, freezer
):
    coord, device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(4):
        await _drop(hass, coord, freezer, entity_id, back=30)
    assert coord.is_flapping(device.id)
    # Back for as long as it ever was between drops: still a flap.
    await _minutes(hass, coord, freezer, 20)
    assert coord.is_flapping(device.id)
    # Back far past its learned flap and the grace for it.
    before = len(phone)
    await _minutes(hass, coord, freezer, 180)
    assert not coord.is_flapping(device.id)
    assert _item(coord, device.id) is None
    said = [call.data.get("message", "") for call in phone[before:]]
    assert any("has stopped dropping out" in line for line in said), said


async def test_a_single_drop_is_what_it_always_was(hass: HomeAssistant, freezer):
    """Guard: one drop is an unavailable device and a recovery."""
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 5)
    item = _item(coord, device.id)
    assert item is not None and "unavailable" in item[TODO_KINDS]
    assert "flapping" not in item[TODO_KINDS]
    hass.states.async_set(entity_id, "closed")
    await _minutes(hass, coord, freezer, 2)
    assert _item(coord, device.id) is None


async def test_the_run_is_stored_and_checks_clean(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    record = coord.data[DATA_DEVICES][device.id]
    assert len(record["flap_drops"]) == 3
    assert record["flap_since"] is not None and record["flap_longest"] > 0
    assert check_records({device.id: record}) == []


async def test_the_pages_say_flapping(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    coord._rebuild_registry_view()
    page = coord.dashboard_device(device.id)
    assert page["status"]["category"] == "flapping"
    assert page["status"]["flap"].startswith("dropped out 3 times since")
    trends = coord.signal_trends()
    assert [row["name"] for row in trends["dropping_out"]] == [NAME]
    assert coord.reachability_phrase(device.id) == (
        "Check its signal and the router it connects through."
    )
