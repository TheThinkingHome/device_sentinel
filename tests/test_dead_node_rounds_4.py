# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_4.py, Version: 0.26.5 (2026-10-16)

"""The fourth adversarial round on 0.26.5, 16 October 2026: the saved
dead word ends with its node and outlives a restart however the outage
began, and an escalated pair keeps the moment it was marked."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
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
    TODO_KIND_FROZEN,
    TODO_KIND_UNAVAILABLE,
)
from custom_components.device_sentinel.escalation import ESCALATED_FROM

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, rec, restart, walk
from .test_zwave_dead_node import _house, _mine

DAY = 86400.0


# ------------------------------------------------------------- finding 1
# coordinator._settle_down returns early when _down_now is None, and a
# device whose only live entity is its node status sensor (finding A of
# round two) always reads None once the status is alive: the status is
# skipped by _live_entity_states and nothing else has a state. So the
# saved [moment, "dead"] is never cleared on the recovery. The next time
# the node dies, _settle_down keeps the stale moment, _outage_began dates
# the new verdict from the old death, the debounce is skipped, and the
# new outage's "down for" runs from the first one. The stale "dead" also
# makes every later alive or awake count as "back from dead".


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


# ------------------------------------------------------------- finding 2
# narrative._went_down_at moves the opening of every unavailable or
# unknown pair to resolved.when - resolved.duration, but ignores the
# escalation copy (ESCALATED_FROM). A device frozen and then marked
# unavailable (a Z-Wave node dead while a freeze stood, an ESPHome drop,
# Wi-Fi) began as a freeze, so its recovery counts from its last report
# (#644). The opening is then rewritten to the start of the silence:
# "was marked unavailable from frozen at 1:00 AM" for a device marked
# unavailable at 5:00 AM, a time that may fall before the brief window.
# _frozen_span_sentence already refuses a change clause; this did not.


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


# ------------------------------------------------------------- finding 3
# The saved down state is upgraded to "dead" only when the outage starts
# with it. A node whose readings all went unavailable first (a Z-Wave JS
# server restart) and that comes back from it dead keeps
# [moment, "unavailable"]. Across a Home Assistant restart, while the
# status reads Z-Wave's own "unknown" (not yet pinged), the cached values
# are taken as the device back: a recovery, then a second fault once the
# status reads dead again. The round-three hold covers only an outage
# that began dead.


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


# ------------------------------------------------------------- finding 4
# _went_down_at can move the opening to an earlier day (an outage saved
# before a restart and published after it, or one that began minutes
# before midnight), and the sentence gives a bare clock time:
# "went unavailable at 10:00 PM and recovered 9 hours later" in the
# morning's brief reads as 10 PM today. _frozen_span_sentence names the
# date when the days differ; this sentence should too.


