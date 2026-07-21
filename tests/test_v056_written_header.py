# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v056_written_header.py, Version: 0.5.6 (2026-07-21)

"""0.5.6 fix: the report 'Written' header is a readable local time.

0.5.5 made the down-devices 'As of' line readable but left the top
'Written' header in raw ISO. Both report headers now read like
'Written July 21, 2026 at 7:53 AM (manual)', local, with the trigger
tag kept.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    src = MockConfigEntry(domain="test", title="Source")
    src.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("test", "w")},
        name="Written Device",
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_written_header_is_readable_on_both_reports(
    hass: HomeAssistant,
):
    """Both report headers read a readable local time with the trigger
    tag, not a raw ISO timestamp."""
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    for name in ("device_telemetry.md", "classification.md"):
        text = open(hass.config.path(f"device_sentinel/{name}")).read()
        written = next(
            line
            for line in text.splitlines()
            if line.startswith("Written")
        )
        assert "(manual)" in written
        assert " at " in written
        # No ISO 'T' date-time separator in the timestamp portion.
        assert "T" not in written.split("(")[0]
