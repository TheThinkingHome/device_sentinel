# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_backup_power.py, Version: 0.30.7 (2026-11-26)

"""UPS or Battery Backup, a tick for one wired device (rule DEV-20).

Powered By stays one answer per model; the backup mark is the device's
own, offered while its power is wired, kept in the answers file, and
gone with the device.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from tests.helpers import register_device, setup_coordinator


async def test_a_wired_device_takes_the_mark_and_its_model_twin_does_not(hass: HomeAssistant):
    first, _ = register_device(hass, "plug1", name="Plug 1")
    second, _ = register_device(hass, "plug2", name="Plug 2")
    for device in (first, second):
        dr.async_get(hass).async_update_device(device.id, manufacturer="Shelly", model="Plug S")
    coord = await setup_coordinator(hass)
    coord.page_set_power(first.id, "Mains Powered")
    coord.page_set_backup(first.id, True)
    assert coord.device_backup(first.id) and not coord.device_backup(second.id)
    # The model's answer is untouched: both plugs still read Mains Powered.
    assert coord.power_of(second.id)["type"] == "Mains Powered"
    view = coord.power_view(first.id)
    assert view["backup_power"] is True and view["kind"] == "mains"
    assert coord._answers_payload()["backup_power"][first.id]["set"]
    coord.page_set_backup(first.id, False)
    assert not coord.device_backup(first.id)
    assert "backup_power" not in coord._answers_payload()


async def test_a_battery_device_or_one_not_known_is_refused(hass: HomeAssistant):
    remote, _ = register_device(hass, "remote", name="Remote")
    coord = await setup_coordinator(hass)
    with pytest.raises(ValueError):
        coord.page_set_backup(remote.id, True)
    coord.page_set_power(remote.id, "AAA", 2)
    with pytest.raises(ValueError):
        coord.page_set_backup(remote.id, True)
    # Untick is always allowed, and does nothing when nothing is ticked.
    coord.page_set_backup(remote.id, False)


async def test_the_mark_is_read_back_and_a_bad_one_dropped(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert coord._backup_read({"a": {"set": "2026-11-26T12:00:00+00:00"}, "b": {"set": 3}, "c": "x"}) == 2
    assert coord.device_backup("a") and not coord.device_backup("b")
    assert coord._backup_read("not a table") == 1 and not coord.device_backup("a")
    assert coord._backup_read(None) == 0


async def test_the_mark_goes_with_its_device(hass: HomeAssistant):
    plug, _ = register_device(hass, "plug", name="Plug")
    coord = await setup_coordinator(hass)
    coord.page_set_power(plug.id, "USB Powered")
    coord.page_set_backup(plug.id, True)
    coord.data["devices"].pop(plug.id, None)
    dr.async_get(hass).async_remove_device(plug.id)
    coord._settle_backup()
    assert not coord.device_backup(plug.id)
