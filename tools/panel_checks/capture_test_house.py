# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/panel_checks/capture_test_house.py, Version: 0.22.20 (2026-09-21)

"""Capture the dashboard's replies from a three-device test house.

Kept here rather than under tests/, so the suite never collects it.
Copy it into tests/, run it with pytest in either harness, and delete
the copy; it writes payloads.json beside the checks. Written 21 September 2026 for
0.22.16's checks: a global mute, a freeze mute, a battery mute, a label
mute, and a battery reading that is not a percentage.
"""
import json
from pathlib import Path
from homeassistant.helpers import device_registry as dr, label_registry as lr
from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES, CONF_FREEZE_MUTED_DEVICES, CONF_MUTED_DEVICES, CONF_MUTED_LABELS,
)
from tests.helpers import register_device, setup_coordinator
from tests.test_battery_report import _seed

# Run from tests/, so the repository root is one level up.
OUT = Path(__file__).resolve().parents[1] / "tools" / "panel_checks" / "payloads.json"
TYPES = ["status", "classification", "problem_list", "recommendations", "integrations",
         "devices", "brief", "battery_trends", "signal_trends"]


async def test_capture(hass, hass_ws_client):
    a, _ = register_device(hass, "a", name="Alpha Panel")
    b, _ = register_device(hass, "b", name="Bravo Phone")
    c, _ = register_device(hass, "c", name="Charlie Plug")
    lux, _ = register_device(hass, "lux", name="LUX Outdoors")
    label = lr.async_get(hass).async_create("Garage spares")
    dr.async_get(hass).async_update_device(c.id, labels={label.label_id})
    coord = await setup_coordinator(hass, {
        CONF_MUTED_DEVICES: [a.id], CONF_BATTERY_MUTED_DEVICES: [a.id, b.id],
        CONF_FREEZE_MUTED_DEVICES: [b.id], CONF_MUTED_LABELS: [label.label_id],
    })
    _seed(coord, lux.id, [196.0] * 16, 186.0)
    client = await hass_ws_client(hass)
    out = {}
    for kind in TYPES:
        await client.send_json_auto_id({"type": f"device_sentinel/{kind}"})
        reply = await client.receive_json()
        assert reply["success"], (kind, reply)
        out[kind] = reply["result"]
    await client.send_json_auto_id({"type": "device_sentinel/device", "device_id": b.id})
    out["device"] = (await client.receive_json())["result"]
    await client.send_json_auto_id({"type": "device_sentinel/integration", "domain": "test"})
    out["integration"] = (await client.receive_json())["result"]
    out["_ids"] = {"bravo": b.id}
    with open(OUT, "w") as handle:
        json.dump(out, handle)
