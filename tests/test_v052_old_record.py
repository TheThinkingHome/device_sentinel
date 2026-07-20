# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.5.2 (2026-07-27)

"""0.5.2 tests: judgment survives a pre-0.5.0 record.

A device record created before 0.5.0 has none of the freeze fields.
The storage prune removes unknown keys but never adds missing ones,
so such a record reaches judgment without frozen_category. Reading it
directly raised KeyError, and because the sweep had no per-device
guard, the first old record killed the whole tick: no verdict for any
device, and the tick's later save and refresh never ran. These tests
pin both the direct fix and the guard.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_NOT_REPORTED,
)
from custom_components.device_sentinel.coordinator import _new_device_record

DOMAIN = "device_sentinel"


def _register_device(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers=({("test", uid)}),
        name=name,
    )


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _pre_050_record(first_observed_iso):
    """A record as a pre-0.5.0 storage load leaves it: no freeze
    fields at all."""
    record = _new_device_record(first_observed_iso, None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = first_observed_iso
    record.pop("frozen_category", None)
    record.pop("frozen_since", None)
    return record


async def test_old_record_judges_without_crashing(hass: HomeAssistant):
    """A pre-0.5.0 record with no freeze fields is judged, not
    crashed on, and an old zero-event ghost gets its verdict."""
    device = _register_device(hass, "ghost", "Front Security")
    coord = await _coordinator(hass)
    record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    coord.data["devices"][device.id] = record
    # The whole sweep runs without raising, and the ghost, well past
    # the 48-hour grace, is flagged not_reported.
    coord._judge_all_devices()
    assert record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED


async def test_every_old_record_in_the_sweep_is_judged(hass: HomeAssistant):
    """Two pre-0.5.0 ghosts, both missing the freeze fields, are both
    judged in one sweep. Before the fix the first killed the tick and
    the second was never reached; both must now be flagged."""
    first = _register_device(hass, "first", "First Ghost")
    second = _register_device(hass, "second", "Second Ghost")
    coord = await _coordinator(hass)
    first_record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    second_record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    coord.data["devices"][first.id] = first_record
    coord.data["devices"][second.id] = second_record
    coord._judge_all_devices()
    assert first_record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED
    assert second_record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED
