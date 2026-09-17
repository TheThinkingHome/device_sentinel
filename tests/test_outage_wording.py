# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_wording.py, Version: 0.21.12 (2026-09-17)

"""What a bridge's row says, down and recovering (rulings #442, #443).

The second fleet's coordinator pull of 16 September read "ZHA
recovering: 14 of 14 devices remain unavailable" beside "0 of the 14
devices have already recovered". The total a down row prints is every
device behind the bridge, and the total a recovering row prints is
what went down, so each now names which total it is. And a recovery
with nothing back yet says what it is waiting for.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    STACK_Z2M,
    UPSTREAM_KIND,
)
from tests.test_bridge_pairing import _Stub, _device
from tests.helpers import setup_coordinator


async def _bridge_back_with(hass, freezer, down: int, back: int):
    """Take a bridge down with `down` devices judged, bring it back,
    and return `back` of them."""
    devices = [
        _device(hass, "mqtt", f"bulb{i}", f"Bulb {i}") for i in range(down)
    ]
    coord = await setup_coordinator(hass)
    # Watched, as a real bridge's devices are; the fixture's entities
    # carry no state, so the rebuild would not watch them on its own.
    for device in devices:
        coord._watched[device.id] = "mqtt"
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await coord._on_render_tick(None)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    await coord._on_render_tick(None)
    began = coord._bridge_down_at[STACK_Z2M]
    now = dt_util.utcnow().timestamp()
    for device in devices:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = now
    freezer.tick(120)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await coord._on_render_tick(None)
    assert coord.bridge_recovering_at(STACK_Z2M) is not None
    # The tick judges every device after it samples the bridge, and
    # these entities never really went unavailable, so the judge
    # cleared them. Set the verdicts as the outage left them: the
    # first `back` returned, the rest still down.
    for index, device in enumerate(devices):
        record = coord.data[DATA_DEVICES][device.id]
        down_still = index >= back
        record[DEV_FROZEN_CATEGORY] = "unavailable" if down_still else None
        record[DEV_FROZEN_SINCE] = now if down_still else None
    assert coord.bridge_recovery_counts(STACK_Z2M) == (down - back, down)
    return coord, began


async def test_a_bridge_back_with_nothing_returned_says_what_it_waits_for(
    hass: HomeAssistant, freezer
):
    coord, began = await _bridge_back_with(hass, freezer, down=3, back=0)
    summary, body = coord._upstream_item_text(
        STACK_Z2M, {UPSTREAM_KIND: began}, 3
    )
    assert summary == "Zigbee2MQTT is back: waiting for 3 devices to reconnect"
    assert "Zigbee2MQTT came back at" in body
    assert "waiting for the 3 devices that went down to reconnect" in body
    assert "already recovered" not in body
    assert "reported as its own problem" in body


async def test_a_bridge_recovery_counts_against_what_went_down(
    hass: HomeAssistant, freezer
):
    coord, began = await _bridge_back_with(hass, freezer, down=3, back=1)
    summary, body = coord._upstream_item_text(
        STACK_Z2M, {UPSTREAM_KIND: began}, 3
    )
    assert summary == (
        "Zigbee2MQTT recovering: 2 of the 3 devices that went down "
        "remain unavailable"
    )
    assert "1 of the 3 devices that went down have already recovered" in body


async def test_one_device_waiting_reads_in_the_singular(
    hass: HomeAssistant, freezer
):
    coord, began = await _bridge_back_with(hass, freezer, down=1, back=0)
    summary, body = coord._upstream_item_text(
        STACK_Z2M, {UPSTREAM_KIND: began}, 1
    )
    assert summary == "Zigbee2MQTT is back: waiting for 1 device to reconnect"
    assert "waiting for the 1 device that went down to reconnect" in body


async def test_one_device_left_of_several_reads_in_the_singular(
    hass: HomeAssistant, freezer
):
    coord, began = await _bridge_back_with(hass, freezer, down=3, back=2)
    summary, _body = coord._upstream_item_text(
        STACK_Z2M, {UPSTREAM_KIND: began}, 3
    )
    assert summary == (
        "Zigbee2MQTT recovering: 1 of the 3 devices that went down "
        "remains unavailable"
    )
