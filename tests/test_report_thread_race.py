# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_report_thread_race.py, Version: 0.24.11 (2026-10-07)

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

Two writes at once (0.24.11). Each report is saved through a temporary
file of a fixed name beside it, and two writes running together shared
it: one write's move found the file gone, and that report was lost.
GitHub's run of 7 October lost a Daily Brief this way, the midnight
write and the brief meeting after a day's clock jump, and the brief was
marked sent without being sent. Reproduced on 0.23.20, 0.24.10 and
0.24.11 (3 to 11 of 20 rounds). Report writes now take turns. These
tests slow each file's move so two writes always overlap.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import BRIEF_TRIGGER, DATA_DEVICES

from custom_components.device_sentinel import reports

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



def _slow_moves(monkeypatch) -> None:
    """Hold each report's final move a moment, so two writes overlap."""
    real_replace = os.replace

    def slow_replace(source, target):
        time.sleep(0.05)
        real_replace(source, target)

    monkeypatch.setattr(reports.os, "replace", slow_replace)


async def test_two_report_writes_at_once_lose_nothing(hass: HomeAssistant, monkeypatch, caplog):
    """The brief, the midnight write and the settled classification at
    once: every report is written, none lost."""
    register_device(hass, "d", "Door")
    coord = await setup_coordinator(hass)
    _slow_moves(monkeypatch)
    caplog.clear()
    brief, _midnight, _settled = await asyncio.gather(
        coord._write_reports_guarded(BRIEF_TRIGGER),
        coord._write_reports_guarded(),
        coord._rewrite_classification(),
    )
    assert "could not write" not in caplog.text and "could not rewrite" not in caplog.text
    assert brief, "the brief's write returns the closed brief"
    for name in ("daily_brief.html", "classification.md", "device_telemetry.md", "silence_episodes.md"):
        assert os.path.exists(hass.config.path("device_sentinel", name)), name
    leftovers = [f for f in os.listdir(hass.config.path("device_sentinel")) if f.endswith(".tmp")]
    assert leftovers == []


async def test_a_brief_that_meets_the_midnight_write_is_still_sent(hass: HomeAssistant, monkeypatch):
    """The fault GitHub caught: the brief closed its day and, its write
    lost to the midnight write, sent nothing. It waits its turn instead."""
    register_device(hass, "d", "Door")
    coord = await setup_coordinator(hass)
    sent: list[str] = []

    async def _send(text: str) -> None:
        sent.append(text)

    coord.async_send_brief = _send  # type: ignore[method-assign]
    _slow_moves(monkeypatch)
    await asyncio.gather(coord._on_brief_time(None), coord._write_reports_guarded())
    assert len(sent) == 1
