# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_poller_verdict.py, Version: 0.28.11 (2026-11-10)

"""The poller verdict that lasts (rule UP-17).

An integration that updates all its devices at once is a poller when
its devices keep the same longest gap each day over five days, or when
its storm tally holds many storms a day on two of the last seven. The
verdict is taken at midnight on every house, kept across a restart,
and dropped after seven days in which neither holds. A known poller's
bursts are never announced, even in the first hour after a restart,
when the hour of storms the older rule read is empty.

A day removed by hand is not counted in either reading, as the freeze
rules do not count it (rule FRZ-25). Devices are compared on the same
dates, and never closer than two seconds, so a 30-second poll is still
seen moving together while devices on their own timers stay apart.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_POLLERS,
    DATA_STORM_DAYS,
    DATA_STORMS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    POLLER_BASIS,
    POLLER_BASIS_LOCKSTEP,
    POLLER_BASIS_STORMS,
    POLLER_GAP,
    POLLER_SEEN,
    POLLER_SINCE,
    STARTUP_GRACE_SECONDS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DEVICES,
    STORM_DAY_DOMAIN,
    STORM_DAY_DURATION,
    STORM_DAY_INTERVAL,
    STORM_DEVICE_THRESHOLD,
    SYS_KIND,
    SYS_STORM_OPEN,
)
from custom_components.device_sentinel.removed_days import gap_dates, set_removed
from custom_components.device_sentinel.study_watch import lockstep
from tests.helpers import register_fleet, setup_coordinator


def _day(days_ago: int) -> str:
    return (dt_util.now().date() - timedelta(days=days_ago)).isoformat()


def _in_step(coord, fleet, gap: float = 360.0) -> None:
    """Five days of the same longest gap on every device, as a cloud
    poll gives (a tester's Alarm.com: about 6 minutes)."""
    for device, _entity in fleet:
        coord.data[DATA_DEVICES].setdefault(device.id, {})[DEV_DAILY_MAX] = [gap] * 5


def _storm_day(domain: str, days_ago: int, count: int, interval: float) -> dict:
    return {
        STORM_DAY_DATE: _day(days_ago), STORM_DAY_DOMAIN: domain, STORM_DAY_COUNT: count,
        STORM_DAY_INTERVAL: interval, STORM_DAY_DEVICES: 20.0, STORM_DAY_DURATION: 5.0,
    }


async def test_devices_in_step_make_a_poller_that_lasts(hass: HomeAssistant):
    source = MockConfigEntry(domain="alarm")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 15)
    coord = await setup_coordinator(hass)
    _in_step(coord, fleet)
    assert not coord._is_polling_integration(source.entry_id, dt_util.utcnow().timestamp())
    coord._fold_pollers(_day(1))
    record = coord.data[DATA_POLLERS]["alarm"]
    assert record[POLLER_BASIS] == POLLER_BASIS_LOCKSTEP
    assert record[POLLER_GAP] == 360.0
    assert record[POLLER_SINCE] == record[POLLER_SEEN] == _day(1)
    # The hour of storms is empty, as it is after a restart, and the
    # verdict holds anyway.
    coord.data[DATA_STORMS] = []
    assert coord._is_polling_integration(source.entry_id, dt_util.utcnow().timestamp())


async def test_a_storm_tally_makes_a_poller_in_two_days(hass: HomeAssistant):
    """A new install has no five days of gaps; Tado's bursts every 5 to
    30 minutes give 48 or more storms a day."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [
        _storm_day("tado", 2, 200, 300.0), _storm_day("tado", 1, 120, 1800.0),
    ]
    coord._fold_pollers(_day(1))
    record = coord.data[DATA_POLLERS]["tado"]
    assert record[POLLER_BASIS] == POLLER_BASIS_STORMS
    assert record[POLLER_GAP] == 1050.0


async def test_one_busy_day_or_a_quiet_tally_is_not_a_poller(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [
        _storm_day("tester", 1, 400, 30.0),  # one bad day
        _storm_day("zha", 2, 3, 900.0), _storm_day("zha", 1, 2, 900.0),  # a reconnect or two
        _storm_day("old", 9, 500, 60.0), _storm_day("old", 8, 500, 60.0),  # outside the week
    ]
    coord._fold_pollers(_day(1))
    assert coord.data.get(DATA_POLLERS) == {}


async def test_devices_that_report_on_their_own_are_not_a_poller(hass: HomeAssistant):
    source = MockConfigEntry(domain="zigbee_like")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 15)
    coord = await setup_coordinator(hass)
    for n, (device, _entity) in enumerate(fleet):
        coord.data[DATA_DEVICES].setdefault(device.id, {})[DEV_DAILY_MAX] = [600.0 + 97 * n + day for day in range(5)]
    coord._fold_pollers(_day(1))
    assert "zigbee_like" not in coord.data.get(DATA_POLLERS, {})


async def test_a_verdict_goes_after_seven_days_without_evidence(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_POLLERS] = {
        "gone": {POLLER_SINCE: _day(30), POLLER_SEEN: _day(8), POLLER_BASIS: POLLER_BASIS_STORMS, POLLER_GAP: 60.0},
        "recent": {POLLER_SINCE: _day(30), POLLER_SEEN: _day(3), POLLER_BASIS: POLLER_BASIS_STORMS, POLLER_GAP: 60.0},
        "damaged": "not a record",
    }
    coord._fold_pollers(_day(1))
    assert set(coord.data[DATA_POLLERS]) == {"recent"}


async def test_a_damaged_store_is_replaced_not_read(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord.data[DATA_POLLERS] = ["not", "a", "mapping"]
    assert coord.is_known_poller("anything") is False
    assert coord.data[DATA_POLLERS] == {}


async def test_a_known_pollers_burst_is_not_announced_after_a_restart(hass: HomeAssistant, freezer):
    """The first bursts after a restart were announced while the hour
    was empty; a known poller's never are."""
    source = MockConfigEntry(domain="alarm")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, STORM_DEVICE_THRESHOLD + 1)
    coord = await setup_coordinator(hass)
    _in_step(coord, fleet)
    coord._fold_pollers(_day(1))
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for _device, entity_id in fleet:
        hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    told = [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row.get(SYS_KIND) == SYS_STORM_OPEN]
    assert told == []
    # Still counted, so the tally keeps its evidence.
    assert coord.data.get(DATA_STORMS)


async def test_a_poller_known_by_its_storms_keeps_its_slow_nights(hass: HomeAssistant):
    """Its storms come every 5 minutes by day, and its devices' longest
    gap is the 30-minute night: the stop threshold follows the night."""
    source = MockConfigEntry(domain="tado")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 3)
    coord = await setup_coordinator(hass)
    for device, _entity in fleet:
        coord.data[DATA_DEVICES].setdefault(device.id, {})[DEV_DAILY_MAX] = [303.0, 1803.0]
    coord.data[DATA_STORM_DAYS] = [_storm_day("tado", 2, 200, 300.0), _storm_day("tado", 1, 120, 300.0)]
    coord._fold_pollers(_day(1))
    assert coord.data[DATA_POLLERS]["tado"][POLLER_GAP] == 1803.0


# A tester's Alarm.com, one device's longest gap each day over 22 days:
# a 6-minute poll, with a 59-hour stall and three shorter ones.
STALLED_DAYS = [
    455.3, 353.6, 351.7, 127187.1, 353.7, 561.1, 581.8, 354.1, 21252.5, 354.7, 484.2,
    39144.8, 354.0, 376.9, 354.2, 354.3, 369.2, 502.3, 347.1, 212411.8, 52.0, 30.8,
]
STALLS = [3, 8, 11, 19]


def _with_stalls(coord, fleet, removed: bool) -> None:
    for device, _entity in fleet:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_DAILY_MAX] = list(STALLED_DAYS)
        if removed:
            dates = gap_dates(record)
            for index in STALLS:
                assert set_removed(record, dates[index], True)


async def test_a_stall_removed_by_hand_is_not_a_pollers_gap(hass: HomeAssistant):
    """Read as the freeze rules read a device's days: the newest 14,
    the longest set aside. The 59-hour stall is set aside on its own,
    though the 11-hour one beside it still counts; removed by hand, the
    gap is the poll's own."""
    source = MockConfigEntry(domain="alarmdotcom")
    source.add_to_hass(hass)
    # Two devices, too few to read as moving together, so the verdict
    # comes from its storms and its devices' own longest gaps.
    fleet = register_fleet(hass, source, 2)
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [_storm_day("alarmdotcom", 2, 2800, 31.0), _storm_day("alarmdotcom", 1, 2800, 31.0)]
    _with_stalls(coord, fleet, removed=False)
    coord._fold_pollers(_day(1))
    assert coord.data[DATA_POLLERS]["alarmdotcom"][POLLER_GAP] == 39144.8
    _with_stalls(coord, fleet, removed=True)
    coord._fold_pollers(_day(1))
    assert coord.data[DATA_POLLERS]["alarmdotcom"][POLLER_GAP] == 484.2


async def test_a_day_removed_by_hand_is_not_read_for_lockstep(hass: HomeAssistant):
    """Removing a stall day from one device's count leaves the rest of
    its days to be compared, and the day itself is never read."""
    source = MockConfigEntry(domain="alarmdotcom")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 4)
    coord = await setup_coordinator(hass)
    days = [360.0, 360.0, 360.0, 360.0, 360.0, 212411.8]
    for device, _entity in fleet:
        coord.data[DATA_DEVICES].setdefault(device.id, {})[DEV_DAILY_MAX] = list(days)
    first = coord.data[DATA_DEVICES][fleet[0][0].id]
    assert set_removed(first, gap_dates(first)[-1], True)
    watched = {device.id: "alarmdotcom" for device, _entity in fleet}
    measure = lockstep(coord.data[DATA_DEVICES], watched)["alarmdotcom"]
    assert measure["devices"] == 4


async def test_two_rows_for_one_day_count_once(hass: HomeAssistant):
    """A missed midnight's catch-up can write a second row for a day."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [_storm_day("tester", 1, 400, 30.0), _storm_day("tester", 1, 300, 30.0)]
    coord._fold_pollers(_day(1))
    assert "tester" not in coord.data.get(DATA_POLLERS, {})


def _dated(coord, device_id: str, days: list[float], skipped: list[str] | None = None) -> None:
    record = coord.data[DATA_DEVICES].setdefault(device_id, {})
    record[DEV_DAILY_MAX] = list(days)
    record["daily_dates"] = {"daily_max": {"last": _day(1), "count": len(days), "skipped": [[d, d] for d in skipped or []]}}


async def test_a_thirty_second_poll_still_moves_together(hass: HomeAssistant):
    """A tester's Alarm.com after its cloud moved to a 30-second poll:
    the last day read 30.8 and 31.7 seconds across its devices, under a
    second apart, where 1% is a third of a second."""
    source = MockConfigEntry(domain="alarmdotcom")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 15)
    coord = await setup_coordinator(hass)
    for n, (device, _entity) in enumerate(fleet):
        _dated(coord, device.id, [502.3, 347.1, 360.0, 52.0, 30.8 if n < 5 else 31.7])
    watched = {device.id: "alarmdotcom" for device, _ in fleet}
    measure = lockstep(coord.data[DATA_DEVICES], watched)["alarmdotcom"]
    assert measure["lockstep"] and measure["in_step"] == 15
    coord._fold_pollers(_day(1))
    assert len(coord.data[DATA_POLLERS]["alarmdotcom"]["devices"]) == 15


async def test_days_are_compared_by_date(hass: HomeAssistant):
    """A device that missed a day is compared with its neighbours on
    the same dates, not on the entry before."""
    source = MockConfigEntry(domain="alarmdotcom")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 4)
    coord = await setup_coordinator(hass)
    for device, _entity in fleet[:3]:
        _dated(coord, device.id, [400.0, 300.0, 200.0, 100.0, 50.0, 40.0])
    # The fourth missed the third-newest day: one entry fewer, the same
    # values on the dates it has.
    skipped = (dt_util.now().date() - timedelta(days=3)).isoformat()  # the day the others read 100
    _dated(coord, fleet[3][0].id, [400.0, 300.0, 200.0, 50.0, 40.0], skipped=[skipped])
    watched = {device.id: "alarmdotcom" for device, _ in fleet}
    assert lockstep(coord.data[DATA_DEVICES], watched)["alarmdotcom"]["in_step"] == 4


async def test_devices_on_their_own_ten_second_timers_stay_apart(hass: HomeAssistant):
    """A tester's TP-Link plugs each report every 10 seconds: their
    longest gaps sit a few seconds apart, and the two-second floor does
    not draw them together."""
    source = MockConfigEntry(domain="tplink")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 10)
    coord = await setup_coordinator(hass)
    for n, (device, _entity) in enumerate(fleet):
        _dated(coord, device.id, [8.0 + (n * 3 + day * 7) % 9 for day in range(5)])
    watched = {device.id: "tplink" for device, _ in fleet}
    assert not lockstep(coord.data[DATA_DEVICES], watched)["tplink"]["lockstep"]


async def test_a_device_with_no_dates_in_common_proves_nothing(hass: HomeAssistant):
    """Two devices of three switched off for a week keep their old
    dates; no date is held by three, so nothing is compared and the
    integration is not a poller, not one in step on no evidence."""
    source = MockConfigEntry(domain="hue")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 3)
    coord = await setup_coordinator(hass)
    _dated(coord, fleet[0][0].id, [4000.0, 3900.0, 4100.0, 4050.0, 3950.0])
    for device, _entity in fleet[1:]:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_DAILY_MAX] = [300.0] * 5
        old = (dt_util.now().date() - timedelta(days=8)).isoformat()
        record["daily_dates"] = {"daily_max": {"last": old, "count": 5, "skipped": []}}
    watched = {device.id: "hue" for device, _ in fleet}
    assert "hue" not in lockstep(coord.data[DATA_DEVICES], watched)
    coord._fold_pollers(_day(1))
    assert "hue" not in coord.data.get(DATA_POLLERS, {})


async def test_the_floor_is_held_to_a_tenth_of_a_fast_gap(hass: HomeAssistant):
    """Plugs each reporting about every 10 seconds, a second or so
    apart: two seconds would be a fifth of the gap and draw them
    together; a tenth keeps them apart."""
    source = MockConfigEntry(domain="tplink")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, 3)
    coord = await setup_coordinator(hass)
    for n, (device, _entity) in enumerate(fleet):
        _dated(coord, device.id, [10.0 + (1.5 if (n + day) % 3 == 0 else 0.0) for day in range(5)])
    watched = {device.id: "tplink" for device, _ in fleet}
    assert not lockstep(coord.data[DATA_DEVICES], watched)["tplink"]["lockstep"]
