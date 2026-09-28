# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_credit.py, Version: 0.23.14 (2026-09-28)

"""An outage is not a device's silence (#536).

The reference rig, 28 September. Zigbee2MQTT was down from 3:40 to 7:37,
one bridge problem throughout; when the three-minute rejoin window
closed, 24 living devices were announced frozen in one check on four
hours they could not have been heard in. The time an upstream was down
is now taken out of its devices' silence, from the stored returns, so
a restart in the middle of an outage cannot erase it. A device already
frozen before the outage keeps that verdict, its last-heard time is
never changed, and the gap across the outage is not learned.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    LEARNING_MIN_DAYS,
    STACK_Z2M,
    SYS_BRIDGE_UP,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_DURATION,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_UP,
)
from custom_components.device_sentinel.detect_freeze import _covered

from .helpers import register_device, setup_coordinator
from .test_bridge_hold import _house, _minutes
from .test_bridge_pairing import _Stub

HOUR = 3600.0


def _event(kind, scope, when, duration=None):
    return {SYS_KIND: kind, SYS_SCOPE: scope, SYS_WHEN: when, SYS_DURATION: duration, "detail": None}


async def _one(hass, domain="mqtt"):
    device, _ = register_device(hass, "d", name="Door Laundry")
    coord = await setup_coordinator(hass)
    coord._watched[device.id] = domain
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3000.0] * (LEARNING_MIN_DAYS + 5)
    return coord, device, record


# ------------------------------------------------------------- the measure


def test_overlapping_spans_are_counted_once():
    assert _covered([(10, 20), (15, 30), (40, 50)], 0, 100) == 30
    assert _covered([(10, 20)], 15, 100) == 5
    assert _covered([], 0, 100) == 0


async def test_a_bridge_outage_is_taken_out_of_the_silence(hass: HomeAssistant):
    coord, device, record = await _one(hass)
    coord._stack_for_device = lambda d: STACK_Z2M
    now = dt_util.utcnow().timestamp()
    back = now - 5 * 60
    record[DEV_LAST_ACTIVITY] = back - 4 * HOUR - 10 * 60  # heard 10 minutes before the outage
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_BRIDGE_UP, STACK_Z2M, back, 4 * HOUR)]
    window = coord._freeze_window(record)
    silence = coord._observed_silence(record, now, device.id, window)
    assert abs(silence - 15 * 60) < 1, silence
    assert record[DEV_LAST_ACTIVITY] == back - 4 * HOUR - 10 * 60, "the last-heard time was changed"


async def test_a_device_frozen_before_the_outage_keeps_its_silence(hass: HomeAssistant):
    coord, device, record = await _one(hass)
    coord._stack_for_device = lambda d: STACK_Z2M
    now = dt_util.utcnow().timestamp()
    window = coord._freeze_window(record)
    back = now - 60
    record[DEV_LAST_ACTIVITY] = back - 4 * HOUR - window - HOUR  # overdue an hour before it began
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_BRIDGE_UP, STACK_Z2M, back, 4 * HOUR)]
    silence = coord._observed_silence(record, now, device.id, window)
    assert silence == now - record[DEV_LAST_ACTIVITY]


async def test_a_short_nightly_outage_costs_a_long_reporter_only_its_minutes(hass: HomeAssistant):
    """The owner's concern: a nightly reboot must not keep a dead
    long reporter from ever being judged."""
    coord, device, record = await _one(hass)
    coord._stack_for_device = lambda d: STACK_Z2M
    record[DEV_DAILY_MAX] = [30 * HOUR] * (LEARNING_MIN_DAYS + 5)
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 40 * HOUR
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(SYS_BRIDGE_UP, STACK_Z2M, now - night * 24 * HOUR, 120.0) for night in (1, 0.5)
    ]
    window = coord._freeze_window(record)
    silence = coord._observed_silence(record, now, device.id, window)
    assert abs(silence - (40 * HOUR - 240)) < 1


async def test_ha_downtime_inside_the_outage_is_not_taken_out_twice(hass: HomeAssistant):
    coord, device, record = await _one(hass)
    coord._stack_for_device = lambda d: STACK_Z2M
    now = dt_util.utcnow().timestamp()
    back = now - 60
    began = back - 4 * HOUR
    record[DEV_LAST_ACTIVITY] = began - 600
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_BRIDGE_UP, STACK_Z2M, back, 4 * HOUR)]
    coord._last_alive = began + HOUR
    coord._downtime = 120.0
    window = coord._freeze_window(record)
    silence = coord._observed_silence(record, now, device.id, window)
    assert abs(silence - (600 + 60)) < 1


async def test_the_broker_integrations_and_wifi_are_upstreams_too(hass: HomeAssistant):
    coord, device, record = await _one(hass, domain="zwave_js")
    now = dt_util.utcnow().timestamp()
    back = now - 60
    record[DEV_LAST_ACTIVITY] = back - HOUR - 300
    window = coord._freeze_window(record)
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_INTEGRATION_UP, "zwave_js", back, HOUR)]
    assert abs(coord._observed_silence(record, now, device.id, window) - 360) < 1
    coord._watched[device.id] = "hue"
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_WIFI_UP, "wifi", back + 1, HOUR)]
    coord._wifi_ties = {device.id: "device_tracker.x"}
    assert abs(coord._observed_silence(record, now, device.id, window) - 360) < 2
    coord._wifi_ties = {}
    coord._watched[device.id] = "mqtt"
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event(SYS_BROKER_DOWN, "mqtt", back - HOUR),
        _event(SYS_BROKER_UP, "mqtt", back),  # a return with no duration: dated from its fall
    ]
    assert abs(coord._observed_silence(record, now, device.id, window) - 360) < 1


async def test_an_unrelated_upstream_is_not_credited(hass: HomeAssistant):
    coord, device, record = await _one(hass, domain="zwave_js")
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 2 * HOUR
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_INTEGRATION_UP, "lutron_caseta", now - 60, HOUR)]
    window = coord._freeze_window(record)
    assert coord._observed_silence(record, now, device.id, window) == 2 * HOUR


# ----------------------------------------------------------- the whole night


async def test_the_night_of_28_september(hass: HomeAssistant, freezer):
    """A four-hour bridge outage with a restart in the middle: nothing is
    announced when the bridge returns, and a device that stays silent
    past its own window after the return is still caught."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    now = dt_util.utcnow()
    hass.states.async_set(seen, (now - timedelta(minutes=5)).isoformat())
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = (now - timedelta(minutes=5)).timestamp()
    await _minutes(hass, coord, freezer, 1)
    assert record[DEV_FROZEN_CATEGORY] is None
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 60)
    # The restart in the middle: the in-memory record of unavailable
    # entities is gone, as it was at 7:34 on the rig.
    coord._pending_unavailable.clear()
    await _minutes(hass, coord, freezer, 180)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, (now - timedelta(minutes=5)).isoformat())
    await _minutes(hass, coord, freezer, 8)
    assert record[DEV_FROZEN_CATEGORY] is None, "four hours of outage counted as the device's silence"
    assert not [e for e in bus if e[0] == "fault"], bus
    window = coord._freeze_window(record)
    await _minutes(hass, coord, freezer, int(window // 60) + 5)
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "a device still silent past its window after the return"


async def test_the_gap_across_an_outage_is_not_learned(hass: HomeAssistant, freezer):
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    now = dt_util.utcnow()
    record = coord.data[DATA_DEVICES][device.id]
    before = (now - 4 * timedelta(hours=1) - timedelta(minutes=10)).timestamp()
    record[DEV_LAST_ACTIVITY] = before
    record[DEV_TODAY_MAX] = None
    coord.data[DATA_SYSTEM_EVENTS] = [_event(SYS_BRIDGE_UP, STACK_Z2M, now.timestamp() - 60, 4 * HOUR)]
    hass.states.async_set(seen, now.isoformat())  # the device speaks after the outage
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] > before
    assert record[DEV_TODAY_MAX] is None, "the four-hour gap was learned as the device's rhythm"
