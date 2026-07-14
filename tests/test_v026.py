# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""0.2.6 tests: the trimmed-maximum preview and Markdown rendering."""

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DEV_DAILY_MAX

DOMAIN = "device_sentinel"


def test_trimmed_maximum_rule():
    from custom_components.device_sentinel.coordinator import (
        DeviceSentinelCoordinator as C,
    )

    # Below the sample threshold: nothing trimmed, plain max.
    operative, set_aside = C._trimmed_maximum([500.0, 9000.0])
    assert operative == 9000.0 and set_aside == set()

    # At threshold: the single spike is set aside; survivors' max rules.
    gaps = [500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0]
    operative, set_aside = C._trimmed_maximum(gaps)
    assert operative == 600.0
    assert set_aside == {4}

    # A recurring spike: one copy set aside, the second counts.
    gaps = [500.0, 9000.0, 600.0, 520.0, 9000.0, 580.0, 560.0]
    operative, set_aside = C._trimmed_maximum(gaps)
    assert operative == 9000.0
    assert len(set_aside) == 1

    # Empty history.
    assert C._trimmed_maximum([]) == (None, set())


async def test_markdown_render_marks_trim(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "md")},
        name="Markdown Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "md", device_id=device.id, config_entry=source
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    # Inject a seven-day history with one spike, then rewrite reports.
    coord.data["devices"][device.id][DEV_DAILY_MAX] = [
        500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)

    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(line for line in text.splitlines() if "Markdown Device" in line)
    assert "~~2.50h~~" in row          # the 9000 s spike, set aside
    assert "**600s**" in row           # the operative rhythm, bold
    assert "| 600s |" in row           # WINDOW BASIS column
    # Newest first: the newest value (560) appears before the oldest (500).
    assert row.index("560s") < row.index("500s")
