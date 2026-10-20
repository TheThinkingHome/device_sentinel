# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_mutes.py, Version: 0.26.8 (2026-10-20)

"""The Daily Brief leaves out what a device is muted for (ruling #715).

Last 24 Hours and Repeat Offenders leave out a device's rows of the
kinds its mutes cover, as the Problem List does: a freeze mute covers
frozen and never reported, an unavailable mute covers unavailable,
unknown and dropping out, the battery and signal mutes their own, and
Mute everything covers every kind. The mute is read as it stands now,
so a row that opened before the mute goes with it. Found on Tim Plas's
house on 20 October 2026: D48, L20 and L21, muted for freeze or
unavailable, stayed in both sections.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FLAPPING,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
)

from tests.helpers import register_device, setup_coordinator

DAY = 86400.0


def _opened(device, kind, when):
    return {
        INC_DEVICE_ID: device.id,
        INC_NAME: device.name,
        INC_KIND: kind,
        INC_EVENT: INCIDENT_OPENED,
        INC_WHEN: when,
        INC_CAUSE: None,
    }


def _twice(device, kind, now):
    """Two unexplained openings on two days, over the repeat floor."""
    return [_opened(device, kind, now - 3 * DAY), _opened(device, kind, now - 3600.0)]


def _repeat_kinds(coord, now):
    return {(row["device_id"], row["kind"]) for row in coord._repeat_offender_rows(now)}


async def _house(hass: HomeAssistant, options_for):
    """One device per mute, each muted as options_for says."""
    devices = {
        key: register_device(hass, key, name=f"Device {key}")[0]
        for key in ("plain", "freeze", "unavailable", "everything", "battery", "signal")
    }
    options = {
        CONF_FREEZE_MUTED_DEVICES: [devices["freeze"].id],
        CONF_UNAVAILABLE_MUTED_DEVICES: [devices["unavailable"].id],
        CONF_MUTED_DEVICES: [devices["everything"].id],
        CONF_BATTERY_MUTED_DEVICES: [devices["battery"].id],
        CONF_SIGNAL_MUTED_DEVICES: [devices["signal"].id],
    }
    coord = await setup_coordinator(hass, options_for(options))
    coord._rebuild_registry_view()
    coord.data[DATA_SYSTEM_EVENTS] = []
    return coord, devices


async def test_repeat_offenders_leave_out_each_muted_kind(hass: HomeAssistant):
    """Each mute takes its own kinds out of Repeat Offenders, and only those."""
    coord, d = await _house(hass, lambda options: options)
    now = dt_util.utcnow().timestamp()
    rows = []
    for kind in (TODO_KIND_FROZEN, TODO_KIND_NEVER_REPORTED, TODO_KIND_UNAVAILABLE,
                 TODO_KIND_UNKNOWN, TODO_KIND_FLAPPING, TODO_KIND_LOW_BATTERY,
                 TODO_KIND_FALLING_BATTERY, TODO_KIND_RAILED_SIGNAL):
        for device in d.values():
            rows += _twice(device, kind, now)
    coord.data[DATA_INCIDENTS] = rows

    shown = _repeat_kinds(coord, now)

    freeze_kinds = {TODO_KIND_FROZEN, TODO_KIND_NEVER_REPORTED}
    down_kinds = {TODO_KIND_UNAVAILABLE, TODO_KIND_UNKNOWN, TODO_KIND_FLAPPING}
    battery_kinds = {TODO_KIND_LOW_BATTERY, TODO_KIND_FALLING_BATTERY}
    every = freeze_kinds | down_kinds | battery_kinds | {TODO_KIND_RAILED_SIGNAL}
    assert {k for i, k in shown if i == d["plain"].id} == every
    assert {k for i, k in shown if i == d["freeze"].id} == every - freeze_kinds
    assert {k for i, k in shown if i == d["unavailable"].id} == every - down_kinds
    assert {k for i, k in shown if i == d["battery"].id} == every - battery_kinds
    assert {k for i, k in shown if i == d["signal"].id} == every - {TODO_KIND_RAILED_SIGNAL}
    # Mute everything had no filter here before 0.26.8.
    assert not {k for i, k in shown if i == d["everything"].id}


async def test_last_24_hours_leaves_out_a_kind_muted_device(hass: HomeAssistant):
    """Tim's case: a lamp muted for freeze, still in Last 24 Hours as frozen."""
    coord, d = await _house(hass, lambda options: options)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [
        _opened(d["freeze"], TODO_KIND_FROZEN, now - 7200.0),
        _opened(d["unavailable"], TODO_KIND_UNAVAILABLE, now - 7000.0),
        _opened(d["plain"], TODO_KIND_FROZEN, now - 6800.0),
    ]

    text = coord._write_brief(
        hass.config.path("www", "device_sentinel"), "manual", now - DAY, now, complete=True,
    )
    tail = text.split("## Last 24 Hours", 1)[1]

    assert "Device plain" in tail
    assert "Device freeze" not in text
    assert "Device unavailable" not in text


async def test_a_freeze_mute_keeps_the_devices_unavailable_rows(hass: HomeAssistant):
    """A freeze mute is not an unavailable mute: going unavailable is still told."""
    coord, d = await _house(hass, lambda options: options)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [_opened(d["freeze"], TODO_KIND_UNAVAILABLE, now - 3600.0)]

    text = coord._write_brief(
        hass.config.path("www", "device_sentinel"), "manual", now - DAY, now, complete=True,
    )

    assert "Device freeze" in text.split("## Last 24 Hours", 1)[1]


async def test_a_lifted_mute_brings_the_rows_back(hass: HomeAssistant):
    """The mute is read as it stands now, not as it stood when the row opened."""
    coord, d = await _house(hass, lambda options: {**options, CONF_FREEZE_MUTED_DEVICES: []})
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = _twice(d["freeze"], TODO_KIND_FROZEN, now)

    assert (d["freeze"].id, TODO_KIND_FROZEN) in _repeat_kinds(coord, now)


async def test_a_row_with_no_device_is_kept(hass: HomeAssistant):
    """A damaged row with no device id is not taken for a muted one."""
    coord, _ = await _house(hass, lambda options: options)
    assert coord._brief_muted(None, TODO_KIND_FROZEN) is False
    assert coord._brief_muted(12, TODO_KIND_FROZEN) is False


async def test_the_brief_tab_says_what_the_file_says(hass: HomeAssistant):
    """The dashboard's Brief tab leaves out the same rows as the written brief."""
    coord, d = await _house(hass, lambda options: options)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [
        _opened(d["freeze"], TODO_KIND_FROZEN, now - 600.0),
        _opened(d["plain"], TODO_KIND_FROZEN, now - 500.0),
        *_twice(d["unavailable"], TODO_KIND_UNAVAILABLE, now),
    ]

    page = coord.dashboard_brief(dt_util.now().date())

    told = {row["device_id"] for row in page["events"]}
    assert d["plain"].id in told
    assert d["freeze"].id not in told
    assert d["unavailable"].id not in told
    assert d["unavailable"].id not in {row["device_id"] for row in page["repeat"]["rows"]}



async def test_the_line_saying_a_device_was_muted_stays(hass: HomeAssistant):
    """Muting a frozen device for freeze leaves its "muted" line in Last 24
    Hours, as before 0.26.8 (adversarial round of 0.26.8)."""
    from custom_components.device_sentinel.const import ACTION_MUTED, INCIDENT_ACTION

    coord, d = await _house(hass, lambda options: options)
    now = dt_util.utcnow().timestamp()
    muted = {**_opened(d["freeze"], TODO_KIND_FROZEN, now - 3000.0), INC_EVENT: INCIDENT_ACTION, INC_CAUSE: ACTION_MUTED}
    everything = {**_opened(d["everything"], TODO_KIND_FROZEN, now - 2900.0), INC_EVENT: INCIDENT_ACTION, INC_CAUSE: ACTION_MUTED}
    coord.data[DATA_INCIDENTS] = [_opened(d["freeze"], TODO_KIND_FROZEN, now - 7200.0), muted, everything]

    assert coord._brief_keeps(muted) is True
    assert coord._brief_keeps(everything) is False
    assert coord._brief_keeps(coord.data[DATA_INCIDENTS][0]) is False
