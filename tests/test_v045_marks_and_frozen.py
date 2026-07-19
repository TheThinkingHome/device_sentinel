# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.5 (2026-07-19)

"""0.4.5 tests: the refined SIGNAL marks.

The floor's earliest occurrence is bold, and a value equal to the
floor is never struck.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_DAILY_MIN,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "m45")},
        name="Marks45 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "m45",
        suggested_object_id="m45_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id


# The marks: earliest floor bold, never strike a value equal to floor.


async def test_repeated_floor_bolds_the_earliest_and_strikes_none_equal(
    hass: HomeAssistant,
):
    """A flat run at the floor value: the earliest occurrence is bold,
    the rest are plain, and none of the equal values is struck. This
    is the flat-button case that read as one bold, one struck, two
    plain before the fix."""
    coord, device_id = await _coordinator(hass)
    # Stored oldest-to-newest; displayed newest-first. Four 48s, k=0
    # under a week so floor is 48. Earliest 48 (index 1) bolds.
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        68.0, 48.0, 48.0, 48.0, 52.0, 48.0, 56.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "Marks45 Device" in line
    )
    # Exactly one bold, and it is a 48; no struck values at all
    # (nothing is strictly below the floor of 48).
    assert row.count("**") == 2  # one bold pair
    assert "**48**" in row
    assert "~~" not in row


async def test_below_floor_is_struck_but_equal_is_not(hass: HomeAssistant):
    """A value strictly below the floor is struck; an equal one is
    not. Floor is 112 here (k=1 at a week trims the 84)."""
    coord, device_id = await _coordinator(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        116.0, 116.0, 116.0, 120.0, 112.0, 112.0, 116.0, 84.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "Marks45 Device" in line
    )
    assert "~~84~~" in row      # strictly below floor 112: struck
    assert "**112**" in row     # earliest 112: bold
    # The other 112 is plain, not struck (equal to the floor).
    assert "~~112~~" not in row
