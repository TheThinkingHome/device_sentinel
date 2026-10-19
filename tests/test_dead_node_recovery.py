# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dead_node_recovery.py, Version: 0.26.7 (2026-10-19)

"""What counts as a Z-Wave device back from a dead node (rulings #670,
#671), from the adversarial rounds on 0.26.5 of 16 October 2026,
regrouped by subject in 0.26.7 (#707). Each test failed on the build
as it stood before its round's fixes.

Accepted rather than tested: a node status sensor switched off while
its node is dead says nothing from then on, so the device can be told
recovered from its cached values.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
    INCIDENT_RESOLVED,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    SYS_DETAIL,
    SYS_DEVICE_PAGE,
    SYS_KIND,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_KIND_UNAVAILABLE,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk
from .test_zwave_dead_node import _house, _mine

DAY = 86400.0

async def _readings_gone_for_six_hours(hass, freezer):
    """A Z-Wave plug whose readings all went unavailable while Z-Wave
    still called the node alive (a re-interview that hung, the node not
    ready): an unavailable verdict that is not a dead node."""
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    arm(coord, device.id, rhythm=3600.0)
    hass.states.async_set(ids["switch"], "off")  # a report
    await hass.async_block_till_done()
    heard = record[DEV_LAST_ACTIVITY]
    hass.states.async_set(ids["switch"], "unavailable")
    hass.states.async_set(ids["rssi"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * 3600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert device.id not in coord._dead_nodes, "precondition: never dead"
    return coord, device, ids, record, heard


async def test_a_value_written_while_the_node_is_dead_is_not_a_recovery(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)
    heard = record[DEV_LAST_ACTIVITY]

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(_mine(faults, device.id)) == 1

    # The same values written again (state_reported), as Z-Wave does when
    # it refreshes a node's statistics after a failed command.
    hass.states.async_set(ids["rssi"], "-42")
    hass.states.async_set(ids["switch"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)

    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(recoveries, device.id), "a dead node was announced recovered"
    assert len(_mine(faults, device.id)) == 1, "the same dead stretch faulted twice"
    assert record[DEV_LAST_ACTIVITY] == heard, "a write while dead was taken as the node speaking"


async def test_a_z_wave_reload_while_the_node_is_dead_is_not_a_recovery(
    hass: HomeAssistant, freezer
):
    """Z-Wave reloads (or its server reconnects) inside the integration
    outage dwell: every entity reads unavailable for a moment and comes
    back with Z-Wave's cached values. _republished returns False for a
    device with an unavailable verdict, so the cached values are taken as
    the genuine recovery #535 names, though the node is still dead."""
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)
    heard = record[DEV_LAST_ACTIVITY]

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    for key in ("switch", "rssi", "status"):
        hass.states.async_set(ids[key], "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(ids["status"], "dead")
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)

    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(recoveries, device.id)
    assert len(_mine(faults, device.id)) == 1
    assert record[DEV_LAST_ACTIVITY] == heard


async def test_alive_alone_counts_the_whole_dead_stretch(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer)
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 80 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    hass.states.async_set(ids["status"], "alive")  # nothing else changes
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)

    assert record[DEV_FROZEN_CATEGORY] is None
    back = _mine(recoveries, device.id)
    assert len(back) == 1
    assert back[0]["down_for"] >= 80 * 60, back[0]


async def test_turning_on_only_the_z_wave_status_is_not_recorded_as_last_seen(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(
        hass, freezer, last_seen=False, status_on=False
    )
    assert coord.page_turn_on(device.id, "node_status") == 1
    rows = [
        r for r in coord.data.get(DATA_SYSTEM_EVENTS) or []
        if r.get(SYS_KIND) == SYS_DEVICE_PAGE
    ]
    assert rows
    assert "Last Seen turned on" not in str(rows[-1].get(SYS_DETAIL)), rows[-1]
    assert "Z-Wave status turned on" in str(rows[-1].get(SYS_DETAIL)), rows[-1]


async def test_a_device_with_only_its_status_sensor_recovers_on_alive(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", "4191921521-20")},
        name="P20 Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    switch = reg.async_get_or_create(
        "switch", "zwave_js", "4191921521.20-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    ).entity_id
    status = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.20.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    assert switch
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id in coord._node_status_entity
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    hass.states.async_set(status, "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None, "stuck unavailable after alive"
    assert len(_mine(recoveries, device.id)) == 1


async def test_values_back_before_the_status_after_a_reload_are_not_a_recovery(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(_mine(faults, device.id)) == 1

    # Z-Wave reloads: everything unavailable for a moment.
    for key in ("switch", "rssi", "status"):
        hass.states.async_set(ids[key], "unavailable")
    await hass.async_block_till_done()
    # The value platforms come back first, with Z-Wave's cached values.
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    # Then the status sensor, still dead.
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)

    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(recoveries, device.id), "a still-dead node was announced recovered"
    assert len(_mine(faults, device.id)) == 1, "one dead stretch faulted twice"


async def test_alive_after_a_long_dead_stretch_does_not_leave_it_listed_unavailable(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    arm(coord, device.id, rhythm=3600.0)
    hass.states.async_set(ids["switch"], "off")  # a report
    await hass.async_block_till_done()

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * 3600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    hass.states.async_set(ids["status"], "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 180)

    items = [
        i for i in coord.data.get(DATA_TODO_ITEMS) or []
        if i.get(TODO_DEVICE_ID) == device.id
    ]
    kinds = set(items[0].get(TODO_KINDS) or {}) if items else set()
    assert TODO_KIND_UNAVAILABLE not in kinds, (
        "Z-Wave calls the node alive, yet the list still says unavailable", kinds,
        record[DEV_FROZEN_CATEGORY],
    )
    resolved = [
        r for r in coord.data[DATA_INCIDENTS]
        if r.get(INC_DEVICE_ID) == device.id
        and r.get(INC_KIND) == TODO_KIND_UNAVAILABLE
        and r.get(INC_EVENT) == INCIDENT_RESOLVED
    ]
    assert resolved, "the unavailable incident never closed"


async def test_readings_back_through_a_z_wave_reload_end_an_outage_that_was_not_a_dead_node(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record, heard = await _readings_gone_for_six_hours(hass, freezer)
    recoveries = record_events(hass, EVENT_RECOVERED)
    faults = record_events(hass, EVENT_FAULT)

    hass.states.async_set(ids["status"], "unavailable")  # Z-Wave reloads
    await hass.async_block_till_done()
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    hass.states.async_set(ids["status"], "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 180)

    assert record[DEV_FROZEN_CATEGORY] is None, record[DEV_FROZEN_CATEGORY]
    assert record[DEV_LAST_ACTIVITY] is not None and record[DEV_LAST_ACTIVITY] > heard
    assert len(_mine(recoveries, device.id)) == 1
    assert not _mine(faults, device.id), "a false frozen fault after the reload"


async def test_an_unknown_status_does_not_hold_a_device_that_was_never_dead(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record, heard = await _readings_gone_for_six_hours(hass, freezer)

    hass.states.async_set(ids["status"], "unknown")
    await hass.async_block_till_done()
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    hass.states.async_set(ids["switch"], "off")  # a fresh, real report
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)

    assert record[DEV_FROZEN_CATEGORY] is None, "stuck unavailable on an unknown status"
    assert record[DEV_LAST_ACTIVITY] > heard, "real reports were discarded"


async def test_dead_then_unreadable_then_alive_is_the_node_coming_back(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    arm(coord, device.id, rhythm=3600.0)
    hass.states.async_set(ids["switch"], "off")
    await hass.async_block_till_done()
    heard = record[DEV_LAST_ACTIVITY]
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * 3600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    # Z-Wave reloads; its cached values come back (rightly ignored), and
    # the node, pinged as Z-Wave starts, answers.
    hass.states.async_set(ids["status"], "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(ids["switch"], "on")
    hass.states.async_set(ids["rssi"], "-42")
    await hass.async_block_till_done()
    hass.states.async_set(ids["status"], "alive")
    await hass.async_block_till_done()
    await walk(hass, freezer, 180)

    assert record[DEV_FROZEN_CATEGORY] is None, record[DEV_FROZEN_CATEGORY]
    assert record[DEV_LAST_ACTIVITY] > heard
    back = _mine(recoveries, device.id)
    assert len(back) == 1
    assert back[0]["down_for"] >= 6 * 3600 - 120, back[0]
