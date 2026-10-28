# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_upstream_push_across_restart.py, Version: 0.27.10 (2026-10-27)

"""The phone pushes of a bridge or broker outage open across a restart
(rule UP-09).

An outage is pushed twice, when down and when over, and only the first
push sounds. A down pushed before the restart is remembered with the
outage, so it is not pushed again after the grace, and its over push
still follows, after the grace if it came back inside it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BROKER_DOWN,
    BROKER_RUNNING,
    DATA_BRIDGE_SEEN,
    DATA_BROKER_SEEN,
    STACK_Z2M,
    UPSTREAM_SETTLE_SECONDS,
)
from custom_components.device_sentinel.interventions import BROKER_LABEL

from tests.helpers import register_device, setup_coordinator
from tests.outage_helpers import past_grace, restart, tick
from tests.test_bridge_pairing import _Stub
from tests.test_broker import _stub
from tests.test_wifi_push_phases import _owed


def _record_pushes(coord, sent):
    """Record every upstream push, and whether it sounds (a push sounds
    unless its name was already announced)."""

    async def _push(name, count, recovered=False):
        sent.append((name, recovered, name not in coord._upstream_announced))
        if recovered:
            coord._upstream_announced.pop(name, None)
        else:
            coord._upstream_announced[name] = count

    coord.async_push_upstream = _push


async def _bridge_pushed_down(hass, freezer, uid):
    rider, _ = register_device(hass, uid, "Rider")
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    coord._watched[rider.id] = "mqtt"
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    freezer.tick(timedelta(seconds=UPSTREAM_SETTLE_SECONDS + 5))
    coord._critical = False
    # The down push goes once, sounding, and is remembered at once.
    assert _owed(coord) == [(STACK_Z2M, False)]
    assert _owed(coord) == []
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["pushed"] is True
    assert coord._critical
    return rider


async def test_bridge_down_is_not_pushed_again_after_a_restart(
    hass: HomeAssistant, freezer
):
    rider = await _bridge_pushed_down(hass, freezer, "rp1")
    coord = await restart(hass, freezer, down=120)
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._stack_for_device = lambda device_id: STACK_Z2M
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=3)
    assert coord.upstream_down_since(rider.id) is not None  # resumed
    assert sent == []
    # When it is over, the over push follows, silent.
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await tick(hass, freezer, step=61, n=5)
    assert sent == [(STACK_Z2M, True, False)]
    assert "pushed" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]


async def test_broker_down_is_not_pushed_again_after_a_restart(
    hass: HomeAssistant, freezer
):
    rider, _ = register_device(hass, "bp1", "Rider")
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    coord._watched[rider.id] = "mqtt"
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING, "started": now - 9000}
    coord._broker_reader = _stub(BROKER_DOWN, now - 9000)
    coord._sample_broker(now)
    assert coord._broker_down_at is not None
    freezer.tick(timedelta(seconds=UPSTREAM_SETTLE_SECONDS + 5))
    assert _owed(coord) == [(BROKER_LABEL, False)]
    assert _owed(coord) == []
    assert coord.data[DATA_BROKER_SEEN]["pushed"] is True

    coord = await restart(hass, freezer, down=120)
    sent: list = []
    _record_pushes(coord, sent)
    coord._rides_the_broker = lambda device_id: True
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=3)
    assert coord.upstream_down_since(rider.id) == (BROKER_LABEL, now)  # resumed
    assert sent == []


async def test_bridge_back_inside_the_grace_still_pushes_over(
    hass: HomeAssistant, freezer
):
    rider = await _bridge_pushed_down(hass, freezer, "rp2")
    coord = await restart(hass, freezer, down=120)
    sent: list = []
    _record_pushes(coord, sent)
    coord._stack_for_device = lambda device_id: STACK_Z2M
    assert coord._in_startup_grace()
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()  # back inside the grace
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=5)
    assert coord.upstream_down_since(rider.id) is None
    assert [(name, over) for name, over, _sound in sent] == [(STACK_Z2M, True)]


async def test_over_push_survives_a_restart_inside_the_hand_back(
    hass: HomeAssistant, freezer
):
    """Back before the restart, still inside its three-minute hand-back,
    so its over push had not gone: it goes after the next grace, once
    and silent."""
    await _bridge_pushed_down(hass, freezer, "hb1")
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    assert _owed(coord) == []
    assert STACK_Z2M in coord._upstream_announced
    assert coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]["pushed"] is True
    freezer.tick(timedelta(seconds=60))

    coord = await restart(hass, freezer, down=60)
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._stack_for_device = lambda device_id: STACK_Z2M
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=5)
    assert sent == [(STACK_Z2M, True, False)]
    assert "pushed" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]


async def test_over_push_is_cleared_once_sent(hass: HomeAssistant, freezer):
    """Back and over before any restart: nothing is left owed."""
    await _bridge_pushed_down(hass, freezer, "hb2")
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await tick(hass, freezer, step=61, n=5)
    assert sent == [(STACK_Z2M, True, False)]
    seen = coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    assert "pushed" not in seen and "devices" not in seen


async def test_bridge_flap_then_restart_pushes_down_once(
    hass: HomeAssistant, freezer
):
    """Down, back and down again inside the hand-back is one outage the
    phone heard once; a restart before the second down settles does
    not push it down again, sounding."""
    rider = await _bridge_pushed_down(hass, freezer, "flap1")
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    assert _owed(coord) == []
    freezer.tick(timedelta(seconds=30))
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._sample_bridges()
    assert _owed(coord) == []  # still inside the settle
    freezer.tick(timedelta(seconds=20))

    coord = await restart(hass, freezer, down=120)
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    coord._stack_for_device = lambda device_id: STACK_Z2M
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=3)
    assert coord.upstream_down_since(rider.id) is not None  # resumed
    assert [p for p in sent if not p[1] and p[2]] == []


@pytest.mark.parametrize("damaged", ["yes", 1, None, [True]])
async def test_a_damaged_pushed_flag_is_dropped(hass: HomeAssistant, damaged):
    """Not a flag: dropped, and the outage is treated as never pushed
    (rule STOR-05)."""
    rider, _ = register_device(hass, "dp", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BRIDGE_SEEN] = {
        STACK_Z2M: {"state": BRIDGE_DOWN, "since": now - 600, "pushed": damaged}
    }
    coord.data[DATA_BROKER_SEEN] = {
        "state": BROKER_DOWN, "since": now - 600, "pushed": damaged
    }
    coord._broker_reader = _stub(BROKER_DOWN, None)
    coord._restore_bridge_state()
    assert "pushed" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    assert "pushed" not in coord.data[DATA_BROKER_SEEN]
    assert STACK_Z2M not in coord._upstream_announced
    assert BROKER_LABEL not in coord._upstream_announced


async def _power_cut(hass, freezer, down=120):
    """The machine loses power: nothing more is written, then a start."""
    from tests.outage_helpers import _quiet, entry_of

    entry = entry_of(hass)
    coordinator = entry.runtime_data
    coordinator._stopped = True
    for name in ("_save_now", "_routine_save", "_save_routine_main",
                 "async_flush_answers", "async_probe_stop"):
        setattr(coordinator, name, _quiet)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=down))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_cleared_bridge_record_reaches_the_file(
    hass: HomeAssistant, freezer, hass_storage
):
    """Once the over push has gone the record is cleared and saved at
    once, not left for an unrelated save (rule UP-09)."""
    from custom_components.device_sentinel.const import STORAGE_KEY

    await _bridge_pushed_down(hass, freezer, "sr1")
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await tick(hass, freezer, step=61, n=5)
    assert sent == [(STACK_Z2M, True, False)]
    assert "pushed" not in coord.data[DATA_BRIDGE_SEEN][STACK_Z2M]
    await tick(hass, freezer, step=60, n=30)  # a quiet half hour
    on_disk = hass_storage[STORAGE_KEY]["data"][DATA_BRIDGE_SEEN][STACK_Z2M]
    assert "pushed" not in on_disk, on_disk


async def test_over_push_not_repeated_after_a_later_power_cut(
    hass: HomeAssistant, freezer
):
    await _bridge_pushed_down(hass, freezer, "sr2")
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    sent: list = []
    _record_pushes(coord, sent)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await tick(hass, freezer, step=61, n=5)
    assert sent == [(STACK_Z2M, True, False)]
    await tick(hass, freezer, step=60, n=30)  # half an hour later
    coord = await _power_cut(hass, freezer)
    again: list = []
    _record_pushes(coord, again)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._stack_for_device = lambda device_id: STACK_Z2M
    await past_grace(hass, freezer)
    await tick(hass, freezer, step=61, n=5)
    assert again == []
