# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_inside_rhythm.py, Version: 0.24.1 (2026-10-03)

"""An outage inside a device's rhythm is ignored; one reaching its grace is not.

A device's wait is its rhythm, its normal longest gap, plus a grace for
the report it is then due to send. An outage shorter than the rhythm
and wholly inside it, from the last report, could only have swallowed
a report the device was not yet due to send, so the gap is learned
whole. One that reaches the grace, or is as long as the rhythm, may
have swallowed the report the device was due to send, so the gap is
forgotten (James, 3 October 2026). Before this rule every stored outage
forgot the gap, so the nightly three-minute Zigbee2MQTT restart cost
slow reporters their gap across it every night.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    STACK_Z2M,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_DURATION,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
)

from .test_bridge_hold import _house

HOUR = 3600.0


def _outage(fell, back):
    return [
        {SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: STACK_Z2M, SYS_WHEN: fell, SYS_DURATION: None, "detail": None},
        {SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: STACK_Z2M, SYS_WHEN: back, SYS_DURATION: back - fell, "detail": None},
    ]


async def _slow_device(hass, freezer, rhythm_hours, silent_hours):
    """A device whose rhythm is `rhythm_hours`, silent for `silent_hours`."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [rhythm_hours * HOUR * (0.95 + 0.01 * (i % 5)) for i in range(20)]
    now = dt_util.utcnow()
    last = (now - timedelta(hours=silent_hours)).timestamp()
    record[DEV_LAST_ACTIVITY] = last
    record[DEV_TODAY_MAX] = None
    return coord, record, seen, now, last


async def _speak(hass, seen, now):
    hass.states.async_set(seen, now.isoformat())
    await hass.async_block_till_done()


async def test_a_short_outage_inside_the_rhythm_is_ignored(hass, freezer):
    """The nightly restart: three minutes, an hour into a ten-hour rhythm."""
    coord, record, seen, now, last = await _slow_device(hass, freezer, 10, 8)
    coord.data[DATA_SYSTEM_EVENTS] = _outage(last + HOUR, last + HOUR + 180)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 7.9 * HOUR


async def test_a_short_outage_in_the_grace_forgets_the_gap(hass, freezer):
    """The same three minutes, when the device was already due."""
    coord, record, seen, now, last = await _slow_device(hass, freezer, 2, 3)
    coord.data[DATA_SYSTEM_EVENTS] = _outage(last + 2.5 * HOUR, last + 2.5 * HOUR + 180)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "an outage in the grace was ignored"


async def test_an_outage_as_long_as_the_rhythm_forgets_the_gap(hass, freezer):
    coord, record, seen, now, last = await _slow_device(hass, freezer, 2, 5)
    coord.data[DATA_SYSTEM_EVENTS] = _outage(last + 600, last + 600 + 2.5 * HOUR)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "an outage longer than the rhythm was ignored"


async def test_a_device_with_no_rhythm_forgets_any_gap_an_outage_touched(hass, freezer):
    coord, record, seen, now, last = await _slow_device(hass, freezer, 10, 8)
    record[DEV_DAILY_MAX] = [HOUR] * 3
    coord.data[DATA_SYSTEM_EVENTS] = _outage(last + HOUR, last + HOUR + 180)
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "a device with no rhythm learned across an outage"


async def test_an_open_outage_inside_the_rhythm_is_ignored_too(hass, freezer):
    """Still marked down at the report, the outage counts as running to
    it; begun ten minutes ago in a ten-hour rhythm, it is inside."""
    coord, record, seen, now, last = await _slow_device(hass, freezer, 10, 8)
    coord._bridge_down_at[STACK_Z2M] = now.timestamp() - 600
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 7.9 * HOUR


async def test_a_rhythm_that_is_not_a_number_forgets_the_gap(hass, freezer):
    """Found by the 0.24.1 adversarial round: every comparison with NaN is
    false, so an unusable rhythm read the outage as inside it."""
    coord, record, seen, now, last = await _slow_device(hass, freezer, 10, 8)
    coord.data[DATA_SYSTEM_EVENTS] = _outage(last + HOUR, last + HOUR + 180)
    coord._freeze_rhythm = lambda r: {"rhythm": float("nan")}
    await _speak(hass, seen, now)
    assert record[DEV_TODAY_MAX] is None, "a rhythm that is not a number learned across an outage"
