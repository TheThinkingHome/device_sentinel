# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_unannounced_outage_across_restart.py, Version: 0.27.5 (2026-10-26)

"""A bridge or broker outage whose down was never told on the bus,
standing across a restart (rule UP-10).

It fell inside one run's startup grace, so its down was held, and Home
Assistant restarted before the grace closed. After the restart it is
held for the new grace and told once afterwards, and only then does its
restored follow: never a restored with no down before it.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_SEEN_STATE,
    BROKER_DOWN,
    BROKER_RUNNING,
    DATA_BRIDGE_SEEN,
    DATA_BROKER_SEEN,
    STACK_Z2M,
)
from custom_components.device_sentinel.interventions import BROKER_LABEL

from tests.helpers import record_events, register_device, setup_coordinator
from tests.outage_helpers import past_grace, restart, walk
from tests.test_bridge_pairing import _Stub
from tests.test_broker import _stub


async def test_a_bridge_down_never_told_is_told_after_the_next_grace(
    hass: HomeAssistant, freezer
):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    assert coord._in_startup_grace()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()  # inside the grace: held, not told
    seen = coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    assert seen[BRIDGE_SEEN_STATE] == BRIDGE_DOWN and seen["told"] is False
    await walk(hass, freezer, 60)
    coord = await restart(hass, freezer, down=60)  # inside the grace
    coord._watched[rider.id] = "mqtt"
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    assert STACK_Z2M not in coord._upstream_owed
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert len(downs) == 1 and list(ups) == []
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["told"] is True
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert len(downs) == 1 and len(ups) == 1


async def test_a_bridge_down_never_told_and_back_inside_the_grace_says_nothing(
    hass: HomeAssistant, freezer
):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await walk(hass, freezer, 60)
    coord = await restart(hass, freezer, down=60)
    coord._watched[rider.id] = "mqtt"
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()  # back inside the new grace
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    await hass.async_block_till_done()
    assert list(downs) == [] and list(ups) == []


async def test_a_broker_down_never_told_is_told_after_the_next_grace(
    hass: HomeAssistant, freezer
):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    assert coord._in_startup_grace()
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BROKER_SEEN] = {BRIDGE_SEEN_STATE: BROKER_RUNNING, "started": now - 50}
    coord._broker_reader = _stub(BROKER_RUNNING, now - 50)
    coord._sample_broker(now)
    coord._broker_reader = _stub(BROKER_DOWN, now - 50)
    coord._sample_broker(now + 1)
    assert coord.data[DATA_BROKER_SEEN]["told"] is False
    await walk(hass, freezer, 60)
    coord = await restart(hass, freezer, down=60)
    coord._watched[rider.id] = "mqtt"
    assert BROKER_LABEL not in coord._upstream_owed
    await past_grace(hass, freezer)
    await walk(hass, freezer, 60)
    assert len(downs) == 1 and list(ups) == []
    later = dt_util.utcnow().timestamp()
    coord._broker_reader.async_stop()
    coord._broker_reader = _stub(BROKER_RUNNING, later - 5)
    coord._sample_broker(later)
    await hass.async_block_till_done()
    assert len(downs) == 1 and len(ups) == 1


@pytest.mark.parametrize("damaged", ["no", 0, None, [False]])
async def test_a_damaged_told_flag_is_dropped(hass: HomeAssistant, damaged):
    """Not a flag: dropped without an exception, and the outage is taken
    as told, as one remembered before the flag existed (rule STOR-07)."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BRIDGE_SEEN] = {
        STACK_Z2M: {"state": BRIDGE_DOWN, "since": now - 600, "told": damaged}
    }
    coord._restore_bridge_state()
    assert "told" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    assert STACK_Z2M in coord._upstream_owed
    assert STACK_Z2M not in coord._upstream_held
