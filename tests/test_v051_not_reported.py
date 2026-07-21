# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v051_not_reported.py, Version: 0.5.1 (2026-07-27)

"""0.5.1 tests: the never-reported verdict, the freeze exclude, and
the menu label guard.

A device that has produced nothing since well before now is flagged
not_reported, its own category ahead of the others, because it has no
rhythm to miss and may have no live entity to read. A freeze-excluded
device is watched but never given any verdict. Every menu step has a
label, so no screen renders blank.
"""

import json
import pathlib

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_EXCLUDED_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_NOT_REPORTED,
    FREEZE_NOT_REPORTED_SECONDS,
)
from custom_components.device_sentinel.coordinator import _new_device_record

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"NR {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _never_reported_record(first_observed_iso: str):
    """Zero events, no activity, observed at the given time."""
    record = _new_device_record(first_observed_iso, None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = first_observed_iso
    return record


async def test_silent_since_install_is_not_reported(hass: HomeAssistant):
    """A device with zero events, first seen well past the grace
    window, is flagged not_reported."""
    device = _register_device(hass, "nr1")
    coord = await _coordinator(hass)
    # Observed 3 days ago, still nothing.
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0  # well past 3 days after 2026-07-08
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_NOT_REPORTED
    )


async def test_recently_added_silent_device_is_not_flagged(
    hass: HomeAssistant,
):
    """A device added moments ago with no events yet is not flagged:
    it may simply be slow to first report, inside the grace window."""
    device = _register_device(hass, "nr2")
    coord = await _coordinator(hass)
    # Observed only an hour before now.
    import datetime

    now = 1_784_600_000.0
    observed = datetime.datetime.fromtimestamp(
        now - 3600, tz=datetime.timezone.utc
    ).isoformat()
    record = _never_reported_record(observed)
    coord.data["devices"][device.id] = record
    assert coord._device_down_category(device.id, record, now) is None


async def test_a_device_that_reported_once_is_not_not_reported(
    hass: HomeAssistant,
):
    """One event ever means the not_reported path never applies, even
    if the device later goes silent: that is a freeze, not a
    never-started."""
    device = _register_device(hass, "nr3")
    coord = await _coordinator(hass)
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    record[DEV_EVENT_COUNT] = 1
    record[DEV_LAST_ACTIVITY] = 1_784_000_000.0
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    # Not not_reported; it has an event. (It is not armed either, so
    # not frozen; the point is it never takes the not_reported branch.)
    assert (
        coord._device_down_category(device.id, record, now)
        != FREEZE_CATEGORY_NOT_REPORTED
    )


async def test_freeze_exclude_suppresses_every_verdict(hass: HomeAssistant):
    """A freeze-excluded device is watched but never given a verdict,
    even one it would otherwise earn."""
    device = _register_device(hass, "fx1")
    coord = await _coordinator(
        hass, {CONF_FREEZE_EXCLUDED_DEVICES: []}
    )
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    # Without the exclude it would be not_reported.
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_NOT_REPORTED
    )
    # Add the device to the freeze exclude and it goes quiet.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={CONF_FREEZE_EXCLUDED_DEVICES: [device.id]},
    )
    assert coord._device_down_category(device.id, record, now) is None


def test_every_menu_step_has_a_label():
    """Every step in the options menu has a label in both string
    files, so no screen renders blank. This is the guard for the
    0.5.0 miss where freeze had a step but no menu label."""
    base = pathlib.Path("custom_components/device_sentinel")
    for fn in ("strings.json", "translations/en.json"):
        data = json.loads((base / fn).read_text())
        init = data["options"]["step"]["init"]
        labels = init["menu_options"]
        # Every step that appears as a menu option (minus init itself)
        # must have a non-empty label.
        steps = set(data["options"]["step"]) - {"init"}
        for step in steps:
            assert step in labels, f"{fn}: {step} has no menu label"
            assert labels[step].strip(), f"{fn}: {step} label is blank"


def test_grace_window_is_48_hours():
    """The not-reported grace is 48 hours, clearing once-a-day
    devices that will have reported twice by then."""
    assert FREEZE_NOT_REPORTED_SECONDS == 48 * 3600
