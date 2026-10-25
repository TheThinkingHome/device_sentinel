# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_page_firmware.py, Version: 0.27.4 (2026-10-25)

"""The dashboard's device page carries the device's firmware (rule DEV-15).

Firmware was recorded correctly, but nothing on the page read it: it
appeared only in the diagnostics download. Ruled a bug by James on 25
October 2026: Advanced shows the current firmware with its recorded
history beneath, beside Hardware version; Simple never shows it. The
server sends it in both modes and the panel decides what is drawn
(tools/panel_checks/check_device_page_layout.js and
check_simple_dashboard.js prove the drawing).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_FIRMWARE_HISTORY

from tests.helpers import register_device, setup_coordinator


async def test_the_page_carries_the_firmware_and_its_history(hass: HomeAssistant):
    device, _ = register_device(hass, "fw1", name="Hallway Plug")
    dr.async_get(hass).async_update_device(device.id, sw_version="9.8.7-rc42")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_FIRMWARE_HISTORY] = [
        ["1.2.3-old55", 1760000000.0], ["9.8.7-rc42", 1761000000.0]]
    firmware = coord.dashboard_device(device.id)["identity"]["firmware"]
    assert firmware["current"] == "9.8.7-rc42"
    # Oldest first, as recorded, each with the moment it was first seen.
    assert firmware["history"] == [
        {"version": "1.2.3-old55", "since": dt_util.utc_from_timestamp(1760000000.0).isoformat()},
        {"version": "9.8.7-rc42", "since": dt_util.utc_from_timestamp(1761000000.0).isoformat()},
    ]


async def test_a_version_not_yet_recorded_is_still_shown(hass: HomeAssistant):
    """A new version is recorded once it has held ten minutes (0.23.10);
    the registry's version is the current one meanwhile."""
    device, _ = register_device(hass, "fw2", name="Porch Plug")
    dr.async_get(hass).async_update_device(device.id, sw_version="2.0")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_FIRMWARE_HISTORY] = [["1.0", 1760000000.0]]
    firmware = coord.dashboard_device(device.id)["identity"]["firmware"]
    assert firmware["current"] == "2.0"
    assert [row["version"] for row in firmware["history"]] == ["1.0"]


async def test_no_firmware_sends_nothing(hass: HomeAssistant):
    device, _ = register_device(hass, "fw3", name="Quiet Plug")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id].pop(DEV_FIRMWARE_HISTORY, None)
    assert coord.dashboard_device(device.id)["identity"]["firmware"] is None


async def test_a_registry_without_a_version_keeps_the_last_recorded(hass: HomeAssistant):
    """A device that stops giving a version keeps its last (note_firmware)."""
    device, _ = register_device(hass, "fw4", name="Attic Plug")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_FIRMWARE_HISTORY] = [["3.1", 1760000000.0]]
    firmware = coord.dashboard_device(device.id)["identity"]["firmware"]
    assert firmware["current"] == "3.1"
