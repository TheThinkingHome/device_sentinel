# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_quiet_devices.py, Version: 0.22.25 (2026-09-22)

"""What the surfaces say about a device that is not speaking.

The reference rig's watering sensor ran its battery flat and went
silent at 7:27 PM. Seventeen hours later its own page showed a green
"Reporting" pill on two devices set aside, its Problem List row was
dated from July's battery rather than the evening's freeze, its
silence episode read closed with nothing said about the silence since,
and a restart replayed the retained MQTT payloads so its signal took
four readings from a device that had said nothing. Each of those is a
surface claiming the device spoke.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_READS,
    EP_AT,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_NAME,
    EP_SINCE,
    EPISODE_ENDED_RESUMED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    STATUS_NEVER_REPORTED,
    STATUS_REPORTING,
    STATUS_SET_ASIDE,
)

from .helpers import register_device, setup_coordinator


def _z2m_device(hass: HomeAssistant, uid: str, name: str):
    """A Zigbee2MQTT device whose clock is its own Last Seen value."""
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", uid)},
        name=name,
    )
    entities = er.async_get(hass)
    seen = entities.async_get_or_create(
        "sensor", "mqtt", f"{uid}_last_seen",
        device_id=device.id, config_entry=source,
        original_device_class="timestamp",
        suggested_object_id=f"{uid}_last_seen",
    ).entity_id
    signal = entities.async_get_or_create(
        "sensor", "mqtt", f"{uid}_linkquality",
        device_id=device.id, config_entry=source,
        original_device_class="signal_strength",
        unit_of_measurement="lqi",
        suggested_object_id=f"{uid}_linkquality",
    ).entity_id
    return device, seen, signal


async def test_a_set_aside_device_is_not_reporting(hass: HomeAssistant):
    """Two devices set aside for having no entities of their own, and a
    coordinator set aside as a duplicate, all read green before."""
    device, entities = register_device(hass, "q1", name="Quiet Plug")
    entity = entities[0]
    hass.states.async_set(entity, "on")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity, "off")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert coord.dashboard_device(device.id)["status"]["category"] == STATUS_REPORTING

    aside = coord._watched.pop(device.id)
    coord._set_aside[device.id] = (None, aside, "no entities")
    assert coord._page_status(device.id, record) == STATUS_SET_ASIDE


async def test_a_device_that_never_spoke_says_so(hass: HomeAssistant):
    device, _entities = register_device(hass, "q2", name="Silent Plug")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = None
    assert coord._page_status(device.id, record) == STATUS_NEVER_REPORTED


async def test_each_problem_carries_its_own_age(hass: HomeAssistant):
    """The freeze started last night; the battery emptied in July. One
    row dated from the battery hid the freeze entirely."""
    device, _entities3 = register_device(hass, "q3", name="Watering Kit")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_VALUE] = 0.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    coord.data["todo_items"] = [{
        "uid": "u1", "device_id": device.id,
        "summary": "Watering Kit: frozen, battery 0%",
        "description": "", "status": "needs_action", "acked_at": None,
        "sort_name": "Watering Kit",
        "kinds": {"frozen": now - 3600 * 17, "low_battery": now - 86400 * 62},
    }]
    text = coord._problems_by_device()[device.id]["problem"]
    assert text.startswith("frozen 17.0h")
    assert "battery 0% 8 and a half weeks" in text
    assert coord._standing_now()[0]["problem"] == text


async def test_a_truncated_silence_still_running_says_so(hass: HomeAssistant):
    """An intervention truncates the episode, and the device has not
    spoken since. The file read "0 still open"."""
    device, _entities4 = register_device(hass, "q4", name="Watering Kit")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_EPISODES] = [{
        EP_DEVICE_ID: device.id, EP_NAME: "Watering Kit",
        EP_SINCE: now - 3600 * 18, "basis": 540.0, "window": 2290.0,
        EP_ENDED: "intervention (reboot)", EP_AT: now - 3600 * 9,
        EP_LAG: None, "learned": None, "taint_seconds": None, "signal": None,
    }]
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = open(
        hass.config.path("device_sentinel", "silence_episodes.md"),
        encoding="utf-8",
    ).read()
    assert "1 still silent" in text
    # The whole silence, and what the lag counts from (0.22.25).
    assert "| 18.00h | intervention (reboot) |" in text
    assert "| not yet, 9.00h since the reboot |" in text

    page = coord.dashboard_device(device.id)
    assert page["silences"][0]["still_silent"] is True

    coord.data[DATA_EPISODES][0][EP_ENDED] = EPISODE_ENDED_RESUMED
    assert coord.dashboard_device(device.id)["silences"][0]["still_silent"] is False


async def test_a_replayed_reading_is_not_a_signal_reading(hass: HomeAssistant):
    """A restart hands back every retained payload. The device's Last
    Seen value comes back unchanged, so it has not spoken, and its
    link quality must not reach the statistics."""
    device, seen, signal = _z2m_device(hass, "q5", "Watering Kit")
    spoke = dt_util.utcnow() - timedelta(hours=18)
    hass.states.async_set(seen, spoke.isoformat())
    hass.states.async_set(signal, "180")
    coord = await setup_coordinator(hass)
    assert coord._last_seen_entity.get(device.id) == seen
    record = coord.data[DATA_DEVICES][device.id]
    # Armed: it has a window, so being overdue means something.
    record[DEV_DAILY_MAX] = [600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = spoke.timestamp()
    before = record[DEV_SIGNAL_READS]

    # The replay: the same values arrive again.
    hass.states.async_set(signal, "180", force_update=True)
    await hass.async_block_till_done()
    assert record[DEV_SIGNAL_READS] == before, "a replayed payload was counted"

    # The device itself speaks: its Last Seen value moves.
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    hass.states.async_set(signal, "176")
    await hass.async_block_till_done()
    assert record[DEV_SIGNAL_READS] > before
