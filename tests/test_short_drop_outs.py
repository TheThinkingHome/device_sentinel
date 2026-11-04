# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_short_drop_outs.py, Version: 0.28.1 (2026-11-03)

"""A device with short drop-outs is one problem, a signal problem
(rule SIG-17).

A door sensor can go unavailable for a few minutes dozens of times a
day and come back on its own each time. Two short drops (each back
within the device's freeze window) within 12 hours put it on the
Problem List once; it stays until 12 hours pass with no short drop. One
push when it is added and one when it is removed. While it is listed, a
drop is not reported until it outlasts the freeze window, and then it
is reported as the device becoming unavailable, from when it went. The
Signal mute silences short drop-outs; the Unavailable mute does not.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    EVENT_WITHDRAWN,
    LEARNING_MIN_DAYS,
    TODO_KINDS,
    TODO_SUMMARY,
)
from custom_components.device_sentinel.normalise import check_records

from .helpers import record_events, register_device, setup_entry

NAME = "S73 Door tilt sensor"
KIND = "short_drop_outs"


async def _minutes(hass, coord, freezer, count: int, alive: str | None = None) -> None:
    """Minute checks; with `alive`, the entity reports each minute."""
    for minute in range(count):
        freezer.tick(60)
        if alive is not None:
            hass.states.async_set(alive, "closed", {"reading": minute})
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()


async def _shed(hass: HomeAssistant, freezer, mutes: tuple[str, ...] = ()):
    """A watched door sensor whose freeze window is learned at about
    20 minutes, so a four-minute drop is short."""
    device, entities = register_device(hass, "s73", name=NAME)
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "closed")
    phone = async_mock_service(hass, "notify", "phone")
    options = {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]}
    for key in mutes:
        options[key] = [device.id]
    entry = await setup_entry(hass, options)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._started_at = dt_util.utcnow().timestamp() - 60
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 500
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 2)
    return coord, device, entity_id, phone


async def _drop(hass, coord, freezer, entity_id, down: int = 4, back: int = 30):
    """One drop: down four minutes, then back for a while."""
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, down)
    hass.states.async_set(entity_id, "closed")
    await _minutes(hass, coord, freezer, back)


def _item(coord, device_id):
    for item in coord.data[DATA_TODO_ITEMS]:
        if item.get("device_id") == device_id:
            return item
    return None


def _said(phone, start=0):
    return [call.data.get("message", "") for call in phone[start:]]


async def test_two_short_drops_make_one_item(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    await _drop(hass, coord, freezer, entity_id)
    assert not coord.is_flapping(device.id)
    await _drop(hass, coord, freezer, entity_id)
    assert coord.is_flapping(device.id)
    item = _item(coord, device.id)
    assert item is not None and list(item[TODO_KINDS]) == [KIND]
    assert item[TODO_SUMMARY] == (
        f"{NAME}: 2 short drop-outs in the last 12 hours, each back within 4 minutes"
    )


async def test_one_push_when_added_and_none_for_the_drops_after(hass: HomeAssistant, freezer):
    coord, _device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    added = [line for line in _said(phone) if "short drop-outs in the last 12 hours" in line]
    assert len(added) == 1, _said(phone)
    before = len(phone)
    for _ in range(6):
        await _drop(hass, coord, freezer, entity_id)
    assert len(phone) == before, _said(phone, before)


async def test_removed_after_twelve_hours_with_no_short_drop(hass: HomeAssistant, freezer):
    coord, device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    await _minutes(hass, coord, freezer, 11 * 60, alive=entity_id)
    assert coord.is_flapping(device.id)
    # Another short drop starts the 12 hours again.
    await _drop(hass, coord, freezer, entity_id, back=0)
    await _minutes(hass, coord, freezer, 11 * 60, alive=entity_id)
    assert coord.is_flapping(device.id)
    before = len(phone)
    await _minutes(hass, coord, freezer, 70, alive=entity_id)
    assert not coord.is_flapping(device.id)
    assert _item(coord, device.id) is None
    assert any("no longer has short drop-outs" in line for line in _said(phone, before)), _said(phone, before)


async def test_a_single_drop_is_what_it_always_was(hass: HomeAssistant, freezer):
    """One drop is an unavailable device and a recovery."""
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 5)
    item = _item(coord, device.id)
    assert item is not None and "unavailable" in item[TODO_KINDS]
    assert KIND not in item[TODO_KINDS]
    hass.states.async_set(entity_id, "closed")
    await _minutes(hass, coord, freezer, 2)
    assert _item(coord, device.id) is None


async def test_a_drop_inside_the_wait_is_not_reported(hass: HomeAssistant, freezer):
    coord, device, entity_id, phone = await _shed(hass, freezer)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    before = len(phone)
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 8)
    item = _item(coord, device.id)
    assert list(item[TODO_KINDS]) == [KIND]
    assert len(phone) == before, _said(phone, before)


async def test_a_long_drop_is_reported_from_when_it_went(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    record = coord.data[DATA_DEVICES][device.id]
    window = coord._freeze_window(record)
    went = dt_util.utcnow().timestamp()
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, int(window // 60) + 3)
    item = _item(coord, device.id)
    assert "unavailable" in item[TODO_KINDS] and KIND in item[TODO_KINDS]
    assert "became unavailable" in item[TODO_SUMMARY] or "unavailable" in item[TODO_SUMMARY]
    told = [f for f in faults if "unavailable" in f["kinds"]]
    assert len(told) == 1
    # Dated from when the device went, not from when it was listed.
    assert abs(item[TODO_KINDS]["unavailable"] - went) < 90
    hass.states.async_set(entity_id, "closed")
    await _minutes(hass, coord, freezer, 2)
    assert any(r["kind"] == "unavailable" and r["down_for"] > window for r in recovered)


async def test_the_signal_mute_silences_it(hass: HomeAssistant, freezer):
    coord, device, entity_id, phone = await _shed(hass, freezer, (CONF_SIGNAL_MUTED_DEVICES,))
    for _ in range(4):
        await _drop(hass, coord, freezer, entity_id)
    assert coord.is_flapping(device.id)
    assert coord.flapping_list == []
    assert not any("short drop-outs" in line for line in _said(phone))
    # Still shown on the device's page.
    assert coord.dashboard_device(device.id)["identity"]["short_drops"]["count"] == 4


async def test_the_unavailable_mute_does_not(hass: HomeAssistant, freezer):
    coord, device, entity_id, phone = await _shed(hass, freezer, (CONF_UNAVAILABLE_MUTED_DEVICES,))
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    assert [row["device_id"] for row in coord.flapping_list] == [device.id]
    assert any("short drop-outs" in line for line in _said(phone))


async def test_the_bus_pair_is_short_drop_outs(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    recovered = record_events(hass, EVENT_RECOVERED)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    await _minutes(hass, coord, freezer, 12 * 60 + 40, alive=entity_id)
    assert [f["kinds"] for f in faults if KIND in f["kinds"]] == [[KIND]]
    assert [r["kind"] for r in recovered if r["kind"] == KIND] == [KIND]


async def test_the_pages_say_short_drop_outs(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    coord._rebuild_registry_view()
    page = coord.dashboard_device(device.id)
    assert page["status"]["category"] == KIND
    assert page["status"]["flap"] == "3 in the last 12 hours"
    trends = coord.signal_trends()
    assert [(row["name"], row["drops"]) for row in trends["dropping_out"]] == [(NAME, 3)]
    assert coord.reachability_phrase(device.id) == (
        "Check its signal and the router it connects through."
    )


async def test_the_state_is_stored_and_checks_clean(hass: HomeAssistant, freezer):
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(2):
        await _drop(hass, coord, freezer, entity_id)
    record = coord.data[DATA_DEVICES][device.id]
    assert record["flap_since"] is not None and len(record["flap_drops"]) == 2
    assert check_records({device.id: record}) == []


async def test_the_fault_report_counts_it(hass: HomeAssistant, freezer):
    """Listed and acknowledged, it is under Short Drop-Outs and counted
    (rule BRIEF-15)."""
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(3):
        await _drop(hass, coord, freezer, entity_id)
    item = _item(coord, device.id)
    item["status"] = "completed"
    lines = coord._reporting_lines()
    assert lines[0] == "## Devices With a Fault (1)"
    at = lines.index("### Short Drop-Outs")
    assert lines[at + 2].startswith(f"- **{NAME}** (3 short drop-outs in the last 12 hours) for ")
    assert lines[at + 2].endswith("[✓ acknowledged]")


async def test_a_standing_dropping_out_item_is_withdrawn_at_the_upgrade(hass: HomeAssistant, freezer):
    """An older dropping-out item: removed with no recovery push and one
    withdrawn event when the startup grace closes."""
    coord, device, _entity_id, phone = await _shed(hass, freezer)
    loaded = {
        DATA_TODO_ITEMS: [
            {"device_id": device.id, "name": NAME, "summary": f"{NAME}: dropped out 5 times",
             "kinds": {"flapping": 1.0}},
            {"device_id": "other", "name": "Other", "summary": "Other: dropped out 3 times, battery low",
             "kinds": {"flapping": 1.0, "low_battery": 2.0}},
        ]
    }
    gone = coord._retire_dropping_out(loaded)
    assert gone == [(device.id, NAME)]
    assert [item["device_id"] for item in loaded[DATA_TODO_ITEMS]] == ["other"]
    assert loaded[DATA_TODO_ITEMS][0]["kinds"] == {"low_battery": 2.0}
    withdrawn = record_events(hass, EVENT_WITHDRAWN)
    recovered = record_events(hass, EVENT_RECOVERED)
    coord._dropping_out_retired = gone
    coord._on_grace_closed(None)
    await hass.async_block_till_done()
    assert [(w["device_id"], w["kinds"], w["reason"]) for w in withdrawn] == [(device.id, ["flapping"], "replaced")]
    assert recovered == []
    assert not any("dropping out" in line for line in _said(phone))


async def test_an_older_dropping_out_state_on_the_record_starts_afresh(hass: HomeAssistant, freezer):
    """A record still carrying the older rule's run (its learned longest
    stay back) is cleared at load, so the device is not listed again at
    once with no short drop to count (rule SIG-17)."""
    coord, device, _entity_id, phone = await _shed(hass, freezer)
    now = dt_util.utcnow().timestamp()
    record = {"flap_since": now - 1800, "flap_drops": [now - 1800, now - 1200, now - 600],
              "flap_back": now - 300, "flap_longest": 240.0}
    loaded = {DATA_DEVICES: {device.id: record}, DATA_TODO_ITEMS: []}
    coord._retire_dropping_out(loaded)
    assert record["flap_since"] is None and record["flap_drops"] == [] and record["flap_longest"] == 0.0
    # The rule's own state is left as it is.
    own = {"flap_since": now - 1800, "flap_drops": [now - 1800], "flap_back": now - 300, "flap_longest": 0.0}
    coord._retire_dropping_out({DATA_DEVICES: {device.id: own}, DATA_TODO_ITEMS: []})
    assert own["flap_since"] == now - 1800
