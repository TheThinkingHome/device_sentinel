# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_restart_handback.py, Version: 0.26.6 (2026-10-18)

"""Restarts, and the values they hand back.

A stack restart, a Home Assistant restart or a full system restart
hands the old values back; that is not the device reporting, so its
clock stays and a frozen verdict stands with no recovery told (#535),
muted for unavailable or not. An outage no older than the restart is
the hand-back; a device off for ten minutes before it is a real return.
A freeze is dated from when its counted silence reached the window,
stepping over the time Home Assistant was off. Found by the
adversarial rounds of 0.26.6.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
)

from .helpers import record_events
from .outage_helpers import restart, walk
from .test_freeze_and_unavailable_mutes import _listed_kinds
from .test_freeze_unavailable_split import _mine, _ready

HOUR = 3600.0


# ------------ a freeze is dated across the time Home Assistant was off


async def _cross_during_restart(hass, freezer, uid, lead, down):
    """Stop Home Assistant `lead` seconds before the device's window
    closes, keep it off `down` seconds, and run on well past the grace."""
    coord, device, ids, record = await _ready(hass, freezer, uid)
    last = float(record[DEV_LAST_ACTIVITY])
    window = coord._freeze_window(record)
    assert window is not None
    to_go = last + window - lead - dt_util.utcnow().timestamp()
    await walk(hass, freezer, to_go, step=300)
    assert record[DEV_FROZEN_CATEGORY] is None
    stopped = dt_util.utcnow().timestamp()
    coord = await restart(hass, freezer, down=down)
    started = dt_util.utcnow().timestamp()
    await walk(hass, freezer, lead + 30 * 60, step=60)
    record = coord.data["devices"][device.id]
    return record, last, window, stopped, started


# A. Control: a short restart. The crossing lands after the start.
async def test_a_control_short_restart_dated_after_start(hass: HomeAssistant, freezer):
    record, last, window, stopped, started = await _cross_during_restart(
        hass, freezer, "r9a", lead=10 * 60, down=180
    )
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert record[DEV_FROZEN_SINCE] >= started


# B. A four-hour blackout that begins ten minutes before the device's
# window closes. Counted silence cannot reach the window while Home
# Assistant is off, so the freeze began after the start; the fixed-point
# loop in _frozen_start runs only len(spans)+1 steps and lands inside the
# blackout.
async def test_b_long_blackout_freeze_not_dated_inside_it(hass: HomeAssistant, freezer):
    record, last, window, stopped, started = await _cross_during_restart(
        hass, freezer, "r9b", lead=10 * 60, down=4 * HOUR
    )
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    since = record[DEV_FROZEN_SINCE]
    assert since >= started, (
        f"dated {(started - since) / 60:.0f} min before Home Assistant "
        f"started, {(since - stopped) / 60:.0f} min into the blackout"
    )


async def test_the_start_steps_over_several_and_overlapping_spans(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r9c")
    window = coord._freeze_window(record)
    last = 1000.0
    cases = [
        ([], last + window),
        ([(last + 10, last + 20)], last + window + 10),
        ([(last + window - 5, last + window + 3600)], last + window + 3600 + 5),
        (
            [(last + 100, last + 200), (last + 150, last + 400), (last + window + 1000, last + window + 2000)],
            last + window + 300,
        ),
        ([(last - 500, last + 50)], last + window + 50),
    ]
    for spans, expected in cases:
        coord._silence_spans = lambda *a, spans=spans, **k: (last, list(spans))
        assert coord._frozen_start(device.id, record, 10 ** 9) == expected, spans
    coord._silence_spans = lambda *a, **k: (last, [])
    assert coord._frozen_start(device.id, record, last + 5) == last + 5, "never in the future"


# ------------------- values handed back by a stack or a restart (#535)


@pytest.mark.parametrize("mode", ["none", "unav", "frz"])
async def test_frozen_through_stack_restart(hass: HomeAssistant, freezer, mode):
    opts = {"none": None, "unav": {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}, "frz": {CONF_FREEZE_MUTED_DEVICES: "SELF"}}[mode]
    coord, device, ids, record = await _ready(hass, freezer, "rp" + mode, opts)
    down = {"now": None}
    real = coord.upstream_down_since
    coord.upstream_down_since = lambda d: (("zwave_js", down["now"]) if d == device.id and down["now"] else real(d))
    await walk(hass, freezer, 6 * HOUR, step=600)
    if mode != "frz":
        assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    heard = record[DEV_LAST_ACTIVITY]
    faults = record_events(hass, EVENT_FAULT)
    back = record_events(hass, EVENT_RECOVERED)
    # The stack restarts: every entity unavailable, two minutes, then the
    # stack hands the old values back, then the hold ends.
    down["now"] = __import__("homeassistant.util.dt", fromlist=["x"]).utcnow().timestamp()
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    for key, eid in ids.items():
        hass.states.async_set(eid, "on" if key == "main" else "87")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    down["now"] = None
    await walk(hass, freezer, 30 * 60)
    info = dict(cat=record[DEV_FROZEN_CATEGORY], moved=record[DEV_LAST_ACTIVITY] != heard,
                items=_listed_kinds(coord, device.id), faults=_mine(faults, device.id), back=_mine(back, device.id))
    assert record[DEV_LAST_ACTIVITY] == heard, info
    if mode != "frz":
        assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, info
        assert _listed_kinds(coord, device.id) == [["frozen"]], info
    assert not _mine(back, device.id), info


@pytest.mark.parametrize("mode", ["none", "unav"])
async def test_frozen_through_ha_restart(hass: HomeAssistant, freezer, mode):
    from .outage_helpers import restart
    from custom_components.device_sentinel.const import DATA_DEVICES
    opts = {"none": None, "unav": {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}}[mode]
    coord, device, ids, record = await _ready(hass, freezer, "hr" + mode, opts)
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    heard = record[DEV_LAST_ACTIVITY]
    faults = record_events(hass, EVENT_FAULT)
    back = record_events(hass, EVENT_RECOVERED)

    def gone():
        for eid in ids.values():
            hass.states.async_set(eid, "unavailable")
    coord = await restart(hass, freezer, before_setup=gone)
    await walk(hass, freezer, 60)
    for key, eid in ids.items():
        hass.states.async_set(eid, "on" if key == "main" else "87")
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    record = coord.data[DATA_DEVICES][device.id]
    info = dict(cat=record[DEV_FROZEN_CATEGORY], items=_listed_kinds(coord, device.id), back=_mine(back, device.id), faults=_mine(faults, device.id))
    assert record[DEV_LAST_ACTIVITY] == heard, info
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, info
    assert not _mine(back, device.id), info


OPTS = {"none": None, "unav": {CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"}, "frz": {CONF_FREEZE_MUTED_DEVICES: "SELF"}}


async def _set(hass, ids, value):
    for key, eid in ids.items():
        hass.states.async_set(eid, value if value == "unavailable" else ("on" if key == "main" else "87"))
    await hass.async_block_till_done()


def _restart_only(device, record, lead, cat0, heard, back, faults):
    """An outage no older than the restart is the stack handing values
    back (#535): the clock stays and a frozen verdict stands, with no
    recovery told. A device off for ten minutes before is a real return."""
    if lead >= 600:
        return
    assert record[DEV_LAST_ACTIVITY] == heard
    assert record[DEV_FROZEN_CATEGORY] == cat0
    assert not [e for e in back if e.data.get("device_id") == device.id]


@pytest.mark.parametrize("frozen", [True, False])
@pytest.mark.parametrize("lead", [0, 100, 600])
@pytest.mark.parametrize("mode", ["none", "unav", "frz"])
async def test_stack_hold(hass: HomeAssistant, freezer, mode, lead, frozen):
    coord, device, ids, record = await _ready(hass, freezer, f"sh{mode}{lead}{frozen}", OPTS[mode])
    down = {"now": None}
    real = coord.upstream_down_since
    coord.upstream_down_since = lambda d: (("zigbee2mqtt", down["now"]) if d == device.id and down["now"] else real(d))
    if frozen:
        await walk(hass, freezer, 6 * HOUR, step=600)
    else:
        await walk(hass, freezer, 20 * 60)
        await _set(hass, ids, "on")
    cat0 = record[DEV_FROZEN_CATEGORY]
    heard = record[DEV_LAST_ACTIVITY]
    back = record_events(hass, EVENT_RECOVERED)
    faults = record_events(hass, EVENT_FAULT)
    if lead:
        await _set(hass, ids, "unavailable")
        await walk(hass, freezer, lead)
    down["now"] = dt_util.utcnow().timestamp()
    await _set(hass, ids, "unavailable")
    await walk(hass, freezer, 120)
    await _set(hass, ids, "on")
    await walk(hass, freezer, 120)
    down["now"] = None
    await walk(hass, freezer, 30 * 60)
    _restart_only(device, record, lead, cat0, heard, back, faults)


@pytest.mark.parametrize("frozen", [True, False])
@pytest.mark.parametrize("lead", [0, 600])
@pytest.mark.parametrize("mode", ["none", "unav", "frz"])
async def test_ha_restart(hass: HomeAssistant, freezer, mode, lead, frozen):
    coord, device, ids, record = await _ready(hass, freezer, f"hr{mode}{lead}{frozen}", OPTS[mode])
    if frozen:
        await walk(hass, freezer, 6 * HOUR, step=600)
    else:
        await walk(hass, freezer, 20 * 60)
        await _set(hass, ids, "on")
    cat0 = record[DEV_FROZEN_CATEGORY]
    heard = record[DEV_LAST_ACTIVITY]
    back = record_events(hass, EVENT_RECOVERED)
    faults = record_events(hass, EVENT_FAULT)
    if lead:
        await _set(hass, ids, "unavailable")
        await walk(hass, freezer, lead)
    coord = await restart(hass, freezer, down=120, before_setup=lambda: [hass.states.async_set(e, "unavailable") for e in ids.values()])
    await walk(hass, freezer, 60)
    await _set(hass, ids, "on")
    await walk(hass, freezer, 40 * 60)
    record = coord.data[DATA_DEVICES][device.id]
    _restart_only(device, record, lead, cat0, heard, back, faults)


@pytest.mark.parametrize("lead", [5, 60])
@pytest.mark.parametrize("down", [240, 600])
@pytest.mark.parametrize("mode", ["none", "unav", "frz"])
async def test_reboot_stack_first(hass: HomeAssistant, freezer, mode, down, lead):
    coord, device, ids, record = await _ready(hass, freezer, f"rb{mode}{down}{lead}", OPTS[mode])
    await walk(hass, freezer, 6 * HOUR, step=600)
    cat0 = record[DEV_FROZEN_CATEGORY]
    heard = record[DEV_LAST_ACTIVITY]
    faults = record_events(hass, EVENT_FAULT)
    back = record_events(hass, EVENT_RECOVERED)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, lead)
    coord = await restart(hass, freezer, down=down)
    await walk(hass, freezer, 60)
    for key, eid in ids.items():
        hass.states.async_set(eid, "on" if key == "main" else "87")
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    record = coord.data[DATA_DEVICES][device.id]
    info = dict(mode=mode, cat0=cat0, cat=record[DEV_FROZEN_CATEGORY], moved=record[DEV_LAST_ACTIVITY] != heard,
                items=_listed_kinds(coord, device.id), back=len(_mine(back, device.id)), faults=len(_mine(faults, device.id)))
    assert not info["moved"], info
    if mode != "frz":
        assert info["cat"] == "frozen", info
    assert not info["back"], info
