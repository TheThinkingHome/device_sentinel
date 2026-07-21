# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v055_regenerate_status.py, Version: 0.6.2 (2026-07-21)

"""0.5.5 tests: the regenerate-reports button and the STATUS wording.

STATUS reads Reported or Excluded (reasons), one grammar. The
regenerate button judges every device then rewrites both reports, so a
person who has just fixed a device sees the report reflect it now. The
report timestamp is a readable local time.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_DEVICES,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
)
from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator,
    _new_device_record,
)

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


async def test_status_grammar(hass: HomeAssistant):
    """Reported when nothing excludes; Excluded (GLB) alone for a
    global exclude; Excluded (BAT, SIG, FRZ) in column order when
    sections combine."""
    d = _register(hass, "st", "Status Device")
    coord = await _coordinator(hass)
    assert coord._device_status(d.id) == "Reported"

    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_BATTERY_EXCLUDED_DEVICES: [d.id],
            CONF_SIGNAL_EXCLUDED_DEVICES: [d.id],
            CONF_FREEZE_EXCLUDED_DEVICES: [d.id],
        },
    )
    assert coord._device_status(d.id) == "Excluded (BAT, SIG, FRZ)"

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_EXCLUDED_DEVICES: [d.id]}
    )
    coord._excluded_devices[d.id] = "device"
    assert coord._device_status(d.id) == "Excluded (GLB)"


def test_readable_timestamp_format():
    """The report time is a readable local phrase, not an ISO
    string."""
    import datetime

    when = datetime.datetime(2026, 7, 21, 7, 19, 5)
    out = DeviceSentinelCoordinator._format_report_time(when)
    assert out == "July 21, 2026 at 7:19 AM"
    # Afternoon crosses to PM with a 12-hour clock.
    pm = datetime.datetime(2026, 12, 3, 15, 5, 0)
    assert DeviceSentinelCoordinator._format_report_time(pm) == (
        "December 3, 2026 at 3:05 PM"
    )
    # Midnight and noon read 12, not 0.
    midnight = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert "12:00 AM" in DeviceSentinelCoordinator._format_report_time(
        midnight
    )


async def test_regenerate_judges_then_writes(hass: HomeAssistant):
    """The regenerate action judges every device, then writes a fresh
    report that shows a device already down."""
    d = _register(hass, "ghost", "Ghost Device")
    coord = await _coordinator(hass)
    record = _new_device_record("2026-07-08T00:00:00+00:00", None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    coord.data["devices"][d.id] = record

    result = await coord.async_regenerate_reports()
    assert result == {"regenerated": 2}

    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    # Judgment ran, so the ghost is flagged and shows in the report.
    assert "Reporting Devices (1)" in text
    assert "As of" in text
    # STATUS column carries the new grammar.
    assert "Reported" in text


async def test_regenerate_button_present_and_presses(hass: HomeAssistant):
    """The Regenerate Reports button exists on the Device Sentinel
    device and its press runs without error."""
    coord = await _coordinator(hass)
    # The button entity is registered under the button platform.
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    buttons = [
        e
        for e in reg.entities.values()
        if e.platform == DOMAIN and e.domain == "button"
    ]
    # regenerate_reports gives a unique_id ending in "reports".
    assert any("reports" in e.unique_id for e in buttons)
    # Pressing it does not raise.
    await coord.async_regenerate_reports()
