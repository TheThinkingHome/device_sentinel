# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_set_aside_left_out.py, Version: 0.27.9 (2026-10-27)

"""Lists and counts read watched devices only (rules SIG-09, WATCH-09):
Signal: Weak, the signal-mute picker and the day's rule line leave out a
device that is set aside, though its record is kept."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_SIGNAL_VALUE

from tests.helpers import register_device, registry_settled, setup_coordinator
from tests.outage_helpers import arm


async def test_a_set_aside_device_leaves_the_signal_lists(hass: HomeAssistant, freezer):
    kept, _ = register_device(hass, "kept", "Kept")
    gone, _ = register_device(hass, "gone", "Gone Disabled")
    coord = await setup_coordinator(hass)
    for d in (kept.id, gone.id):
        arm(coord, d, rhythm=600.0)
        coord.data[DATA_DEVICES][d][DEV_SIGNAL_VALUE] = -70.0
    dr.async_get(hass).async_update_device(gone.id, disabled_by=dr.DeviceEntryDisabler.USER)
    await hass.async_block_till_done()
    freezer.tick(5)
    await registry_settled(hass)
    coord._rebuild_registry_view()
    assert gone.id in coord._set_aside and gone.id in coord.data[DATA_DEVICES]
    coord.signal_badday = lambda record: {"bad": True, "fall": 9.0, "baseline": -60.0, "today": -69.0}
    assert {row["device_id"] for row in coord.signal_weak_list} == {kept.id}
    assert {row["device_id"] for row in coord.detected_signals} == {kept.id}
    coord.rule_counts_fold(dt_util.utcnow().timestamp())
    assert ": 1 device(s) waited" in coord.rule_day_line
