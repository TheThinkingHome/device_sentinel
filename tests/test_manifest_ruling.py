# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_manifest_ruling.py, Version: 0.27.10 (2026-10-27)

"""The manifest names frontend, mqtt, esphome, zha and lutron_caseta, and
nothing else (rules STACK-03, STACK-08, DASH-01).

Extended Diagnostics may read another integration's private state, and
nothing goes in the manifest for it, so a reader of the manifest never
sees integrations Device Sentinel does not use. Home Assistant's own
validator, hassfest, refuses an undeclared import, so this test holds
both halves and the gate catches what hassfest would.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "device_sentinel"

# The only other integrations the code may import: the entity platforms
# Device Sentinel provides and the core services it uses, which
# hassfest accepted from the first release.
ALLOWED = {"button", "diagnostics", "frontend", "http", "panel_custom", "repairs", "sensor", "todo", "websocket_api"}


def test_the_manifest_declares_nothing_new():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    # esphome: the one integration whose private state detection reads, named
    # so a reader of the manifest sees it, and loaded first so the flag is
    # there at the first read. after_dependencies only, so Device Sentinel
    # starts without it (rule STACK-08).
    # zha: the time ZHA last heard each device, read the same way
    # (rule STACK-04).
    # lutron_caseta: its hub's session, read to judge the hub up or down
    # (rule STACK-09).
    # frontend and panel_custom: the dashboard is registered through
    # panel_custom, so both are set up first, and frontend leaves the list
    # loaded after (rule DASH-01).
    assert manifest.get("after_dependencies") == ["esphome", "lutron_caseta", "mqtt", "zha"]
    assert manifest.get("dependencies") == ["frontend", "http", "panel_custom", "websocket_api"]
    assert "requirements" not in manifest


def test_no_integration_is_imported():
    found = set()
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"homeassistant\.components\.([a-z_]+)", text))
    assert found <= ALLOWED, sorted(found - ALLOWED)
