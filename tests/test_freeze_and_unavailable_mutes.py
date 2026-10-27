# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_freeze_and_unavailable_mutes.py, Version: 0.27.10 (2026-10-27)

"""The freeze mute and the unavailable mute, each its own kind (rules
MUTE-06, MUTE-07, MUTE-08).

The freeze mute silences what is judged from silence: frozen and never
reported. The unavailable mute, by label or device, silences unavailable
and dropping out. Neither one hides the other's trouble, a mute is never
a recovery, and a mute lifted while the device is still down lists it
again from when its trouble began, with a push. At the first update a
label or device muted for freeze is muted for unavailable too, so
nothing changes on an upgraded house; an integration muted for freeze
stays freeze only. The settings screen saves and prunes the two
sections apart, and the reports name each mute (rule MUTE-10).
"""

from __future__ import annotations

import datetime
import time
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_LABELS,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_DOWN_BEGAN_AS,
    DEV_DOWN_SINCE,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FLAP_DROPS,
    DEV_FLAP_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DOMAIN,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    OPTIONS_MINOR_VERSION,
    SYS_DETAIL,
)

from custom_components.device_sentinel.config_flow import settle_options

from .helpers import record_events, setup_coordinator
from .outage_helpers import past_grace, restart, walk
from .test_exclusions import _register
from .test_freeze_unavailable_split import _mine, _ready
from .test_zwave_dead_node import _house as _zwave_house

HOUR = 3600.0


# --------------------------------------------- what each mute silences


async def test_a_device_off_at_the_wall_and_muted_for_unavailable_is_never_told(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "u1", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 24 * HOUR, step=1800)
    assert record[DEV_FROZEN_CATEGORY] is None, "off for days: neither unavailable nor frozen"
    assert not _mine(faults, device.id)


async def test_an_unavailable_muted_device_that_goes_quiet_is_called_frozen(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u2", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _mine(faults, device.id)


@pytest.mark.parametrize(
    ("uid", "kwargs"),
    [("u3a", {}), ("u3b", {"main": "event", "extras": (("sensor", None),)})],
)
async def test_an_unavailable_muted_device_reading_only_unknown_is_judged_by_its_clock(
    hass: HomeAssistant, freezer, uid, kwargs
):
    """Never gone as unavailable, an unavailable-muted device is frozen
    once silent past its window (rule MUTE-06)."""
    coord, device, ids, record = await _ready(hass, freezer, uid, {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}, **kwargs)
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _mine(faults, device.id)


async def test_an_unavailable_muted_device_back_inside_the_grace_is_not_called_frozen(
    hass: HomeAssistant, freezer
):
    """Its return inside the grace is the device back, not the stack
    republishing, so it is not called frozen (rule MUTE-06)."""
    coord, device, ids, record = await _ready(hass, freezer, "u4", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] is None
    coord._grace_until = dt_util.utcnow().timestamp() + 300
    faults = record_events(hass, EVENT_FAULT)
    for key, eid in ids.items():
        hass.states.async_set(eid, "on" if key == "main" else "86")
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)


async def test_an_unavailable_muted_device_is_still_told_never_reported(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u5", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    now = dt_util.utcnow().timestamp() + 30 * 86400
    assert coord._device_down_category(device.id, record, now) == FREEZE_CATEGORY_NEVER_REPORTED


async def test_a_label_muted_for_unavailable_silences_unavailable_only(hass: HomeAssistant, freezer):
    label = lr.async_get(hass).async_create("Wall switched")
    coord, device, ids, record = await _ready(hass, freezer, "u7", {CONF_UNAVAILABLE_MUTED_LABELS: [label.label_id]})
    dr.async_get(hass).async_update_device(device.id, labels={label.label_id})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await past_grace(hass, freezer)
    assert coord._unavailable_muted(device.id)
    assert coord.mute_text(device.id) == "unavailable (label: Wall switched)"
    assert coord.label_meaning(label.label_id) == "mutes unavailable"
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    record = coord.data["devices"][device.id]
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)


async def test_a_freeze_mute_alone_is_still_told_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u8", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _mine(faults, device.id)


def _items(coord, device_id):
    return [i for i in coord.todo_items if i["device_id"] == device_id]


# (b)/(d) An unavailable-muted device that is frozen and then goes
# unavailable keeps its frozen item: the freeze is not muted, so the
# frozen kind does not retire as a recovery (rule MUTE-06).
async def test_unavailable_mute_does_not_turn_a_frozen_device_going_unavailable_into_a_recovery(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(
        hass, freezer, "zz1", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _items(coord, device.id), "precondition: the frozen device is listed"
    back = record_events(hass, EVENT_RECOVERED)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert not _mine(back, device.id), "the device never reported; nothing recovered"


async def _stepped_back(hass, freezer, uid):
    """An unavailable item held over a verdict that stepped back to
    frozen while the entities are not loaded (rule LIST-07)."""
    coord, device, ids, record = await _ready(hass, freezer, uid)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    for eid in ids.values():
        hass.states.async_remove(eid)
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert [list(i["kinds"]) for i in _items(coord, device.id)] == [["unavailable"]], "precondition: held"
    return coord, device


# (d) A freeze mute on a held item whose shown kind is unavailable does
# not retire the item as a recovery, because the unavailable trouble is
# not muted (rule MUTE-06).
async def test_a_freeze_mute_on_a_held_unavailable_item_is_not_a_recovery(
    hass: HomeAssistant, freezer
):
    coord, device = await _stepped_back(hass, freezer, "zz4")
    back = record_events(hass, EVENT_RECOVERED)
    coord.page_set_mute(device.id, "freeze", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert not _mine(back, device.id), "a mute is not a recovery (#537)"


# (d) The hold never keeps a down kind the person has muted, so an
# unavailable mute does not leave "unavailable" on the item while
# frozen arrives beneath it (rule MUTE-06).
async def test_the_hold_never_keeps_a_kind_the_person_muted(hass: HomeAssistant, freezer):
    coord, device = await _stepped_back(hass, freezer, "zz5")
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert all("unavailable" not in i["kinds"] for i in _items(coord, device.id))


# (a)/(b) A freeze-muted device that has never reported and whose every
# main entity reads unavailable is still reported unavailable, because
# the freeze mute covers only what is judged from silence (rule MUTE-06).
async def test_a_freeze_muted_never_reported_device_that_is_unavailable_is_reported(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(
        hass, freezer, "zz6", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    now = dt_util.utcnow().timestamp() + 30 * 86400
    assert coord._device_down_category(device.id, record, now) == FREEZE_CATEGORY_UNAVAILABLE


# The probe reads the unavailable mute as well as the freeze mute, so
# an unavailable-muted Z-Wave node the stack calls dead reads as muted,
# not "reporting" and a disagreement (rule STACK-12).
async def test_the_probe_reads_an_unavailable_muted_dead_node_as_muted(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _zwave_house(hass, freezer)
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_UNAVAILABLE_MUTED_DEVICES: [device.id]})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    view = coord._probe_views(
        {"device_id": device.id, "stack": "zwave_js", "now": "dead", "detail": ""},
        dt_util.utcnow().timestamp(),
    )
    assert view["agrees"] != "no"


# A device frozen, then escalated to unavailable, then muted for
# unavailable from its item (the mute the list offers for that kind),
# is silent past its window and its freeze is not muted, so it stays
# frozen on the list, as it does when muted first
# (test_unavailable_mute_does_not_turn_a_frozen_device_going_unavailable_into_a_recovery)
# (rule MUTE-06).
async def test_an_unavailable_mute_set_after_the_escalation_still_leaves_the_freeze(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r2c")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "precondition: frozen"
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: escalated"
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _items(coord, device.id), "the freeze is not muted; the device stays listed"


# A device that froze, went unavailable, then read unknown, and is then
# muted for unavailable from its item, keeps its freeze. Losing the
# verdict on the first sweep would let the clock call it frozen afresh
# on the next: a second "stopped reporting" item and push, dated now.
# How the trouble began decides, whatever the device reads now; the
# same holds with nothing readable after a restart (rule MUTE-06).
async def test_an_unavailable_mute_keeps_the_freeze_of_a_device_now_reading_unknown(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r3a")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "precondition: frozen"
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: escalated"
    assert record[DEV_DOWN_BEGAN_AS] == FREEZE_CATEGORY_FROZEN, "precondition: began frozen"
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: held (#529)"
    since = record[DEV_FROZEN_SINCE]
    assert since is not None
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] is not None, "the freeze is not muted (#529)"
    for _ in range(5):
        await walk(hass, freezer, 60)
        record = coord.data[DATA_DEVICES][device.id]
        assert record[DEV_FROZEN_CATEGORY] is not None, "never cleared while nothing was heard"
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] == since, "the same freeze, not a new one dated now"
    assert _items(coord, device.id), "the device stays listed"


# A device that went unavailable and now reads only unknown is held
# unavailable. Muting it for unavailable must not clear the record and
# let the next sweep call it frozen from the clock: that would raise a
# new "stopped reporting" item and push for a trouble that began as
# unavailable, by the act of muting it. Unmuted, the same device stays
# unavailable and is never re-told as frozen (rules MUTE-06, MUTE-07).
async def test_an_unavailable_mute_does_not_turn_a_held_drop_into_a_new_freeze(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r4a")
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: unavailable"
    assert record[DEV_DOWN_BEGAN_AS] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: began unavailable"
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "precondition: held (#529)"

    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    faults = record_events(hass, EVENT_FAULT)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 6 * HOUR, step=600)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] != FREEZE_CATEGORY_FROZEN, (
        "a trouble that began as unavailable is not re-told as a freeze by muting it"
    )
    assert not [e for e in faults if e.get("device_id") == device.id], "no new alert after the mute"
    assert not _items(coord, device.id), "the item left as muted and does not come back"


# A device already unavailable when its integration, bridge or Wi-Fi
# goes keeps its own row. Muted for unavailable while the upstream is
# down, the sweep never runs on it, so its stored verdict would stand
# and keep the muted item on the Problem List, in the Device problem
# sensor and in reports for the whole outage. The mute takes the item
# off at once; the same holds for a freeze mute on a frozen device
# (rules MUTE-07, UP-05).
async def test_a_mute_set_while_the_upstream_holds_the_device_takes_its_item_off(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r6a")
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _items(coord, device.id), "precondition: the unavailable device is listed"
    went = dt_util.utcnow().timestamp()
    real = coord.upstream_down_since
    coord.upstream_down_since = (
        lambda device_id: ("test", went) if device_id == device.id else real(device_id)
    )
    await walk(hass, freezer, 120)
    assert _items(coord, device.id), "precondition: broken before its upstream, it keeps its row"
    back = record_events(hass, EVENT_RECOVERED)
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert not _items(coord, device.id), "muted for unavailable, the item must leave"
    assert device.id not in {r["device_id"] for r in coord.reportable_down_rows}
    assert not _mine(back, device.id), "a mute is not a recovery (#537)"


# A mute from the Problem List takes the item off at once, not at the
# next minute tick: the stored verdict goes with it, so the panel's
# refresh right after the Mute chip draws no item, and a fault push held
# for its settle delay is not sent for a device the person has just
# muted (rule MUTE-07).
async def test_a_mute_from_the_problem_list_takes_the_item_off_at_once(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "r6b")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _items(coord, device.id), "precondition: the frozen device is listed"
    # The freeze mute takes a frozen item (rule MUTE-06).
    coord.page_set_mute(device.id, "freeze", True, "problem_list")
    await hass.async_block_till_done()
    assert not _items(coord, device.id), "the item should leave on the save, not a minute later"


# A device muted for unavailable mid-flap reads no flap on its page, as
# it is off the list (rule MUTE-07).
async def test_an_unavailable_muted_device_does_not_read_flapping(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(
        hass, freezer, "r6d", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}
    )
    record[DEV_FLAP_SINCE] = dt_util.utcnow().timestamp() - 600
    assert not [r for r in coord.flapping_list if r["device_id"] == device.id]
    assert coord._page_status(device.id, record) != "flapping"
    hass.config_entries.async_update_entry(coord.entry, options={})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_FLAP_SINCE] = dt_util.utcnow().timestamp() - 600
    assert coord._page_status(device.id, record) == "flapping", "unmuted, the flap shows"


# 1. A device muted for unavailable shows no flapping on its page: not
# the status word, and not the "dropped out N times since" suffix the
# panel appends to it (rule MUTE-07).
async def test_r16_1_unavailable_muted_page_has_no_flap_words(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(
        hass, freezer, "r16a", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}
    )
    now = dt_util.utcnow().timestamp()
    record[DEV_FLAP_SINCE] = now - 600
    record[DEV_FLAP_DROPS] = [now - 600, now - 400, now - 200]
    page = coord.dashboard_device(device.id)
    assert page["status"]["category"] != "flapping"
    assert page["status"]["flap"] == "", ("device page still says", page["status"]["flap"])


async def _flap(hass, freezer, ids, times=3):
    for _ in range(times):
        for eid in ids.values():
            hass.states.async_set(eid, "unavailable")
        await hass.async_block_till_done()
        await walk(hass, freezer, 6 * 60)
        for key, eid in ids.items():
            hass.states.async_set(eid, "on" if key == "main" else "80")
        await hass.async_block_till_done()
        await walk(hass, freezer, 3 * 60)


# 3. The same with the device's freeze mute: a freeze-muted device
# dropping out again and again is on the list as a flap (rule MUTE-06).
async def test_r21_3_freeze_muted_flapping_device_is_listed(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r21c", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    await _flap(hass, freezer, ids, times=4)
    assert record.get(DEV_FLAP_SINCE) is not None
    assert [i for i in coord.todo_items if i["device_id"] == device.id] or _mine(faults, device.id)


# 4. Unavailable-muted device: the page reads no flap and no down word,
# and the problem list API offers nothing (rule MUTE-07).
async def test_r21_4_unavailable_muted_page(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r21d", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    await _flap(hass, freezer, ids)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not coord.flapping_list
    assert coord._page_status(device.id, record) not in ("unavailable", "flapping", "frozen", "unknown")


# ---------------------------------------------- how each mute is named


async def test_the_reports_name_each_mute(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u6", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    assert not coord._freeze_muted(device.id)
    assert coord._device_status(device.id) == "Muted (UNAV)"
    assert coord.mute_text(device.id) == "unavailable (device)"
    assert coord.page_mutes(device.id)["freeze"]["on"] is False


# A device muted for freeze and for unavailable names both mutes, in its
# text and its tag, each its own kind (rule MUTE-10).
async def test_both_mutes_are_named_when_both_are_set(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(
        hass, freezer, "r6c",
        {CONF_FREEZE_MUTED_DEVICES: "SELF", CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"},
    )
    assert coord._device_status(device.id) == "Muted (FRZ, UNAV)"
    assert coord.mute_text(device.id) == "freeze (device); unavailable (device)"
    coord.page_set_mute(device.id, "unavailable", False, "device_page")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    assert coord._device_status(device.id) == "Muted (FRZ)"
    assert coord._freeze_muted(device.id), "the freeze mute stays"


# The device_telemetry.md legend explains every tag the STATUS column
# prints, UNAV among them, so a reader meeting "Muted (UNAV)" has
# something to read it by (rule MUTE-10).
async def test_the_status_legend_explains_the_unavailable_tag(hass: HomeAssistant):
    from custom_components.device_sentinel.coordinator import _new_device_record

    device = _register(hass, "r3leg", "Legend Device")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id] = _new_device_record(
        "2026-07-08T00:00:00+00:00", None
    )
    await hass.async_add_executor_job(coord._write_reports, "test")
    with open(hass.config.path("device_sentinel/device_telemetry.md"), encoding="utf-8") as handle:
        text = handle.read()
    assert "FRZ freeze" in text, "precondition: the legend is there"
    assert "UNAV" in text


def _rec(coord, device_id):
    return coord.data["devices"][device_id]


async def _mute_reloaded(hass, coord, device_id, kind, on):
    coord.page_set_mute(device_id, kind, on, "device_page")
    await hass.async_block_till_done()
    return coord.entry.runtime_data


# 3. Lifting the unavailable mute on a device that also carries its own
# freeze mute: the brief's line must not say freeze was unmuted.
async def test_3_lift_unavailable_text_with_freeze_mute_kept(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r10e", {CONF_FREEZE_MUTED_DEVICES: "SELF"})
    coord = await _mute_reloaded(hass, coord, device.id, "unavailable", True)
    coord = await _mute_reloaded(hass, coord, device.id, "unavailable", False)
    assert coord._freeze_muted(device.id)
    detail = coord.data[DATA_SYSTEM_EVENTS][-1][SYS_DETAIL]
    assert "freeze unmuted" not in detail, detail


# ---------------------- the upgrade copies freeze mutes to unavailable


async def test_the_first_update_carries_label_and_device_freeze_mutes_over(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, version=1, minor_version=5,
        options={
            CONF_FREEZE_MUTED_INTEGRATIONS: ["zwave_js"],
            CONF_FREEZE_MUTED_LABELS: ["quiet", "garage"],
            CONF_FREEZE_MUTED_DEVICES: ["d1", "d2"],
            CONF_UNAVAILABLE_MUTED_DEVICES: ["d2", "d3"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == OPTIONS_MINOR_VERSION
    assert entry.options[CONF_UNAVAILABLE_MUTED_LABELS] == ["quiet", "garage"]
    assert entry.options[CONF_UNAVAILABLE_MUTED_DEVICES] == ["d2", "d3", "d1"]
    assert entry.options[CONF_FREEZE_MUTED_INTEGRATIONS] == ["zwave_js"]
    assert "unavailable_muted_integrations" not in entry.options


async def test_the_carry_over_happens_once(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, version=1, minor_version=OPTIONS_MINOR_VERSION,
        options={CONF_FREEZE_MUTED_DEVICES: ["d1"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert CONF_UNAVAILABLE_MUTED_DEVICES not in entry.options


async def _upgraded(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, version=1, minor_version=5,
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == OPTIONS_MINOR_VERSION
    return entry


@pytest.mark.parametrize("value", ["d1abc", {"d1": 1}])
async def test_a_hand_edited_value_that_is_not_a_list_copies_nothing(hass: HomeAssistant, value):
    """A string is not split into its characters, nor a mapping into its keys."""
    entry = await _upgraded(hass, {CONF_FREEZE_MUTED_DEVICES: value, CONF_FREEZE_MUTED_LABELS: value})
    assert entry.options.get(CONF_UNAVAILABLE_MUTED_DEVICES) in (None, [])
    assert entry.options.get(CONF_UNAVAILABLE_MUTED_LABELS) in (None, [])


async def test_a_pick_listed_twice_is_copied_once(hass: HomeAssistant):
    entry = await _upgraded(
        hass, {CONF_FREEZE_MUTED_DEVICES: ["d1", "d1"], CONF_UNAVAILABLE_MUTED_DEVICES: "x"}
    )
    assert entry.options[CONF_UNAVAILABLE_MUTED_DEVICES] == ["d1"]


# ------------------------------------------------- the settings screen


# ------------------------------------------------ the settings screen


async def _freeze_screen(hass):
    from tests.helpers import setup_entry
    from .test_exclusions import _ladder_device

    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 7)
    entry = await setup_entry(hass, {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "freeze"}
    )
    assert result["step_id"] == "freeze"
    return entry, device, result


async def test_the_screen_saves_unavailable_mutes_and_prunes_a_covered_device(hass: HomeAssistant):
    """A device pick under a label picked in the same section is dropped
    on save; the label is kept."""
    label = lr.async_get(hass).async_create("Wall Switched")
    entry, device, result = await _freeze_screen(hass)
    dr.async_get(hass).async_update_device(device.id, labels={label.label_id})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "freeze_muting": {CONF_FREEZE_MUTED_LABELS: [], CONF_FREEZE_MUTED_DEVICES: []},
            "unavailable_muting": {
                CONF_UNAVAILABLE_MUTED_LABELS: [label.label_id],
                CONF_UNAVAILABLE_MUTED_DEVICES: [device.id],
            },
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "menu"
    assert entry.options[CONF_UNAVAILABLE_MUTED_LABELS] == [label.label_id]
    assert entry.options[CONF_UNAVAILABLE_MUTED_DEVICES] == []
    assert entry.options[CONF_FREEZE_MUTED_DEVICES] == []


async def test_a_freeze_label_does_not_prune_an_unavailable_pick(hass: HomeAssistant):
    """The two sections are separate: a freeze label over the device
    leaves its unavailable pick alone."""
    label = lr.async_get(hass).async_create("Slow")
    entry, device, result = await _freeze_screen(hass)
    dr.async_get(hass).async_update_device(device.id, labels={label.label_id})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "freeze_muting": {CONF_FREEZE_MUTED_LABELS: [label.label_id], CONF_FREEZE_MUTED_DEVICES: []},
            "unavailable_muting": {
                CONF_UNAVAILABLE_MUTED_LABELS: [],
                CONF_UNAVAILABLE_MUTED_DEVICES: [device.id],
            },
        },
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_FREEZE_MUTED_LABELS] == [label.label_id]
    assert entry.options[CONF_UNAVAILABLE_MUTED_DEVICES] == [device.id]


# (a) Settling the options prunes the unavailable mute like every other:
# a globally muted device, or one Home Assistant no longer has, leaves
# it (rule MUTE-03).
async def test_settle_prunes_the_unavailable_mute_like_every_other(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "zz7")
    settled = settle_options(hass, coord, {
        CONF_MUTED_DEVICES: [device.id],
        CONF_UNAVAILABLE_MUTED_DEVICES: [device.id, "0123456789abcdef0123456789abcdef"],
    })
    assert settled.get(CONF_UNAVAILABLE_MUTED_DEVICES, []) == []


# ----------------- setting and lifting a mute while the device is down


async def _gone(hass, freezer, ids):
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)


async def test_p1_lift_unavailable_mute_while_down(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p1")
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    await _gone(hass, freezer, ids)
    since0 = record[DEV_FROZEN_SINCE]
    coord.page_set_mute(device.id, "unavailable", True, "device_page")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    coord.page_set_mute(device.id, "unavailable", False, "device_page")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] == since0
    assert len(_mine(faults, device.id)) == 2, "told again when the mute is lifted"
    assert not _mine(back, device.id)


async def test_p2_lift_freeze_mute_on_frozen(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p2")
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    since0 = record[DEV_FROZEN_SINCE]
    coord.page_set_mute(device.id, "freeze", True, "device_page")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    coord.page_set_mute(device.id, "freeze", False, "device_page")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] == since0, "dated from the original start"
    assert len(_mine(faults, device.id)) == 2, "told again when the mute is lifted"
    assert not _mine(back, device.id)


async def test_p4_mute_inside_grace_while_its_integration_loads(hass: HomeAssistant, freezer):
    from homeassistant.config_entries import ConfigEntryState
    coord, device, ids, record = await _ready(hass, freezer, "p4")
    back = record_events(hass, EVENT_RECOVERED)
    await _gone(hass, freezer, ids)
    assert _items(coord, device.id)
    source = hass.config_entries.async_get_entry(getattr(device, "config_entry_id", None) or next(iter(device.config_entries)))

    def failing():
        source.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    coord = await restart(hass, freezer, down=60, before_setup=failing)
    await walk(hass, freezer, 60)
    assert coord._in_startup_grace()
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    assert not _items(coord, device.id), "muted, the item leaves at once"
    assert not _mine(back, device.id)


async def test_p4b_after_grace_it_leaves_silently(hass: HomeAssistant, freezer):
    from homeassistant.config_entries import ConfigEntryState
    coord, device, ids, record = await _ready(hass, freezer, "p4b")
    back = record_events(hass, EVENT_RECOVERED)
    await _gone(hass, freezer, ids)
    source = hass.config_entries.async_get_entry(getattr(device, "config_entry_id", None) or next(iter(device.config_entries)))
    coord = await restart(hass, freezer, down=60, before_setup=lambda: source.mock_state(hass, ConfigEntryState.SETUP_RETRY))
    await walk(hass, freezer, 60)
    coord.page_set_mute(device.id, "unavailable", True, "problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert not _items(coord, device.id)
    assert not _mine(back, device.id)


async def test_p5_held_muted_device_page_status(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p5")
    await _gone(hass, freezer, ids)
    went = dt_util.utcnow().timestamp()
    real = coord.upstream_down_since
    coord.upstream_down_since = (
        lambda device_id: ("test", went) if device_id == device.id else real(device_id)
    )
    await walk(hass, freezer, 120)
    coord.page_set_mute(device.id, "unavailable", True, "device_page")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert coord._page_status(device.id, record) != FREEZE_CATEGORY_UNAVAILABLE, "muted for unavailable, it reads no down verdict"


async def test_a_device_muted_while_frozen_is_told_unavailable_from_when_it_went(
    hass: HomeAssistant, freezer
):
    coord, device, ids, record = await _ready(hass, freezer, "p6")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    frozen_at = record[DEV_FROZEN_SINCE]
    coord.page_set_mute(device.id, "freeze", True, "device_page")
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 2 * HOUR, step=600)
    record = coord.data["devices"][device.id]
    assert record[DEV_FROZEN_CATEGORY] is None
    went = dt_util.utcnow().timestamp()
    await _gone(hass, freezer, ids)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] != frozen_at
    assert abs(record[DEV_FROZEN_SINCE] - went) <= 120, "from when it became unavailable"


async def _mute(hass, coord, device_id, kind, on):
    coord.page_set_mute(device_id, kind, on, "device_page")
    await hass.async_block_till_done()


# B. A freeze-muted frozen device across a restart, lifted after.
async def test_b_frozen_start_survives_restart(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8b")
    faults = record_events(hass, EVENT_FAULT)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    since0 = record[DEV_FROZEN_SINCE]
    await _mute(hass, coord, device.id, "freeze", True)
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 30 * 60)
    # States kept: the freeze mute took the verdict away, and with it
    # the held values (rule WATCH-12), so a value handed back at the
    # start is read as a report.
    coord = await restart(hass, freezer, down=120, keep_states=True)
    await walk(hass, freezer, 15 * 60)
    await _mute(hass, coord, device.id, "freeze", False)
    await walk(hass, freezer, 10 * 60)
    record = coord.data["devices"][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] == since0
    assert len(_mine(faults, device.id)) == 2


# C. An unavailable-muted unavailable device across a restart, lifted after.
async def test_c_unavailable_start_survives_restart(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8c")
    faults = record_events(hass, EVENT_FAULT)
    await _gone(hass, freezer, ids)
    since0 = record[DEV_FROZEN_SINCE]
    await _mute(hass, coord, device.id, "unavailable", True)
    await walk(hass, freezer, 30 * 60)
    coord = await restart(hass, freezer, down=120)
    await walk(hass, freezer, 15 * 60)
    await _mute(hass, coord, device.id, "unavailable", False)
    await walk(hass, freezer, 10 * 60)
    record = coord.data["devices"][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] == since0
    assert len(_mine(faults, device.id)) == 2


def _mono(coord):
    box = {"off": 0.0}
    coord._monotonic = lambda: time.monotonic() + box["off"]
    return box


async def _clock_step(hass, freezer, coord, seconds):
    box = _mono(coord)
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=seconds))
    box["off"] -= seconds
    await coord._on_render_tick(None)
    await hass.async_block_till_done()


# D. Control: an unmuted frozen device keeps its verdict across a clock step.
async def test_d_control_unmuted_frozen_keeps_across_clock_step(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8d")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    await _clock_step(hass, freezer, coord, 2 * HOUR)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


# E. The "everything" mute set on a frozen device and lifted while still
# frozen: dated from when the freeze began (rule MUTE-08).
async def test_e_global_mute_lift_dates_from_start(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8e")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    since0 = record[DEV_FROZEN_SINCE]
    await _mute(hass, coord, device.id, "everything", True)
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 30 * 60)
    await _mute(hass, coord, device.id, "everything", False)
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 10 * 60)
    record = coord.data["devices"][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] == since0, (record[DEV_FROZEN_SINCE] - since0)


# F. A device that froze while freeze-muted (never listed), mute lifted:
# when is it dated from? Compared with an unavailable one that went while
# muted (rule MUTE-08).
async def test_f_froze_under_mute_dated_at_lift(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8f")
    await _mute(hass, coord, device.id, "freeze", True)
    coord = coord.entry.runtime_data
    record = coord.data["devices"][device.id]
    await walk(hass, freezer, 8 * HOUR, step=600)
    lift = dt_util.utcnow().timestamp()
    await _mute(hass, coord, device.id, "freeze", False)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] < lift - HOUR, (lift - record[DEV_FROZEN_SINCE])


async def test_f2_went_unavailable_under_mute_dated_from_going(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8f2")
    await _mute(hass, coord, device.id, "unavailable", True)
    went = dt_util.utcnow().timestamp()
    await _gone(hass, freezer, ids)
    await walk(hass, freezer, 2 * HOUR, step=600)
    lift = dt_util.utcnow().timestamp()
    await _mute(hass, coord, device.id, "unavailable", False)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert abs(record[DEV_FROZEN_SINCE] - went) < 120, (lift - record[DEV_FROZEN_SINCE])


# G. With the "everything" mute: a held device muted for everything
# still shows its down word on the page (rule MUTE-09).
async def test_g_held_globally_muted_device_page_status(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8g")
    await _gone(hass, freezer, ids)
    went = dt_util.utcnow().timestamp()

    def hold(c):
        real = c.upstream_down_since
        c.upstream_down_since = (
            lambda device_id: ("test", went) if device_id == device.id else real(device_id)
        )

    hold(coord)
    await walk(hass, freezer, 120)
    await _mute(hass, coord, device.id, "everything", True)
    if coord.entry.runtime_data is not coord:
        coord = coord.entry.runtime_data
        hold(coord)
    await walk(hass, freezer, 30 * 60)
    record = coord.data["devices"][device.id]
    assert not _items(coord, device.id)
    assert coord._page_status(device.id, record) != FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]


async def test_d3_same_as_d2_without_the_step(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r8d3")
    faults = record_events(hass, EVENT_FAULT)
    await walk(hass, freezer, 6 * HOUR, step=600)
    await _mute(hass, coord, device.id, "freeze", True)
    coord = coord.entry.runtime_data
    await walk(hass, freezer, 10 * 60)
    record = coord.data["devices"][device.id]
    _mono(coord)
    await walk(hass, freezer, 10 * 60)
    await _mute(hass, coord, device.id, "freeze", False)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, record[DEV_FROZEN_CATEGORY]
    assert len(_mine(faults, device.id)) == 2


# 4. A never-reported device listed, freeze-muted, lifted while still
# never reported: listed again from when that trouble began (rule MUTE-08).
async def test_4_never_reported_lift_dated_from_start(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r10f")
    faults = record_events(hass, EVENT_FAULT)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(days=5)).isoformat()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_NEVER_REPORTED
    since0 = record[DEV_FROZEN_SINCE]
    coord = await _mute_reloaded(hass, coord, device.id, "freeze", True)
    await walk(hass, freezer, 3 * HOUR, step=600)
    record = _rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] is None
    coord = await _mute_reloaded(hass, coord, device.id, "freeze", False)
    await walk(hass, freezer, 10 * 60)
    record = _rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_NEVER_REPORTED
    assert len(_mine(faults, device.id)) == 2
    assert record[DEV_FROZEN_SINCE] <= since0, (record[DEV_FROZEN_SINCE] - since0) / 60


# 2. A flapping device muted for unavailable, the mute lifted while it
# is down and still flapping: listed again and pushed (rule MUTE-08).
async def test_r21_2_unavailable_mute_lifted_on_a_flapping_device(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r21b")
    await _flap(hass, freezer, ids)
    assert record.get(DEV_FLAP_SINCE) is not None
    coord.page_set_mute(device.id, "unavailable", True)
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert not [i for i in coord.todo_items if i["device_id"] == device.id]
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    items = [i for i in coord.todo_items if i["device_id"] == device.id]
    assert items, "not listed again"
    assert _mine(faults, device.id), ("not pushed again", items, record.get(DEV_FLAP_SINCE))


async def _gone_then_unknown(hass, freezer, coord, ids):
    went = dt_util.utcnow().timestamp()
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    for eid in ids.values():
        hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * HOUR, step=300)
    return went


async def test_a_lifted_unavailable_mute_reads_as_a_device_never_muted(hass: HomeAssistant, freezer):
    """Gone, then reading unknown (a stack restart), then the mute lifted:
    unavailable from the saved outage start, as a device never muted
    reads, not frozen from its clock (rule MUTE-08)."""
    coord, device, ids, record = await _ready(hass, freezer, "u23a", {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    went = await _gone_then_unknown(hass, freezer, coord, ids)
    assert record[DEV_FROZEN_CATEGORY] is None
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert abs(float(record[DEV_FROZEN_SINCE]) - went) < 120
    assert _mine(faults, device.id), "a lifted mute pushes (rule 8)"


async def test_the_twin_never_muted_holds_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u23b")
    await _gone_then_unknown(hass, freezer, coord, ids)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_muting_unavailable_on_a_frozen_then_gone_device_lists_it_frozen_with_one_push(hass: HomeAssistant, freezer):
    """Frozen, then gone: muting unavailable shows it frozen again, with
    one push, because there is no quiet move between kinds (rule MUTE-06)."""
    coord, device, ids, record = await _ready(hass, freezer, "u23c")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    items = [i["kinds"] for i in coord.todo_items if i["device_id"] == device.id]
    assert items and "frozen" in items[0], items
    assert len(_mine(faults, device.id)) == 1


async def test_muting_freeze_on_a_never_reported_device_that_is_gone_lists_it_unavailable_with_one_push(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "u23d")
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_NEVER_REPORTED
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    items = [i["kinds"] for i in coord.todo_items if i["device_id"] == device.id]
    assert items and "unavailable" in items[0], items
    assert len(_mine(faults, device.id)) == 1


async def test_after_the_device_reports_a_new_outage_is_pushed(hass: HomeAssistant, freezer):
    """The quiet move lasts only while the device stays down: once it
    reports, its next outage is news again."""
    coord, device, ids, record = await _ready(hass, freezer, "u23e")
    await walk(hass, freezer, 6 * HOUR, step=600)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    for n, eid in enumerate(ids.values()):
        hass.states.async_set(eid, str(20 + n))
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert not [i for i in coord.todo_items if i["device_id"] == device.id]
    faults = record_events(hass, EVENT_FAULT)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert _mine(faults, device.id), "a new freeze after a report is pushed"


def _pushes(coord):
    got = []
    orig = coord.async_fire_events

    async def spy(events, *a, **k):
        for fam, line, rec in events:
            if not rec:
                got.append(line)
        return await orig(events, *a, **k)

    coord.async_fire_events = spy
    return got


def _mine_lines(lines, uid):
    return [line for line in lines if f"Sensor {uid}" in line]


def _listed_kinds(coord, device_id):
    return [sorted(i["kinds"]) for i in coord.todo_items if i["device_id"] == device_id]


async def _all(hass, ids, value):
    for eid in ids.values():
        hass.states.async_set(eid, value)
    await hass.async_block_till_done()


async def _report(hass, ids, n):
    for key, eid in ids.items():
        hass.states.async_set(eid, ("on" if n % 2 else "off") if key == "main" else str(80 + n))
    await hass.async_block_till_done()


# B2. A freeze-muted device is still reported when it becomes
# unavailable. Frozen and listed, freeze-muted from its item (it leaves
# silently), still silent; an hour later Home Assistant calls it
# unavailable. Expect a push for the unavailable (rule MUTE-06).
@pytest.mark.parametrize("how", ["page", "label_options"])
async def test_b2_freeze_muted_then_goes_unavailable_pushes(hass: HomeAssistant, freezer, how):
    coord, device, ids, record = await _ready(hass, freezer, "b2" + how)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    if how == "page":
        coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    else:
        label = lr.async_get(hass).async_create("Sleepy")
        dr.async_get(hass).async_update_device(device.id, labels={label.label_id})
        await hass.async_block_till_done()
        hass.config_entries.async_update_entry(
            coord.entry, options={**coord.entry.options, CONF_FREEZE_MUTED_LABELS: [label.label_id]})
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    await walk(hass, freezer, HOUR, step=300)
    assert _listed_kinds(coord, device.id) == []
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 3 * HOUR, step=300)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _listed_kinds(coord, device.id) == [["unavailable"]]
    assert _mine(faults, device.id) and _mine_lines(lines, "b2" + how), (
        "freeze-muted device went unavailable with no push", _mine(faults, device.id),
        _mine_lines(lines, "b2" + how), "last", record[DEV_LAST_ACTIVITY], getattr(coord, "_mute_moved", {}).get(device.id))


# B2r. Same with a restart between the mute and the unavailable: the
# marker is not persisted, and the push still comes, as in B2.
async def test_b2r_restart_between(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "b2r")
    await walk(hass, freezer, 6 * HOUR, step=600)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    coord = await restart(hass, freezer)
    await walk(hass, freezer, 15 * 60)
    from custom_components.device_sentinel.const import DATA_DEVICES
    record = coord.data[DATA_DEVICES][device.id]
    faults = record_events(hass, EVENT_FAULT)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 3 * HOUR, step=300)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _mine(faults, device.id)


# B3. Lifting the unavailable mute while still down pushes again
# (rule MUTE-08).
async def test_b3_lifted_unav_mute_pushes(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "b3")
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == [["unavailable"]]
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    assert _listed_kinds(coord, device.id) == [["unavailable"]]
    assert _mine(faults, device.id) and _mine_lines(lines, "b3"), (_mine(faults, device.id), _mine_lines(lines, "b3"))


# B3f. A freeze-muted frozen device unmuted while still silent pushes
# again (rule MUTE-08).
async def test_b3f_lifted_freeze_mute_pushes(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "b3f")
    await walk(hass, freezer, 6 * HOUR, step=600)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "freeze", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    assert _listed_kinds(coord, device.id) == [["frozen"]]
    assert _mine(faults, device.id)


# B4. After a mute moved the listing, the device reports, then a genuinely
# new outage: must push.
@pytest.mark.parametrize("kind", ["freeze", "unavailable"])
async def test_b4_new_outage_after_report_pushes(hass: HomeAssistant, freezer, kind):
    coord, device, ids, record = await _ready(hass, freezer, "b4" + kind)
    await walk(hass, freezer, 6 * HOUR, step=600)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    coord.page_set_mute(device.id, kind, True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    await _report(hass, ids, 1)
    await walk(hass, freezer, 10 * 60)
    await _report(hass, ids, 2)
    await walk(hass, freezer, 10 * 60)
    faults = record_events(hass, EVENT_FAULT)
    if kind == "freeze":
        await _all(hass, ids, "unavailable")
        await walk(hass, freezer, 30 * 60)
    else:
        await walk(hass, freezer, 8 * HOUR, step=600)
    assert _listed_kinds(coord, device.id)
    assert _mine(faults, device.id), (_listed_kinds(coord, device.id), getattr(coord, "_mute_moved", {}).get(device.id))


# B5. Never reported with entities unavailable, freeze-muted (unavailable
# shows, no push), then reports for the first time, then goes
# unavailable again: must push.
async def test_b5_never_reported_first_report_then_down(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "b5")
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    await _all(hass, ids, "unavailable")
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_NEVER_REPORTED
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    # Shown as unavailable now, with one push (rule MUTE-06).
    assert len(_mine(faults, device.id)) == 1
    faults = record_events(hass, EVENT_FAULT)
    await _report(hass, ids, 1)
    await walk(hass, freezer, 10 * 60)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 30 * 60)
    assert _listed_kinds(coord, device.id) == [["unavailable"]]
    assert _mine(faults, device.id), "new outage after first report not pushed"


async def test_b7_global_mute_unmute(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "b7")
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    faults = record_events(hass, EVENT_FAULT)
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_MUTED_DEVICES: [device.id]})
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    n_mute = len(_mine(faults, device.id))
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_MUTED_DEVICES: []})
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    assert n_mute == 0 and len(_mine(faults, device.id)) == 1


# B8. Two devices: marker on one does not silence the other.
async def test_b8_two_devices(hass: HomeAssistant, freezer):
    from .test_freeze_unavailable_split import _sensor
    from .outage_helpers import arm
    s2, dev2, ids2 = _sensor(hass, "b8b")
    for key, eid in ids2.items():
        hass.states.async_set(eid, "off" if key == "main" else "87")
    coord, device, ids, record = await _ready(hass, freezer, "b8a")
    arm(coord, dev2.id)
    await _report(hass, ids2, 1)
    await walk(hass, freezer, 6 * HOUR, step=600)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    await _report(hass, ids2, 2)
    await walk(hass, freezer, 120)
    assert _listed_kinds(coord, dev2.id) == []
    faults = record_events(hass, EVENT_FAULT)
    await _all(hass, ids2, "unavailable")
    await walk(hass, freezer, 30 * 60)
    assert _listed_kinds(coord, dev2.id) and _mine(faults, dev2.id)


def _info(coord, device_id, record):
    return dict(
        cat=record[DEV_FROZEN_CATEGORY],
        since=record.get(DEV_FROZEN_SINCE),
        down=record.get(DEV_DOWN_SINCE),
        moved=getattr(coord, "_mute_moved", {}).get(device_id),
        items=_listed_kinds(coord, device_id),
        now=dt_util.utcnow().timestamp(),
    )


# P1. Never reported, entities reading unknown, freeze-muted from its
# item, an hour later unavailable. Trouble that begins after the mute is
# listed, sent on the bus and pushed (rules MUTE-06, MUTE-07).
async def test_p1_never_reported_unknown_then_unavailable_after_mute(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p1")
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = "2026-07-11T00:00:00+00:00"
    await _all(hass, ids, "unknown")
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_NEVER_REPORTED, _info(coord, device.id, record)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    assert _listed_kinds(coord, device.id) == []
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["unavailable"]], info
    assert _mine(faults, device.id) and _mine_lines(lines, "p1"), ("no push", info)


# P2. Frozen by its clock while its entities read unknown, freeze-muted,
# an hour later unavailable: must push (rules MUTE-06, MUTE-07).
async def test_p2_frozen_unknown_then_unavailable_after_mute(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p2")
    await _all(hass, ids, "unknown")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, _info(coord, device.id, record)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    assert _listed_kinds(coord, device.id) == []
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["unavailable"]], info
    assert _mine(faults, device.id) and _mine_lines(lines, "p2"), ("no push", info)


# P3. Listed unavailable (never muted), entities then read unknown (held
# unavailable), muted for unavailable, lifted while still silent:
# relisted unavailable from the outage start and pushed, not judged by
# the clock (rule MUTE-08).
async def test_p3_unknown_before_mute_then_lift(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p3")
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == [["unavailable"]]
    start = record[DEV_FROZEN_SINCE]
    await _all(hass, ids, "unknown")
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert _listed_kinds(coord, device.id) == []
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, device.id, record)
    info["under"] = getattr(coord, "_unavailable_under_mute", {}).get(device.id)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, info
    assert record[DEV_FROZEN_SINCE] == start, (start, info)
    assert _mine(faults, device.id) and _mine_lines(lines, "p3"), ("no push", info)


# P3c. Control: muted while entities still read unavailable, then
# unknown, then lifted. Passes.
async def test_p3c_control(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p3c")
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    await _all(hass, ids, "unknown")
    await walk(hass, freezer, 30 * 60)
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _mine(faults, device.id)


# P4. Clock stepped back two hours after a freeze mute; the device then
# goes unavailable. Expected: a fault and a push, never a listing dated
# before the mute stamp (rules MUTE-06, FRZ-21).
async def test_p4_clock_back_after_mute(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "p4")
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    freezer.move_to(dt_util.utcnow() - datetime.timedelta(hours=2))
    await walk(hass, freezer, 10 * 60)
    faults = record_events(hass, EVENT_FAULT)
    lines = _pushes(coord)
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 3 * HOUR, step=300)
    info = _info(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["unavailable"]], info
    assert _mine(faults, device.id) and _mine_lines(lines, "p4"), ("no push", info)


def _st(coord, device_id, record):
    return dict(cat=record[DEV_FROZEN_CATEGORY], since=record.get(DEV_FROZEN_SINCE),
                began=record.get("down_began_as"), down=record.get(DEV_DOWN_SINCE),
                items=_listed_kinds(coord, device_id))


async def _frozen_then_gone(hass, freezer, uid):
    coord, device, ids, record = await _ready(hass, freezer, uid)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    frozen_since = record[DEV_FROZEN_SINCE]
    await _all(hass, ids, "unavailable")
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    return coord, device, ids, record, frozen_since


# C1. Frozen, then gone; muted for unavailable: listed frozen (one push).
# Then freeze muted too (a slip), then the freeze mute lifted again: the
# device is back where it was, muted for unavailable only, and reads
# frozen again as it did a minute before, because lifting a mute while
# still down relists from when trouble began (rule MUTE-08).
async def test_c1_unav_muted_frozen_then_freeze_mute_and_lift(hass, freezer):
    coord, device, ids, record, frozen_since = await _frozen_then_gone(hass, freezer, "c1")
    coord.page_set_mute(device.id, "unavailable", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == [["frozen"]], _st(coord, device.id, record)
    faults = record_events(hass, EVENT_FAULT)
    back = record_events(hass, EVENT_RECOVERED)
    coord.page_set_mute(device.id, "freeze", True, source="problem_list")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == []
    coord.page_set_mute(device.id, "freeze", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    info = _st(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["frozen"]], info
    assert record[DEV_FROZEN_SINCE] == frozen_since, (frozen_since, info)
    assert len(_mine(faults, device.id)) == 1, info
    assert not _mine(back, device.id)


# C2. Frozen, then gone (listed unavailable); freeze muted (no change), then
# unavailable muted too (leaves), then the freeze mute lifted: muted for
# unavailable only, the same state as C1 before its slip, which lists the
# device frozen.
async def test_c2_freeze_then_unav_then_lift_freeze(hass, freezer):
    coord, device, ids, record, frozen_since = await _frozen_then_gone(hass, freezer, "c2")
    coord.page_set_mute(device.id, "freeze", True)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == [["unavailable"]], _st(coord, device.id, record)
    coord.page_set_mute(device.id, "unavailable", True)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert _listed_kinds(coord, device.id) == []
    coord.page_set_mute(device.id, "freeze", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    info = _st(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["frozen"]], info


# C3. Control for C1: unavailable muted alone, then lifted: unavailable
# again, one push, no recovery.
async def test_c3_control(hass, freezer):
    coord, device, ids, record, frozen_since = await _frozen_then_gone(hass, freezer, "c3")
    coord.page_set_mute(device.id, "unavailable", True)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    back = record_events(hass, EVENT_RECOVERED)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(back, device.id)


# C4. Frozen (entities still holding values, not gone); both mutes; freeze
# lifted: frozen again from its freeze start, pushed once.
async def test_c4_frozen_both_mutes_lift_freeze(hass, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "c4")
    await walk(hass, freezer, 6 * HOUR, step=600)
    frozen_since = record[DEV_FROZEN_SINCE]
    coord.page_set_mute(device.id, "freeze", True)
    coord.page_set_mute(device.id, "unavailable", True)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    faults = record_events(hass, EVENT_FAULT)
    coord.page_set_mute(device.id, "freeze", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    info = _st(coord, device.id, record)
    assert _listed_kinds(coord, device.id) == [["frozen"]], info
    assert record[DEV_FROZEN_SINCE] == frozen_since, info
    assert len(_mine(faults, device.id)) == 1
