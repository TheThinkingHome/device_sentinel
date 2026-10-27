# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_model_pace.py, Version: 0.27.9 (2026-10-27)

"""How fast the others of a battery's model fall, as context (#738).

Measured on both houses on 23 October 2026: a battery given its sisters'
pace missed its own by about as much as the pace, so the pace is shown
beside a battery and never sets its time left.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import DEV_BATTERY_DAILY, DEV_BATTERY_VALUE

from .helpers import register_device, registry_settled, setup_coordinator


def _falling(per_week: float, start: float = 90.0) -> list[float]:
    return [round(start - per_week / 7 * day, 2) for day in range(35)]


def _model(hass: HomeAssistant, uid: str, name: str, per_week: float, model: str = "3RDS17BZ"):
    device, _ = register_device(hass, uid, name)
    dr.async_get(hass).async_update_device(device.id, manufacturer="Third Reality", model=model)
    return device, per_week


async def test_the_others_of_a_model_give_its_pace(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    made = [
        _model(hass, "m1", "Door A", 0.7), _model(hass, "m2", "Door B", 1.4), _model(hass, "m3", "Door C", 2.1),
        _model(hass, "m4", "Lone Sensor", 1.0, model="ONE-OFF"),
        _model(hass, "m5", "Pair A", 1.0, model="PAIR"), _model(hass, "m6", "Pair B", 1.0, model="PAIR"),
    ]
    await registry_settled(hass)
    for device, per_week in made:
        record = coord.data["devices"][device.id]
        record[DEV_BATTERY_DAILY] = _falling(per_week)
        record[DEV_BATTERY_VALUE] = record[DEV_BATTERY_DAILY][-1]
    (a, _), (b, _), (c, _), (lone, _), (pair, _), _ = made
    paces = coord.battery_model_paces()
    # Door A's others are B and C: the range 1.4 to 2.1 (rule BAT-16).
    assert paces[a.id]["others"] == 2, paces[a.id]
    assert abs(paces[a.id]["pace_low"] - 1.4) < 0.15 and abs(paces[a.id]["pace_high"] - 2.1) < 0.15, paces[a.id]
    assert abs(paces[c.id]["pace_low"] - 0.7) < 0.15 and abs(paces[c.id]["pace_high"] - 1.4) < 0.15, paces[c.id]
    assert paces[b.id]["model"] == "Third Reality 3RDS17BZ"
    # Fewer than two others: nothing is said.
    assert lone.id not in paces and pair.id not in paces
    # Shown on the page and on Battery Trends; never the time left.
    page = coord._page_battery(coord.data["devices"][a.id], a.id)
    assert page["model_pace"] == paces[a.id]
    rows = {row["name"]: row for row in coord.battery_trends()["steady"] + coord.battery_trends()["falling"]}
    assert rows["Door A"]["model_pace"] == paces[a.id]
