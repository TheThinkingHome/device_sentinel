# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_frozen_gap_grew.py, Version: 0.30.12 (2026-11-28)

"""A frozen device whose wait grows past its silence is not told as recovered (rule FRZ-26).

A house's outdoor sensor changed its rhythm after a Zigbee channel change.
Listed at 17:28, it came off the Problem List at the midnight fold, when
its longer gaps were learned and its wait passed its silence, and the
brief said "recovered after 9.0h". It reported at 02:31. It now leaves as
a withdrawal: the brief says it was removed without reporting because its
gap grew, nothing is pushed, and the bus hears device_sentinel_withdrawn
with the reason gap_grew, so an automation waiting on the fault gets its
answer. A device that reports still recovers as before.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    ACTION_GAP_GREW,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    EVENT_WITHDRAWN,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    INC_WINDOWS,
    INCIDENT_ACTION,
    WITHDRAWN_REASON_GAP_GREW,
)
from custom_components.device_sentinel.narrative import after_midnight, gap_grew_words

from .helpers import record_events, register_device, setup_coordinator

HOUR = 3600.0


async def _listed(hass: HomeAssistant):
    device, (eid,) = register_device(hass, "lux", "LUX Outdoors")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "21.5")
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [0.9 * HOUR] * (FREEZE_ARMING_DAYS + 7)
    record[DEV_TODAY_MAX] = None
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 9 * HOUR
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert any(item["device_id"] == device.id for item in coord.todo_items)
    return coord, device, eid, record


async def test_a_wait_that_grows_past_the_silence_is_a_withdrawal(hass: HomeAssistant, freezer):
    coord, device, _eid, record = await _listed(hass)
    recovered = record_events(hass, EVENT_RECOVERED)
    withdrawn = record_events(hass, EVENT_WITHDRAWN)
    # The fold learns the longer gaps: the wait passes the 9 hours of silence.
    record[DEV_DAILY_MAX] = [11.0 * HOUR] * (FREEZE_ARMING_DAYS + 7)
    coord._judge_all_devices()
    coord._sync_problem_list()
    # Its minute on the list passes (rule LIST-06).
    freezer.tick(timedelta(seconds=90))
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not any(item["device_id"] == device.id for item in coord.todo_items)
    assert recovered == [], "it has not spoken, so nothing recovered"
    assert len(withdrawn) == 1
    assert withdrawn[0]["reason"] == WITHDRAWN_REASON_GAP_GREW
    row = [r for r in coord.data[DATA_INCIDENTS] if r.get("device_id") == device.id][-1]
    assert row["event"] == INCIDENT_ACTION and row[INC_CAUSE] == ACTION_GAP_GREW
    before, after = row[INC_WINDOWS]["before"], row[INC_WINDOWS]["after"]
    assert before < 9 * HOUR < after
    phrase = coord._brief_phrase(row)
    assert phrase.startswith("left the Problem List: its gap grew from ")
    assert phrase.endswith(" and it has not been heard yet")
    sentence = coord._compose_event(row)
    assert "was removed from the Problem List at " in sentence
    assert "without reporting because its gap grew from " in sentence
    assert "recovered" not in sentence and "recovered" not in phrase


async def test_a_device_that_reports_still_recovers(hass: HomeAssistant, freezer):
    coord, device, eid, record = await _listed(hass)
    recovered = record_events(hass, EVENT_RECOVERED)
    withdrawn = record_events(hass, EVENT_WITHDRAWN)
    hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=90))
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] is None
    assert len(recovered) == 1 and withdrawn == []
    assert device.id not in coord._gap_grew


def test_the_words_and_the_midnight_test():
    row = {INC_WINDOWS: {"before": 2.2 * HOUR, "after": 8.4 * HOUR}}
    assert gap_grew_words(row) == ("2.2h", "8.4h")
    assert gap_grew_words({}) is None
    assert gap_grew_words({INC_WINDOWS: {"before": "x", "after": 1.0}}) is None
    tz = dt_util.get_default_time_zone()
    assert after_midnight(datetime(2026, 11, 28, 0, 1, tzinfo=tz).timestamp())
    assert not after_midnight(datetime(2026, 11, 28, 0, 20, tzinfo=tz).timestamp())
    assert not after_midnight(datetime(2026, 11, 27, 17, 28, tzinfo=tz).timestamp())
    assert not after_midnight(None)
