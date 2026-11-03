# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_bridge_down_wait.py, Version: 0.28.0 (2026-11-03)

"""An upstream that goes down in the seconds before a restart is the
restart (rule UP-03).

On the reference rig the Zigbee2MQTT bridge goes offline 3 to 8 seconds
before Home Assistant stops each night. A minute check that fell in that
gap would write a bridge outage, so the brief would tell a three-minute
outage on some nights and not on others. A bridge newly down waits a
minute before its outage is written down and
announced: a stop inside the wait leaves no trace, and a bridge back
inside it was never an outage. An integration entry and a hub already
wait about as long, and are proven here to the same end.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_DOWN_WAIT_SECONDS,
    BRIDGE_RUNNING,
    BRIDGE_SEEN_STATE,
    DATA_BRIDGE_SEEN,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_SINCE,
    STACK_Z2M,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_INTEGRATION_DOWN,
)

from tests.helpers import record_events, register_device, setup_coordinator
from tests.test_bridge_pairing import _Stub
from tests.test_upstream_loading import _plant_integration


def _kinds(coord, kind):
    return [row for row in coord.data[DATA_SYSTEM_EVENTS] if row["kind"] == kind]


async def _rig(hass):
    rider, (eid,) = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    return coord, rider, eid


async def test_a_bridge_down_seconds_before_a_stop_leaves_no_trace(hass: HomeAssistant, freezer):
    """The rig's night: offline, one check, then Home Assistant stops."""
    coord, _rider, _eid = await _rig(hass)
    downs = record_events(hass, "device_sentinel_upstream_down")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    freezer.tick(3)
    coord._sample_bridges()
    await coord._on_hass_stop(None)
    await hass.async_block_till_done()
    assert _kinds(coord, SYS_BRIDGE_DOWN) == []
    assert list(downs) == []
    # Nothing a restart could resume or owe a recovery for.
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M][BRIDGE_SEEN_STATE] == BRIDGE_RUNNING
    assert coord._bridge_down_at == {}


async def test_a_bridge_back_inside_the_wait_was_never_an_outage(hass: HomeAssistant, freezer):
    coord, _rider, _eid = await _rig(hass)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    freezer.tick(BRIDGE_DOWN_WAIT_SECONDS - 10)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    freezer.tick(120)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert _kinds(coord, SYS_BRIDGE_DOWN) == [] and _kinds(coord, SYS_BRIDGE_UP) == []
    assert list(downs) == [] and list(ups) == []
    assert coord._bridge_down_pending == {}


async def test_a_bridge_down_past_the_wait_is_dated_from_the_first_check(hass: HomeAssistant, freezer):
    coord, _rider, _eid = await _rig(hass)
    downs = record_events(hass, "device_sentinel_upstream_down")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    first = dt_util.utcnow().timestamp()
    coord._sample_bridges()
    assert _kinds(coord, SYS_BRIDGE_DOWN) == []
    freezer.tick(BRIDGE_DOWN_WAIT_SECONDS + 1)
    coord._sample_bridges()
    await hass.async_block_till_done()
    (row,) = _kinds(coord, SYS_BRIDGE_DOWN)
    assert abs(row["when"] - first) < 1
    assert abs(coord._bridge_down_at[STACK_Z2M] - first) < 1
    assert len(downs) == 1
    assert abs(dt_util.parse_datetime(downs[0]["since"]).timestamp() - first) < 1


async def test_a_device_waits_with_its_bridge(hass: HomeAssistant, freezer):
    """Inside the wait a device behind the bridge is held as it was, so
    one that went with the bridge gets no verdict of its own."""
    coord, rider, eid = await _rig(hass)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    assert coord._held_by_upstream(rider.id, dt_util.utcnow().timestamp())
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(30)
    coord._judge_all_devices()
    assert coord.data[DATA_DEVICES][rider.id].get(DEV_FROZEN_SINCE) is None


async def test_a_reader_that_dates_its_own_outage_is_believed_at_once(hass: HomeAssistant):
    """ZHA has already waited out its own dwell when it reads down."""
    coord, _rider, _eid = await _rig(hass)
    onset = dt_util.utcnow().timestamp() - 70
    stub = _Stub(BRIDGE_DOWN)
    stub.down_since = onset
    coord._bridge_readers[STACK_Z2M] = stub
    coord._sample_bridges()
    (row,) = _kinds(coord, SYS_BRIDGE_DOWN)
    assert abs(row["when"] - onset) < 1


async def test_an_integration_down_seconds_before_a_stop_leaves_no_trace(hass: HomeAssistant, freezer):
    """An integration entry already waits a minute before it is down."""
    source, device = _plant_integration(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._watched[device.id] = "controller_hub"
    coord._sample_integrations(dt_util.utcnow().timestamp())
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    freezer.tick(5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    await coord._on_hass_stop(None)
    await hass.async_block_till_done()
    assert _kinds(coord, SYS_INTEGRATION_DOWN) == []
    source.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_a_hub_down_seconds_before_a_stop_leaves_no_trace(hass: HomeAssistant, freezer):
    """A hub is down only after a second not-connected reading (rule
    STACK-09), so one lost just before a stop is never told."""
    from custom_components.device_sentinel.const import EVENT_FAULT

    from tests.test_lutron_hub import _house, _item, _past_grace, _tick

    h = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    await _past_grace(hass, freezer)
    h.garage.runtime_data.bridge._leap = None
    await _tick(hass, freezer)
    await h.coord._on_hass_stop(None)
    await hass.async_block_till_done()
    assert _item(h.coord, h.g_hub.id) is None
    assert h.coord.hub_down_since(h.g_hub.id) is None
    assert [f for f in faults if f["device_id"] == h.g_hub.id] == []
