# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_boot_handback.py, Version: 0.27.5 (2026-10-26)

"""A value handed back at boot is not the device speaking (rules UP-06,
WATCH-10).

On a real boot Device Sentinel can set up before the integrations it
watches, and their entities then arrive with no previous state, carrying
the value they kept. Known Gap 63: that first value is read as a report,
so a frozen device recovers across a restart without saying anything.
James ruled the fix for the release after 0.27.5 (26 October 2026): each
watched entity's last value is stored, and after a restart a first value
with no previous state that equals the stored one is a hand-back.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
)

from tests.helpers import record_events, register_device, setup_coordinator
from tests.outage_helpers import arm, past_grace, rec, restart, walk


@pytest.mark.xfail(
    strict=True,
    reason="Known Gap 63: the boot hand-back is read as a report; "
    "fixed in the release after 0.27.5",
)
async def test_a_frozen_device_stays_frozen_when_its_value_is_handed_back(
    hass: HomeAssistant, freezer
):
    """A door with no Last Seen, frozen before a restart. After the
    restart its integration comes up after Device Sentinel and hands
    back the value it kept, with no previous state: the door has said
    nothing, so it stays frozen and no recovery is sent."""
    device, (eid,) = register_device(hass, "door", "Door")
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer)
    assert hass.states.get(eid).state == "on"
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    assert [e["device_id"] for e in recovered] == []
