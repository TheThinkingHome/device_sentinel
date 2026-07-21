# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v036_exclusions.py, Version: 0.3.6 (2026-07-19)

"""0.3.6 tests: the exclude surface and the todo identity attributes.

Exclusion suppresses judgment, not observation: excluded devices and
entities keep clocks and statistics and never appear in reporting.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    STARTUP_GRACE_SECONDS,
)

DOMAIN = "device_sentinel"


def _battery_device(hass, source, index):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", f"ex{index}")},
        name=f"Excl Device {index}",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"ex{index}_pct",
        device_id=device.id, config_entry=source,
        original_device_class="battery",
    )
    return device, reg.entity_id


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_excluded_device_keeps_learning_never_reported(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 1)
    entry = await _setup(
        hass, options={CONF_EXCLUDED_DEVICES: [device.id]}
    )
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(battery_eid, "10")  # far below threshold
    await hass.async_block_till_done()

    # Observation continues: events counted, verdict stored.
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_EVENT_COUNT] > 0
    # Judgment suppressed: never reported.
    assert coord.battery_low_count == 0
    assert coord.battery_low_list == []
    assert coord._excluded_devices[device.id] == "device"


async def test_integration_exclude_respects_primary_owner(
    hass: HomeAssistant,
):
    """A multi-homed device is caught only by its owning domain."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    tracker = MockConfigEntry(domain="router_tracker")
    tracker.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("camera_brand", "cam9")},
        name="Multi-homed Cam",
    )
    dev_reg.async_update_device(
        device.id, add_config_entry_id=tracker.entry_id
    )
    er.async_get(hass).async_get_or_create(
        "camera", "camera_brand", "cam9_uid",
        device_id=device.id, config_entry=owner,
    )

    # Excluding the tracker does not catch the camera.
    entry = await _setup(
        hass, options={CONF_EXCLUDED_INTEGRATIONS: ["router_tracker"]}
    )
    coord = entry.runtime_data
    assert device.id not in coord._excluded_devices

    # Excluding the owner does, applied live through options.
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_EXCLUDED_INTEGRATIONS: ["camera_brand"]},
    )
    await hass.async_block_till_done()
    assert coord._excluded_devices[device.id] == "integration"


async def test_classification_shows_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _battery_device(hass, source, 4)
    entry = await _setup(
        hass, options={CONF_EXCLUDED_DEVICES: [device.id]}
    )
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    assert "Excluded from judgment" in text
    assert "| Excl Device 4 | device | device |" in text


async def test_todo_identity_attributes(hass: HomeAssistant):
    await _setup(hass)
    state = hass.states.get("todo.device_sentinel_problem_list")
    assert state is not None
    assert state.attributes["sentinel_type"] == "problem_list"
    # Assert identity is present, not a pinned number: a version bump
    # must not fail a test about attributes existing.
    assert state.attributes["sentinel_version"]
