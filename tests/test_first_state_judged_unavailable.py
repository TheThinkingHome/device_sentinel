# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_first_state_judged_unavailable.py, Version: 0.28.12 (2026-11-11)

"""A device judged unavailable that comes back at a start (rules UNAV-05,
UP-06).

A first value written as the device's integration finishes loading is
handed back inside the startup grace, but a device Device Sentinel had
judged unavailable is a real return, its stack now saying it is
available. That holds whether the integration finishes before Home
Assistant's start event (a first state) or after it (a placeholder
first): the outcome does not depend on load order.

The device here holds no values (it showed none in the run its verdict
began, as a device that died across a restart does), so the held-values
watch does not decide. Expected: in both load orders the return is a
recovery, not a listing as frozen.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_HELD_VALUES,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from tests.outage_helpers import restart, walk
from tests.test_freeze_unavailable_split import _ready


@pytest.mark.parametrize("placeholders", [False, True])
async def test_judged_unavailable_device_back_across_a_start_recovers(
    hass: HomeAssistant, freezer, placeholders
):
    coord, device, ids, record = await _ready(hass, freezer, f"r7u{int(placeholders)}")
    window = coord._freeze_window(record)
    assert window is not None
    # Nothing good seen this run before it went: no values to hold.
    coord._last_good.clear()
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not record.get(DEV_HELD_VALUES)
    # Down well past its freeze window.
    await walk(hass, freezer, window + 3600, step=300)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    last = float(record[DEV_LAST_ACTIVITY])

    def _fixed_while_off():
        # Battery changed or lamp switched back on while the house was off;
        # its integration comes up holding values again.
        for key, eid in ids.items():
            hass.states.async_set(eid, "off" if key == "main" else "91")

    coord = await restart(
        hass, freezer, down=120, before_setup=_fixed_while_off, placeholders=placeholders
    )
    await walk(hass, freezer, 6 * 60)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] is None, (
        f"placeholders={placeholders}: a device judged unavailable and back "
        f"across a start is listed {record[DEV_FROZEN_CATEGORY]!r}, not recovered"
    )
    assert float(record[DEV_LAST_ACTIVITY]) > last
