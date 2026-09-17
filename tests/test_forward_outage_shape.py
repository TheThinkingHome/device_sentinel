# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_forward_outage_shape.py, Version: 0.21.12 (2026-09-17)

"""Forward simulation of 0.21.12's stored shape on both fleets (#306).

0.21.12 writes a worst figure on every ended outage (#442) and two new
event kinds for a Wi-Fi recovery (#444). A replay over data the fleets
already hold proves the writers; this synthesizes the new shape onto
each fleet's own events, passes it through the storage check, and
renders every report over it, which proves the readers.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_DOWN,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_RECOVERY_WITHDRAWN,
    SYS_WIFI_UP,
    SYS_WORST,
)
from custom_components.device_sentinel.normalise import damaged_rows
from tests.conftest import FLEET_ABSENT, fleet_path
from tests.test_campaign_consistency import _check_pages, _render_fleet

FLEETS = {
    "james": fleet_path("james", "device_sentinel.storage"),
    "tim": fleet_path("tim", "device_sentinel_storage.json"),
}
_UPS = (SYS_WIFI_UP, SYS_BRIDGE_UP, SYS_INTEGRATION_UP)


def _synthesize(data):
    """Give every ended outage its worst figure, and add a recovery's
    moments inside the brief's window."""
    events = data.setdefault(DATA_SYSTEM_EVENTS, [])
    for index, row in enumerate(events):
        if row.get(SYS_KIND) in _UPS:
            total = row.get(SYS_DEVICES) or 20 + index % 7
            row[SYS_DEVICES] = total
            row[SYS_WORST] = (0, 1, total, total // 2)[index % 4]
    now = dt_util.utcnow().timestamp()
    events += [
        {SYS_WHEN: now - 1800, SYS_KIND: SYS_WIFI_DOWN, SYS_SCOPE: "wifi",
         "detail": None, SYS_DURATION: None, SYS_DEVICES: 74},
        {SYS_WHEN: now - 1500, SYS_KIND: SYS_WIFI_RECOVERING,
         SYS_SCOPE: "wifi", "detail": None, SYS_DURATION: None},
        {SYS_WHEN: now - 1450, SYS_KIND: SYS_WIFI_RECOVERY_WITHDRAWN,
         SYS_SCOPE: "wifi", "detail": None, SYS_DURATION: None},
        {SYS_WHEN: now - 1400, SYS_KIND: SYS_WIFI_RECOVERING,
         SYS_SCOPE: "wifi", "detail": None, SYS_DURATION: None},
        {SYS_WHEN: now - 1200, SYS_KIND: SYS_WIFI_UP, SYS_SCOPE: "wifi",
         "detail": None, SYS_DURATION: 600.0, SYS_DEVICES: 74,
         SYS_WORST: 56},
        {SYS_WHEN: now - 900, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "zha",
         "detail": None, SYS_DURATION: None},
        {SYS_WHEN: now - 200, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "zha",
         "detail": None, SYS_DURATION: 700.0, SYS_DEVICES: 55,
         SYS_WORST: 14},
    ]
    events.sort(key=lambda row: row[SYS_WHEN])
    return data


@pytest.mark.parametrize("fleet", ["james", "tim"])
async def test_the_new_shape_renders_on_the_fleet(
    hass: HomeAssistant, tmp_path, fleet
):
    source = FLEETS[fleet]
    if not source.exists():
        pytest.skip(FLEET_ABSENT)
    with open(source, encoding="utf-8") as handle:
        loaded = json.load(handle)
    data = _synthesize(loaded.get("data", loaded))
    assert damaged_rows(data) == {}

    target = tmp_path / source.name
    target.write_text(json.dumps(loaded), encoding="utf-8")
    for diagnostics in source.parent.glob("config_entry*.json"):
        shutil.copy(diagnostics, tmp_path / diagnostics.name)

    _carried, pages = await _render_fleet(hass, target)
    _check_pages(pages)

    brief = pages["daily_brief.html"]
    assert "WiFi network came back, devices reconnecting" in brief
    assert "WiFi recovery stalled, outage continues" in brief
    assert "WiFi outage ended after 10m, 56 of 74 devices went down" in brief
    assert "zha bridge came back after" in brief
    assert "14 of 55 devices went down" in brief
    # The table gives its times to the second.
    assert re.search(r"<td>[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2}:\d{2} [AP]M</td>", brief)
    # And the summary tells the recovery once, not line by line.
    summary = brief[brief.index("In Short"):brief.index("Last 24 Hours")]
    assert "devices reconnecting" not in summary
    assert "began reconnecting" not in summary
