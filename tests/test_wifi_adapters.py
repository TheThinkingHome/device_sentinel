# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_wifi_adapters.py, Version: 0.30.0 (2026-11-21)

"""Which Wi-Fi adapter is used, and why there is none (rule UP-12).

A server can have its own adapter and a USB one plugged in for range.
The Supervisor lists them in no promised order, so the scan takes the
one connected to a network, then one switched on, then the first. The
download lists every adapter, marks the one in use, says why none was
found, and names the hardware.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import CONF_WIFI_NETWORKS
from custom_components.device_sentinel.wifi import pick_adapter

from tests.helpers import setup_coordinator

IOT = "Harbor-IoT"
POINT = {"mac": "02:A1:B2:11:C3:D4", "ssid": IOT, "signal": 77,
         "frequency": 2422, "mode": "infrastructure"}
BUILT_IN_OFF = {"interface": "wlo1", "type": "wireless", "enabled": False,
                "connected": False, "wifi": None}
USB_CONNECTED = {"interface": "wlx00c0ca123456", "type": "wireless", "enabled": True,
                 "connected": True, "wifi": {"ssid": IOT, "signal": 80}}
ETHERNET = {"interface": "enp2s0", "type": "ethernet", "enabled": True,
            "connected": True, "wifi": None}


class FakeSupervisor:
    def __init__(self, rows: list[dict[str, Any]], board: str | None = "generic-x86-64") -> None:
        self.rows = rows
        self.board = board
        self.fail = False
        self.scanned: list[str] = []

    async def send_command(self, path: str, method: str = "get") -> dict:
        if self.fail:
            raise ConnectionError("supervisor is not answering")
        if path == "/network/info":
            return {"data": {"interfaces": list(self.rows)}}
        if path == "/os/info":
            return {"data": {"board": self.board}}
        if path.endswith("/accesspoints"):
            self.scanned.append(path.split("/")[3])
            return {"data": {"accesspoints": [POINT]}}
        raise AssertionError(f"unexpected path {path}")


def test_pick_connected_then_on_then_first():
    on = {"interface": "b", "enabled": True, "connected": False}
    off = {"interface": "a", "enabled": False, "connected": False}
    joined = {"interface": "c", "enabled": True, "connected": True}
    assert pick_adapter([off, on, joined])["interface"] == "c"
    assert pick_adapter([off, on])["interface"] == "b"
    assert pick_adapter([off])["interface"] == "a"
    assert pick_adapter([]) is None


async def test_the_usb_adapter_is_scanned_when_the_built_in_is_off(hass: HomeAssistant):
    """Built-in listed first and off, USB connected: the scan uses the USB one."""
    fake = FakeSupervisor([ETHERNET, BUILT_IN_OFF, USB_CONNECTED])
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [IOT]})
    await coord.async_sweep_wifi()
    assert fake.scanned and set(fake.scanned) == {"wlx00c0ca123456"}
    assert coord.wifi_scan_diagnostics["interface"] == "wlx00c0ca123456"
    assert coord.wifi_missing_networks == []


async def test_download_lists_every_adapter_and_marks_the_one_used(hass: HomeAssistant):
    fake = FakeSupervisor([ETHERNET, BUILT_IN_OFF, USB_CONNECTED])
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [IOT]})
    found = await coord.async_adapter_diagnostics()
    assert found["why"] == "ok"
    assert found["board"] == "generic-x86-64"
    assert found["adapters"] == [
        {"interface": "wlo1", "enabled": False, "connected": False, "used": False},
        {"interface": "wlx00c0ca123456", "enabled": True, "connected": True, "used": True},
    ]
    assert IOT not in str(found), "a network name reached the download"


async def test_why_no_adapter(hass: HomeAssistant):
    """No Supervisor, the Supervisor failing, and no wireless adapter at all."""
    coord = await setup_coordinator(hass)
    hass.data.pop("hassio", None)
    found = await coord.async_adapter_diagnostics()
    assert found == {"why": "no_supervisor", "adapters": [], "board": None}

    fake = FakeSupervisor([ETHERNET], board="rpi4-64")
    hass.data["hassio"] = fake
    found = await coord.async_adapter_diagnostics()
    assert found["why"] == "no_adapter"
    assert found["board"] == "rpi4-64"

    fake.fail = True
    found = await coord.async_adapter_diagnostics()
    assert found["why"] == "supervisor_error: ConnectionError"
    assert found["board"] is None


async def test_unused_adapter_names_the_connected_one(hass: HomeAssistant):
    """With no network chosen, the Daily Brief's adapter line names the USB one."""
    hass.data["hassio"] = FakeSupervisor([BUILT_IN_OFF, USB_CONNECTED])
    coord = await setup_coordinator(hass)
    await coord.async_check_unused_adapter()
    assert coord._wifi_adapter_unused == "wlx00c0ca123456"
    assert coord._wifi_adapter_off is False
