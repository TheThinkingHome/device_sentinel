# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.0 (2026-07-18)

"""0.4.0 tests: the signal dwell recorder and the rail-stuck detector.

The rulings of 2026-07-18, each pinned:
- Two danger formulas, one per physical scale (#58): LQI flags below a
  fraction of the device's own floor, RSSI below a fixed dB offset.
- Signal is reported as dwell, not crossings (#59): a below-the-line
  timer accumulates into a daily percentage, and a dip that recovers
  counts only for the moment it lasted.
- A silent-below device keeps accruing: an open timer closes at "now"
  at rollover, so a link that dies below the line reads a full day.
- A rail value (LQI 255, RSSI -128) is not a reading (#60): it never
  feeds the floor or the timer, and a full day of nothing but rail is
  the stuck state. Any real reading clears it.

These tests drive the coordinator's own feed methods with a frozen
clock rather than replaying the event bus, because the rulings are
about the arithmetic of time, and the event plumbing is already
proven by the telemetry tests.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_RAIL_SINCE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    SIGNAL_LQI_DANGER_FACTOR,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    SIGNAL_RAIL_STUCK_SECONDS,
    SIGNAL_RSSI_DANGER_OFFSET,
)
from custom_components.device_sentinel.coordinator import (
    _new_device_record,
)

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str):
    """Create a real registry device so setup watches it rather than
    pruning its storage record as an orphan."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"Dwell {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _armed_lqi_record(floor_days=None):
    """A record with an established LQI floor of 80."""
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = floor_days or [80, 96, 88, 80, 104, 92, 80]
    return record


def _armed_rssi_record():
    """A record with an established RSSI floor of -70 dBm."""
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = [-60, -66, -70, -62, -58, -64, -70]
    return record


# The danger lines (#58).


async def test_lqi_danger_line_is_a_fraction_of_the_floor(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    # Trimmed minimum of the seven days drops the single worst (80),
    # leaving a floor of 80 (it repeats), so the line is floor * 0.70.
    line = coord._danger_line(record)
    assert line == 80 * SIGNAL_LQI_DANGER_FACTOR


async def test_rssi_danger_line_is_a_db_offset(hass: HomeAssistant):
    coord = await _coordinator(hass)
    record = _armed_rssi_record()
    line = coord._danger_line(record)
    assert line == -70 - SIGNAL_RSSI_DANGER_OFFSET


async def test_no_line_before_arming(hass: HomeAssistant):
    """Dwell measures against a settled floor; a device inside its
    arming days accumulates nothing rather than being judged against
    a floor still moving."""
    coord = await _coordinator(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96, 88]
    assert coord._danger_line(record) is None
    coord._feed_signal(record, 5.0, 1000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] is None
    assert record[DEV_SIGNAL_BELOW_TODAY] == 0.0


# The dwell timer (#59).


async def test_dip_and_recovery_accumulates_only_the_dip(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
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
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, 40.0, 1000.0)
    coord._feed_signal(record, 35.0, 1500.0)
    coord._feed_signal(record, 45.0, 2000.0)
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0
    assert record[DEV_SIGNAL_BELOW_TODAY] == 0.0
    coord._feed_signal(record, 90.0, 3000.0)
    assert record[DEV_SIGNAL_BELOW_TODAY] == 2000.0


async def test_rollover_writes_the_daily_percentage(hass: HomeAssistant):
    coord = await _coordinator(hass)
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
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, 40.0, 1000.0)  # goes below, then silence
    coord._roll_dwell(record, now=1000.0 + 86400.0)
    assert record[DEV_SIGNAL_DWELL_DAILY] == [100.0]
    # Still below: the timer restarted at the rollover instant.
    assert record[DEV_SIGNAL_BELOW_SINCE] == 1000.0 + 86400.0


async def test_unarmed_device_rolls_no_percentage(hass: HomeAssistant):
    coord = await _coordinator(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_SIGNAL_DAILY_MIN] = [80, 96]
    coord._roll_dwell(record, now=1_000_000.0)
    assert record[DEV_SIGNAL_DWELL_DAILY] == []


# The rails and the stuck detector (#60).


async def test_rail_feeds_nothing_but_the_rail_clock(hass: HomeAssistant):
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    assert record[DEV_SIGNAL_RAIL_SINCE] == 1000.0
    assert record[DEV_SIGNAL_TODAY_MIN] is None
    assert record[DEV_SIGNAL_VALUE] is None
    assert record[DEV_SIGNAL_BELOW_SINCE] is None


async def test_rssi_rail_is_also_a_rail(hass: HomeAssistant):
    """James S24+ hit -128 once inside real readings; that spike must
    open the rail clock, not poison the floor."""
    coord = await _coordinator(hass)
    record = _armed_rssi_record()
    coord._feed_signal(record, SIGNAL_RAIL_RSSI, 1000.0)
    assert record[DEV_SIGNAL_RAIL_SINCE] == 1000.0
    assert record[DEV_SIGNAL_TODAY_MIN] is None


async def test_a_real_reading_clears_the_rail_clock(hass: HomeAssistant):
    """The recovered-by-hand case: the moment a revived sensor sends a
    real value, it clears itself without anyone's help."""
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    coord._feed_signal(record, SIGNAL_RAIL_LQI, 1000.0)
    coord._feed_signal(record, 116.0, 2000.0)
    assert record[DEV_SIGNAL_RAIL_SINCE] is None
    assert record[DEV_SIGNAL_VALUE] == 116.0
    assert record[DEV_SIGNAL_TODAY_MIN] == 116.0


async def test_stuck_needs_a_full_day_of_rail(hass: HomeAssistant):
    import homeassistant.util.dt as dt_util

    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    now = dt_util.utcnow().timestamp()
    record[DEV_SIGNAL_RAIL_SINCE] = now - 3600  # railed one hour
    assert coord.signal_rail_stuck(record) is False
    record[DEV_SIGNAL_RAIL_SINCE] = now - SIGNAL_RAIL_STUCK_SECONDS - 1
    assert coord.signal_rail_stuck(record) is True


async def test_never_railed_is_never_stuck(hass: HomeAssistant):
    coord = await _coordinator(hass)
    record = _armed_lqi_record()
    assert coord.signal_rail_stuck(record) is False


# Persistence: the timers survive a restart.


async def test_dwell_fields_survive_storage_round_trip(
    hass: HomeAssistant, hass_storage
):
    """below_since and the day's accumulator are storage fields, so a
    restart mid-dip loses nothing: the timer reopens where it stood."""
    device = _register_device(hass, "roundtrip")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
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
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    old = coord.data["devices"][device.id]
    for key in (
        DEV_SIGNAL_BELOW_SINCE,
        DEV_SIGNAL_BELOW_TODAY,
        DEV_SIGNAL_DWELL_DAILY,
        DEV_SIGNAL_RAIL_SINCE,
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
    assert migrated[DEV_SIGNAL_RAIL_SINCE] is None
