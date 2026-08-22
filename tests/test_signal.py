# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal.py, Version: 0.15.6 (2026-08-17)

"""Signal detection: the floor line, the dwell timer, and the rail.

A device's danger line is its own trimmed floor, the lowest daily
reading after a k-ladder drops the anomalies, filtered of rail values
so a stuck fill reading cannot define it, and tunable by a sensitivity
slider. Below-the-line time accumulates as a daily dwell percentage
rather than counting crossings, so a dip that recovers counts only for
what it lasted. A rail (LQI 255, RSSI -128) is not a reading: it feeds
neither floor nor dwell, and the daily low sitting at the fill value
for three days running is the confirmed rail. This file holds the floor
line and how it renders, the dwell timer and its rollover, the rail
detector, signal exclusion as recorded-not-reported, and the tracked
count surface.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_SCALE,
    SIGNAL_SCALE_LQI,
    SIGNAL_SCALE_RSSI,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    RAIL_CONFIRM_DAYS,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    UNIT_SIGNALS,
)
from custom_components.device_sentinel.detect_signal import (
    SignalMixin,
    scale_of,
    signal_bucket,
)
from custom_components.device_sentinel.coordinator import (
    _new_device_record,
)

from tests.helpers import setup_coordinator, setup_coordinator_flat_line, setup_entry

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str):
    """A real registry device carrying one link-quality sensor, so
    setup watches it rather than pruning its storage record as an
    orphan. Returns the device."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"Signal {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


def _record(daily_min):
    """A device record seeded with a signal daily-min history."""
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = list(daily_min)
    return record


def _armed_lqi_record(floor_days=None):
    """A record with an established LQI floor of 80."""
    return _record(floor_days or [80, 96, 88, 80, 104, 92, 80])


def _armed_rssi_record():
    """A record with an established RSSI floor of -70 dBm."""
    return _record([-60, -66, -70, -62, -58, -64, -70])


async def _rail_coordinator(hass):
    """A coordinator with one registered link-quality device, returning
    the coordinator and that device's id. The rail tests read and write
    the device's series directly, so they need its id in hand."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "rail48")},
        name="Rail48 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rail48",
        suggested_object_id="rail48_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator_flat_line(hass)
    return coord, device.id


# ------------------------------------------- the line is the floor (#66)


def _trimmed(coordinator, depth):
    """Return the coordinator with a chosen trim depth.

    The trim is a constant since ruling #311, so a test
    that needs a different depth patches the accessor
    rather than saving an option nothing reads.
    """
    coordinator._signal_trim = lambda: depth
    return coordinator


async def test_lqi_line_is_the_trimmed_floor(hass: HomeAssistant):
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    # Seven days is the week rung, k=1: the single lowest 80 is
    # dropped, and 80 repeats, so the floor and the line are 80.
    line = coord._danger_line(record)
    assert line == 80


async def test_rssi_line_is_the_trimmed_floor(hass: HomeAssistant):
    """Same rule as LQI, no offset: below the floor is below the
    floor whichever sign the scale carries."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_rssi_record()
    line = coord._danger_line(record)
    assert line == -70


async def test_line_lives_from_the_first_day(hass: HomeAssistant):
    """Under a week the ladder's k is 0, so the line is the plain
    lowest reading and dwell measures from the very first day; there
    is no arming wait to sit out."""
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88]
    assert coord._danger_line(record) == 80
    coord._feed_signal(record, 5.0, 1000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0


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
    coord = await setup_coordinator_flat_line(hass)

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


# -------------------------------------- the rail-filtered floor (0.4.3)

async def test_rail_history_does_not_poison_the_floor(hass: HomeAssistant):
    """Door Laundry sat at rail 255 for a week, then read a real 172.
    Before the fix the floor was 255 and the line was garbage; now
    the rail days are filtered out and the floor is the one real
    reading, 172."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([SIGNAL_RAIL_LQI] * 7 + [172.0])
    assert coord._danger_line(record) == 172.0


async def test_all_rail_history_has_no_floor(hass: HomeAssistant):
    """A device whose entire history is rail has no floor at all,
    rather than a false one at the rail value."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([SIGNAL_RAIL_LQI] * 5)
    assert coord._danger_line(record) is None


async def test_sitting_exactly_at_the_floor_does_not_count(
    hass: HomeAssistant
):
    """Ruling #251: dwell counts strictly below the line. The floor
    is a value the device actually visits (its trimmed minimum), so
    at-or-below counting read every visit to a device's own floor as
    dwell, which is what kept a healthy plateaued link permanently
    dwelling. At margin 0 the line is the floor, and sitting on it is
    now ordinary life; one step under it still counts."""
    coord = await setup_coordinator_flat_line(hass)
    record = _record([80.0, 96.0, 88.0])  # k=0, floor 80
    assert coord._danger_line(record) == 80.0
    coord._feed_signal(record, 80.0, 1000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] is None
    coord._feed_signal(record, 79.0, 2000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] == 2000.0


# ------------------------------------------- the sensitivity slider

async def test_slider_right_raises_the_floor(hass: HomeAssistant):
    """A week of readings gives base k=1. The slider adds to k:
    right (+1) trims one more low, so the floor sits higher and is
    brushed more often."""
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    base = await setup_coordinator_flat_line(hass)
    assert base._danger_line(_record(days)) == 84.0  # k=1, drop 80
    right = _trimmed(await setup_coordinator_flat_line(hass), 1)
    assert right._danger_line(_record(days)) == 88.0  # k=2, drop 80,84


async def test_slider_left_lowers_the_floor(hass: HomeAssistant):
    """Left (-1) trims one fewer low, so the floor sits at the rawest
    reading and is rarely crossed. At a week, -1 takes k to 0."""
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    left = _trimmed(await setup_coordinator_flat_line(hass), -1)
    assert left._danger_line(_record(days)) == 80.0  # k=0, plain lowest


async def test_the_effective_k_never_eats_the_last_reading(
    hass: HomeAssistant,
):
    """One value always survives to be the floor.

    Until ruling #311 this file also tested the trim slider clamping
    to its -2..+2 band, which mattered because a hand-edited option
    could arrive out of range. The trim is a constant now and cannot,
    so what is left is the bound that still runs: however deep the
    trim, the effective k stops one short of the series length, and
    a floor computed from nothing at all is the fault this prevents.
    """
    days = [80.0, 84.0, 88.0, 92.0, 96.0, 100.0, 104.0]
    coord = await setup_coordinator_flat_line(hass)

    # At the shipped depth the ladder trims one reading at a week, so
    # the floor is the second lowest.
    assert coord._danger_line(_record(days)) == 84.0

    # A push far past the band cannot leave a series empty: k stops
    # at one short of its length and the floor is the highest value.
    pushed = _trimmed(await setup_coordinator_flat_line(hass), 99)
    assert pushed._danger_line(_record(days)) == 104.0
    assert pushed._danger_line(_record([40.0, 90.0])) == 90.0
    assert pushed._signal_effective_k(7) == 6
    assert pushed._signal_effective_k(2) == 1

    # And a push the other way floors k at zero rather than going
    # negative, which would index from the wrong end.
    pulled = _trimmed(await setup_coordinator_flat_line(hass), -99)
    assert pulled._signal_effective_k(7) == 0
    assert pulled._danger_line(_record(days)) == 80.0


# ------------------------------------------------- the dwell timer (#59)

async def test_dip_and_recovery_accumulates_only_the_dip(
    hass: HomeAssistant,
):
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()  # line = 56
    coord._feed_signal(record, 40.0, 1000.0)  # below: stamp
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0
    coord._feed_signal(record, 90.0, 1300.0)  # recovered: accumulate
    assert record[DEV_SIGNAL_BELOW_SINCE] is None
    assert record[DEV_SIGNAL_BELOW_TODAY] == 300.0
    # A second dip adds to the same day's total.
    coord._feed_signal(record, 30.0, 2000.0)
    coord._feed_signal(record, 100.0, 2600.0)
    assert record[DEV_SIGNAL_BELOW_TODAY] == 900.0


async def test_staying_below_does_not_double_count(hass: HomeAssistant):
    """Repeated below-line readings keep one open timer; they do not
    re-stamp or accumulate until recovery closes it."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, 40.0, 1000.0)
    coord._feed_signal(record, 35.0, 1500.0)
    coord._feed_signal(record, 45.0, 2000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0
    assert record[DEV_SIGNAL_BELOW_TODAY] == 0.0
    coord._feed_signal(record, 90.0, 3000.0)
    assert record[DEV_SIGNAL_BELOW_TODAY] == 2000.0


async def test_rollover_writes_the_daily_percentage(hass: HomeAssistant):
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    record[DEV_SIGNAL_BELOW_TODAY] = 8640.0  # 10% of a day
    coord._roll_dwell(record, now=1_000_000.0)
    assert record[DEV_SIGNAL_DWELL_DAILY] == [10.0]
    assert record[DEV_SIGNAL_BELOW_TODAY] == 0.0


async def test_silent_below_reads_the_whole_silence(hass: HomeAssistant):
    """The ruling that shares blood with the freeze machinery: a link
    that dies below the line was below for the whole silence, so an
    open timer closes at now and the device is re-stamped so the new
    day continues without a seam."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, 40.0, 1000.0)  # goes below, then silence
    coord._roll_dwell(record, now=1000.0 + 86400.0)
    assert record[DEV_SIGNAL_DWELL_DAILY] == [100.0]
    # Still below: the timer restarted at the rollover instant.
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0 + 86400.0


async def test_young_device_rolls_a_percentage(hass: HomeAssistant):
    """With the line live from day one, even a two-day history rolls
    a dwell percentage; a device with no signal history at all is
    the only one that rolls nothing."""
    coord = await setup_coordinator_flat_line(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96]
    coord._roll_dwell(record, now=1_000_000.0)
    assert record[DEV_SIGNAL_DWELL_DAILY] == [0.0]
    bare = _new_device_record("2026-07-11T00:00:00+00:00", None)
    coord._roll_dwell(bare, now=1_000_000.0)
    assert bare[DEV_SIGNAL_DWELL_DAILY] == []


# ------------------------------------- the rails and stuck detector (#60)

async def test_rail_feeds_neither_floor_nor_dwell(hass: HomeAssistant):
    """A rail value is not a measurement: it never touches the floor
    or the dwell timer. But it is still a reading, so it stamps the
    signal value and starts the frozen clock like any other."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    assert record[DEV_SIGNAL_TODAY_MIN] is None
    assert record[DEV_SIGNAL_BELOW_SINCE] is None
    assert record[DEV_SIGNAL_VALUE] == SIGNAL_RAIL_LQI
    assert record[DEV_SIGNAL_LAST_CHANGE] == 1000.0


async def test_rssi_rail_does_not_poison_the_floor(hass: HomeAssistant):
    """James S24+ hit -128 once inside real readings; that spike must
    not feed the floor. It is still a reading for the frozen clock."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_rssi_record()
    coord._feed_signal(record, SIGNAL_RAIL_RSSI, 1000.0)
    assert record[DEV_SIGNAL_TODAY_MIN] is None
    assert record[DEV_SIGNAL_VALUE] == SIGNAL_RAIL_RSSI


async def test_a_changed_reading_moves_the_frozen_clock(
    hass: HomeAssistant,
):
    """The recovered-by-hand case: the moment a revived sensor sends a
    different value, last_change advances and it is no longer flat."""
    coord = await setup_coordinator_flat_line(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    coord._feed_signal(record, 116.0, 2000.0)
    assert record[DEV_SIGNAL_LAST_CHANGE] == 2000.0
    assert record[DEV_SIGNAL_VALUE] == 116.0
    assert record[DEV_SIGNAL_TODAY_MIN] == 116.0


# --------------------------- the rail confirmed over three days (0.4.8)

async def test_three_rail_days_confirm_a_rail(hass: HomeAssistant):
    """The daily low at the fill value for three days running is a
    rail."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [88.0, 92.0, SIGNAL_RAIL_LQI,
                                 SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is True


async def test_two_rail_days_do_not_confirm(hass: HomeAssistant):
    """Fewer than three consecutive rail days is not yet a rail: a
    rail that comes and goes within a day or two never confirms."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [88.0, SIGNAL_RAIL_LQI, 92.0,
                                 SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is False


async def test_a_recovered_rail_clears(hass: HomeAssistant):
    """Three rail days then a real reading is not a rail: the most
    recent three days are not all rail."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI,
                                 SIGNAL_RAIL_LQI, 88.0, 90.0]
    assert coord.signal_railed(rec) is False


async def test_rssi_rail_confirms_too(hass: HomeAssistant):
    """The RSSI rail (-128) confirms the same way as the LQI rail."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_RSSI] * RAIL_CONFIRM_DAYS
    assert coord.signal_railed(rec) is True


async def test_a_steady_plausible_value_is_not_a_rail(hass: HomeAssistant):
    """The motion-blind case: a steady plausible value, however long
    it holds, is never a rail. Only the fill value is."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [-49.0, -49.0, -49.0, -49.0, -49.0]
    assert coord.signal_railed(rec) is False


async def test_short_history_is_not_a_rail(hass: HomeAssistant):
    """Fewer than three days of history cannot confirm a rail."""
    coord, device_id = await _rail_coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_SIGNAL_DAILY_MIN] = [SIGNAL_RAIL_LQI, SIGNAL_RAIL_LQI]
    assert coord.signal_railed(rec) is False


# ------------------------------------ exclusion: recorded, not reported

async def test_excluded_device_by_device_id(hass: HomeAssistant):
    coord = await setup_coordinator_flat_line(hass, {CONF_SIGNAL_MUTED_DEVICES: ["dev-plug"]})
    assert coord._signal_muted("dev-plug") is True
    assert coord._signal_muted("dev-other") is False


async def test_excluded_device_by_integration_and_label(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(
        hass,
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: ["mqtt"],
            CONF_SIGNAL_MUTED_LABELS: ["noisy"],
        },
    )
    coord._watched["dev-mqtt"] = "mqtt"
    coord._device_labels["dev-labelled"] = frozenset({"noisy"})
    assert coord._signal_muted("dev-mqtt") is True
    assert coord._signal_muted("dev-labelled") is True


async def test_excluded_device_still_records_but_is_not_reported(
    hass: HomeAssistant,
):
    """The living room router plug case: excluded from reporting, but
    its floor and dwell keep accumulating in storage so re-including
    it is instant. The report shows excl; the problem list skips it."""
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
    coord = await setup_coordinator_flat_line(hass, {CONF_SIGNAL_MUTED_DEVICES: [device.id]})
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [80.0, 96.0, 88.0]
    record[DEV_SIGNAL_VALUE] = 80.0
    record[DEV_SIGNAL_DWELL_DAILY] = [12.5]

    # Still observed: the floor is computed, history is intact.
    assert coord._danger_line(record) == 80.0
    # Not judged: absent from the frozen list regardless of state.
    assert all(
        row["name"] != "LR Router Plug"
        for row in coord.signal_problem_list
    )
    # The report marks it excl in the dwell and frozen columns.
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "LR Router Plug" in line
    )
    # excl in the dwell column; the battery column after is "-"
    # since this plug reports no battery. There is no frozen column.
    assert "| excl | - |" in row
    # But the daily lows are still shown, floor bold: not hidden.
    assert "88 96 **80**" in row


# ----------------------------------------------- persistence of dwell

async def test_dwell_fields_survive_storage_round_trip(
    hass: HomeAssistant, hass_storage
):
    """below_since and the day's accumulator are storage fields, so a
    restart mid-dip loses nothing: the timer reopens where it stood."""
    device = _register_device(hass, "roundtrip")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88, 80, 104, 92, 80]
    coord._feed_signal(record, 40.0, 1000.0)
    record[DEV_SIGNAL_BELOW_TODAY] = 123.0
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data.data["devices"][device.id]
    assert reloaded[DEV_SIGNAL_BELOW_SINCE] == 1000.0
    assert reloaded[DEV_SIGNAL_BELOW_TODAY] == 123.0


async def test_pre_040_storage_gains_the_new_fields(hass: HomeAssistant):
    """A 0.3.x record has none of the dwell fields; setup must default
    them rather than crash or wipe."""
    device = _register_device(hass, "pre040")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    old = coord.data["devices"][device.id]
    for key in (
        DEV_SIGNAL_BELOW_SINCE,
        DEV_SIGNAL_BELOW_TODAY,
        DEV_SIGNAL_DWELL_DAILY,
        DEV_SIGNAL_LAST_CHANGE,
        ):
        old.pop(key, None)
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    migrated = entry.runtime_data.data["devices"][device.id]
    assert migrated[DEV_SIGNAL_BELOW_SINCE] is None
    assert migrated[DEV_SIGNAL_BELOW_TODAY] == 0.0
    assert migrated[DEV_SIGNAL_DWELL_DAILY] == []
    assert migrated[DEV_SIGNAL_LAST_CHANGE] is None


# ------------------------------------------------ the tracked surface

async def _enable_tracked_signals(hass, entry):
    """Turn on the tracked-signals sensor, disabled by default under
    #239, so the two tests below have a state to read."""
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(
        "sensor", "device_sentinel", f"{entry.entry_id}_tracked_signals"
    )
    reg.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_tracked_signals_sensor_exists(hass: HomeAssistant):
    entry = await setup_entry(hass)
    await _enable_tracked_signals(hass, entry)
    state = hass.states.get("sensor.device_sentinel_signal_tracked")
    assert state is not None
    assert state.attributes["unit_of_measurement"] == UNIT_SIGNALS


async def test_tracked_counts_armed_devices_and_splits_by_scale(
    hass: HomeAssistant,
):
    device = _register_device(hass, "tracked")
    entry = await setup_entry(hass)
    await _enable_tracked_signals(hass, entry)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88, 80, 104, 92, 80]
    coord._notify()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_signal_tracked")
    assert int(state.state) == 1
    assert state.attributes["lqi"] == 1
    assert state.attributes["rssi"] == 0


# ------------------------------------ the sensitivity slider label

async def _slider_coord(hass, sensitivity):
    """A coordinator at a given signal-sensitivity slider value, for
    reading the word the report header shows for that setting."""
    return _trimmed(await setup_coordinator_flat_line(hass), sensitivity)


@pytest.mark.parametrize(
    "value,word",
    [
        (-2, "None"),
        (-1, "Light"),
        (0, "Normal"),
        (1, "Deep"),
        (2, "Deepest"),
    ],
)
async def test_slider_renders_as_a_word(
    hass: HomeAssistant, value: int, word: str
):
    """Each slider value shows its word in the SIGNAL header."""
    coord = await _slider_coord(hass, value)
    assert coord._signal_trim_label() == word


async def test_an_unknown_trim_depth_still_renders_a_word(
    hass: HomeAssistant,
):
    """The header names a depth or says Normal, never nothing.

    The trim is a constant since ruling #311, so only Normal can be
    reached in service. The fallback is kept because the header is
    read by a person and a blank cell in a pipe-delimited row reads
    as a bug rather than as a default.
    """
    coord = await _slider_coord(hass, 99)
    assert coord._signal_trim_label() == "Normal"


def _sig_entry(entity_id, device_class=None, unit=None, name=None):
    """A registry-entry double carrying a unit (ruling #283)."""

    class _E:
        pass

    e = _E()
    e.entity_id = entity_id
    e.unique_id = entity_id.split(".", 1)[1]
    e.original_name = name
    e.original_device_class = device_class
    e.device_class = None
    e.unit_of_measurement = unit
    e.original_unit_of_measurement = unit
    return e


def test_a_percentage_called_rssi_is_refused():
    """Tasmota's inversion, refused by unit rather than by vendor.

    Tasmota reports RSSI as a 0 to 100 quality figure and Signal as
    the dBm, so on a Tasmota device an entity called RSSI carries a
    percentage. All seven such devices on the first ZHA fleet to send
    data were consistent with 2 x (dBm + 100) clamped, one sitting
    exactly on the clamp at -50 dBm against 100 percent, so it
    restates a number already recorded.
    """
    for unit in ("%", "percent", "PERCENTAGE", " % "):
        assert not SignalMixin._is_signal(
            _sig_entry("sensor.tasmota_e13_rssi", unit=unit)
        ), unit


def test_the_dbm_entity_beside_it_is_kept():
    """The same device's real measurement is untouched."""
    assert SignalMixin._is_signal(
        _sig_entry(
            "sensor.tasmota_e13_signal",
            device_class="signal_strength",
            unit="dBm",
        )
    )


def test_the_signal_strength_class_is_never_refused():
    """Home Assistant permits only dB and dBm for that class, so an
    entity carrying it cannot be a percentage and never reaches the
    unit test. Asserted anyway, because the class is the one path
    that must not depend on a unit being present."""
    for unit in ("dBm", "dB", None, "%"):
        assert SignalMixin._is_signal(
            _sig_entry(
                "sensor.master_city_blinds_signal_strength",
                device_class="signal_strength",
                unit=unit,
            )
        ), unit


def test_a_unitless_name_match_is_kept():
    """The narrowness of #283, which is the whole point of it.

    Nothing in any diagnostics says what unit a Zigbee2MQTT
    linkquality entity carries. A rule refusing every unrecognized
    unit would have taken signal from 74 devices on the reference
    fleet if the guess were wrong, so only a percentage is refused
    and everything else is kept.
    """
    for unit in (None, "", "lqi", "LQI", "dBm", "arbitrary"):
        assert SignalMixin._is_signal(
            _sig_entry("sensor.door_master_linkquality", unit=unit)
        ), unit


def test_the_registry_unit_wins_over_the_original():
    """A person can change a unit, and the changed one is what the
    state carries, so it is the one that decides."""
    ent = _sig_entry("sensor.plug_rssi", unit=None)
    ent.original_unit_of_measurement = "dBm"
    ent.unit_of_measurement = "%"
    assert not SignalMixin._is_signal(ent)
    ent.unit_of_measurement = "dBm"
    ent.original_unit_of_measurement = "%"
    assert SignalMixin._is_signal(ent)


def test_an_entity_with_no_unit_attribute_at_all_is_kept():
    """Older registry doubles and any entry without the field.

    The recognizer must not depend on an attribute existing, because
    a missing unit is not a percentage.
    """

    class _Bare:
        entity_id = "sensor.door_master_lqi"
        unique_id = "door_master_lqi"
        original_name = None
        original_device_class = None
        device_class = None

    assert SignalMixin._is_signal(_Bare())


def test_the_two_real_fleets_classify_as_expected():
    """Every signal entity naming pattern seen on either fleet.

    The reference fleet loses nothing, and the ZHA fleet loses only
    the percentage.
    """
    kept = [
        _sig_entry("sensor.door_master_linkquality"),
        _sig_entry("sensor.temperature_outdoors_linkquality"),
        _sig_entry(
            "sensor.stove_vent_relays_signal",
            device_class="signal_strength",
            unit="dBm",
        ),
        _sig_entry(
            "sensor.master_city_blinds_signal_strength",
            device_class="signal_strength",
            unit="dBm",
        ),
        _sig_entry("sensor.s25_main_bath_toilet_leak_lqi"),
        _sig_entry(
            "sensor.s25_main_bath_toilet_leak_rssi",
            device_class="signal_strength",
            unit="dBm",
        ),
    ]
    for ent in kept:
        assert SignalMixin._is_signal(ent), ent.entity_id
    assert not SignalMixin._is_signal(
        _sig_entry("sensor.e13_grumpy_desk_dragon_light_rssi", unit="%")
    )


def test_the_sign_decides_the_scale():
    """RSSI is negative at any Zigbee receiver; LQI runs 0 to 255
    (ruling #284). Zero is a valid link quality and not a plausible
    received power, so it belongs with LQI."""
    for value in (-1.0, -66.0, -106.0, -128.0):
        assert scale_of(value) == SIGNAL_SCALE_RSSI, value
    for value in (0.0, 1.0, 94.0, 247.0, 255.0):
        assert scale_of(value) == SIGNAL_SCALE_LQI, value


def test_one_scale_stays_at_the_top_of_the_record():
    """A Zigbee2MQTT device publishes linkquality alone, so nothing
    about it changes: no block is allocated and it costs 20 bytes."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    bucket = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert bucket is rec
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert rec[DEV_SIGNAL_ALT] is None


def test_a_second_scale_gets_its_own_block():
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    signal_bucket(rec, SIGNAL_SCALE_RSSI)
    alt = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert alt is not rec
    assert alt is rec[DEV_SIGNAL_ALT]
    assert alt[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    # and the block holds no judgment fields
    assert "signal_dwell_daily_pct" not in alt
    assert "signal_daily_line" not in alt


def test_rssi_takes_the_primary_even_when_lqi_arrived_first():
    """Precedence is RSSI (ruling #285), and a ZHA device's LQI
    entity may well report first. The two trade places rather than
    either being discarded, so nothing already learned is lost."""
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    lqi = signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert lqi is rec
    rec[DEV_SIGNAL_VALUE] = 215.0
    rec[DEV_SIGNAL_DAILY_MIN] = [200.0, 205.0]
    rec[DEV_SIGNAL_READS] = 41

    rssi = signal_bucket(rec, SIGNAL_SCALE_RSSI)
    assert rssi is rec
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    # the LQI it had learned moved down, intact
    alt = rec[DEV_SIGNAL_ALT]
    assert alt[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_LQI
    assert alt[DEV_SIGNAL_VALUE] == 215.0
    assert alt[DEV_SIGNAL_DAILY_MIN] == [200.0, 205.0]
    assert alt[DEV_SIGNAL_READS] == 41
    # and the top is clear for RSSI rather than holding LQI's numbers
    assert rec[DEV_SIGNAL_VALUE] is None
    assert rec[DEV_SIGNAL_DAILY_MIN] == []
    assert rec[DEV_SIGNAL_READS] == 0


def test_lqi_never_displaces_rssi():
    rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
    signal_bucket(rec, SIGNAL_SCALE_RSSI)
    rec[DEV_SIGNAL_VALUE] = -70.0
    signal_bucket(rec, SIGNAL_SCALE_LQI)
    assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI
    assert rec[DEV_SIGNAL_VALUE] == -70.0


def test_routing_is_stable_however_the_readings_interleave():
    """Whatever order the two entities report in, the device ends up
    with RSSI on top and LQI in the block."""
    import itertools

    for order in itertools.permutations(
        [-70.0, 215.0, -66.0, 247.0, -71.0]
    ):
        rec = _new_device_record("2026-08-17T00:00:00+00:00", 1.0)
        for value in order:
            bucket = signal_bucket(rec, scale_of(value))
            bucket[DEV_SIGNAL_VALUE] = value
        assert rec[DEV_SIGNAL_SCALE] == SIGNAL_SCALE_RSSI, order
        assert rec[DEV_SIGNAL_VALUE] < 0, order
        assert rec[DEV_SIGNAL_ALT][DEV_SIGNAL_VALUE] > 0, order
