# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_blocking_io.py, Version: 0.28.13 (2026-11-13)

"""The Brief tab reads no file on the event loop.

The brief names a changed setting by the label its screen carries,
read from strings.json. The file was once read the first time a brief
holding a "settings changed" row was built, and the dashboard's Brief
tab builds its page on the event loop, so Home Assistant logged a
blocking call once after each restart. The labels are read on a
worker thread while Device Sentinel starts.
"""

from __future__ import annotations

import builtins
import threading

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import SYS_OPTIONS_CHANGED

from tests.helpers import setup_entry


def _watch_strings_on_loop(monkeypatch) -> list[str]:
    """Record each open of strings.json made on the calling thread."""
    loop_thread = threading.get_ident()
    seen: list[str] = []
    real_open = builtins.open

    def spy(path, *args, **kwargs):
        if str(path).endswith("strings.json") and threading.get_ident() == loop_thread:
            seen.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    return seen


async def test_the_labels_are_read_while_starting(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    labels = getattr(coord, "_option_label_cache", None)
    assert labels, "the setting labels are read during setup"
    assert labels.get("low_threshold") == "Low Battery Threshold"


async def test_the_brief_tab_opens_no_file_on_the_loop(hass: HomeAssistant, monkeypatch):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._record_system_event(SYS_OPTIONS_CHANGED, detail="low_threshold")
    seen = _watch_strings_on_loop(monkeypatch)
    page = coord.dashboard_brief(dt_util.now().date())
    assert page is not None
    assert seen == []
    # The row still names the setting by its screen label.
    assert "Low Battery Threshold" in coord._changed_labels("low_threshold")
