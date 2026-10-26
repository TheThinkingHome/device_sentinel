# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_broker_outage_events.py, Version: 0.27.5 (2026-10-26)

"""A broker outage's dates and its bus pair (rules UP-02, UP-04, UP-10).

A quick broker restart runs from its last message before the restart to
its first after, and fires upstream_down and upstream_restored like any
other outage. A broker outage open across a Home Assistant restart is
resumed from when it went down, announced down only once, and gets its
restored, even when it comes back inside the startup grace.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    BROKER_DOWN,
    BROKER_RUNNING,
    BROKER_UNKNOWN,
    DATA_BROKER_SEEN,
    DATA_SYSTEM_EVENTS,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
)
from custom_components.device_sentinel.interventions import BROKER_LABEL

from tests.helpers import record_events, register_device, setup_coordinator
from tests.test_broker import _stub


# ------------------------------------------------------- a quick restart


async def test_a_quick_restart_is_dated_from_its_last_message(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    rider, _ = register_device(hass, "rider", "Rider")
    coord._watched[rider.id] = "mqtt"
    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BROKER_SEEN] = {BRIDGE_SEEN_STATE: BROKER_RUNNING, "started": 1.0}
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    # Last message 10 minutes ago, back 9 minutes ago, noticed now.
    coord._broker_reader = _stub(
        BROKER_RUNNING, now - 540, regressed=True, stopped_at=now - 600
    )
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    coord._sample_broker(now)
    await hass.async_block_till_done()
    rows = coord.data[DATA_SYSTEM_EVENTS][before:]
    assert [r["kind"] for r in rows] == [SYS_BROKER_DOWN, SYS_BROKER_UP]
    down, up = rows
    assert down["when"] == now - 600
    assert up["when"] == now - 540
    assert up["duration"] == 60
    # The integration's page shows it starting before it ended.
    outages = [o for v in coord.integration_outages().values() for o in v]
    went = dt_util.parse_datetime(outages[0]["went_down"]).timestamp()
    assert abs(went - (now - 600)) < 1
    # The bus hears the pair, with the same count on both halves.
    assert len(downs) == 1 and len(ups) == 1
    assert downs[0]["kind"] == ups[0]["kind"] == "broker"
    assert downs[0]["devices"] == ups[0]["devices"] == 1
    assert ups[0]["for_seconds"] == 60
    assert dt_util.parse_datetime(downs[0]["since"]).timestamp() == now - 600
    # Its time is taken out of a rider's silence, from the right span.
    spans = coord._stored_outages()[(SYS_BROKER_UP, "mqtt")]
    assert spans == [(now - 600, now - 540)]
    # Over by the time it is seen: nothing is claimed.
    assert coord.upstream_down_since(rider.id) is None


async def test_a_quick_restart_inside_the_grace_says_nothing(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert coord._in_startup_grace()
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BROKER_SEEN] = {BRIDGE_SEEN_STATE: BROKER_RUNNING, "started": 1.0}
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord._broker_reader = _stub(
        BROKER_RUNNING, now - 40, regressed=True, stopped_at=now - 100
    )
    coord._sample_broker(now)
    coord._grace_until = 0.0
    coord._announce_held_upstreams()
    await hass.async_block_till_done()
    assert list(downs) == [] and list(ups) == []


# --------------------------------------------------- across a restart


async def _restarted_with_broker_down(hass, grace=True):
    rider, _ = register_device(hass, "rider", "Rider")
    coord = await setup_coordinator(hass)
    coord._watched[rider.id] = "mqtt"
    now = dt_util.utcnow().timestamp()
    # Remembered from the run before: down an hour ago, announced with
    # three devices behind it.
    coord.data[DATA_BROKER_SEEN] = {
        BRIDGE_SEEN_STATE: BROKER_DOWN,
        BRIDGE_SEEN_SINCE: now - 3600,
        "started": 1.0,
        "devices": 3,
    }
    coord._broker_reader = _stub(BROKER_UNKNOWN, None)
    if not grace:
        coord._grace_until = 0.0
    coord._restore_bridge_state()
    return coord, rider, now


async def test_an_outage_across_a_restart_is_resumed(hass: HomeAssistant):
    coord, rider, now = await _restarted_with_broker_down(hass, grace=False)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    # Silent all run, past the grace: still the same outage.
    assert coord._sample_broker(now) == BROKER_DOWN
    assert coord._broker_down_at == now - 3600
    assert coord.upstream_down_since(rider.id) == (BROKER_LABEL, now - 3600)
    assert coord.upstream_down_since_for(BROKER_LABEL) == now - 3600
    await hass.async_block_till_done()
    assert list(downs) == []  # announced before the restart, not again
    # It comes back.
    coord._broker_reader = _stub(BROKER_RUNNING, now + 50)
    coord._sample_broker(now + 60)
    await hass.async_block_till_done()
    rows = coord.data[DATA_SYSTEM_EVENTS][before:]
    assert [r["kind"] for r in rows] == [SYS_BROKER_UP]
    assert rows[0]["duration"] == 3660
    assert list(downs) == []
    assert len(ups) == 1
    assert ups[0]["devices"] == 3
    assert ups[0]["for_seconds"] == 3660
    assert coord.upstream_down_since(rider.id) is None


async def test_an_outage_across_a_restart_back_inside_the_grace_is_closed(
    hass: HomeAssistant,
):
    coord, rider, now = await _restarted_with_broker_down(hass, grace=True)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    assert coord._in_startup_grace()
    coord._broker_reader = _stub(BROKER_RUNNING, now + 20)
    coord._sample_broker(now + 30)
    await hass.async_block_till_done()
    assert len(ups) == 1 and ups[0]["devices"] == 3
    coord._grace_until = 0.0
    coord._announce_held_upstreams()
    coord._sample_broker(now + 400)
    await hass.async_block_till_done()
    assert list(downs) == [] and len(ups) == 1


async def test_the_worst_count_survives_a_restart(hass: HomeAssistant):
    """Remembered while down and restored at the start, so the broker's
    return records the most it had down at once (rule UP-11)."""
    coord, rider, now = await _restarted_with_broker_down(hass, grace=False)
    coord._upstream_peak[BROKER_LABEL] = 2
    coord._note_upstream_peaks()
    assert coord.data[DATA_BROKER_SEEN]["worst"] == 2
    coord.data[DATA_BROKER_SEEN]["worst"] = 4
    coord._upstream_peak.clear()
    coord._upstream_said.clear()
    coord._restore_bridge_state()
    coord._broker_reader = _stub(BROKER_RUNNING, now + 50)
    coord._sample_broker(now + 60)
    up = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_BROKER_UP][-1]
    assert up["worst"] == 4
    assert "worst" not in coord.data[DATA_BROKER_SEEN]


async def test_a_damaged_worst_count_is_dropped(hass: HomeAssistant):
    coord, rider, now = await _restarted_with_broker_down(hass, grace=False)
    coord.data[DATA_BROKER_SEEN]["worst"] = "lots"
    coord._upstream_peak.clear()
    coord._restore_bridge_state()
    assert "worst" not in coord.data[DATA_BROKER_SEEN]
    assert BROKER_LABEL not in coord._upstream_peak
