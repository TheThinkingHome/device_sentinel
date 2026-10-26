# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_outage_storage.py, Version: 0.27.5 (2026-10-26)

"""The stored Wi-Fi outage's shape (rules STOR-05, STOR-09, UP-04).

A new top-level key has a shape, is checked at load and at save, and
a damaged one is dropped whole without an exception.
"""

from __future__ import annotations

import copy

from custom_components.device_sentinel.const import DATA_WIFI_OUTAGE
from custom_components.device_sentinel.normalise import (
    SCALARS,
    check_containers,
    check_storage,
    repair_containers,
)

GOOD = {
    "since": 1792970000.0,
    "declared": 1792970060.0,
    "fallen": {"device_tracker.a": 1792970000.0},
    "worst": 3,
    "devices": 6,
    "told": True,
    "pushed": False,
    "scan_down": None,
    "recovering": None,
}


def test_the_key_has_a_shape():
    assert DATA_WIFI_OUTAGE in SCALARS


def test_a_whole_outage_passes_both_gates():
    data = {DATA_WIFI_OUTAGE: copy.deepcopy(GOOD)}
    assert check_containers(data) == []
    assert check_storage(data) == []
    data[DATA_WIFI_OUTAGE]["scan_down"] = 1792970000.0
    assert check_storage(data) == []


def test_each_damage_is_a_fault_and_is_dropped():
    damages = [
        "an outage",
        [],
        {**GOOD, "since": None},
        {**GOOD, "since": 12.0},
        {**GOOD, "declared": "x"},
        {**GOOD, "fallen": ["device_tracker.a"]},
        {**GOOD, "fallen": {"device_tracker.a": "noon"}},
        {**GOOD, "fallen": {"": 1792970000.0}},
        {**GOOD, "worst": -1},
        {**GOOD, "worst": True},
        {**GOOD, "devices": 2.5},
        {**GOOD, "told": 1},
        {**GOOD, "pushed": None},
        {**GOOD, "scan_down": "later"},
        {**GOOD, "recovering": 12.0},
        {key: value for key, value in GOOD.items() if key != "recovering"},
        {key: value for key, value in GOOD.items() if key != "worst"},
        {**GOOD, "extra": 1},
    ]
    for damaged in damages:
        data = {DATA_WIFI_OUTAGE: damaged}
        assert check_containers(data), damaged
        assert check_storage(data), damaged
        counts = repair_containers(data)
        assert DATA_WIFI_OUTAGE not in data, damaged
        assert counts.get("keys dropped") == 1
