# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_broker_restart_at_stop.py, Version: 0.27.8 (2026-10-27)

"""A broker that restarted since the last minute check, just before Home
Assistant stops, is told at the stop with its length (rule UP-02): the
next start would see only its start time move."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_SEEN_STATE,
    BROKER_RUNNING,
    DATA_BROKER_SEEN,
    DATA_SYSTEM_EVENTS,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
)

from tests.helpers import register_device, setup_coordinator
from tests.test_broker import _stub


async def test_a_restart_just_before_the_stop_has_its_length(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    rider, _ = register_device(hass, "rider", "Rider")
    coord._watched[rider.id] = "mqtt"
    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BROKER_SEEN] = {BRIDGE_SEEN_STATE: BROKER_RUNNING, "started": 1.0}
    coord._broker_reader = _stub(BROKER_RUNNING, now - 20, regressed=True, stopped_at=now - 50)
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    await coord._on_hass_stop(SimpleNamespace())
    await hass.async_block_till_done()
    rows = coord.data[DATA_SYSTEM_EVENTS][before:]
    kinds = [r["kind"] for r in rows]
    assert kinds.count(SYS_BROKER_DOWN) == 1 and kinds.count(SYS_BROKER_UP) == 1
    up = next(r for r in rows if r["kind"] == SYS_BROKER_UP)
    assert up["duration"] == 30


async def test_a_broker_check_that_fails_does_not_stop_the_save(hass: HomeAssistant, caplog):
    coord = await setup_coordinator(hass)

    class Broken:
        @property
        def state(self):
            raise RuntimeError("reader gone")

        def async_stop(self):
            return None

    coord._broker_reader = Broken()
    saved = []

    async def save(*_a, **_k):
        saved.append(True)

    coord._save_now = save
    await coord._on_hass_stop(SimpleNamespace())
    await hass.async_block_till_done()
    assert saved
