# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_model_pace_range.py, Version: 0.27.9 (2026-10-27)

"""A model's pace is a range, the slowest and fastest of the other cells
of the same maker and model with a weekly fall; a cell with no fall yet,
one that rose or one that held flat does not count, and fewer than two others say nothing
(rule BAT-16)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
)

from .helpers import register_device, setup_coordinator


def _falling(per_week):
    return [round(80.0 - (per_week / 7) * day, 2) for day in range(42)]


NEW = [99.0] * 10                                   # under four weeks
RISEN = [round(40.0 + day, 2) for day in range(42)]  # a new cell put in
FLAT = [100.0] * 42                                 # reads 100 for weeks


async def _model(hass, series):
    devices = []
    for key in series:
        device, _ = register_device(hass, f"m{key}", name=f"Door {key}")
        dr.async_get(hass).async_update_device(device.id, manufacturer="Aqara", model="MCCGQ11LM")
        devices.append(device)
    coord = await setup_coordinator(hass)
    for key, device in zip(series, devices):
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_BATTERY_DAILY] = list(series[key])
        record[DEV_BATTERY_VALUE] = series[key][-1]
    return coord, devices


async def test_the_pace_is_the_range_of_the_falling_others(hass: HomeAssistant):
    coord, devices = await _model(hass, {
        "a": _falling(1.0), "b": _falling(2.0), "c": _falling(3.0), "d": NEW, "e": RISEN, "f": FLAT,
    })
    paces = coord.battery_model_paces()
    got = paces[devices[0].id]
    assert got["others"] == 2
    assert 1.5 < got["pace_low"] < got["pace_high"] < 3.5
    assert "pace" not in got
    # The new cell sees all three falling cells.
    assert paces[devices[3].id]["others"] == 3


async def test_fewer_than_two_falling_others_say_nothing(hass: HomeAssistant):
    coord, devices = await _model(hass, {"a": _falling(2.0), "b": _falling(2.0), "c": NEW, "d": NEW})
    paces = coord.battery_model_paces()
    assert devices[0].id not in paces
    assert paces[devices[2].id]["others"] == 2
