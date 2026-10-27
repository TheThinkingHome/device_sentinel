# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_log_lines.py, Version: 0.27.8 (2026-10-27)

"""Home Assistant's log is for errors and debugging (rule GEN-10). An
ordinary first start writes nothing above debug but the storage it
created, and the routine counts it used to write, the signal census and
the set-aside total, are gone."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .helpers import register_device, setup_coordinator

LOGGER_NAME = "custom_components.device_sentinel"


def _ours(caplog, level):
    return [
        r.getMessage() for r in caplog.records
        if r.name.startswith(LOGGER_NAME) and r.levelno >= level
    ]


async def _house(hass):
    reg = er.async_get(hass)
    plug, _ = register_device(hass, "s1", name="Plug")
    reg.async_get_or_create("sensor", "test", "s1_rssi", device_id=plug.id,
                            original_device_class="signal_strength",
                            unit_of_measurement="dBm")
    other, _ = register_device(hass, "s2", name="Bathroom Sensor")
    reg.async_get_or_create("sensor", "test", "s2_linkquality_pct", device_id=other.id,
                            original_name="Linkquality", unit_of_measurement="%")
    register_device(hass, "empty", name="Nothing On It")   # set aside: no entities
    return await setup_coordinator(hass)


async def test_an_ordinary_start_writes_nothing_above_debug(hass: HomeAssistant, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    await _house(hass)
    # A first start says only that it created its storage, the one trace
    # left if storage is ever lost.
    said = [m for m in _ours(caplog, logging.INFO) if "no existing storage, creating" not in m]
    assert said == [], said


async def test_the_routine_counts_are_gone(hass: HomeAssistant, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    await _house(hass)
    every = _ours(caplog, logging.DEBUG)
    assert not any("signal entity(s)" in m and "refused" in m and m[0].isdigit() for m in every)
    assert not any(m.startswith("Set aside ") and "device(s)" in m for m in every)
    assert not any("signal census" in m.lower() for m in every)


async def test_a_hand_reset_of_the_learned_days_is_logged(hass: HomeAssistant, caplog):
    from custom_components.device_sentinel.const import DATA_DEVICES, DEV_LOGNORMAL_DAYS

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    device, _ = register_device(hass, "d1", name="Door")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_LOGNORMAL_DAYS] = 20
    caplog.clear()
    assert coord.use_trimmed_maximum(device.id)
    # The learned days are gone for good, and this line is their only trace.
    assert any("set to the" in m and "by hand" in m for m in _ours(caplog, logging.INFO))
