# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.3 (2026-07-19)

"""0.4.3 tests: the floor is the line.

Covers the four things the rework introduced: the sensitivity slider
(direction and both clamps), the rail-filtered floor that fixes the
Door Laundry bug, at-or-below counting, and signal exclusion as
recorded-not-reported.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_EXCLUDED_INTEGRATIONS,
    CONF_SIGNAL_EXCLUDED_LABELS,
    CONF_SIGNAL_SENSITIVITY,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_VALUE,
    SIGNAL_RAIL_LQI,
)
from custom_components.device_sentinel.coordinator import (
    _new_device_record,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _record(daily_min):
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = list(daily_min)
    return record


# The rail-filtered floor: the Door Laundry bug.


async def test_rail_history_does_not_poison_the_floor(hass: HomeAssistant):
    """Door Laundry sat at rail 255 for a week, then read a real 172.
    Before the fix the floor was 255 and the line was garbage; now
    the rail days are filtered out and the floor is the one real
    reading, 172."""
    coord = await _coordinator(hass)
    record = _record([SIGNAL_RAIL_LQI] * 7 + [172.0])
    assert coord._danger_line(record) == 172.0


async def test_all_rail_history_has_no_floor(hass: HomeAssistant):
    """A device whose entire history is rail has no floor at all,
    rather than a false one at the rail value."""
    coord = await _coordinator(hass)
    record = _record([SIGNAL_RAIL_LQI] * 5)
    assert coord._danger_line(record) is None


# At or below the floor counts.


async def test_sitting_exactly_at_the_floor_counts(hass: HomeAssistant):
    """A device sitting on its own trimmed floor is living at its
    lows, the thing being measured, so it accumulates dwell."""
    coord = await _coordinator(hass)
    record = _record([80.0, 96.0, 88.0])  # k=0, floor 80
    assert coord._danger_line(record) == 80.0
    coord._feed_signal(record, 80.0, 1000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0


# The sensitivity slider.


async def test_slider_right_raises_the_floor(hass: HomeAssistant):
    """A week of readings gives base k=1. The slider adds to k:
    right (+1) trims one more low, so the floor sits higher and is
    brushed more often."""
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    base = await _coordinator(hass)
    assert base._danger_line(_record(days)) == 84.0  # k=1, drop 80
    right = await _coordinator(hass, {CONF_SIGNAL_SENSITIVITY: 1})
    assert right._danger_line(_record(days)) == 88.0  # k=2, drop 80,84


async def test_slider_left_lowers_the_floor(hass: HomeAssistant):
    """Left (-1) trims one fewer low, so the floor sits at the rawest
    reading and is rarely crossed. At a week, -1 takes k to 0."""
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    left = await _coordinator(hass, {CONF_SIGNAL_SENSITIVITY: -1})
    assert left._danger_line(_record(days)) == 80.0  # k=0, plain lowest


async def test_slider_clamps_at_both_ends(hass: HomeAssistant):
    """Out-of-range slider values are clamped to the -2..+2 band, and
    the effective k can never eat the last reading: one value always
    survives to be the floor."""
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    # Far left, beyond -2: clamped, k floored at 0, floor is lowest.
    far_left = await _coordinator(hass, {CONF_SIGNAL_SENSITIVITY: -9})
    assert far_left._danger_line(_record(days)) == 80.0
    # Far right, beyond +2: base 1 + 2 = k 3, drops the three lowest,
    # floor is the fourth, 92.
    far_right = await _coordinator(hass, {CONF_SIGNAL_SENSITIVITY: 9})
    assert far_right._danger_line(_record(days)) == 92.0
    # A two-value history with a big right push cannot go below one
    # survivor: k clamps to len-1 = 1, floor is the higher value.
    far_right_short = await _coordinator(
        hass, {CONF_SIGNAL_SENSITIVITY: 9}
    )
    assert far_right_short._danger_line(_record([40.0, 90.0])) == 90.0


# Exclusion is recorded, not reported.


async def test_excluded_device_by_device_id(hass: HomeAssistant):
    coord = await _coordinator(
        hass, {CONF_SIGNAL_EXCLUDED_DEVICES: ["dev-plug"]}
    )
    assert coord._signal_excluded("dev-plug") is True
    assert coord._signal_excluded("dev-other") is False


async def test_excluded_device_by_integration_and_label(
    hass: HomeAssistant,
):
    coord = await _coordinator(
        hass,
        {
            CONF_SIGNAL_EXCLUDED_INTEGRATIONS: ["mqtt"],
            CONF_SIGNAL_EXCLUDED_LABELS: ["noisy"],
        },
    )
    coord._watched["dev-mqtt"] = "mqtt"
    coord._device_labels["dev-labelled"] = frozenset({"noisy"})
    assert coord._signal_excluded("dev-mqtt") is True
    assert coord._signal_excluded("dev-labelled") is True


async def test_excluded_device_still_records_but_is_not_reported(
    hass: HomeAssistant,
):
    """The living room router plug case: excluded from reporting, but
    its floor and dwell keep accumulating in storage so re-including
    it is instant. The report shows excl; the frozen list skips it."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "plug")},
        name="LR Router Plug",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "plug",
        suggested_object_id="plug_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await _coordinator(
        hass, {CONF_SIGNAL_EXCLUDED_DEVICES: [device.id]}
    )
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [80.0, 96.0, 88.0]
    record[DEV_SIGNAL_VALUE] = 80.0
    record[DEV_SIGNAL_DWELL_DAILY] = [12.5]

    # Still observed: the floor is computed, history is intact.
    assert coord._danger_line(record) == 80.0
    # Not judged: absent from the frozen list regardless of state.
    assert all(
        row["name"] != "LR Router Plug"
        for row in coord.signal_frozen_list
    )
    # The report marks it excl in the dwell and frozen columns.
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "LR Router Plug" in line
    )
    assert "| excl | excl |" in row
    # But the daily lows are still shown: the history is not hidden.
    assert "88 96 80" in row
