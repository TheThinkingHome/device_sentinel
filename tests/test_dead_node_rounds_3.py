# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_3.py, Version: 0.26.5 (2026-10-16)

"""The third adversarial round on 0.26.5, 16 October 2026. Each test
failed on the build as it stood before the round's fixes. Accepted
rather than tested: a frozen device taken back counts from when it was
watched again (#650), so its sentence's quiet time is that moment;
and an unavailable device's paired sentence opens at its debounced
verdict while its span counts from when it went (#644), so the
recovery reads a few minutes late, as in 0.26.4. Correcting that for
every device was tried in round three and withdrawn in round four,
because it moved openings for escalations and across midnight."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
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
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import arm, walk
from .test_zwave_dead_node import _house, _mine


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


# ------------------------------------------------------------- finding 1
# detect_freeze._dead_node holds an unreadable status sensor as dead
# whenever ANY unavailable verdict stands, not only one a dead node
# raised. A person reloads Z-Wave to fix a node whose readings were all
# unavailable (status alive): the status sensor reads unavailable with
# the rest, the readings come back first and are thrown away as "values
# written while the node is dead", the status then reads alive (not dead
# before, so no contact), and the next sweep turns the standing
# unavailable verdict into a false frozen one: the device's clock never
# moved through six hours. 0.26.4 took the returning value as the
# recovery (#535).


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


# ------------------------------------------------------------- finding 1b
# The same hold, stuck: the status sensor reads Z-Wave's own "unknown"
# (the node status after a Z-Wave JS restart until the node is heard),
# which is STATE_UNKNOWN and so unreadable. The readings are back and
# changing, every one is discarded, and the device stays unavailable for
# as long as the status reads unknown, though it was never dead.


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


# ------------------------------------------------------------- finding 2
# The node's contact is read only from a "dead" -> "alive" change. A dead
# node through a Z-Wave reload or a Home Assistant restart goes dead ->
# unavailable (held) -> alive: Z-Wave pinged it on starting and heard it.
# The coordinator neither records the contact nor dates the recovery
# (_node_came_back), so the device's clock stays at its last report six
# hours back and the next sweep calls it frozen.


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


# ------------------------------------------------------------- finding 3
# The frozen sentence was fixed for a duration that counts from before
# the opening; the unavailable one was not. Since #644 (amended) an
# unavailable recovery counts from when the device went, and the opening
# is written after the 180 s debounce, so "became unavailable at <opening>
# and recovered <span> later" puts the recovery minutes after it came.
# From 0.26.5 _node_came_back makes this every dead node's sentence:
# P03, dead at 6:53:06 PM, opened about 6:57 PM, alive at 8:13:02 PM.


# ------------------------------------------------------------- finding 4
# narrative._frozen_span_sentence names the zones only when the two times
# fall on the same date (`elif`). Quiet at 11:00 PM CDT on 31 October and
# back at 1:30 AM CST on 1 November is three and a half hours; the
# sentence "stopped reporting at Oct 31, 11:00 PM and recovered at 1:30
# AM" reads two and a half.


async def test_a_freeze_across_midnight_and_the_clock_change_names_the_zones(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    before = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Chicago"))
    try:
        quiet = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc).timestamp()  # 11:00 PM CDT, Oct 31
        verdict = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CDT
        back = datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc).timestamp()  # 1:30 AM CST
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
    assert "CDT" in sentence and "CST" in sentence, sentence
