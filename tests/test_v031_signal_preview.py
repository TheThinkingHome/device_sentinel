# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v031_signal_preview.py, Version: 0.4.3 (2026-07-19)

"""Signal line tests: the floor is the line, shown in the report.

Rewritten for 0.4.3, which retired the factor and offset formulas:
the line is the trimmed floor itself, chosen by the k ladder, and the
report shows it alongside the daily lows it was chosen from.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_DAILY_MIN,
)

DOMAIN = "device_sentinel"


async def test_line_in_report(hass: HomeAssistant):
    """The report shows the line, the family, and the daily lows.

    With the ladder, six days is still under the week rung, so k=0
    and the line is the plain lowest; the seventh day crosses to k=1
    and the single lowest is dropped, which is how a one-day anomaly
    stops defining the floor.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sig31")},
        name="Signal Preview Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "sig31",
        suggested_object_id="sig31_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    # Six signal days, k=0: the line is the plain lowest, live from
    # the first day rather than waiting out an arming period.
    coord.data["devices"][device.id][DEV_SIGNAL_DAILY_MIN] = [
        120.0, 118.0, 122.0, 119.0, 121.0, 117.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line
        for line in text.splitlines()
        if "Signal Preview Device" in line
    )
    # k=0 under a week: the floor is the plain lowest, 117, shown
    # bold. Nothing is trimmed yet, so no strikethrough.
    assert "**117** 121 119 122 118 120" in row

    # Seventh day brings an anomalous 40: the ladder steps to k=1,
    # the 40 is dropped, and the line is the second lowest, 117.
    coord.data["devices"][device.id][DEV_SIGNAL_DAILY_MIN].append(40.0)
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line
        for line in text.splitlines()
        if "Signal Preview Device" in line
    )
    # k=1 at a week: the anomalous 40 is trimmed (struck), and the
    # floor is the second lowest, 117, bold. Newest first, so the 40
    # leads and the marks show the line against the readings behind it.
    assert "~~40~~ **117** 121 119 122 118 120" in row
