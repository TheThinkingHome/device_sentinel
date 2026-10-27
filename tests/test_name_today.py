# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_name_today.py, Version: 0.27.9 (2026-10-27)

"""Each surface shows the name a device has today (rule DEV-02), the
Brief tab's past days included."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    TODO_KIND_FROZEN,
)

from .helpers import register_device, registry_settled, setup_coordinator


def _opened(device_id, name, when):
    return {
        INC_DEVICE_ID: device_id, INC_NAME: name, INC_KIND: TODO_KIND_FROZEN,
        INC_EVENT: INCIDENT_OPENED, INC_WHEN: when, INC_CAUSE: None, INC_DURATION: None,
    }


async def test_a_past_day_lists_the_name_of_today(hass: HomeAssistant):
    device, _ = register_device(hass, "d2", name="Old Name")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [_opened(device.id, "Old Name", now - 3600)]
    dr.async_get(hass).async_update_device(device.id, name_by_user="New Name")
    await hass.async_block_till_done()
    await registry_settled(hass)
    assert [row["name"] for row in coord._standing_at(now)] == ["New Name"]


async def test_a_device_no_longer_known_keeps_its_stored_name(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [_opened("gone_device", "Stored Name", now - 3600)]
    assert [row["name"] for row in coord._standing_at(now)] == ["Stored Name"]
