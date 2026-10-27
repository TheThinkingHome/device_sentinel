# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_release_line.py, Version: 0.27.10 (2026-10-27)

"""The release running, at the foot of the dashboard (rule DASH-15).

A person sees which release runs without opening Settings or HACS. The
status reply names "Device Sentinel" and the manifest's version, with a
link to that release's notes. The link appears only where the version
reads as a release tag, so an odd value is printed and never built into
an address.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from tests.helpers import setup_coordinator

MANIFEST = Path(__file__).parent.parent / "custom_components" / "device_sentinel" / "manifest.json"


async def test_the_status_names_the_release_and_links_its_notes(hass: HomeAssistant, hass_ws_client):
    coord = await setup_coordinator(hass)
    version = json.loads(MANIFEST.read_text())["version"]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/status"})
    reply = await client.receive_json()
    assert reply["success"], reply
    assert reply["result"]["release"] == {
        "words": f"Device Sentinel {version}",
        "url": f"https://github.com/TheThinkingHome/device_sentinel/releases/tag/{version}",
    }
    assert coord.version == version


async def test_an_odd_version_is_printed_without_a_link(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    for odd in ("0.27.0b1", "0.27.0/../../evil", "", "dev", "1"):
        coord.version = odd
        release = coord.dashboard_release()
        assert release["url"] is None, odd
        assert release["words"] == f"Device Sentinel {odd}".strip(), odd
    coord.version = None
    assert coord.dashboard_release() == {"words": "Device Sentinel", "url": None}
    coord.version = "1.0.0"
    assert coord.dashboard_release()["url"].endswith("/releases/tag/1.0.0")
