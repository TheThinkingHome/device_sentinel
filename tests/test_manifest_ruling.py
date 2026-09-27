# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_manifest_ruling.py, Version: 0.23.11 (2026-09-27)

"""The manifest names only frontend and mqtt (ruled 26 September 2026).

Rule 3 of the stack readers: Extended Diagnostics may read another
integration's private state, and nothing goes in the manifest, so a
reader of it never sees integrations Device Sentinel does not use.
0.23.11 as first built broke it: its Thread probe imported
homeassistant.components.thread, and Home Assistant's own validator,
hassfest, refused the repository until the import was declared. The
rule was kept and the import removed. This test holds both halves, so
the gate catches what hassfest caught.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "device_sentinel"

# The only other integrations the code may import: the entity platforms
# Device Sentinel provides and the core services it uses, which
# hassfest accepted from the first release.
ALLOWED = {"button", "diagnostics", "frontend", "http", "repairs", "sensor", "todo", "websocket_api"}


def test_the_manifest_declares_nothing_new():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("after_dependencies") == ["frontend", "mqtt"]
    assert manifest.get("dependencies") == ["http", "websocket_api"]
    assert "requirements" not in manifest


def test_no_integration_is_imported():
    found = set()
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"homeassistant\.components\.([a-z_]+)", text))
    assert found <= ALLOWED, sorted(found - ALLOWED)
