# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_start_handback.py, Version: 0.28.12 (2026-11-11)

"""A value handed back as Home Assistant starts (rules UNAV-05, FRZ-11).

On a real start an integration that finishes after Device Sentinel adds
its entities with the values it kept, each written as a first state.
Inside the startup grace that is the integration handing back its cache,
not the device speaking: a device that fell silent before the restart
keeps its clock and is listed on time. Outside the grace a first state
is a device paired or an entity switched on, and it speaks.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_FROZEN,
)

from tests.outage_helpers import restart, walk
from tests.test_freeze_unavailable_split import _ready


async def _silent_before_window(hass, freezer, uid, domain="test"):
    """A device that reported once and then fell silent; stop at a third
    of its window before it would be listed."""
    coord, device, ids, record = await _ready(hass, freezer, uid, domain=domain)
    last = float(record[DEV_LAST_ACTIVITY])
    window = coord._freeze_window(record)
    assert window is not None
    lead = min(40 * 60, window / 3)
    await walk(hass, freezer, last + window - lead - dt_util.utcnow().timestamp(), step=300)
    assert record[DEV_FROZEN_CATEGORY] is None
    return coord, device, ids, last, lead


async def test_a_first_state_handed_back_at_a_start_does_not_move_the_clock(
    hass: HomeAssistant, freezer
):
    """Its integration finishes after Device Sentinel, as on a real boot,
    and writes the value it kept as a first state. The device said
    nothing, so its clock stays and it is listed on time."""
    coord, device, ids, last, lead = await _silent_before_window(hass, freezer, "r6sa")
    coord = await restart(hass, freezer, down=120)
    record = coord.data[DATA_DEVICES][device.id]
    assert hass.states.get(ids["main"]).state == "on"
    assert record[DEV_LAST_ACTIVITY] == pytest.approx(last), (
        "the value handed back at the start moved the clock of a silent device"
    )
    await walk(hass, freezer, lead + 30 * 60, step=60)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_a_first_state_outside_the_grace_is_the_device(hass: HomeAssistant, freezer):
    """An entity switched back on long after the start: its first value
    is the device speaking."""
    coord, device, ids, last, _lead = await _silent_before_window(hass, freezer, "r6sc")
    hass.states.async_remove(ids["main"])
    await hass.async_block_till_done()
    hass.states.async_set(ids["main"], "off")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_LAST_ACTIVITY] > last
