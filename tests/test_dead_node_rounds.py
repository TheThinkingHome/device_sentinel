# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds.py, Version: 0.26.5 (2026-10-16)

"""The first adversarial round on 0.26.5 (rulings #670, #671 and the
frozen sentence), 16 October 2026. Each test failed on the build as it
stood before the round's fixes."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
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
    SYS_DETAIL,
    SYS_DEVICE_PAGE,
    SYS_KIND,
    TODO_KIND_FROZEN,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import walk
from .test_zwave_dead_node import _house, _mine


# --------------------------------------------------------------- finding 1
# coordinator._on_state_changed (line ~3233) and _on_state_reported (line
# ~3384) guard "a value written while the connection is down is not the
# device speaking" for ESPHome (#640) only. A Z-Wave node reading dead
# still has every entity available, so any write to one of them (the
# statistics sensors Z-Wave rewrites as failed commands mount up, or the
# values handed back by a Z-Wave reload) runs _record_activity, which
# calls _clear_freeze_verdict: a recovery is announced for a node that is
# still dead, and the next sweeps raise the fault again.


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


# --------------------------------------------------------------- finding 2
# Tim's real P03 case: Z-Wave marks the node alive "with no other entity
# changing". No report runs, so _report_ends_down is never set, and
# problem_list._down_for falls back to the incident's opening, which is
# written only after the 180 s debounce. The recovered event (and the
# brief's duration) is then three to four minutes short of the dead
# stretch, where the report path counts it whole (#644: an outage that
# began as unavailable counts from when it went).


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


# --------------------------------------------------------------- finding 3
# narrative._frozen_span_sentence says "reported again at" for every
# resolved freeze, but a freeze can clear with no report at all: the wait
# grows (a day folds in, a setting changes). _down_for documents that
# path ("A freeze that cleared with no report ... counts from the last
# report"), and the resolved row cannot tell the composer which it was.


async def test_a_freeze_cleared_by_a_longer_wait_is_not_told_as_a_report(
    hass: HomeAssistant, freezer
):
    from .test_recovery_one_way import _armed_device, _minutes_on

    coord, device, _eid = await _armed_device(hass, freezer, "quiet1")
    await _minutes_on(hass, freezer, 240)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    heard = record[DEV_LAST_ACTIVITY]

    record[DEV_DAILY_MAX] = [12 * 3600.0] * (FREEZE_ARMING_DAYS + 2)
    await _minutes_on(hass, freezer, 1)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_LAST_ACTIVITY] == heard, "precondition: it never reported"

    rows = [
        r for r in coord.data[DATA_INCIDENTS]
        if r.get(INC_DEVICE_ID) == device.id and r.get(INC_KIND) == TODO_KIND_FROZEN
    ]
    opened = next(r for r in rows if r[INC_EVENT] == INCIDENT_OPENED)
    resolved = next(r for r in rows if r[INC_EVENT] == INCIDENT_RESOLVED)
    sentence = coord._compose_episode(opened, resolved)
    assert "reported again" not in sentence, sentence


# --------------------------------------------------------------- finding 4
# The frozen sentence across the autumn clock change, on a house that
# keeps daylight saving (Tim Plas, Minnesota). Quiet at 1:30 AM CDT, back
# at 1:10 AM CST forty minutes later: the sentence reads as a return
# before the stop.


async def test_a_freeze_across_the_fall_back_hour_does_not_read_backwards(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CDT
        verdict = datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc).timestamp()  # 1:05 AM CST
        back = datetime(2026, 11, 1, 7, 10, tzinfo=timezone.utc).timestamp()  # 1:10 AM CST
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
    assert "stopped reporting at 1:30 AM and reported again at 1:10 AM" not in sentence, sentence


# --------------------------------------------------------------- finding 5
# device_actions.page_enable_last_seen records "Last Seen turned on" for
# any enable, though from 0.26.5 it may have turned on only the Z-Wave
# status sensor, on a device with no Last Seen at all. The device's line
# in the brief then names an act that did not happen.


async def test_turning_on_only_the_z_wave_status_is_not_recorded_as_last_seen(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(
        hass, freezer, last_seen=False, status_on=False
    )
    assert coord.page_enable_last_seen(device.id) == 1
    rows = [
        r for r in coord.data.get(DATA_SYSTEM_EVENTS) or []
        if r.get(SYS_KIND) == SYS_DEVICE_PAGE
    ]
    assert rows
    assert "Last Seen turned on" not in str(rows[-1].get(SYS_DETAIL)), rows[-1]


# --------------------------------------------------------------- finding 6
# report_brief._recommendation_items names "Z-Wave status" among the
# disabled kinds and sends the reader to "the Enable buttons ... to turn
# them on by kind", but there is no Z-Wave status button: Enable Last
# Seen does it (#671). The Repairs text was updated to say so; the brief
# was not.


async def test_the_brief_names_the_button_that_turns_on_the_z_wave_status(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _house(hass, freezer, status_on=False)
    counts = coord.awaiting_enable_counts()
    assert counts["node_status"] == 1 and counts["last_seen"] == 0
    text = " ".join(i for i in coord._recommendation_items() if "Z-Wave status" in i)
    assert text
    assert "Enable Last Seen" in text, text
