# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_startup_grace_recovery.py, Version: 0.27.10 (2026-10-27)

"""A device that really reports inside the startup grace (rule WATCH-10).

Its verdict and its Problem List line go at once; its
device_sentinel_recovered event is held and fired when the grace
closes, so an automation that heard the fault still hears it end.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
)

from custom_components.device_sentinel.events import DATA_HELD_RECOVERIES

from tests.helpers import record_events, register_device, setup_coordinator
from tests.outage_helpers import arm, past_grace, rec, reload, restart, walk


def _listed(coord, device_id) -> bool:
    return any(i.get("device_id") == device_id for i in coord.todo_items)


async def _frozen_door_across_a_restart(hass, freezer):
    """A door frozen and listed before a restart, inside the next grace."""
    device, (eid,) = register_device(hass, "door", "Door")
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    faults = record_events(hass, EVENT_FAULT)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert [f["device_id"] for f in faults] == [device.id]
    coord = await restart(hass, freezer)
    assert coord._in_startup_grace()
    assert _listed(coord, device.id)
    return device, eid, coord


async def test_recovery_inside_grace_is_held_until_it_closes(
    hass: HomeAssistant, freezer
):
    device, eid, coord = await _frozen_door_across_a_restart(hass, freezer)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(eid, "off")  # the device speaks, inside the grace
    await hass.async_block_till_done()
    # The verdict and the line go at once (rule WATCH-10).
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert not _listed(coord, device.id)
    # The event waits for the grace to close.
    assert coord._in_startup_grace()
    assert list(recovered) == []
    await walk(hass, freezer, 6 * 60)
    await hass.async_block_till_done()
    assert not coord._in_startup_grace()
    assert [e["device_id"] for e in recovered] == [device.id]
    assert recovered[0]["kind"] == "frozen"


async def test_held_recovery_fires_once(hass: HomeAssistant, freezer):
    """The grace close and any later event do not send it twice."""
    device, eid, coord = await _frozen_door_across_a_restart(hass, freezer)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * 60)
    coord._release_held_recoveries()
    await walk(hass, freezer, 5 * 60)
    await hass.async_block_till_done()
    assert len(recovered) == 1


async def test_a_held_recovery_survives_a_reload_inside_the_grace(
    hass: HomeAssistant, freezer
):
    device, eid, coord = await _frozen_door_across_a_restart(hass, freezer)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(eid, "off")  # reports inside the grace
    await hass.async_block_till_done()
    assert not _listed(coord, device.id)
    await walk(hass, freezer, 60)  # an option saved a minute later
    coord = await reload(hass)
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    assert not coord._in_startup_grace()
    assert [e["device_id"] for e in recovered] == [device.id]
    assert not coord.data.get(DATA_HELD_RECOVERIES)


async def test_a_held_recovery_survives_a_restart_inside_the_grace(
    hass: HomeAssistant, freezer
):
    device, eid, coord = await _frozen_door_across_a_restart(hass, freezer)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    coord = await restart(hass, freezer, down=60)  # a second restart
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    assert [e["device_id"] for e in recovered] == [device.id]
    assert not coord.data.get(DATA_HELD_RECOVERIES)


async def test_a_sent_recovery_is_not_sent_again_after_a_restart(
    hass: HomeAssistant, freezer
):
    device, eid, coord = await _frozen_door_across_a_restart(hass, freezer)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * 60)  # the grace closes and sends it
    assert len(recovered) == 1
    coord = await restart(hass, freezer, down=60)
    assert coord._held_recoveries == []
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    assert len(recovered) == 1


@pytest.mark.parametrize(
    "stored",
    [
        "junk",
        [1, None, "x"],
        [{"device_id": "a", "name": "A", "area": "Unassigned", "kind": "frozen",
          "down_for": "long", "resolved_by": "self"}],
        [{"device_id": 5, "name": "A", "area": "Unassigned", "kind": "frozen",
          "down_for": 60, "resolved_by": "self"}],
        [{"name": "A"}],
    ],
)
async def test_a_damaged_held_recovery_is_dropped(hass: HomeAssistant, stored):
    """Dropped without an exception, and nothing is sent for it (rule
    STOR-05)."""
    coord = await setup_coordinator(hass)
    recovered = record_events(hass, "device_sentinel_recovered")
    coord.data[DATA_HELD_RECOVERIES] = stored
    coord._restore_held_recoveries()
    assert coord._held_recoveries == []
    assert DATA_HELD_RECOVERIES not in coord.data
    coord._release_held_recoveries()
    await hass.async_block_till_done()
    assert list(recovered) == []


async def test_a_sound_held_recovery_is_kept(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    good = {"device_id": "a", "name": "A", "area": "Unassigned", "kind": "frozen",
            "down_for": None, "resolved_by": "unknown"}
    coord.data[DATA_HELD_RECOVERIES] = [good, {"name": "bad"}]
    coord._restore_held_recoveries()
    assert coord._held_recoveries == [good]
    assert coord.data[DATA_HELD_RECOVERIES] == [good]


async def test_held_recovery_survives_a_report_while_setup_waits_for_mqtt(
    hass: HomeAssistant, freezer
):
    """A restart inside the grace with one recovery held. While the new
    run's setup waits for MQTT, a second listed device really reports:
    its recovery is held too, and the first is not overwritten, because
    the held list is taken back before setup listens (rule WATCH-10)."""
    import asyncio
    from unittest.mock import patch

    from custom_components.device_sentinel.transport_mqtt import MQTTBrokerReader

    a, (ea,) = register_device(hass, "door_a", "Door A")
    b, (eb,) = register_device(hass, "door_b", "Door B")
    hass.states.async_set(ea, "on")
    hass.states.async_set(eb, "on")
    coord = await setup_coordinator(hass)
    for dev in (a, b):
        record = arm(coord, dev.id, rhythm=600.0)
        record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, a.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert rec(coord, b.id)[DEV_FROZEN_CATEGORY] == "frozen"
    # States kept across both restarts, so the only reports are the two
    # this test makes.
    coord = await restart(hass, freezer, keep_states=True)
    recovered = record_events(hass, "device_sentinel_recovered")
    hass.states.async_set(ea, "off")  # A speaks inside the grace: held
    await hass.async_block_till_done()
    assert [p["device_id"] for p in coord._held_recoveries] == [a.id]
    await walk(hass, freezer, 60)

    real_start = MQTTBrokerReader.async_start

    async def slow_start(reader):
        # B speaks while setup waits for the MQTT client.
        hass.states.async_set(eb, "off")
        for _ in range(5):
            await asyncio.sleep(0)
        return await real_start(reader)

    with patch.object(MQTTBrokerReader, "async_start", slow_start):
        coord = await restart(hass, freezer, down=60, keep_states=True)
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    assert not coord.data.get(DATA_HELD_RECOVERIES)
    sent = [e["device_id"] for e in recovered]
    assert b.id in sent
    assert a.id in sent, "Door A's held recovery was never sent"
