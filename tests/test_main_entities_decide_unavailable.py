# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_main_entities_decide_unavailable.py, Version: 0.27.5 (2026-10-26)

"""A device's main entities decide whether it is unavailable.

The main entities are the ones Home Assistant puts in no category. A
device is unavailable when they read unavailable and no entity of its
own is actively reporting; a report through another entity keeps it
alive only for its freeze window, or an hour while it is still
learning. Unknown, and an event entity at rest, count as nothing: a
standing verdict is held until the device reports, and the clock
judges the rest (James, 17 and 18 October 2026). Found by the
adversarial rounds of 0.26.6.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, restart, walk
from .test_freeze_and_unavailable_mutes import _all, _gone, _items, _listed_kinds
from .test_freeze_unavailable_split import _mine, _ready

HOUR = 3600.0


# -------------------------------------------- the main entities decide


def _rec(coord, device_id):
    return coord.data["devices"][device_id]


# 1. Control: main entity unavailable, diagnostic held by the stack: judged
# unavailable on the main entity (rule 5).
async def test_1a_control_main_unavailable_diag_held(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r10a")
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# 1. Rule 5: a device whose only main entity reads unavailable while its
# diagnostic keeps reporting fresh values. Judged unavailable on the main
# entity; each diagnostic report is the device reporting (#529) and ends
# the verdict; the sweep lists it again. Over four hours, one outage that
# never ended: how many faults and recoveries are told?
async def test_r18_1_a_device_reporting_through_a_diagnostic_is_alive(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r18a")
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    value = 80
    for _ in range(8):
        value += 1
        hass.states.async_set(ids["x0"], str(value))
        await hass.async_block_till_done()
        await walk(hass, freezer, 30 * 60)
    items = [i for i in coord.todo_items if i["device_id"] == device.id]
    # A device actively reporting is alive, whatever its main entity
    # reads (James, 17 October 2026): told down once, back once at its
    # first report, and not listed again while it keeps reporting.
    assert len(_mine(faults, device.id)) == 1
    assert len(_mine(back, device.id)) == 1
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not items


async def _alive_through_battery(hass, freezer, uid, options=None):
    coord, device, ids, record = await _ready(hass, freezer, uid, options)
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    hass.states.async_set(ids["x0"], "81")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    return coord, device, ids, record, faults, back


# 1. Rule 5 then the whole device goes: the door reading is gone, the
# battery reports once (alive), then the battery goes unavailable too.
# Every entity of its own reads unavailable and nothing reports; the
# device is never judged unavailable again.
async def test_r19_1_whole_device_down_after_one_report(hass: HomeAssistant, freezer):
    coord, device, ids, record, faults, back = await _alive_through_battery(hass, freezer, "r19a")
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, (
        "every entity unavailable, not judged down", record[DEV_FROZEN_CATEGORY])


# 1b. As 1 with a freeze mute (rule 1: still reported when unavailable).
async def test_r19_1b_freeze_muted_whole_device_down_never_reported(hass: HomeAssistant, freezer):
    coord, device, ids, record, faults, back = await _alive_through_battery(
        hass, freezer, "r19b", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    n = len(_mine(faults, device.id))
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    assert len(_mine(faults, device.id)) == n + 1


# 1. Rule 5: main entity gone, the diagnostic reports once, then the
# device dies and the diagnostic only holds its value. Freeze-muted, so
# only an unavailable verdict could ever tell it.
async def test_r21_1_one_old_report_keeps_a_dead_device_alive(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r21a", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    hass.states.async_set(ids["x0"], "85")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 24 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, (
        "main unavailable three days, one diagnostic report three days ago, nothing since",
        record[DEV_FROZEN_CATEGORY], coord._reporting_through_others(device.id))


# ----------------------- unknown and an event at rest count as nothing


# (c)/(f) A device whose only main entity is an event entity at rest:
# _states_of turns its unknown into EVENT_RESTING, so the "all main
# entities read unknown" fallback in _live_entity_states
# (coordinator.py 5084-5090) never fires and the diagnostic going
# unavailable is never read. On 0.26.5 this device was unavailable.
async def test_a_device_whose_only_main_entity_is_an_event_at_rest_is_read_on_all(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(
        hass, freezer, "zz3", main="event",
        extras=(("sensor", EntityCategory.DIAGNOSTIC),))
    hass.states.async_set(ids["main"], "unknown")
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# (f) A standing unknown verdict from 0.26.5 is cleared on the first
# sweep (detect_freeze.py 755-785 return None for all-unknown when the
# clock is short of the window) and retires as a recovery while the
# device still says nothing. The docstring of the existing test
# test_an_unknown_problem_standing_at_the_upgrade_waits_for_the_device
# promises the hold, but that test never checks for a recovery.
async def test_an_unknown_problem_standing_at_the_upgrade_is_not_announced_recovered(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "zz2")
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNKNOWN
    record["frozen_since"] = dt_util.utcnow().timestamp()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert _items(coord, device.id), "precondition: the 0.26.5 unknown item stands"
    back = record_events(hass, EVENT_RECOVERED)
    await walk(hass, freezer, 10 * 60)
    assert not _mine(back, device.id), "a rule change is not a recovery (#529)"
    assert _items(coord, device.id)


# R2-1. detect_freeze.py 794-795: with every entity reading unknown, a
# standing UNKNOWN verdict (from 0.26.5) is returned before the freeze
# clock is read, so a device silent far past its window is never called
# frozen. 0.26.5 escalated it (FREEZE_CATEGORY_PRIORITY), and rule 4 says
# unknown counts as nothing, leaving the clock to judge.
async def test_a_standing_unknown_on_an_all_unknown_device_still_goes_frozen_by_the_clock(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r2a")
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNKNOWN
    record["frozen_since"] = dt_util.utcnow().timestamp()
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


# A. Control: an unavailable device whose entities then read unknown keeps
# its verdict until it reports (rule 4, standing branch).
async def test_a_control_unmuted_unavailable_then_unknown_holds(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8a")
    await _gone(hass, freezer, ids)
    since0 = record[DEV_FROZEN_SINCE]
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] == since0


# 1b. The same device's main entity then reads unknown, the stack still
# holding the diagnostic; the device never reports. Rule 4: unknown counts
# as nothing and a standing verdict is held until the device reports.
async def test_1b_main_goes_unknown_diag_held_no_false_recovery(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r10b")
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    hass.states.async_set(ids["main"], "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    assert not _mine(back, device.id), "recovered without reporting"


# 1c. As 1b through a restart: an MQTT-style main entity comes back unknown
# (no retained value), the diagnostic restored. The device is still dead.
async def test_1c_restart_main_unknown_diag_held(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r10c")
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def _states():
        hass.states.async_set(ids["main"], "unknown")
        hass.states.async_set(ids["x0"], "87")

    # Known Gap 63, the boot hand-back read as a report: states kept.
    coord = await restart(hass, freezer, down=120, before_setup=_states, keep_states=True)
    await walk(hass, freezer, 20 * 60)
    record = _rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    assert not _mine(back, device.id), "recovered without reporting"


DIAG = ("sensor", EntityCategory.DIAGNOSTIC)


# C. Rules 4/5: only main entity an event entity; it goes unavailable, then
# back to rest (unknown) while the stack still holds the diagnostic. The
# binary_sensor twin (round 10, test 1b) is held; this one recovers.
async def test_c_event_main_back_to_rest_diag_held(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r11d", main="event", extras=(DIAG,))
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, (coord._live_entity_states(device.id), record[DEV_FROZEN_SINCE], record.get("down_since"), coord._grace_until - dt_util.utcnow().timestamp())
    hass.states.async_set(ids["main"], "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert not _mine(back, device.id), ("recovered without reporting", record[DEV_FROZEN_CATEGORY])
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]


# U1. Never muted: a 60 s drop (inside the 180 s debounce), then every
# entity reads unknown (a stack restart), no report, for an hour.
async def test_u1_short_drop_then_unknown(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u1")
    faults = record_events(hass, EVENT_FAULT)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 60)
    await _all(hass, ids, "unknown")
    trail = []
    for _ in range(12):
        await walk(hass, freezer, 60)
        trail.append((record[DEV_FROZEN_CATEGORY], _listed_kinds(coord, device.id)))
    await walk(hass, freezer, HOUR, step=300)
    _ = ("U1 trail", trail, "end", record[DEV_FROZEN_CATEGORY], _listed_kinds(coord, device.id),
          "down_since", record.get(DEV_DOWN_SINCE), "faults", len(_mine(faults, device.id)))
    assert record[DEV_FROZEN_CATEGORY] is None, ("listed unavailable while reading unknown after a 60s blip",
                                                 record[DEV_FROZEN_CATEGORY], _listed_kinds(coord, device.id))


def _remote(hass, uid):
    """A Zigbee remote as Zigbee2MQTT gives it: an action sensor (main,
    no category) and a battery and a link quality (diagnostic)."""
    source = MockConfigEntry(domain="test", title="test")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=f"Remote {uid}")
    reg = er.async_get(hass)
    main = reg.async_get_or_create("sensor", "test", f"{uid}_action", device_id=device.id,
                                   config_entry=source).entity_id
    batt = reg.async_get_or_create("sensor", "test", f"{uid}_batt", device_id=device.id,
                                   config_entry=source, entity_category=EntityCategory.DIAGNOSTIC).entity_id
    lqi = reg.async_get_or_create("sensor", "test", f"{uid}_lqi", device_id=device.id,
                                  config_entry=source, entity_category=EntityCategory.DIAGNOSTIC).entity_id
    return device, main, batt, lqi


async def _report_for(hass, freezer, lqi, seconds, every=1800):
    value = 100
    for _ in range(int(seconds // every)):
        await walk(hass, freezer, every)
        value = 101 if value == 100 else 100
        hass.states.async_set(lqi, str(value))
        await hass.async_block_till_done()


# 1. Rule 5 with #647: a remote whose action sensor (its only main entity)
# reads unknown, as one does until first pressed, while its link quality
# reports every half hour. It is not down: its clock moves, no verdict is
# given. But _down_now reads only the main entity, so the outage start is
# saved the moment the action goes unknown and is never cleared while the
# device reports. When the remote really drops, two days later, it is
# listed from that old start, published inside the debounce.
async def test_r17_1_reporting_device_with_unknown_main_has_no_outage_start(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, main, batt, lqi = _remote(hass, "r17a")
    hass.states.async_set(main, "single")
    hass.states.async_set(batt, "87")
    hass.states.async_set(lqi, "100")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    await _report_for(hass, freezer, lqi, 2 * 24 * HOUR)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_DOWN_SINCE] is None, ("outage start saved on a reporting device", record[DEV_DOWN_SINCE])


async def test_r17_2_later_drop_dated_from_the_drop(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, main, batt, lqi = _remote(hass, "r17b")
    hass.states.async_set(main, "single")
    hass.states.async_set(batt, "87")
    hass.states.async_set(lqi, "100")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    await _report_for(hass, freezer, lqi, 2 * 24 * HOUR)
    drop = dt_util.utcnow().timestamp()
    for eid in (main, batt, lqi):
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    assert record[DEV_FROZEN_CATEGORY] is None, ("published inside the debounce", record[DEV_FROZEN_SINCE])
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    since = record[DEV_FROZEN_SINCE]
    assert since >= drop - 120, ("dated before the drop by hours", (drop - since) / HOUR)


# 6. As 2, the remote then dropping out four times in two hours, each drop
# ten minutes, its link quality back between them, the action still unknown.
# Every drop is dated from the same stale start, so none counts as new.
async def test_r17_6_dropping_out_with_unknown_main_is_seen(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, main, batt, lqi = _remote(hass, "r17f")
    hass.states.async_set(main, "single")
    hass.states.async_set(batt, "87")
    hass.states.async_set(lqi, "100")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    await _report_for(hass, freezer, lqi, 6 * HOUR)
    sinces = []
    for n in range(4):
        for eid in (main, batt, lqi):
            hass.states.async_set(eid, "unavailable")
        await hass.async_block_till_done()
        await walk(hass, freezer, 10 * 60)
        sinces.append(record[DEV_FROZEN_SINCE])
        hass.states.async_set(main, "unknown")
        hass.states.async_set(batt, "87")
        hass.states.async_set(lqi, str(90 + n))
        await hass.async_block_till_done()
        await walk(hass, freezer, 15 * 60)
    assert coord.is_flapping(device.id), ("drops dated", sinces, record.get("flap_drops"))
