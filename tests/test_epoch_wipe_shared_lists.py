# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_epoch_wipe_shared_lists.py, Version: 0.28.12 (2026-11-11)

"""A statistics-epoch wipe gives each device its own lists (rule STOR-19).

coordinator.async_setup builds ONE fresh record (`fresh =
_new_device_record(...)`) and assigns its values to every stored record
for each field outside EPOCH_KEPT. The list defaults (the gap history
DEV_DAILY_MAX above all) become one list object shared by every device.
The midnight fold appends in place (record[DEV_DAILY_MAX].append(...)),
so at the first midnight after the wipe every device's gap history gets
every device's day, and the learned rhythm of the whole house is wrong
until it ages out. _reconcile_records builds a fresh record per device for
exactly this reason; the epoch wipe does not.

No epoch change ships in this release, so today this needs a stored epoch that
differs (a damaged or missing stats_epoch). The next STATS_EPOCH bump
would meet it on every house. Older than 0.28.x.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_STATS_EPOCH,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    STATS_EPOCH,
    STORAGE_KEY,
)
from tests.helpers import register_device, setup_coordinator


async def test_epoch_wipe_does_not_share_one_list_between_devices(
    hass: HomeAssistant, hass_storage
):
    first, _ = register_device(hass, "epoch_a", "Epoch A")
    second, _ = register_device(hass, "epoch_b", "Epoch B")
    old = {
        DEV_LAST_ACTIVITY: None,
        DEV_DAILY_MAX: [100.0, 200.0],
        DEV_TODAY_MAX: 50.0,
        "first_observed": "2026-07-01T00:00:00+00:00",
        DEV_EVENT_COUNT: 9,
    }
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            "first_installed": "2026-07-01T00:00:00+00:00",
            "setup_count": 5,
            DATA_STATS_EPOCH: "0.2.0",
            DATA_DEVICES: {first.id: dict(old), second.id: dict(old)},
        },
    }
    coord = await setup_coordinator(hass)
    assert coord.data[DATA_STATS_EPOCH] == STATS_EPOCH  # the premise: the wipe ran
    a = coord.data[DATA_DEVICES][first.id]
    b = coord.data[DATA_DEVICES][second.id]
    assert a[DEV_DAILY_MAX] == [] and b[DEV_DAILY_MAX] == []  # the premise
    # What the midnight fold does to one device must not reach the other.
    a[DEV_DAILY_MAX].append(1234.0)
    assert b[DEV_DAILY_MAX] == [], (
        "the epoch wipe handed every device the same gap-history list; "
        "the first fold writes each device's day into all of them"
    )
    shared = [
        field for field, value in a.items()
        if isinstance(value, (list, dict)) and value is b.get(field)
    ]
    assert not shared, shared
