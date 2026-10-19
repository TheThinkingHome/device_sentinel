# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dead_node_outage_dates.py, Version: 0.26.7 (2026-10-19)

"""When a dead node's outage starts and ends, and the device whose only
enabled entity is its node status (rulings #670, #671, #647), from the
adversarial rounds on 0.26.5 of 16 October 2026, regrouped by subject
in 0.26.7 (#707). Each test failed on the build as it stood before its
round's fixes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_TAINTED,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    TODO_KIND_FROZEN,
    TODO_KIND_UNAVAILABLE,
)
from custom_components.device_sentinel.escalation import ESCALATED_FROM

from .helpers import record_events, registry_settled, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, rec, restart, walk
from .test_zwave_dead_node import _house, _mine

DAY = 86400.0

async def _lonely(hass: HomeAssistant, freezer, node: int, switch_on: bool = False):
    """A Z-Wave device whose only enabled entity is its node status."""
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", f"4191921521-{node}")},
        name=f"P{node} Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    switch = reg.async_get_or_create(
        "switch", "zwave_js", f"4191921521.{node}-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=None if switch_on else er.RegistryEntryDisabler.USER,
    ).entity_id
    status = reg.async_get_or_create(
        "sensor", "zwave_js", f"4191921521.{node}.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    if switch_on:
        hass.states.async_set(switch, "on")
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    return coord, device, switch, status, record


async def test_a_status_only_device_dead_twice_dates_the_second_death_from_itself(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", "4191921521-21")},
        name="P21 Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "switch", "zwave_js", "4191921521.21-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    status = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.21.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    hass.states.async_set(status, "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record.get(DEV_DOWN_SINCE) is None, (
        "the first death's start outlived its recovery", record.get(DEV_DOWN_SINCE)
    )

    await walk(hass, freezer, 2 * 3600)
    second = dt_util.utcnow().timestamp()
    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    # Inside the 180 s debounce of the second death.
    assert record[DEV_FROZEN_CATEGORY] is None, "the second death skipped its debounce"
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] >= second - 1, (
        "the second death was dated from the first", record[DEV_FROZEN_SINCE], second
    )

    hass.states.async_set(status, "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    back = _mine(recoveries, device.id)
    assert len(back) == 2
    assert back[1]["down_for"] < 30 * 60, back[1]


async def test_an_escalated_unavailable_pair_keeps_the_moment_it_was_marked(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    quiet = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc).timestamp()
    marked = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc).timestamp()
    back = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc).timestamp()
    opened = {
        INC_DEVICE_ID: "d", INC_NAME: "P03 Z-Wave Smart plug",
        INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED,
        INC_WHEN: marked, INC_CAUSE: None, INC_DURATION: None,
        ESCALATED_FROM: TODO_KIND_FROZEN,
    }
    resolved = {
        INC_DEVICE_ID: "d", INC_NAME: "P03 Z-Wave Smart plug",
        INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: back, INC_CAUSE: None, INC_DURATION: back - quiet,
    }
    sentence = coord._compose_episode(opened, resolved)
    assert f"from frozen at {coord._clock(quiet)}" not in sentence, sentence
    assert coord._clock(marked) in sentence, sentence


async def test_dead_learned_after_an_unavailable_start_outlives_a_restart(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)

    for key in ("switch", "rssi", "status"):
        hass.states.async_set(ids[key], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    # The server is back; the node cannot be reached.
    hass.states.async_set(ids["status"], "dead")
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def cached_values_status_not_known_yet():
        hass.states.async_set(ids["status"], "unknown")
        hass.states.async_set(ids["switch"], "on")
        hass.states.async_set(ids["rssi"], "-42")

    coord = await restart(hass, freezer, before_setup=cached_values_status_not_known_yet)
    record = rec(coord, device.id)
    await walk(hass, freezer, 6 * 60)
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)

    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(recoveries, device.id), "a dead node was told recovered across a restart"
    assert len(_mine(faults, device.id)) == 1, "one outage faulted twice"


async def test_status_only_device_heard_during_a_restart_is_not_left_unavailable(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", "4191921521-22")},
        name="P22 Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "switch", "zwave_js", "4191921521.22-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    status = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.22.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def heard_while_home_assistant_was_down():
        # Z-Wave JS heard the node during the downtime and hands its
        # status back already alive, before Device Sentinel listens.
        hass.states.async_set(status, "alive")

    coord = await restart(
        hass, freezer, down=600, before_setup=heard_while_home_assistant_was_down
    )
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 20 * 60)

    assert record.get(DEV_DOWN_SINCE) is None
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "a node Z-Wave calls alive was left unavailable", record[DEV_FROZEN_CATEGORY]
    )
    # Whether the return is announced across a restart follows the
    # existing restart rules; what matters here is that it is not stuck.
    assert len(_mine(recoveries, device.id)) <= 1


async def test_r6_back_from_dead_is_recorded_once(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    coord, device, _switch, status, record = await _lonely(hass, freezer, 30)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    calls: list[str | None] = []
    original = coord._record_activity

    def counting(device_id, *args, **kwargs):
        if device_id == device.id:
            calls.append(args[1] if len(args) > 1 else kwargs.get("entity_id"))
        return original(device_id, *args, **kwargs)

    coord._record_activity = counting
    before = int(record[DEV_EVENT_COUNT])
    hass.states.async_set(status, "alive")
    await hass.async_block_till_done()

    assert len(calls) == 1, (
        "the node coming back was recorded as the device speaking more than once",
        calls,
    )
    assert int(record[DEV_EVENT_COUNT]) == before + 1, (
        "one return counted as two events",
        before,
        record[DEV_EVENT_COUNT],
    )


async def test_r6_stale_unavailable_start_does_not_date_the_next_death(
    hass: HomeAssistant, freezer
):
    """A switch dropped briefly, then was switched off by its owner,
    leaving the status sensor alone: the saved start of the drop must
    not date the node's death hours later."""
    freezer.move_to(PIN)
    coord, device, switch, status, record = await _lonely(hass, freezer, 31, switch_on=True)

    hass.states.async_set(switch, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    assert record.get(DEV_DOWN_SINCE) is not None
    # The owner switches the value entity off while it is unavailable.
    er.async_get(hass).async_update_entity(
        switch, disabled_by=er.RegistryEntryDisabler.USER
    )
    hass.states.async_remove(switch)
    await hass.async_block_till_done()
    await registry_settled(hass)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None

    await walk(hass, freezer, 2 * 3600)
    death = dt_util.utcnow().timestamp()
    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "the death skipped its debounce on a stale saved start",
        record.get(DEV_FROZEN_SINCE),
    )
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] >= death - 1, (
        "the death was dated from an outage that ended hours before",
        record[DEV_FROZEN_SINCE],
        death,
    )


async def test_r6_saved_start_from_0264_does_not_date_the_next_death(
    hass: HomeAssistant, freezer
):
    """The same through the upgrade: 0.26.4 read the status sensor as a
    reading and could save [moment, "unavailable"] for a status-only
    device; 0.26.5 never clears it."""
    freezer.move_to(PIN)
    coord, device, _switch, status, record = await _lonely(hass, freezer, 32)
    record[DEV_DOWN_SINCE] = [dt_util.utcnow().timestamp() - 6 * 3600, "unavailable"]

    await walk(hass, freezer, 3600)
    death = dt_util.utcnow().timestamp()
    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None, "the death skipped its debounce"
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] >= death - 1, (
        record[DEV_FROZEN_SINCE],
        death,
    )


async def test_a7_rename_inside_rebuild_cooldown_keeps_outage_start(
    hass: HomeAssistant, freezer, monkeypatch
):
    freezer.move_to(PIN)
    coord, device, switch, status, record = await _lonely(
        hass, freezer, 70, switch_on=True
    )

    hass.states.async_set(switch, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    saved = record.get(DEV_DOWN_SINCE)
    assert saved is not None and saved[1] != "dead"
    tainted_before = record.get(DEV_TAINTED)

    # A rebuild ran inside the last cooldown, so this one waits.
    monkeypatch.setattr(
        coord._registry_debouncer, "async_schedule_call", lambda: None
    )
    new_id = "switch.p70_renamed"
    er.async_get(hass).async_update_entity(switch, new_entity_id=new_id)
    hass.states.async_remove(switch)
    hass.states.async_set(new_id, "unavailable")
    await hass.async_block_till_done()

    # The minute sweep, or any status sensor write, inside the window.
    coord._settle_down(device.id, None)

    assert record.get(DEV_DOWN_SINCE) == saved, (
        "a rename inside the rebuild cooldown ended an outage the device "
        "is still in",
        record.get(DEV_DOWN_SINCE),
        saved,
    )
    assert record.get(DEV_TAINTED) == tainted_before

    # The rebuild catches up: the start is still the original one.
    monkeypatch.undo()
    coord._rebuild_and_notify()
    coord._settle_down(device.id, None)
    assert record.get(DEV_DOWN_SINCE) == saved
