# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_poller_stop.py, Version: 0.28.10 (2026-11-10)

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
- the push at its end says it was updating again, as the brief does.
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


def _silent_since(coord, fleet, seconds_ago: float) -> float:
    last = dt_util.utcnow().timestamp() - seconds_ago
    for device, _entity in fleet:
        coord.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] = last
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
    coord.data[DATA_DEVICES][fleet[0][0].id][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
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
    coord.data[DATA_DEVICES][fleet[3][0].id][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
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
    coord.data[DATA_DEVICES][fleet[0][0].id][DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
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
