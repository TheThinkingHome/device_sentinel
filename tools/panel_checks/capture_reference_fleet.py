# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/panel_checks/capture_reference_fleet.py, Version: 0.22.20 (2026-09-21)

"""Capture every dashboard reply from the reference fleet.

Kept here rather than under tests/, so the suite never collects it.
Copy it into tests/, run it, and delete the copy. It reads the committed
anonymized fleet by default, and its output then carries no real name;
run with DEVICE_SENTINEL_FLEET_DIR pointed at real files only to
diagnose, and never commit that output. Writes payloads_fleet.json,
which check_0_22_17.js reads. Do not freeze the clock here: freezing
breaks the WebSocket's sign-in.
"""
import json
from pathlib import Path
from tests.test_campaign_consistency import _render_fleet, JAMES_LIVE

# Run from tests/, so the repository root is one level up.
OUT = Path(__file__).resolve().parents[1] / "tools" / "panel_checks" / "payloads_fleet.json"
TYPES = ["status", "classification", "problem_list", "recommendations", "integrations",
         "devices", "brief", "battery_trends", "signal_trends"]


async def test_capture(hass, hass_ws_client):
    await _render_fleet(hass, JAMES_LIVE)
    coord = hass.config_entries.async_entries("device_sentinel")[0].runtime_data
    client = await hass_ws_client(hass)
    out = {}
    for kind in TYPES:
        await client.send_json_auto_id({"type": f"device_sentinel/{kind}"})
        reply = await client.receive_json()
        assert reply["success"], (kind, reply)
        out[kind] = reply["result"]
    # The device with the longest signal history, so its page draws a
    # full graph; chosen by the data, since the fleet's names are
    # stand-ins.
    device = max(
        coord.data["devices"],
        key=lambda d: (len(coord.data["devices"][d].get("signal_daily_p5") or []), d),
    )
    await client.send_json_auto_id({"type": "device_sentinel/device", "device_id": device})
    out["device"] = (await client.receive_json())["result"]
    await client.send_json_auto_id({"type": "device_sentinel/integration", "domain": "test"})
    out["integration"] = (await client.receive_json())["result"]
    out["_ids"] = {"bravo": device}
    with open(OUT, "w") as handle:
        json.dump(out, handle)
