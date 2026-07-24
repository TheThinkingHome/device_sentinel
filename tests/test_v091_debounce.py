# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v091_debounce.py, Version: 0.9.1 (2026-07-24)

"""0.9.1 tests: the grace-share taint debounce (#137).

The flat 180 s taint discarded a genuine self-recovery whenever an
unavailable stretch inside the silence crossed 180 s, whatever the
true silence length. On the fleet this lost Button James Night
Table's 9.01h gap (basis 6.30h) and kept flagging Door Master
(basis 3.71h) for silences it survived on its own.

The fix makes the threshold per device: a floor plus a share of the
device's freeze window. A blip under it is a hiccup and the silence
is learned; an unavailable over it is real downtime and the gap is
discarded. These tests drive the real state-change handlers so the
whole debounce path is exercised, and they assert the two fleet
cases by name, the fast-device floor, and the recorder that writes
the tainting duration for the rig to read.
"""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EP_TAINT_SECONDS,
    FREEZE_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
)

DOMAIN = "device_sentinel"

# Pinned at 01:00 UTC (the harness runs in UTC) so the multi-hour
# silences below never cross midnight, which would roll the live
# maximum into the daily series and empty the value being asserted.
# The same lesson from the A1 baseline: keep the test off the wall
# clock rather than reason about it.
_PIN = "2026-07-24T01:00:00+00:00"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device, entity.entity_id


async def _coordinator(hass, freezer):
    freezer.move_to(_PIN)
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return coord


def _arm(coord, device_id, basis_hours):
    """Give a device a learned rhythm so it has a freeze window.

    The debounce takes a share of that window, so an armed device is
    what exercises the share; an unarmed device gets the floor alone
    and is tested separately.
    """
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [basis_hours * 3600.0] * (FREEZE_ARMING_DAYS + 2)


async def _silence(hass, freezer, eid, silent_hours, unavailable_seconds):
    """Drive a real silence: report, go quiet, blip unavailable, return.

    The device reports, stays silent for silent_hours, reads
    unavailable for unavailable_seconds partway through, then reports
    a real value on its own. Every step goes through the state-change
    handlers so the debounce path is what decides the outcome.
    """
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=silent_hours * 3600.0))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=unavailable_seconds))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()


def _learned_gap(record):
    """Return the largest gap the device has learned, live or rolled.

    Robust to a midnight rollover that moves the live maximum into
    the daily series: the learned gap is the max across both.
    """
    candidates = list(record[DEV_DAILY_MAX])
    if record[DEV_TODAY_MAX] is not None:
        candidates.append(record[DEV_TODAY_MAX])
    return max(candidates) if candidates else None


async def test_button_james_long_self_recovery_is_learned(
    hass: HomeAssistant, freezer
):
    """The lost-data case, now fixed. A 9h self-recovery on a device
    with a ~6.3h basis, its unavailable blip a few seconds, is
    learned: the debounce (floor + share) is far longer than the
    blip, so no taint is set and the real gap reaches the maximum."""
    device, eid = _register(hass, "bj", "Button James Night Table")
    coord = await _coordinator(hass, freezer)
    _arm(coord, device.id, 6.3)
    rec = coord.data[DATA_DEVICES][device.id]

    await _silence(hass, freezer, eid, silent_hours=9.0, unavailable_seconds=8)

    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 8 * 3600
    # No episode was tainted: the gap is honest, not excluded.
    assert all(
        ep.get(EP_TAINT_SECONDS) is None
        for ep in coord.data.get(DATA_EPISODES, [])
    )


async def test_door_master_real_outage_stays_discarded(
    hass: HomeAssistant, freezer
):
    """The false-flag case, still correct. A device with a ~3.7h
    basis, unavailable well past its debounce before it returns, has
    that gap discarded: the taint fires and the completed gap is
    excluded from learning."""
    device, eid = _register(hass, "dm", "Door Master")
    coord = await _coordinator(hass, freezer)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    _arm(coord, device.id, 3.7)
    rec = coord.data[DATA_DEVICES][device.id]

    # Go unavailable long enough to taint (past floor + share), then
    # come back on the device's own report. The taint is set on the
    # recovering transition and consumed by the completing stamp.
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=90 * 60))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    # The gap that spanned the outage is discarded: the live maximum
    # never took it.
    assert rec[DEV_TODAY_MAX] is None or rec[DEV_TODAY_MAX] < 90 * 60
    assert rec[DEV_TAINTED] is False  # consumed by the recovery


async def test_a_fast_device_keeps_the_floor_against_a_two_second_blip(
    hass: HomeAssistant, freezer
):
    """The reason the floor exists. A device with a tiny window would
    get a near-zero debounce from a pure share, so a two-second mesh
    blip would taint it. The floor holds: two seconds is far under
    the ten-minute floor, so the gap is learned."""
    device, eid = _register(hass, "f1", "Fast Sensor")
    coord = await _coordinator(hass, freezer)
    _arm(coord, device.id, 0.02)  # ~72 s basis, a very fast device
    rec = coord.data[DATA_DEVICES][device.id]

    await _silence(
        hass, freezer, eid, silent_hours=0.5, unavailable_seconds=2
    )

    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 0.5 * 3600 - 5


async def test_the_recorder_writes_the_tainting_duration(
    hass: HomeAssistant, freezer
):
    """Step 4's recorder, proven. When a taint discards a gap, the
    unavailable duration lands on the episode as taint_seconds, so
    the rig can measure the real spread rather than a guess."""
    device, eid = _register(hass, "rec", "Recorder Sensor")
    coord = await _coordinator(hass, freezer)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()

    # Arm the device and backdate its last contact past its basis so
    # the silence scan opens an episode for it.
    coord._grace_until = 0.0
    _arm(coord, device.id, 3.7)
    rec_record = coord.data[DATA_DEVICES][device.id]
    rec_record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - 6 * 3600.0
    )
    coord._judge_all_devices()
    assert coord.data.get(DATA_EPISODES), "no episode opened"

    # Now taint it with a long unavailable and recover on its own.
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60 * 60))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    tainted = [
        ep
        for ep in coord.data.get(DATA_EPISODES, [])
        if ep.get(EP_TAINT_SECONDS) is not None
    ]
    assert tainted, "no episode recorded a tainting duration"
    assert tainted[0][EP_TAINT_SECONDS] == pytest.approx(60 * 60, abs=5)


async def test_an_unarmed_device_uses_the_floor(
    hass: HomeAssistant, freezer
):
    """A device with no learned window falls back to the floor alone:
    with nothing learned there is no grace to take a share of. A
    five-minute unavailable is under the ten-minute floor and is
    learned; the same on an armed device is well within its window
    too, so the floor is the operative rule here."""
    device, eid = _register(hass, "u1", "Unarmed Sensor")
    coord = await _coordinator(hass, freezer)
    rec = coord.data[DATA_DEVICES][device.id]
    # Not armed: no DEV_DAILY_MAX, so _freeze_window is None.
    assert len(rec[DEV_DAILY_MAX]) < FREEZE_ARMING_DAYS

    await _silence(
        hass,
        freezer,
        eid,
        silent_hours=0.5,
        unavailable_seconds=DEFAULT_TAINT_FLOOR_MINUTES * 60 - 120,
    )

    # Five minutes < the ten-minute floor, so no taint: learned.
    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 0.5 * 3600 - 5
