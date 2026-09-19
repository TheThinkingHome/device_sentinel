# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_wording.py, Version: 0.22.0 (2026-09-18)

"""What the brief says when a battery level jumps.

The rule that finds a new cell sees one reading a day, so a charge
and a replacement look the same to it: a device charged from 54 to
87 percent on issue #11's house passes the same test a fresh cell
does. Resetting the history is right either way, since a charged
cell starts a new discharge. Saying "replaced" is not, so every
surface names both and claims neither.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_BATTERY_REPLACED,
    SYS_DETAIL,
    SYS_KIND,
    SYS_SCOPE,
    SYS_SCOPE_SYSTEM,
    SYS_WHEN,
)

from tests.helpers import register_device, setup_coordinator


def _row(device_id: str) -> dict:
    return {
        SYS_WHEN: dt_util.utcnow().timestamp() - 300.0,
        SYS_KIND: SYS_BATTERY_REPLACED,
        SYS_SCOPE: SYS_SCOPE_SYSTEM,
        SYS_DETAIL: f"{device_id} 54 86",
    }


async def test_the_sentence_names_both_causes(hass: HomeAssistant):
    """The In Short sentence says replaced or recharged, with both levels."""
    device, _ = register_device(hass, "curtain", name="Living Room Curtain")
    coord = await setup_coordinator(hass)
    sentence = coord._system_event_sentence(_row(device.id))

    assert "Living Room Curtain" in sentence
    assert "replaced or recharged" in sentence
    assert "54% to 86%" in sentence
    assert "had its battery replaced at" not in sentence


async def test_the_table_cell_names_both_causes(hass: HomeAssistant):
    """The Last 24 Hours cell says the same thing in its short form."""
    device, _ = register_device(hass, "curtain", name="Living Room Curtain")
    coord = await setup_coordinator(hass)
    cell = coord._system_event_phrase(_row(device.id))

    assert cell == "battery replaced or recharged (54% to 86%)"


async def test_the_written_brief_never_claims_a_replacement(hass: HomeAssistant):
    """End to end: the page on disk carries the new wording only."""
    device, _ = register_device(hass, "curtain", name="Living Room Curtain")
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [_row(device.id)]
    await hass.async_add_executor_job(coord._write_reports, "manual")
    path = hass.config.path("www", "device_sentinel", "daily_brief.html")
    text = await hass.async_add_executor_job(
        lambda: open(path, encoding="utf-8").read()
    )

    assert "replaced or recharged" in text
    assert "battery replaced (" not in text
    assert "had its battery replaced at" not in text
