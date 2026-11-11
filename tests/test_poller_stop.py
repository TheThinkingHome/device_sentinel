# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_poller_stop.py, Version: 0.28.11 (2026-11-10)

"""A poller that stops updating is one outage, not one row per device
(rule UP-17).

A tester's Alarm.com stopped updating for 59 hours while its entry
stayed loaded. Each of its 15 devices was told frozen on its own, 6 to
9.5 hours late on its learned window, and nothing named the cause. A
known poller loaded but silent for twice its usual longest gap, never
under ten minutes, is now an integration outage of its own kind:

- one Problem List row, "Alarm.com stopped updating", pushed as any
  outage is, with its devices counted under it, not listed;
- the brief: "stopped updating at", and "was updating again" when the
  first device is heard;
- the silence is not learned, as any outage's (rule FRZ-12);
- only a device heard since it began ends it: a restart's young run or
  a verdict dropped does not, so a restart in the middle of a stop never
  gives a false "updating again" and a second push;
- the push at its end says it was updating again, as the brief does;
- for a poller known by its devices moving together, the stop is judged
  on those devices, so a camera of the same entry on its own timer
  cannot hide one;
- only real reports count, so a clock step, or a stamp rewritten when a
  device returns, never ends a stop or starts one;
- a stop found after a restart is dated from the restart, not from
  before it.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_POLLERS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    POLLER_DEVICES,
    STARTUP_GRACE_SECONDS,
    SYS_DETAIL,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    SYS_KIND,
)
from custom_components.device_sentinel.outage_detail import STALLED, parse_detail
from tests.helpers import register_fleet, setup_coordinator

GAP = 360.0  # about 6 minutes, the tester's Alarm.com on its original integration


def _day(days_ago: int) -> str:
    return (dt_util.now().date() - timedelta(days=days_ago)).isoformat()


async def _poller(hass: HomeAssistant, freezer, domain: str = "alarm", devices: int = 15, aged: bool = True):
    source = MockConfigEntry(domain=domain, title="Alarm.com")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    fleet = register_fleet(hass, source, devices)
    coord = await setup_coordinator(hass)
    for device, _entity in fleet:
        coord.data[DATA_DEVICES].setdefault(device.id, {})[DEV_DAILY_MAX] = [GAP] * 5
    coord._fold_pollers(_day(1))
    # A run older than the threshold, unless a test wants a young one.
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5 + (3 * GAP if aged else 0)))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return source, fleet, coord


def _heard(coord, device_id: str, when: float) -> None:
    """A real report: the stored stamp and the run's own record of it."""
    coord.data[DATA_DEVICES][device_id][DEV_LAST_ACTIVITY] = when
    coord._heard_at[device_id] = when


def _silent_since(coord, fleet, seconds_ago: float) -> float:
    last = dt_util.utcnow().timestamp() - seconds_ago
    for device, _entity in fleet:
        _heard(coord, device.id, last)
    return last


def _outages(coord, kind):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row.get(SYS_KIND) == kind]


async def test_a_silent_poller_is_one_outage(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    last = _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    down = _outages(coord, SYS_INTEGRATION_DOWN)
    assert len(down) == 1
    assert parse_detail(down[0][SYS_DETAIL])[2] == STALLED
    assert down[0]["when"] == last, "dated from when its devices were last heard"
    assert coord.integration_stalled("alarm")
    # Its devices are counted under it, not listed one by one.
    device = fleet[0][0]
    assert coord.upstream_down_since(device.id) == ("alarm", last)
    # The brief says what was seen.
    sentence = coord._system_event_sentence(down[0])
    assert sentence.startswith("Alarm.com stopped updating at ") or "stopped updating at" in sentence
    assert "went down" not in sentence and "reload" not in sentence


async def test_its_problem_list_row_names_the_stop(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    since = coord.upstream_down_since_for("alarm")
    summary, description = coord._upstream_item_text("alarm", {"upstream": since}, 0)
    assert "stopped updating: 15 devices not heard from" in summary
    assert "hears" in description and "not each device" in description


async def test_a_short_quiet_is_not_a_stop(hass: HomeAssistant, freezer):
    """Under twice the usual gap, and under ten minutes, is the poll's
    own rhythm."""
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP - 30)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _outages(coord, SYS_INTEGRATION_DOWN) == []


async def test_the_first_device_heard_ends_it(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    # One device is heard again.
    _heard(coord, fleet[0][0].id, dt_util.utcnow().timestamp())
    coord._sample_integrations(dt_util.utcnow().timestamp())
    up = _outages(coord, SYS_INTEGRATION_UP)
    assert len(up) == 1
    assert parse_detail(up[0][SYS_DETAIL])[2] == STALLED
    assert not coord.integration_stalled("alarm")
    sentence = coord._system_event_sentence(up[0])
    assert "was updating again at" in sentence
    # No hand-back: the whole poller returns in one update.
    assert coord.upstream_down_since(fleet[1][0].id) is None


async def test_an_integration_that_is_not_a_poller_never_stalls(hass: HomeAssistant, freezer):
    source = MockConfigEntry(domain="zigbee_like")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    fleet = register_fleet(hass, source, 15)
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    _silent_since(coord, fleet, 86400)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _outages(coord, SYS_INTEGRATION_DOWN) == []


async def test_time_home_assistant_was_down_is_not_a_stop(hass: HomeAssistant, freezer):
    """After a restart the silence counts from the restart, so a poller
    whose next update is one of its slow ones is not told stopped."""
    _source, fleet, coord = await _poller(hass, freezer, aged=False)
    # Last heard well before this run began; the run itself is young.
    _silent_since(coord, fleet, 6 * 3600)
    start = coord._run_start()
    now = dt_util.utcnow().timestamp()
    assert now - start < 2 * GAP, "the run is younger than the threshold"
    coord._sample_integrations(now)
    assert _outages(coord, SYS_INTEGRATION_DOWN) == []


def _restarted(coord, seconds_ago: float) -> None:
    """A new run, past its startup grace and younger than the threshold."""
    coord._started_at = dt_util.utcnow().timestamp() - seconds_ago
    coord._grace_until = coord._started_at
    coord._heard_at.clear()


async def test_a_restart_in_the_middle_of_a_stop_keeps_it_open(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    # The run is young, so the stop is not found again, and nothing has
    # been heard: it stays open, with no row saying it came back.
    _restarted(coord, 301)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    assert _outages(coord, SYS_INTEGRATION_UP) == []
    assert len(_outages(coord, SYS_INTEGRATION_DOWN)) == 1
    # A verdict dropped is not the poller updating again either.
    coord.data[DATA_POLLERS] = {}
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    # A device heard ends it, once.
    _heard(coord, fleet[3][0].id, dt_util.utcnow().timestamp())
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert not coord.integration_stalled("alarm")
    assert len(_outages(coord, SYS_INTEGRATION_UP)) == 1


async def test_the_push_at_its_end_says_updating_again(hass: HomeAssistant, freezer):
    source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    # As when the down push has gone to the phone.
    seen = coord._entry_outages()[f"alarm|{source.entry_id}"]
    seen["pushed"] = True
    _heard(coord, fleet[0][0].id, dt_util.utcnow().timestamp())
    coord._sample_integrations(dt_util.utcnow().timestamp())
    row = coord._integration_over_row("alarm")
    assert row is not None and parse_detail(row[SYS_DETAIL])[2] == STALLED
    sentence = coord._system_event_sentence(row)
    assert "was updating again at" in sentence and "came back" not in sentence


async def test_an_unclean_restart_is_not_a_report(hass: HomeAssistant, freezer):
    """An unclean restart sets each device's last report to the moment
    it loads, before the run starts. That is no report, so the stop stays
    open, with no second push."""
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _restarted(coord, 301)
    # As the unclean restart leaves them: stamped as the store loaded.
    for device, _entity in fleet:
        coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = coord._started_at - 2
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    assert _outages(coord, SYS_INTEGRATION_UP) == []


async def test_a_camera_on_its_own_timer_cannot_hide_a_stop(hass: HomeAssistant, freezer):
    """A tester's Alarm.com: 13 sensors move together, and its cameras
    refresh on a timer of their own. The stop is judged on the 13."""
    _source, fleet, coord = await _poller(hass, freezer)
    sensors, cameras = fleet[:13], fleet[13:]
    coord.data[DATA_POLLERS]["alarm"][POLLER_DEVICES] = sorted(device.id for device, _ in sensors)
    _silent_since(coord, sensors, 2 * GAP + 60)
    for device, _entity in cameras:
        _heard(coord, device.id, dt_util.utcnow().timestamp() - 30)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    # A camera heard again does not end it; a sensor does.
    _heard(coord, cameras[0][0].id, dt_util.utcnow().timestamp())
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    _heard(coord, sensors[0][0].id, dt_util.utcnow().timestamp())
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert not coord.integration_stalled("alarm")


async def test_a_list_with_none_of_the_entrys_devices_judges_them_all(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    coord.data[DATA_POLLERS]["alarm"][POLLER_DEVICES] = ["a device since removed"]
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")


async def test_a_stamp_rewritten_without_a_report_does_not_end_a_stop(hass: HomeAssistant, freezer):
    """A device's return, or a damaged clock repaired, rewrites its
    last-report stamp with no report behind it."""
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 2 * GAP + 60)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    for device, _entity in fleet:
        coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert coord.integration_stalled("alarm")
    assert _outages(coord, SYS_INTEGRATION_UP) == []


async def test_a_clock_step_is_not_a_stop(hass: HomeAssistant, freezer):
    """After the clock is moved, the reports before it are on the old
    time; the silence counts from the step."""
    _source, fleet, coord = await _poller(hass, freezer)
    _silent_since(coord, fleet, 6 * 3600)
    coord._heard_at.clear()
    coord._heard_floor = dt_util.utcnow().timestamp() - 60
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _outages(coord, SYS_INTEGRATION_DOWN) == []


async def test_a_stop_after_a_restart_is_dated_from_the_restart(hass: HomeAssistant, freezer):
    _source, fleet, coord = await _poller(hass, freezer)
    for device, _entity in fleet:
        coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 6 * 3600
    _restarted(coord, 3 * GAP)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    down = _outages(coord, SYS_INTEGRATION_DOWN)
    assert len(down) == 1
    assert down[0]["when"] == coord._run_start()
