# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.5.3 (2026-07-27)

"""0.5.3 tests: exclusion relationship and the STATUS column.

A globally excluded device is judged by nothing, so the sweep skips
it (no verdict computed) and the section pickers do not offer it. The
telemetry gains a STATUS column reading reported, global, or the
section tags that suppress a device.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_DEVICES,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
)
from custom_components.device_sentinel.coordinator import _new_device_record

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _ghost_record():
    record = _new_device_record("2026-07-08T00:00:00+00:00", None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    return record


async def test_globally_excluded_device_is_not_judged(hass: HomeAssistant):
    """A globally excluded device gets no verdict: the sweep skips it,
    rather than computing a verdict that the report then hides."""
    device = _register(hass, "gx", "Excluded Ghost")
    coord = await _coordinator(hass)
    # Exclude it globally.
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_EXCLUDED_DEVICES: [device.id]}
    )
    coord._excluded_devices[device.id] = "device"
    record = _ghost_record()
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    assert coord._device_down_category(device.id, record, now) is None


async def test_status_reads_the_exclusion_state(hass: HomeAssistant):
    """STATUS is reported when nothing excludes, global when globally
    excluded (alone), and the section tags otherwise."""
    device = _register(hass, "st", "Status Device")
    coord = await _coordinator(hass)
    # Nothing excludes: reported.
    assert coord._device_status(device.id) == "reported"

    # Section excludes: tags, no global.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_BATTERY_EXCLUDED_DEVICES: [device.id],
            CONF_FREEZE_EXCLUDED_DEVICES: [device.id],
        },
    )
    status = coord._device_status(device.id)
    assert "BAT" in status and "FRZ" in status and "SIG" not in status
    assert "global" not in status

    # Global exclude wins and shows alone.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_EXCLUDED_DEVICES: [device.id],
            CONF_BATTERY_EXCLUDED_DEVICES: [device.id],
        },
    )
    coord._excluded_devices[device.id] = "device"
    assert coord._device_status(device.id) == "global"


async def test_report_has_status_column(hass: HomeAssistant):
    """The telemetry table carries a STATUS column and its legend."""
    device = _register(hass, "rep", "Report Device")
    coord = await _coordinator(hass)
    coord.data["devices"][device.id] = _new_device_record(
        "2026-07-08T00:00:00+00:00", None
    )
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    header = next(
        line for line in text.splitlines() if "DEVICE | STATUS" in line
    )
    assert "STATUS" in header
    # The legend explains the tags.
    assert "BAT battery" in text
    assert "SIG signal" in text
    assert "FRZ freeze" in text
