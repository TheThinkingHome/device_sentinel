# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_bridge_outage_across_restart.py, Version: 0.27.5 (2026-10-26)

"""A bridge outage open across a restart (rule UP-10).

It was announced down before the restart, so it is not announced down
again after the grace, and it gets its restored, even when the bridge
returns inside the grace.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    DATA_BRIDGE_SEEN,
    STACK_Z2M,
)

from tests.helpers import record_events, register_device, setup_coordinator
from tests.test_bridge_pairing import _Stub


async def _restarted_with_bridge_down(hass, devices=None):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    now = dt_util.utcnow().timestamp()
    seen = {BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: now - 1800}
    if devices is not None:
        seen["devices"] = devices
    coord.data[DATA_BRIDGE_SEEN] = {STACK_Z2M: seen}
    coord._grace_until = now + 300  # inside the startup grace
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._restore_bridge_state()
    return coord, rider, now


async def test_back_inside_the_grace_gets_its_restored(hass: HomeAssistant):
    coord, rider, now = await _restarted_with_bridge_down(hass, devices=4)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert [u["name"] for u in ups] == [STACK_Z2M]
    assert ups[0]["devices"] == 4
    assert ups[0]["for_seconds"] >= 1800
    coord._grace_until = 0.0
    coord._announce_held_upstreams()
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert list(downs) == [] and len(ups) == 1


async def test_still_down_after_the_grace_is_not_announced_again(
    hass: HomeAssistant, freezer
):
    coord, rider, now = await _restarted_with_bridge_down(hass)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    assert coord.upstream_down_since(rider.id) == (STACK_Z2M, now - 1800)
    coord._grace_until = 0.0
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    assert list(downs) == []
    # Back after the grace: one restored, counted as it is now.
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert list(downs) == []
    assert [u["name"] for u in ups] == [STACK_Z2M]
    assert ups[0]["devices"] == 1


async def test_a_down_announced_in_this_run_stores_its_count(hass: HomeAssistant):
    """So a restart in the middle can close it with the same count."""
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    downs = record_events(hass, "device_sentinel_upstream_down")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert [d["devices"] for d in downs] == [1]
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["devices"] == 1


# ------------------------------------------------ the worst count kept


def _up_rows(coord):
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_BRIDGE_UP

    return [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_BRIDGE_UP]


async def test_the_worst_count_is_remembered_while_down(hass: HomeAssistant):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    coord._upstream_peak[STACK_Z2M] = 3
    coord._note_upstream_peaks()
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["worst"] == 3
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    assert "worst" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]


async def test_the_worst_count_survives_a_restart(hass: HomeAssistant):
    """Down with five at worst before the restart: its end says five,
    not the one still down after it (rule UP-11)."""
    coord, rider, now = await _restarted_with_bridge_down(hass, devices=6)
    coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["worst"] = 5
    coord._upstream_peak.clear()
    coord._upstream_said.clear()
    coord._restore_bridge_state()
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    (up,) = _up_rows(coord)
    assert up["worst"] == 5
    assert up["devices"] >= 5


@pytest.mark.parametrize("damaged", ["5", -1, True, 5.5, 10**13, None, [5]])
async def test_a_damaged_worst_count_is_dropped(hass: HomeAssistant, damaged):
    coord, rider, now = await _restarted_with_bridge_down(hass, devices=damaged)
    coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["worst"] = damaged
    coord._upstream_peak.clear()
    coord._upstream_said.clear()
    coord._restore_bridge_state()  # no exception
    seen = coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    assert "worst" not in seen and "devices" not in seen
    assert STACK_Z2M not in coord._upstream_peak
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    (up,) = _up_rows(coord)
    assert up["worst"] == 0
    assert [u["devices"] for u in ups] == [1]
