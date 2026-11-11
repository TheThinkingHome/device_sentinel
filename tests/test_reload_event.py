# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_reload_event.py, Version: 0.28.12 (2026-11-11)

"""A reload is its own event, not a restart (rule UP-06).

Reloading Device Sentinel from its menu, or turning it off and on, while
Home Assistant runs on is recorded as a reload. The brief says "Device
Sentinel was reloaded at", and the first setup in a Home Assistant run is
still the restart.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_KIND, SYS_RELOAD, SYS_RESTART

from tests.helpers import setup_entry


def _kinds(coord) -> list[str]:
    return [row.get(SYS_KIND) for row in coord.data.get(DATA_SYSTEM_EVENTS) or []]


async def test_a_reload_is_not_a_restart(hass: HomeAssistant):
    entry = await setup_entry(hass)
    assert _kinds(entry.runtime_data).count(SYS_RESTART) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    kinds = _kinds(coord)
    assert kinds.count(SYS_RESTART) == 1
    assert kinds.count(SYS_RELOAD) == 1
    row = next(r for r in coord.data[DATA_SYSTEM_EVENTS] if r.get(SYS_KIND) == SYS_RELOAD)
    assert coord._system_event_sentence(row).startswith("Device Sentinel was reloaded at")
