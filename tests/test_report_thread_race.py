# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_report_thread_race.py, Version: 0.23.13 (2026-09-27)

"""The reports' worker thread and a changing device list (0.23.13).

The reports are written on a worker thread while the event loop adds a
record when a device pairs and deletes one when it goes. Found proving
0.22.29, where the signal report failed with "dictionary changed size
during iteration" and lost that day's reports; on 0.23.12 the same
churn failed 25 of 150 report writes, every one in watched_records, the
one function every surface reads the store through. It now iterates a
snapshot taken in one step. This test churns the map from a second
thread with the interpreter switching threads as often as it can, so a
live iteration fails within a few thousand calls.
"""

from __future__ import annotations

import sys
import threading

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_DEVICES

from .helpers import register_device, setup_coordinator


async def test_watched_records_survives_a_changing_map(hass: HomeAssistant):
    for index in range(40):
        register_device(hass, f"r{index}", f"Device {index}")
    coord = await setup_coordinator(hass)
    devices = coord.data[DATA_DEVICES]
    template = dict(next(iter(devices.values())))
    stop = threading.Event()

    def churn():
        count = 0
        while not stop.is_set():
            key = f"churn-{count % 20}"
            if key in devices:
                devices.pop(key, None)
            else:
                devices[key] = dict(template)
            count += 1

    failures = []
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    worker = threading.Thread(target=churn, daemon=True)
    worker.start()
    try:
        for _ in range(20000):
            try:
                coord.watched_records()
            except RuntimeError as err:
                failures.append(str(err))
                break
    finally:
        stop.set()
        worker.join()
        sys.setswitchinterval(previous)
    assert not failures, failures
