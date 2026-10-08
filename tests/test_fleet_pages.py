# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_fleet_pages.py, Version: 0.25.0 (2026-10-08)

"""Every device of a real house through the server's device page.

The replay that proved 0.24.10 and 0.24.11 on the owner's house, run
by hand from the private archive since 6 October, made permanent on
the committed houses (fleet refresh, 8 October 2026). Each device is
seated with its own daily gaps and their dates, ``lognormal_days``,
``first_observed``, and from the clocks its ``event_count`` and
``last_activity``, and the clock stands where the house saved its
clocks. Its page is then built by ``dashboard_device``.

For each device with a window:
1. the rhythm on the status bar is a real number shorter than its
   window, since the bar shows the rhythm of the rule in use (0.24.10);
2. the Trimmed Maximum chart has a real number, and the Log-Normal
   Percentile chart has one whenever the page names its days.

It failed on 0.24.9, whose bar showed the 14-day rhythm and whose rule
figures were lists, and it caught the blank charts real data drew that
hand-made samples did not.
"""

from __future__ import annotations

import json
import math

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import DATA_DEVICES
from custom_components.device_sentinel.records import _new_device_record

from .conftest import fleet_param
from .helpers import register_device, setup_coordinator

KEYS = ("daily_max", "daily_dates", "lognormal_days", "first_observed",
        "event_count", "last_activity")

HOUSES = [
    fleet_param("reference", "device_sentinel.storage", id="reference",
                clocks=("reference", "device_sentinel.clocks")),
    fleet_param("second", "device_sentinel_storage.json", id="second",
                clocks=("second", "device_sentinel_clocks.json")),
]
# The fourth fleet is left out: its records are of 0.22.3, before each
# day kept its date (0.24.4), and this test seats records as the page
# reads them, past the load that would date them.


def _real(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@pytest.mark.parametrize(("storage", "clocks"), HOUSES)
async def test_every_device_page_of_a_real_house_draws(
    hass: HomeAssistant, freezer, storage, clocks
):
    with open(storage, encoding="utf-8") as handle:
        records = json.load(handle)["data"]["devices"]
    with open(clocks, encoding="utf-8") as handle:
        clock_file = json.load(handle)["data"]
    freezer.move_to(dt_util.utc_from_timestamp(clock_file["saved_at"]))
    hot = clock_file["clocks"]

    seated = []
    for number, (key, record) in enumerate(records.items()):
        device, _ = register_device(hass, f"fp{number}", f"Page {number:03d}")
        seated.append((device.id, key, {**record, **hot.get(key, {})}))
    coord = await setup_coordinator(hass)

    faults, judged = [], 0
    for device_id, key, stats in seated:
        record = _new_device_record(stats.get("first_observed") or "2026-07-01T00:00:00+00:00", None)
        record.update({k: stats[k] for k in KEYS if k in stats})
        coord.data[DATA_DEVICES][device_id] = record
        page = coord.dashboard_device(device_id)
        window, rhythm = page["status"].get("window"), page["status"].get("rhythm")
        if window is None:
            continue
        judged += 1
        if not (_real(rhythm) and rhythm < window):
            faults.append(f"{key}: rhythm {rhythm!r} not shorter than window {window!r}")
        block = page.get("rhythm") or {}
        figures = block.get("rules", block)
        if not _real(figures.get("trimmed")):
            faults.append(f"{key}: the Trimmed Maximum chart has no number")
        if figures.get("lognormal_days") and not _real(figures.get("lognormal")):
            faults.append(f"{key}: the Log-Normal Percentile chart has no number")
    assert judged, "no device of the house has a window"
    assert not faults, "\n".join(faults[:20])
