# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_2.py, Version: 0.26.5 (2026-10-16)

"""The second adversarial round on 0.26.5, 16 October 2026. Each test
failed on the build as it stood before the round's fixes. One finding
is accepted rather than tested: a node status sensor switched off while
its node is dead says nothing from then on, so the device can be told
recovered from its cached values."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    DEV_FROZEN_CATEGORY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    TODO_DEVICE_ID,
    TODO_KIND_FROZEN,
    TODO_KIND_UNAVAILABLE,
    TODO_KINDS,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk
from .test_zwave_dead_node import _house, _mine

DAY = 86400.0


# ------------------------------------------------------------- finding A
# A Z-Wave device whose only enabled own entity is its node status
# sensor (every value entity disabled). _live_entity_states skips the
# status sensor, so after "alive" the states list is empty and
# _device_down_category returns the stored verdict through the
# _has_registered_entities branch: the device stays unavailable forever,
# though Z-Wave says the node is alive.


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


# ------------------------------------------------------------- finding B
# A status sensor that is unreadable (unavailable or unknown, as through
# a Z-Wave reload or a host reboot before Z-Wave JS has pinged its
# nodes) reads as "not dead". If the node's cached values come back
# before its status does, the guard in _on_state_changed lets them
# through, _republished returns False for an unavailable verdict, and a
# still-dead node is announced recovered, then faulted again once the
# status reads dead.


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


# ------------------------------------------------------------- finding C
# The status sensor switched off (or removed) while the node is dead:
# Home Assistant removes its state, _dead_node reads False, the cached
# values hold, and the next sweep announces a recovery for a node
# nobody heard. "A sensor that is switched off says nothing" should mean
# the verdict waits for the device to report, not that it recovered.


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


# ------------------------------------------------------------- finding E
# narrative._frozen_span_sentence adds zone names only when the naive
# local times run backwards. Across the autumn change, quiet at 1:10 AM
# CDT and back at 1:20 AM CST is seventy minutes, and the sentence reads
# "stopped reporting at 1:10 AM and recovered at 1:20 AM": ten minutes.
# Zone names are needed whenever the two offsets differ.


async def test_a_freeze_across_the_fall_back_hour_names_the_zones(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 6, 10, tzinfo=timezone.utc).timestamp()  # 1:10 AM CDT
        verdict = datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc).timestamp()  # 1:05 AM CST
        back = datetime(2026, 11, 1, 7, 20, tzinfo=timezone.utc).timestamp()  # 1:20 AM CST
        opened = {
            INC_DEVICE_ID: "d", INC_NAME: "Door Master", INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: INCIDENT_OPENED, INC_WHEN: verdict, INC_CAUSE: None, INC_DURATION: None,
        }
        resolved = dict(opened, **{
            INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: back, INC_DURATION: back - quiet,
        })
        sentence = coord._compose_episode(opened, resolved)
    finally:
        dt_util.set_default_time_zone(before)
    assert "at 1:10 AM and recovered at 1:20 AM" not in sentence, sentence
    assert "CDT" in sentence and "CST" in sentence, sentence

